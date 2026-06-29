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

__version__ = "1.1.0"


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
        if uses_math:
            self._lines.append('#include <math.h>')
        for inc in sorted(module.includes):
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
            if g.init is not None:
                init_str = self._value_c(g.init)
                self._lines.append(f'{prefix}{g.ctype} {g.name} = {init_str};')
            else:
                self._lines.append(f'{prefix}{g.ctype} {g.name};')
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
        temp_vars: set = set()
        for bb in fn.blocks:
            for instr in bb.instructions:
                if isinstance(instr, (IRBinary, IRUnary, IRCall, IRCast, IRArrayAccess, IRMemberAccess)):
                    if instr.dest and instr.dest.kind == 'temp':
                        temp_vars.add(instr.dest)
                elif isinstance(instr, IRCopy):
                    if instr.dest.kind == 'temp':
                        temp_vars.add(instr.dest)
                    if instr.src.kind == 'temp':
                        temp_vars.add(instr.src)

        for tv in sorted(temp_vars, key=lambda v: v.name):
            self._lines.append(f'  {tv.ctype} {tv.name};')

        # Emit declared locals
        for local in fn.locals:
            self._lines.append(f'  {local.ctype} {local.name};')

        if temp_vars or fn.locals:
            self._lines.append('')

        # Use structured if/else for simple branch patterns
        blocks = fn.blocks
        if self._is_simple_if_else(blocks):
            self._emit_structured_if(blocks)
        else:
            for bb in blocks:
                if bb.label != fn.entry_block and bb.label:
                    self._lines.append(f'  // {bb.label}')
                for instr in bb.instructions:
                    # Track source line from IR instruction
                    if hasattr(instr, 'line') and instr.line > 0:
                        self._track_source(instr.line)
                    c_line = self._instr_c(instr)
                    if c_line:
                        self._lines.append(f'  {c_line}')
                        self._record_mapping(len(self._lines) - 1)

        self._lines.append('}')
        self._lines.append('')

    def _emit_setup(self, module: IRModule) -> None:
        self._section('SETUP')
        self._lines.append('void setup(void) {')
        hal = self._hal
        self._lines.append(f'  {hal.serial_begin(self._baud)}' if hal else f'  Serial.begin({self._baud}UL);')

        # Pin modes
        for name, number in self._pins.items():
            if name in self._pwm_pins:
                continue
            dir_str = (
                'INPUT_PULLUP' if name in self._on_pins
                else _PIN_DIRECTION.get('output', 'OUTPUT')
            )
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

        # Also check for tick/loop/user_loop functions
        handler_names = {h['name'] for h in
                         module.every_handlers + module.on_event_handlers + module.on_threshold_handlers}
        for fn in module.functions:
            if fn.name in ('_iotift_tick', '_iotift_handle_loop', 'user_loop'):
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

    def _is_simple_if_else(self, blocks: List[BasicBlock]) -> bool:
        """Check if blocks form a simple if-then-else pattern."""
        if len(blocks) < 3:
            return False
        # Entry block terminates with a branch
        entry = blocks[0]
        if not isinstance(entry.terminator, IRBranch):
            return False
        return True

    def _emit_structured_if(self, blocks: List[BasicBlock]) -> None:
        """Emit blocks as structured if/else instead of goto."""
        entry = blocks[0]
        branch = entry.terminator
        if not isinstance(branch, IRBranch):
            # Fallback: emit raw
            for bb in blocks:
                for instr in bb.instructions:
                    c_line = self._instr_c(instr)
                    if c_line:
                        self._lines.append(f'  {c_line}')
            return

        # Emit non-terminator instructions from entry block
        for instr in entry.instructions:
            if isinstance(instr, IRBranch):
                continue
            if hasattr(instr, 'line') and instr.line > 0:
                self._track_source(instr.line)
            c_line = self._instr_c(instr)
            if c_line:
                self._lines.append(f'  {c_line}')
                self._record_mapping(len(self._lines) - 1)

        cond = self._value_c(branch.cond)
        true_label = branch.true_label
        false_label = branch.false_label

        # Find the true/end blocks
        true_block = None
        end_block = None
        for bb in blocks:
            if bb.label == true_label:
                true_block = bb
            if bb.label == false_label:
                end_block = bb

        self._lines.append(f'  if ({cond}) {{')

        # Emit true block
        if true_block:
            for instr in true_block.instructions:
                if isinstance(instr, (IRBranch, IRJump)):
                    continue
                if hasattr(instr, 'line') and instr.line > 0:
                    self._track_source(instr.line)
                c_line = self._instr_c(instr)
                if c_line:
                    self._lines.append(f'    {c_line}')
                    self._record_mapping(len(self._lines) - 1)

        self._lines.append(f'  }}')

        # Emit remaining blocks after the if (end block, etc.)
        emitted_labels = {entry.label, true_label}
        for bb in blocks:
            if bb.label in emitted_labels:
                continue
            emitted_labels.add(bb.label)
            if bb.label != entry.label and bb.label:
                pass  # skip label comments for structured
            for instr in bb.instructions:
                if isinstance(instr, (IRJump, IRReturn)) and isinstance(instr, IRReturn):
                    if hasattr(instr, 'line') and instr.line > 0:
                        self._track_source(instr.line)
                    c_line = self._instr_c(instr)
                    if c_line:
                        self._lines.append(f'  {c_line}')
                        self._record_mapping(len(self._lines) - 1)
                elif not isinstance(instr, (IRJump,)):
                    if hasattr(instr, 'line') and instr.line > 0:
                        self._track_source(instr.line)
                    c_line = self._instr_c(instr)
                    if c_line:
                        self._lines.append(f'  {c_line}')
                        self._record_mapping(len(self._lines) - 1)
