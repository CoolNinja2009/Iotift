"""
IOTIFT IR → C Code Generator — Milestone 2

Walks the IRModule and produces production-quality C++ for ESP32 (Arduino framework).
Replaces the direct AST→C codegen when using the IR pipeline.
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any, TYPE_CHECKING
from ir import (
    IRModule, IRFunction, IRGlobal, IRStruct, IREnum, IRTypeAlias,
    BasicBlock, IRValue,
    IRLabel, IRBinary, IRUnary, IRCopy, IRLoad, IRStore,
    IRCall, IRCallIndirect, IRBranch, IRJump, IRReturn,
    IRCast, IRArrayAccess, IRMemberAccess, IRInstr,
)

__version__ = "2.1.0"


def _dedent(text: str) -> str:
    """Remove the longest common leading whitespace from all non-empty lines."""
    lines = text.split('\n')
    non_empty = [ln for ln in lines if ln.strip()]
    if not non_empty:
        return text
    common = min(len(ln) - len(ln.lstrip()) for ln in non_empty)
    if common == 0:
        return text
    return '\n'.join(ln[common:] if ln.strip() else ln for ln in lines)


_PIN_DIRECTION = {
    'output': 'OUTPUT',
    'input':  'INPUT_PULLUP',
    'analog': 'INPUT',
    'i2c':    'INPUT',
    'pwm':    'OUTPUT',
}

# Precedence for minimal parenthesization
_PREC = {
    '||': 1, '&&': 2,
    '==': 3, '!=': 3, '<': 3, '>': 3, '<=': 3, '>=': 3,
    '+': 4, '-': 4,
    '*': 5, '/': 5, '%': 5,
    'unary': 6, 'call': 7, 'member': 7, 'index': 7,
}


class IRCodeGen:
    """IRModule → production C++ for ESP32 (Arduino framework)."""

    def __init__(self, device: str = 'esp32',
                 baud_rate: int = 115200,
                 scheduler_slots: int = 16,
                 debug_source_map: bool = False) -> None:
        self._device = device
        self._baud = baud_rate
        self._max_tasks = scheduler_slots
        self._lines: List[str] = []
        self._hal: Optional[HALBase] = None  # loaded in generate()

        # Pin registry (populated from IR module)
        self._pins: Dict[str, int] = {}
        self._pwm_pins: Dict[str, Dict] = {}
        self._on_pins: set = set()

        # Loop call list
        self._loop_calls: List[str] = []

        # Source map (Milestone 5 — enabled via --debug)
        self._debug_source_map = debug_source_map
        self._current_iot_line: int = 0
        self._source_map_entries: List[dict] = []  # [{iot_line, c_lines: [start, end]}]

    @property
    def source_map(self) -> Optional[dict]:
        """Return the source map as a JSON-serializable dict, or None if disabled."""
        if not self._debug_source_map or not self._source_map_entries:
            return None
        return {
            'version': 1,
            'source': '',
            'generated': '',
            'mappings': self._source_map_entries,
        }

    def _track_source(self, line: int) -> None:
        """Set the current .iot source line for mapping."""
        if self._debug_source_map and line > 0:
            self._current_iot_line = line

    def _record_mapping(self, c_line_index: int) -> None:
        """Record that the current .iot line produced a C line."""
        if not self._debug_source_map or self._current_iot_line <= 0:
            return
        # Check if we already have an entry for this iot line
        if (self._source_map_entries and
                self._source_map_entries[-1]['iot_line'] == self._current_iot_line):
            # Extend the range
            entry = self._source_map_entries[-1]
            entry['c_lines'][1] = c_line_index
        else:
            self._source_map_entries.append({
                'iot_line': self._current_iot_line,
                'c_lines': [c_line_index, c_line_index],
            })

    # ─────────────────────────────────────────
    #  PUBLIC ENTRY
    # ─────────────────────────────────────────

    def generate(self, module: IRModule) -> str:
        """Produce the final C++ source string from an IRModule."""
        # Load HAL based on device
        try:
            from hal import get_hal
            self._hal = get_hal(module.device)
        except (ImportError, ValueError):
            self._hal = None
        self._pins = module.pins
        self._pwm_pins = module.pwm_pins

        # Collect on-event pins for INPUT_PULLUP setup
        for eh in module.on_event_handlers:
            self._on_pins.add(eh.get('pin', ''))

        self._emit_file_header()
        self._emit_includes(module)
        self._emit_config_defines()
        self._emit_pin_macros()
        self._emit_enums(module)
        self._emit_structs(module)
        self._emit_type_aliases(module)
        self._emit_global_blocks(module)
        self._emit_global_state(module)
        self._emit_scheduler(module)
        self._emit_functions(module)
        self._emit_setup(module)
        self._emit_main_loop(module)

        # Inject source map comments if debug enabled
        if self._debug_source_map and self._source_map_entries:
            self._inject_source_comments()

        # Update source map with final output path info
        if self._source_map_entries:
            self.source_map['source'] = module.source_path or ''
            self.source_map['generated'] = 'generated.c'

        return '\n'.join(self._lines)

    def _inject_source_comments(self) -> None:
        """Post-process: inject // @iot:line N comments into C output."""
        # Build a reverse index: C line → iot line
        c_to_iot: Dict[int, int] = {}
        for entry in self._source_map_entries:
            start, end = entry['c_lines']
            for c_line in range(start, end + 1):
                c_to_iot[c_line] = entry['iot_line']

        # Inject comments: scan lines in reverse and insert
        new_lines = []
        for i, line in enumerate(self._lines):
            # Skip blank lines and comment-only lines for cleanliness
            stripped = line.strip()
            if stripped and not stripped.startswith('// @iot:') and not stripped.startswith('/*'):
                if i in c_to_iot and not stripped.startswith('#'):
                    new_lines.append(f'{line}  // @iot:line {c_to_iot[i]}')
                    continue
            new_lines.append(line)

        self._lines = new_lines

    # ─────────────────────────────────────────
    #  EMIT SECTIONS
    # ─────────────────────────────────────────

    def _emit_file_header(self) -> None:
        now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        self._lines += [
            '/**',
            ' * @file    generated.c',
            f' * @brief   Auto-generated by Iotift Compiler v{__version__}',
            ' *',
            f' * @date    {now}',
            f' * @target  ESP32 (Arduino framework)',
            ' *',
            ' * @warning This file is auto-generated.  Edits will be overwritten.',
            ' */',
            '',
        ]

    def _emit_includes(self, module: IRModule) -> None:
        self._lines.append('#include <Arduino.h>')
        if module.has_wifi:
            self._lines.append('#include <WiFi.h>')
        # Check for math function usage across all functions
        uses_math = module.uses_math
        if not uses_math:
            for fn in module.functions:
                for bb in fn.blocks:
                    for instr in bb.instructions:
                        if isinstance(instr, IRCall) and instr.func in (
                            'sin', 'cos', 'tan', 'sqrt', 'pow', 'floor', 'ceil',
                            'round', 'log', 'exp', 'fabs', 'abs',
                        ):
                            uses_math = True
                            break
        # Only emit math.h if actually needed and not already present
        if uses_math:
            # Check that math.h isn't already in header_blocks or global_blocks
            all_c_blocks = '\n'.join(module.header_blocks + module.global_blocks)
            if '#include <math.h>' not in all_c_blocks:
                self._lines.append('#include <math.h>')
        for inc in sorted(module.includes):
            if inc not in self._lines:
                self._lines.append(inc)
        for code in module.header_blocks:
            self._lines.append(_dedent(code))
        if module.header_blocks:
            self._lines.append('')
        self._lines.append('')

    def _emit_config_defines(self) -> None:
        self._lines += [
            '/* ============================================================================',
            ' *  COMPILE-TIME CONFIGURATION',
            ' * ============================================================================ */',
            '',
            f'#ifndef IOTIFT_BAUD_RATE',
            f'#define IOTIFT_BAUD_RATE          {self._baud}UL',
            f'#endif',
            '',
            f'#ifndef IOTIFT_SCHEDULER_SLOTS',
            f'#define IOTIFT_SCHEDULER_SLOTS    {self._max_tasks}U',
            f'#endif',
            '',
        ]

    def _emit_pin_macros(self) -> None:
        if not self._pins:
            return
        self._section('PIN DEFINITIONS')
        for name, number in self._pins.items():
            self._lines.append(f'static const uint8_t {name}_PIN = {number}U;')
        self._lines.append('')

    def _emit_enums(self, module: IRModule) -> None:
        if not module.enums:
            return
        self._section('ENUM DEFINITIONS')
        for enum in module.enums:
            bt = enum.backing_type or 'int'
            ct = self._map_ctype(bt)
            self._lines.append(f'typedef enum {{')
            for var_name, val in enum.variants:
                if val is not None:
                    self._lines.append(f'  {enum.name}_{var_name} = {val},')
                else:
                    self._lines.append(f'  {enum.name}_{var_name},')
            self._lines.append(f'}} {enum.name};')
        self._lines.append('')

    def _emit_structs(self, module: IRModule) -> None:
        if not module.structs:
            return
        self._section('STRUCT DEFINITIONS')
        for s in module.structs:
            self._lines.append(f'struct {s.name} {{')
            for f in s.fields:
                self._lines.append(f'  {f.ctype} {f.name};')
            self._lines.append('};')
        self._lines.append('')

    def _emit_type_aliases(self, module: IRModule) -> None:
        if not module.type_aliases:
            return
        for ta in module.type_aliases:
            self._lines.append(f'typedef {ta.aliased_type} {ta.name};')
        self._lines.append('')

    def _emit_global_blocks(self, module: IRModule) -> None:
        for code in module.global_blocks:
            self._lines.append(_dedent(code))
        if module.global_blocks:
            self._lines.append('')

    def _emit_global_state(self, module: IRModule) -> None:
        if not module.globals:
            return
        self._section('GLOBAL STATE')
        for g in module.globals:
            qualifiers = []
            if g.is_static:
                qualifiers.append('static')
            if g.is_const:
                qualifiers.append('const')
            if g.is_volatile:
                qualifiers.append('volatile')
            prefix = ' '.join(qualifiers) + ' ' if qualifiers else ''
            # Handle array types
            if g.array_size > 0:
                type_str = f'{g.ctype} {g.name}[{g.array_size}]'
            else:
                type_str = f'{g.ctype} {g.name}'
            if g.init is not None:
                init_str = self._value_c(g.init)
                self._lines.append(f'{prefix}{type_str} = {init_str};')
            else:
                self._lines.append(f'{prefix}{type_str};')
        self._lines.append('')

    def _emit_scheduler(self, module: IRModule) -> None:
        if not module.scheduler_needed:
            return
        self._section('INTERNAL SCHEDULER (deferred execution)')
        n = module.scheduler_slots

        self._lines += [
            'typedef enum {',
            '  IOTIFT_TASK_NONE = 0,',
            '  IOTIFT_TASK_PIN,',
            '  IOTIFT_TASK_INT_VAR,',
            '} iotift_task_type_t;',
            '',
            'typedef struct {',
            '  iotift_task_type_t type;',
            '  unsigned long      trigger_time;',
            '  uint8_t            pin;',
            '  uint8_t            pin_value;',
            '  int *              var_ptr;',
            '  int                var_value;',
            '} iotift_task_t;',
            '',
            f'#ifndef IOTIFT_SCHEDULER_SLOTS',
            f'#define IOTIFT_SCHEDULER_SLOTS {n}U',
            f'#endif',
            '',
            f'static iotift_task_t _iotift_scheduler[IOTIFT_SCHEDULER_SLOTS];',
            f'static uint8_t _iotift_scheduler_size = 0U;',
            f'static bool _iotift_scheduler_overflow = false;',
            '',
            'static void _iotift_scheduler_swap(uint8_t i, uint8_t j) {',
            '  iotift_task_t tmp = _iotift_scheduler[i];',
            '  _iotift_scheduler[i] = _iotift_scheduler[j];',
            '  _iotift_scheduler[j] = tmp;',
            '}',
            '',
            'static void _iotift_schedule_pin(uint8_t p, uint8_t val, unsigned long delay) {',
            '  if (_iotift_scheduler_size >= IOTIFT_SCHEDULER_SLOTS) {',
            '    _iotift_scheduler_overflow = true;',
            '    return;',
            '  }',
            '  uint8_t i = _iotift_scheduler_size++;',
            '  _iotift_scheduler[i].type         = IOTIFT_TASK_PIN;',
            '  _iotift_scheduler[i].trigger_time = millis() + delay;',
            '  _iotift_scheduler[i].pin          = p;',
            '  _iotift_scheduler[i].pin_value    = val;',
            '  /* bubble-up */',
            '  while (i > 0U) {',
            '    uint8_t parent = (i - 1U) >> 1U;',
            '    if (_iotift_scheduler[i].trigger_time >= _iotift_scheduler[parent].trigger_time) break;',
            '    _iotift_scheduler_swap(i, parent);',
            '    i = parent;',
            '  }',
            '}',
            '',
            'static void _iotift_schedule_int(int *var, int val, unsigned long delay) {',
            '  if (_iotift_scheduler_size >= IOTIFT_SCHEDULER_SLOTS) {',
            '    _iotift_scheduler_overflow = true;',
            '    return;',
            '  }',
            '  uint8_t i = _iotift_scheduler_size++;',
            '  _iotift_scheduler[i].type         = IOTIFT_TASK_INT_VAR;',
            '  _iotift_scheduler[i].trigger_time = millis() + delay;',
            '  _iotift_scheduler[i].var_ptr      = var;',
            '  _iotift_scheduler[i].var_value    = val;',
            '  /* bubble-up */',
            '  while (i > 0U) {',
            '    uint8_t parent = (i - 1U) >> 1U;',
            '    if (_iotift_scheduler[i].trigger_time >= _iotift_scheduler[parent].trigger_time) break;',
            '    _iotift_scheduler_swap(i, parent);',
            '    i = parent;',
            '  }',
            '}',
            '',
            'static void _iotift_scheduler_tick(void) {',
            '  unsigned long now = millis();',
            '  while (_iotift_scheduler_size > 0U &&',
            '         _iotift_scheduler[0].trigger_time <= now) {',
            '    iotift_task_t task = _iotift_scheduler[0];',
            '    /* Execute task */',
            '    if (task.type == IOTIFT_TASK_PIN) {',
            '      digitalWrite(task.pin, task.pin_value);',
            '    } else if (task.type == IOTIFT_TASK_INT_VAR) {',
            '      *(task.var_ptr) = task.var_value;',
            '    }',
            '    /* Replace root with last element */',
            '    _iotift_scheduler[0] = _iotift_scheduler[--_iotift_scheduler_size];',
            '    /* bubble-down */',
            '    uint8_t i = 0U;',
            '    for (;;) {',
            '      uint8_t smallest = i;',
            '      uint8_t left  = (i << 1U) + 1U;',
            '      uint8_t right = (i << 1U) + 2U;',
            '      if (left < _iotift_scheduler_size &&',
            '          _iotift_scheduler[left].trigger_time < _iotift_scheduler[smallest].trigger_time)',
            '        smallest = left;',
            '      if (right < _iotift_scheduler_size &&',
            '          _iotift_scheduler[right].trigger_time < _iotift_scheduler[smallest].trigger_time)',
            '        smallest = right;',
            '      if (smallest == i) break;',
            '      _iotift_scheduler_swap(i, smallest);',
            '      i = smallest;',
            '    }',
            '  }',
            '}',
            '',
        ]
        self._loop_calls.append('_iotift_scheduler_tick();')

    def _emit_functions(self, module: IRModule) -> None:
        """Emit all IR functions as C functions."""
        if not module.functions:
            return

        # Separate user functions from handler functions
        user_fns = []
        handler_fns = []

        handler_prefixes = ('_iotift_on_', '_iotift_every_', '_iotift_threshold_',
                            '_iotift_after_', '_iotift_handle_loop', '_iotift_tick', 'user_loop')

        for fn in module.functions:
            if fn.name == '_iotift_setup':
                # Inline into setup()
                continue
            if any(fn.name.startswith(p) for p in handler_prefixes):
                handler_fns.append(fn)
            else:
                user_fns.append(fn)

        # Emit user functions
        if user_fns:
            self._section('USER FUNCTIONS')
            for fn in user_fns:
                self._emit_function(fn)

        # Emit handler functions
        if handler_fns:
            self._section('EVENT & TIMER HANDLERS')
            for fn in handler_fns:
                self._emit_function(fn)

    def _emit_function(self, fn: IRFunction) -> None:
        """Emit a single IR function as C."""
        params = ', '.join(
            f'{p.ctype} {p.name}' for p in fn.params
        ) if fn.params else 'void'

        sig = f'{fn.attrs}static {fn.return_type} {fn.name}({params})'
        self._lines.append(f'{sig} {{')

        # Emit local variable declarations (collect from blocks)
        temp_vars: Dict[str, IRValue] = {}
        for bb in fn.blocks:
            for instr in bb.instructions:
                for field in ['dest', 'src', 'left', 'right', 'operand']:
                    val = getattr(instr, field, None)
                    if isinstance(val, IRValue) and val.kind == 'temp':
                        if val.name not in temp_vars:
                            temp_vars[val.name] = val

        for tv in sorted(temp_vars.values(), key=lambda v: v.name):
            # Skip void-typed temps (e.g., from void function calls used as statements)
            if tv.ctype == 'void':
                continue
            self._lines.append(f'  {tv.ctype} {tv.name};')

        # Emit declared locals
        for local in fn.locals:
            self._lines.append(f'  {local.ctype} {local.name};')

        if temp_vars or fn.locals:
            self._lines.append('')

        # Emit function body using CFG-based structured traversal
        blocks = fn.blocks
        if not blocks:
            self._lines.append('}')
            self._lines.append('')
            return

        entry_label = fn.entry_block or blocks[0].label
        labels, succ, pred = self._build_cfg(blocks)
        order, back_edges = self._dfs_order(entry_label, labels, succ)

        # Find all loop headers (targets of back-edges)
        loop_headers = {tgt for _, tgt in back_edges}

        # Build the set of ALL labels targeted by IRJump instructions.
        # These must be emitted as proper C labels (not comments) so that
        # 'goto target;' statements have a valid landing point.
        jump_targets: set = set()
        for bb in blocks:
            for instr in bb.instructions:
                if isinstance(instr, IRJump):
                    jump_targets.add(instr.label)
                elif isinstance(instr, IRBranch):
                    jump_targets.add(instr.true_label)
                    jump_targets.add(instr.false_label)
        # Also add loop headers (back-edge targets must be labels too)
        jump_targets.update(loop_headers)
        # Add no_inline_targets - labels that will get gotos for merge points
        # Build during traversal, so collect from blocks as fallthrough targets
        for bb in blocks:
            for instr in bb.instructions:
                if isinstance(instr, IRJump) and instr.label not in loop_headers:
                    jump_targets.add(instr.label)

        emitted = set()
        # For loop headers, emit as while(1) { ... } with break/goto inside
        # For now, emit loop headers as raw goto blocks
        self._emit_cfg_region(entry_label, labels, succ, pred,
                             order, back_edges, emitted, 1, loop_headers,
                             jump_targets=jump_targets)

        # Emit any remaining unvisited blocks (e.g., merge points not reached by
        # structured traversal). Emit proper C labels for jump targets.
        for bb in blocks:
            if bb.label not in emitted:
                if bb.label in jump_targets:
                    self._lines.append(f'  {bb.label}:')
                else:
                    self._lines.append(f'  // {bb.label}')
                for instr in bb.instructions:
                    c_line = self._instr_c(instr)
                    if c_line:
                        self._lines.append(f'  {c_line}')

        self._lines.append('}')
        self._lines.append('')

    def _build_cfg(self, blocks):
        """Build CFG maps from blocks: (labels, successors, predecessors)."""
        labels = {bb.label: bb for bb in blocks}
        succ = {}
        pred = {}
        for bb in blocks:
            lbl = bb.label
            succ[lbl] = []
            term = bb.terminator
            if isinstance(term, IRBranch):
                succ[lbl] = [term.true_label, term.false_label]
            elif isinstance(term, IRJump):
                succ[lbl] = [term.label]
        for bb in blocks:
            lbl = bb.label
            if lbl not in pred:
                pred[lbl] = []
        for src, targets in succ.items():
            for tgt in targets:
                if tgt not in pred:
                    pred[tgt] = []
                if src not in pred[tgt]:
                    pred[tgt].append(src)
        return labels, succ, pred

    def _dfs_order(self, entry_label, labels, succ):
        """Compute DFS visit order and detect back-edges.

        Returns (order: dict[label→int], back_edges: set[(src, tgt)]).
        """
        order = {}
        counter = [0]
        on_stack = set()
        back_edges = set()

        def dfs(label):
            if label not in labels:
                return
            if label not in order:
                order[label] = counter[0]
                counter[0] += 1
                on_stack.add(label)
                for tgt in succ.get(label, []):
                    if tgt in on_stack:
                        back_edges.add((label, tgt))
                    elif tgt not in order:
                        dfs(tgt)
                on_stack.discard(label)

        dfs(entry_label)
        # Also process any unvisited blocks
        for lbl in labels:
            if lbl not in order:
                dfs(lbl)
        return order, back_edges

    def _emit_cfg_region(self, label, labels, succ, pred, order, back_edges,
                         emitted, indent, loop_headers=None,
                         no_inline_targets=None, jump_targets=None):
        """Recursively emit a CFG region as structured C.

        Uses goto-based emission as the primary strategy (simple and correct).
        Structured if/else is used only for simple patterns that guarantee correctness.

        Args:
            no_inline_targets: set of label names that should NOT be inlined when
                               reached via IRJump. Used by structured if to prevent
                               the merge/else block from being pulled inside the if body.
            jump_targets: set of ALL labels that are targeted by any IRJump or IRBranch.
                          These are emitted as proper C labels (not comments).
        """
        if loop_headers is None:
            loop_headers = set()
        if no_inline_targets is None:
            no_inline_targets = set()
        if jump_targets is None:
            jump_targets = set()

        if label in emitted or label not in labels:
            return

        emitted.add(label)
        bb = labels[label]
        term = bb.terminator
        indent_str = '  ' * indent

        # Emit label as proper C label if it's a target of any branch/jump,
        # otherwise as a comment for readability.
        if label in jump_targets:
            self._lines.append(f'{indent_str}{label}:')
        else:
            self._lines.append(f'{indent_str}// {label}')

        # Emit body instructions (up to first terminator)
        body_instrs = []
        for instr in bb.instructions:
            if isinstance(instr, (IRBranch, IRJump, IRReturn)):
                term = instr
                break
            body_instrs.append(instr)

        for instr in body_instrs:
            if hasattr(instr, 'line') and instr.line > 0:
                self._track_source(instr.line)
            c_line = self._instr_c(instr)
            if c_line:
                self._lines.append(f'{indent_str}{c_line}')
                self._record_mapping(len(self._lines) - 1)

        if term is None:
            # Fall-through: continue to any unvisited successor
            for tgt in succ.get(label, []):
                if tgt not in emitted:
                    self._emit_cfg_region(tgt, labels, succ, pred,
                                         order, back_edges, emitted, indent,
                                         loop_headers, no_inline_targets, jump_targets)
            return

        if isinstance(term, IRReturn):
            self._lines.append(f'{indent_str}{self._instr_c(term)}')
            return

        if isinstance(term, IRJump):
            target = term.label
            is_back_edge = (label, target) in back_edges or target in loop_headers
            if is_back_edge:
                # Back-edge to loop header — emit goto to form the loop
                self._lines.append(f'{indent_str}goto {target};')
                return
            if target in no_inline_targets:
                # Don't inline this target (structured if merge point)
                # Emit goto and let the target be visited separately
                self._lines.append(f'{indent_str}goto {target};')
                return
            if target not in emitted:
                # Forward jump — inline the target block
                self._emit_cfg_region(target, labels, succ, pred,
                                     order, back_edges, emitted, indent,
                                     loop_headers, no_inline_targets, jump_targets)
            else:
                # Jump to already emitted block — emit goto
                self._lines.append(f'{indent_str}goto {target};')
            return

        if isinstance(term, IRBranch):
            cond = self._value_c(term.cond)
            true_label = term.true_label
            false_label = term.false_label

            # Try structured if/else for simple patterns
            true_path = labels.get(true_label)
            false_path = labels.get(false_label)

            true_is_return = (true_path and isinstance(true_path.terminator, IRReturn))
            true_is_jump = (true_path and isinstance(true_path.terminator, IRJump))
            false_is_return = (false_path and isinstance(false_path.terminator, IRReturn))

            # Simple guard: if (cond) { return X; } then continue
            if true_is_return and not false_is_return:
                self._lines.append(f'{indent_str}if ({cond}) {{')
                self._emit_cfg_region(true_label, labels, succ, pred,
                                     order, back_edges, emitted, indent + 1,
                                     loop_headers, no_inline_targets, jump_targets)
                self._lines.append(f'{indent_str}}}')
                if false_label not in emitted:
                    self._emit_cfg_region(false_label, labels, succ, pred,
                                         order, back_edges, emitted, indent,
                                         loop_headers, no_inline_targets, jump_targets)
                return

            # Simple if/else: both branches return
            if true_is_return and false_is_return:
                self._lines.append(f'{indent_str}if ({cond}) {{')
                self._emit_cfg_region(true_label, labels, succ, pred,
                                     order, back_edges, emitted, indent + 1,
                                     loop_headers, no_inline_targets, jump_targets)
                self._lines.append(f'{indent_str}}} else {{')
                self._emit_cfg_region(false_label, labels, succ, pred,
                                     order, back_edges, emitted, indent + 1,
                                     loop_headers, no_inline_targets, jump_targets)
                self._lines.append(f'{indent_str}}}')
                return

            # Simple if with merge: if (cond) { ... } then continuation
            # Check if true path merges back to false path (no else)
            if not false_is_return and self._reaches(true_label, false_label,
                                                     labels, succ, back_edges, set()):
                self._lines.append(f'{indent_str}if ({cond}) {{')
                # Prevent inlining of the merge point (false_label) from inside
                # the then-block's IRJump. This keeps the merge point code AFTER
                # the if body, not inside it.
                self._emit_cfg_region(true_label, labels, succ, pred,
                                     order, back_edges, emitted, indent + 1,
                                     loop_headers,
                                     no_inline_targets=no_inline_targets | {false_label},
                                     jump_targets=jump_targets)
                self._lines.append(f'{indent_str}}}')
                if false_label not in emitted:
                    self._emit_cfg_region(false_label, labels, succ, pred,
                                         order, back_edges, emitted, indent,
                                         loop_headers, no_inline_targets, jump_targets)
                return

            # elif chain detection
            if true_is_jump and false_path and isinstance(false_path.terminator, IRBranch):
                # Extract the merge point (end label) from the true path's IRJump.
                # Both the false_label (elif chain) AND the merge point (end)
                # must be blocked from inlining to keep continuation code AFTER
                # the if body, not inside it.
                true_jump_target = true_path.terminator.label
                self._lines.append(f'{indent_str}if ({cond}) {{')
                self._emit_cfg_region(true_label, labels, succ, pred,
                                     order, back_edges, emitted, indent + 1,
                                     loop_headers,
                                     no_inline_targets=no_inline_targets | {false_label, true_jump_target},
                                     jump_targets=jump_targets)
                # Close the if body; _emit_cfg_else_chain will emit 'else if' or 'else'
                self._lines.append(f'{indent_str}}}')
                if false_label not in emitted:
                    self._emit_cfg_else_chain(false_label, labels, succ, pred,
                                              order, back_edges, emitted, indent,
                                              loop_headers, no_inline_targets, jump_targets,
                                              merge_target=true_jump_target)
                return

            # If true path is jump and false path is jump: structured if/else
            if true_is_jump and false_path and isinstance(false_path.terminator, IRJump):
                true_jump_target = true_path.terminator.label
                self._lines.append(f'{indent_str}if ({cond}) {{')
                self._emit_cfg_region(true_label, labels, succ, pred,
                                     order, back_edges, emitted, indent + 1,
                                     loop_headers,
                                     no_inline_targets=no_inline_targets | {false_label, true_jump_target},
                                     jump_targets=jump_targets)
                self._lines.append(f'{indent_str}}} else {{')
                self._emit_cfg_region(false_label, labels, succ, pred,
                                     order, back_edges, emitted, indent + 1,
                                     loop_headers, no_inline_targets, jump_targets)
                self._lines.append(f'{indent_str}}}')
                return

            # Fallback: goto-based branch (always correct)
            self._lines.append(
                f'{indent_str}if ({cond}) goto {true_label}; else goto {false_label};'
            )
            if true_label not in emitted:
                self._emit_cfg_region(true_label, labels, succ, pred,
                                     order, back_edges, emitted, indent,
                                     loop_headers, no_inline_targets, jump_targets)
            if false_label not in emitted:
                self._emit_cfg_region(false_label, labels, succ, pred,
                                     order, back_edges, emitted, indent,
                                     loop_headers, no_inline_targets, jump_targets)
            return

    def _emit_cfg_else_chain(self, label, labels, succ, pred, order, back_edges,
                             emitted, indent, loop_headers=None,
                             no_inline_targets=None, jump_targets=None,
                             merge_target=None, skip_else=False):
        """Emit the 'else if' chain from a branch point.

        Args:
            merge_target: The end label (merge point) that all elif/else body IRJumps
                          target. This is blocked from inlining inside the bodies.
            skip_else: If True, we are already inside an else block from a parent
                       elif with body_instrs; don't emit another else wrapper.
        """
        if loop_headers is None:
            loop_headers = set()
        if no_inline_targets is None:
            no_inline_targets = set()
        if jump_targets is None:
            jump_targets = set()

        if label in emitted or label not in labels:
            return

        emitted.add(label)
        bb = labels[label]
        term = bb.terminator
        indent_str = '  ' * indent

        # Collect body instructions (condition computation for elif).
        body_instrs = []
        for instr in bb.instructions:
            if isinstance(instr, (IRBranch, IRJump, IRReturn)):
                term = instr
                break
            body_instrs.append(instr)

        if isinstance(term, IRBranch):
            cond = self._value_c(term.cond)
            true_label = term.true_label
            false_label = term.false_label

            true_path = labels.get(true_label)
            false_path = labels.get(false_label)

            true_is_jump = (true_path and isinstance(true_path.terminator, IRJump))
            false_is_branch = (false_path and isinstance(false_path.terminator, IRBranch))
            false_is_jump = (false_path and isinstance(false_path.terminator, IRJump))

            elif_jump_target = None
            if true_is_jump:
                elif_jump_target = true_path.terminator.label
            blocked_targets = no_inline_targets | {false_label}
            if elif_jump_target:
                blocked_targets = blocked_targets | {elif_jump_target}
            if merge_target:
                blocked_targets = blocked_targets | {merge_target}

            if body_instrs:
                # Condition computation exists — wrap in else block
                if not skip_else:
                    self._lines.append(f'{indent_str}else {{')
                    inner = indent + 1
                else:
                    inner = indent
                inner_str = '  ' * inner

                for instr in body_instrs:
                    c_line = self._instr_c(instr)
                    if c_line:
                        self._lines.append(f'{inner_str}{c_line}')

                body_indent = inner + 1
                self._lines.append(f'{inner_str}if ({cond}) {{')
                self._emit_cfg_region(true_label, labels, succ, pred,
                                     order, back_edges, emitted, body_indent,
                                     loop_headers,
                                     no_inline_targets=blocked_targets,
                                     jump_targets=jump_targets)
                self._lines.append(f'{inner_str}}}')

                # Handle else branch: recurse with skip_else=True since we're inside else
                if false_label not in emitted:
                    if false_is_branch or false_is_jump:
                        self._lines.append(f'{inner_str}else {{')
                        if false_is_branch:
                            self._emit_cfg_else_chain(false_label, labels, succ, pred,
                                                      order, back_edges, emitted, inner + 1,
                                                      loop_headers, no_inline_targets, jump_targets,
                                                      merge_target=merge_target, skip_else=True)
                        else:
                            else_blocked = no_inline_targets
                            if merge_target:
                                else_blocked = else_blocked | {merge_target}
                            self._emit_cfg_region(false_label, labels, succ, pred,
                                                 order, back_edges, emitted, inner + 1,
                                                 loop_headers, else_blocked, jump_targets)
                        self._lines.append(f'{inner_str}}}')

                if not skip_else:
                    self._lines.append(f'{indent_str}}}')
            elif skip_else:
                # Inside else block already, no body_instrs — emit plain if
                self._lines.append(f'{indent_str}if ({cond}) {{')
                self._emit_cfg_region(true_label, labels, succ, pred,
                                     order, back_edges, emitted, indent + 1,
                                     loop_headers,
                                     no_inline_targets=blocked_targets,
                                     jump_targets=jump_targets)
                self._lines.append(f'{indent_str}}}')

                if false_label not in emitted:
                    if false_is_branch or false_is_jump:
                        self._lines.append(f'{indent_str}else {{')
                        if false_is_branch:
                            self._emit_cfg_else_chain(false_label, labels, succ, pred,
                                                      order, back_edges, emitted, indent + 1,
                                                      loop_headers, no_inline_targets, jump_targets,
                                                      merge_target=merge_target, skip_else=True)
                        else:
                            else_blocked = no_inline_targets
                            if merge_target:
                                else_blocked = else_blocked | {merge_target}
                            self._emit_cfg_region(false_label, labels, succ, pred,
                                                 order, back_edges, emitted, indent + 1,
                                                 loop_headers, else_blocked, jump_targets)
                        self._lines.append(f'{indent_str}}}')
            else:
                # No body_instrs, not skipped — clean else if
                self._lines.append(f'{indent_str}else if ({cond}) {{')
                self._emit_cfg_region(true_label, labels, succ, pred,
                                     order, back_edges, emitted, indent + 1,
                                     loop_headers,
                                     no_inline_targets=blocked_targets,
                                     jump_targets=jump_targets)
                self._lines.append(f'{indent_str}}}')

                if false_label not in emitted:
                    if false_is_branch:
                        self._emit_cfg_else_chain(false_label, labels, succ, pred,
                                                  order, back_edges, emitted, indent,
                                                  loop_headers, no_inline_targets, jump_targets,
                                                  merge_target=merge_target)
                    elif false_is_jump:
                        self._lines.append(f'{indent_str}else {{')
                        else_blocked = no_inline_targets
                        if merge_target:
                            else_blocked = else_blocked | {merge_target}
                        self._emit_cfg_region(false_label, labels, succ, pred,
                                             order, back_edges, emitted, indent + 1,
                                             loop_headers, else_blocked, jump_targets)
                        self._lines.append(f'{indent_str}}}')
            return

        if isinstance(term, IRJump):
            target = term.label
            is_back_edge = (label, target) in back_edges or target in loop_headers
            if not is_back_edge and target not in no_inline_targets and target not in emitted:
                if not skip_else:
                    self._lines.append(f'{indent_str}else {{')
                else_blocked = no_inline_targets
                if merge_target:
                    else_blocked = else_blocked | {merge_target}
                self._emit_cfg_region(target, labels, succ, pred,
                                     order, back_edges, emitted, indent + 1,
                                     loop_headers, else_blocked, jump_targets)
                if not skip_else:
                    self._lines.append(f'{indent_str}}}')
            return

        if isinstance(term, IRReturn):
            if not skip_else:
                self._lines.append(f'{indent_str}else {{')
            self._lines.append(f'{indent_str}  {self._instr_c(term)}')
            if not skip_else:
                self._lines.append(f'{indent_str}}}')
            return

    def _reaches(self, start, target, labels, succ, back_edges, visited):
        """Check if start label can reach target via successors."""
        if start == target:
            return True
        if start in visited or start not in labels:
            return False
        visited.add(start)
        for tgt in succ.get(start, []):
            if (start, tgt) not in back_edges:
                if self._reaches(tgt, target, labels, succ, back_edges, visited):
                    return True
        return False

    def _emit_setup(self, module: IRModule) -> None:
        self._section('SETUP')
        self._lines.append('void setup(void) {')
        hal = self._hal
        # Check if Serial.begin is already emitted by user setup blocks
        user_has_serial_begin = any(
            'Serial.begin' in code or 'serial_begin' in code
            for code in module.setup_blocks
        )
        # Also check _iotift_setup function for Serial.begin
        if not user_has_serial_begin:
            for fn in module.functions:
                if fn.name == '_iotift_setup':
                    for bb in fn.blocks:
                        for instr in bb.instructions:
                            if isinstance(instr, IRCallIndirect):
                                if 'Serial.begin' in instr.func_expr:
                                    user_has_serial_begin = True
                                    break
        if not user_has_serial_begin:
            self._lines.append(f'  {hal.serial_begin(self._baud)}' if hal else f'  Serial.begin({self._baud}UL);')

        # Pin modes
        for name, number in self._pins.items():
            if name in self._pwm_pins:
                continue
            # Determine direction from pin declaration (stored in module)
            pin_dir = module.pin_directions.get(name, 'output')
            if pin_dir in _PIN_DIRECTION:
                dir_str = _PIN_DIRECTION[pin_dir]
            elif name in self._on_pins:
                dir_str = 'INPUT_PULLUP'
            else:
                dir_str = 'OUTPUT'
            if hal:
                self._lines.append(f'  {hal.pin_mode(f"{name}_PIN", dir_str)}')
            else:
                self._lines.append(f'  pinMode({name}_PIN, {dir_str});')

        # PWM setup
        for pin_name, info in self._pwm_pins.items():
            ch = info.get('channel', 0)
            freq = info.get('freq', 5000)
            res = info.get('resolution', 8)
            num = info.get('number', 0)
            if hal:
                for line in hal.pwm_setup(ch, freq, res):
                    self._lines.append(f'  {line}')
                self._lines.append(f'  {hal.pwm_attach(num, ch)}')
            else:
                self._lines.append(f'  ledcSetup({ch}U, {freq}, {res});')
                self._lines.append(f'  ledcAttachPin({num}U, {ch}U);')

        # Initialize timer baselines
        for eh in module.every_handlers:
            time_var = eh.get('time_var', '')
            if time_var:
                self._lines.append(f'  {time_var} = millis();')

        # Attach hardware interrupts (Phase 3)
        for irq in module.interrupts:
            pin = irq['pin']
            mode = irq['mode']
            isr = irq['isr_name']
            if hal:
                self._lines.append(f'  {hal.attach_interrupt(f"{pin}_PIN", isr, mode)}')
            else:
                self._lines.append(
                    f'  attachInterrupt(digitalPinToInterrupt({pin}_PIN), {isr}, {mode});'
                )

        # Top-level setup statements (from _iotift_setup function)
        for fn in module.functions:
            if fn.name == '_iotift_setup':
                for bb in fn.blocks:
                    for instr in bb.instructions:
                        c_line = self._instr_c(instr)
                        if c_line:
                            self._lines.append(f'  {c_line}')

        # User c setup blocks
        for code in module.setup_blocks:
            for ln in _dedent(code).split('\n'):
                self._lines.append('  ' + ln)

        # Run tick block once at startup (not in loop)
        for fn in module.functions:
            if fn.name == '_iotift_tick':
                self._lines.append('  _iotift_tick();')
                break

        self._lines.append('}')
        self._lines.append('')

    def _emit_main_loop(self, module: IRModule) -> None:
        self._section('MAIN LOOP')
        self._lines.append('void loop(void) {')

        # Collect loop calls from handlers
        for eh in module.every_handlers:
            self._loop_calls.append(f'{eh["name"]}();')
        for eh in module.on_event_handlers:
            self._loop_calls.append(f'{eh["name"]}();')
        for eh in module.on_threshold_handlers:
            self._loop_calls.append(f'{eh["name"]}();')

        # Also check for loop/user_loop functions (tick runs in setup, not loop)
        handler_names = {h['name'] for h in
                         module.every_handlers + module.on_event_handlers + module.on_threshold_handlers}
        for fn in module.functions:
            if fn.name in ('_iotift_handle_loop', 'user_loop'):
                if fn.name not in handler_names:
                    self._loop_calls.append(f'{fn.name}();')

        for call in sorted(set(self._loop_calls)):
            self._lines.append('  ' + call)

        for code in module.loop_blocks:
            for ln in _dedent(code).split('\n'):
                self._lines.append('  ' + ln)

        self._lines.append('  yield();')
        self._lines.append('}')
        self._lines.append('')

    # ─────────────────────────────────────────
    #  INSTRUCTION → C
    # ─────────────────────────────────────────

    def _instr_c(self, instr) -> str:
        """Convert a single IR instruction to a C statement."""

        if isinstance(instr, IRLabel):
            return f'// {instr.label}:'

        if isinstance(instr, IRCopy):
            src = self._value_c(instr.src)
            dst = self._value_c(instr.dest)
            return f'{dst} = {src};'

        if isinstance(instr, IRBinary):
            left = self._value_c(instr.left)
            right = self._value_c(instr.right)
            op = instr.op
            dst = self._value_c(instr.dest)
            result = f'{left} {op} {right}'
            return f'{dst} = {result};'

        if isinstance(instr, IRUnary):
            operand = self._value_c(instr.operand)
            dst = self._value_c(instr.dest)
            return f'{dst} = {instr.op}{operand};'

        if isinstance(instr, IRLoad):
            src = self._value_c(instr.src)
            dst = self._value_c(instr.dest)
            return f'{dst} = {src};'

        if isinstance(instr, IRStore):
            src = self._value_c(instr.src)
            dst = self._value_c(instr.dest)
            return f'{dst} = {src};'

        if isinstance(instr, IRCall):
            args = ', '.join(self._value_c(a) for a in instr.args)
            if instr.func == 'breakpoint':
                if self._hal:
                    return self._hal.breakpoint_instruction() + ';'
                return '/* breakpoint */'
            if instr.dest:
                dst = self._value_c(instr.dest)
                return f'{dst} = {instr.func}({args});'
            return f'{instr.func}({args});'

        if isinstance(instr, IRCallIndirect):
            # For method calls and HAL calls, the func_expr contains the full expression
            args = ', '.join(self._value_c(a) for a in instr.args)
            expr = instr.func_expr
            if instr.dest:
                dst = self._value_c(instr.dest)
                if '(' in expr:
                    return f'{dst} = {expr};'
                else:
                    return f'{dst} = {expr}({args});'
            else:
                if '(' in expr:
                    return f'{expr};'
                elif expr.strip():
                    return f'{expr}({args});'
                else:
                    return f'// ({args});'

        if isinstance(instr, IRBranch):
            cond = self._value_c(instr.cond)
            return f'if ({cond}) goto {instr.true_label}; else goto {instr.false_label};'

        if isinstance(instr, IRJump):
            return f'goto {instr.label};'

        if isinstance(instr, IRReturn):
            if instr.value:
                val = self._value_c(instr.value)
                return f'return {val};'
            return 'return;'

        if isinstance(instr, IRCast):
            src = self._value_c(instr.src)
            dst = self._value_c(instr.dest)
            ct = instr.target_type
            return f'{dst} = (({ct})({src}));'

        if isinstance(instr, IRMemberAccess):
            obj = self._value_c(instr.obj)
            dst = self._value_c(instr.dest)
            return f'{dst} = {obj}.{instr.member};'

        if isinstance(instr, IRArrayAccess):
            base = self._value_c(instr.base)
            idx = self._value_c(instr.index)
            dst = self._value_c(instr.dest)
            return f'{dst} = {base}[{idx}];'

        return f'// unhandled: {type(instr).__name__}'

    # ─────────────────────────────────────────
    #  VALUE → C STRING
    # ─────────────────────────────────────────

    def _value_c(self, val: Any) -> str:
        """Convert an IRValue or constant to a C string."""
        if isinstance(val, IRValue):
            if val.kind == 'const':
                return self._const_c(val)
            if val.kind == 'void':
                return ''
            return val.name
        if isinstance(val, bool):
            return 'true' if val else 'false'
        if isinstance(val, (int, float)):
            return str(val)
        if isinstance(val, str):
            return val
        return str(val)

    def _const_c(self, val: IRValue) -> str:
        """Format a constant value for C."""
        v = val.const_value
        ctype = val.ctype
        if ctype == 'str' or ctype == 'const char*':
            return f'"{v}"'
        if ctype == 'bool':
            return 'true' if v else 'false'
        if ctype == 'char':
            if v == '\n': return "'\\n'"
            if v == '\t': return "'\\t'"
            if v == '\r': return "'\\r'"
            if v == '\\': return "'\\\\'"
            if v == '\'': return "'\\''"
            return f"'{v}'"
        return str(v)

    # ─────────────────────────────────────────
    #  HELPERS
    # ─────────────────────────────────────────

    def _map_ctype(self, name: str) -> str:
        mapping = {
            'int': 'int', 'float': 'float', 'bool': 'bool',
            'str': 'const char*', 'char': 'char', 'void': 'void',
            'u8': 'uint8_t', 'u16': 'uint16_t', 'u32': 'uint32_t', 'u64': 'uint64_t',
            'i8': 'int8_t', 'i16': 'int16_t', 'i32': 'int32_t', 'i64': 'int64_t',
            'f32': 'float', 'f64': 'double', 'uint': 'unsigned int',
        }
        return mapping.get(name, name)

    def _section(self, title: str) -> None:
        self._lines.append('')
        self._lines.append(
            '/* ========================================'
            '============================================'
        )
        self._lines.append(f' *  {title}')
        self._lines.append(
            ' * ========================================'
            '============================================ */'
        )
        self._lines.append('')

    # ─────────────────────────────────────────
    #  STRUCTURED CONTROL FLOW
    # ─────────────────────────────────────────
    # (Replaced by topological block ordering in _emit_function)
