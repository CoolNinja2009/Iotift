"""
IOTIFT Code Generator — Milestone 0

Walks the AST and produces production-quality C++ for ESP32 (Arduino framework).
"""

from __future__ import annotations
from datetime import datetime, timezone
from ast_nodes import *
from typing import List, Any, Optional
import re

__version__ = "2.0.0"


class CodeGenError(Exception):
    """Raised when code generation encounters an unhandled node."""
    pass


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


# ─────────────────────────────────────────
#  DEVICE CONFIG  (ESP32 only)
# ─────────────────────────────────────────

_PIN_DIRECTION = {
    'output': 'OUTPUT',
    'input':  'INPUT_PULLUP',
    'analog': 'INPUT',
    'i2c':    'INPUT',
    'pwm':    'OUTPUT',
}

_CTYPE = {
    'int':   'int',
    'float': 'float',
    'bool':  'bool',
    'str':   'const char*',
    'char':  'char',
    'void':  'void',
    'u8':    'uint8_t',
    'u16':   'uint16_t',
    'u32':   'uint32_t',
    'u64':   'uint64_t',
    'i8':    'int8_t',
    'i16':   'int16_t',
    'i32':   'int32_t',
    'i64':   'int64_t',
    'f32':   'float',
    'f64':   'double',
    'uint':  'unsigned int',
}


class CodeGen:
    """AST → production C++ for ESP32 (Arduino framework)."""

    def __init__(self, device: str = 'esp32',
                 baud_rate: int = 115200,
                 scheduler_slots: int = 16) -> None:
        self._device = device
        self._baud = baud_rate
        self._max_tasks = scheduler_slots

        # ── accumulation buffers ──
        self._lines: List[str] = []

        # ── pin registry ──
        self._pins: dict[str, PinDecl] = {}
        self._pwm_pins: dict[str, dict] = {}
        self._pwm_channel: int = 0

        # ── timer / event state ──
        self._every_count: int = 0
        self._every_labels: dict[str, str] = {}     # label → active-var name
        self._every_time_vars: List[str] = []
        self._scheduler_needed: bool = False
        self._on_pins: set[str] = set()

        # ── output sections ──
        self._declared_vars: set[str] = set()
        self._header_blocks: List[str] = []
        self._global_blocks: List[str] = []
        self._global_state: List[str] = []
        self._user_fns: List[List[str]] = []
        self._handler_fns: List[List[str]] = []
        self._setup_lines: List[str] = []
        self._setup_blocks: List[str] = []
        self._loop_calls: List[str] = []
        self._loop_blocks: List[str] = []
        self._includes: set[str] = set()
        self._uses_math: bool = False
        self._enums: dict[str, EnumDecl] = {}

    # ─────────────────────────────────────────
    #  PUBLIC ENTRY
    # ─────────────────────────────────────────

    def generate(self, program: Program) -> str:
        """Produce the final C++ source string for *program*."""
        for node in program.body:
            self._collect(node)

        self._emit_file_header()
        self._emit_includes()
        self._emit_config_defines()
        self._emit_pin_macros()
        self._emit_enums()
        self._emit_global_blocks()
        self._emit_global_state()
        self._emit_scheduler()
        self._emit_user_fns()
        self._emit_handler_fns()
        self._emit_setup()
        self._emit_main_loop()

        return '\n'.join(self._lines)

    # ─────────────────────────────────────────
    #  COLLECT PASS  (first pass — register, don't emit)
    # ─────────────────────────────────────────

    def _collect(self, node: Node) -> None:
        if isinstance(node, DeviceDecl):
            self._device = node.name

        elif isinstance(node, ImportDecl):
            import sys
            print(
                f"Warning: import \"{node.path}\" is not resolved — skipping.",
                file=sys.stderr,
            )
            self._global_state.append(f'// import "{node.path}" (unresolved)')

        elif isinstance(node, PinDecl):
            self._collect_pin(node)

        elif isinstance(node, VarDecl):
            self._global_state.append(self._var_decl_c(node))

        elif isinstance(node, ArrayDecl):
            ct = _CTYPE.get(node.vtype, node.vtype)
            self._global_state.append(f"{ct} {node.name}[{node.size}];")

        elif isinstance(node, StructDecl):
            lines = [f"struct {node.name} {{"]
            for f in node.fields:
                ct = _CTYPE.get(f.vtype, f.vtype)
                lines.append(f"  {ct} {f.name};")
            lines.append("};")
            self._global_state.extend(lines)

        elif isinstance(node, EnumDecl):
            self._enums[node.name] = node

        elif isinstance(node, TypeAliasDecl):
            ct = _CTYPE.get(node.aliased_type, node.aliased_type)
            self._global_state.append(f"typedef {ct} {node.name};")

        elif isinstance(node, PeripheralDecl):
            # Emit as comment for now; full HAL integration in Milestone 3
            cfg_str = ', '.join(f'{k}: {v}' for k, v in node.config.items())
            self._global_state.append(
                f"// {node.periph_type} {node.name} {{ {cfg_str} }}"
            )

        elif isinstance(node, FnDecl):
            self._collect_fn_decl(node)

        elif isinstance(node, ExternFnDecl):
            ret = node.return_type or 'void'
            rt = _CTYPE.get(ret, ret)
            params = ', '.join(
                f"{_CTYPE.get(p.vtype, p.vtype)} {p.name}" for p in node.params
            ) or 'void'
            self._global_state.append(f"extern {rt} {node.name}({params});")

        elif isinstance(node, CBlockNode):
            if not node.code.strip():
                return
            target = {
                'header': self._header_blocks,
                'global': self._global_blocks,
                'setup':  self._setup_blocks,
                'loop':   self._loop_blocks,
            }.get(node.scope, self._global_blocks)
            target.append(node.code)

        elif isinstance(node, OnEvent):
            self._collect_on_event(node)

        elif isinstance(node, OnThreshold):
            self._collect_on_threshold(node)

        elif isinstance(node, EveryBlock):
            self._collect_every(node)

        elif isinstance(node, LoopBlock):
            self._collect_loop_block(node)

        elif isinstance(node, VoidLoop):
            body_lines = [
                ln for s in node.body for ln in self._stmt_lines(s)
            ]
            self._user_fns.append(
                self._make_fn('void', 'user_loop', '', body_lines)
            )
            self._loop_calls.append('user_loop();')

        elif isinstance(node, TickBlock):
            body_lines = [
                ln for s in node.body for ln in self._stmt_lines(s)
            ]
            self._user_fns.append(
                self._make_fn('void', '_iotift_tick', '', body_lines)
            )
            self._loop_calls.append('_iotift_tick();')

        elif isinstance(node, PwmSetup):
            # Top-level PwmSetup overrides defaults before setup() is emitted.
            if node.pin in self._pwm_pins:
                self._pwm_pins[node.pin]['freq'] = self._expr_c(node.freq)
                self._pwm_pins[node.pin]['resolution'] = self._expr_c(node.resolution)

        elif isinstance(node, DeferStmt):
            # Defer is a no-op at top level; only meaningful inside functions.
            pass

        elif isinstance(node, (Assign, CompoundAssign, FnCall, MethodCall,
                                PrintStmt, PwmWrite, ExprStmt)):
            self._setup_lines.extend(self._stmt_lines(node))

        elif isinstance(node, AssignAfter):
            self._scheduler_needed = True
            self._setup_lines.extend(self._stmt_lines(node))

    # ─────────────────────────────────────────
    #  COLLECT HELPERS
    # ─────────────────────────────────────────

    def _collect_pin(self, node: PinDecl) -> None:
        if node.name not in self._pins:
            self._pins[node.name] = node
        if node.direction == 'pwm':
            ch = self._pwm_channel
            self._pwm_channel += 1
            self._pwm_pins[node.name] = {
                'number':     node.number,
                'channel':    ch,
                'freq':       node.pwm_freq or 5000,
                'resolution': node.pwm_resolution or 8,
            }

    def _collect_fn_decl(self, node: FnDecl) -> None:
        ret = node.return_type or 'void'
        rt = _CTYPE.get(ret, ret)
        params = ', '.join(
            f"{_CTYPE.get(p.vtype, p.vtype)} {p.name}" for p in node.params
        ) if node.params else ''
        body_lines = [
            ln for s in node.body for ln in self._stmt_lines(s, '  ')
        ]
        attrs = 'IRAM_ATTR ' if node.is_isr else ''
        self._user_fns.append(
            self._make_fn(f'{attrs}{rt}', node.name, params, body_lines)
        )

    def _collect_on_event(self, node: OnEvent) -> None:
        self._on_pins.add(node.pin)
        if self._needs_scheduler(node.body):
            self._scheduler_needed = True

        # Skip empty handlers
        if not node.body:
            return

        fn_name = f"_iotift_on_{node.pin}_{node.event}"
        last_var = f"_iotift_last_{node.pin}_state"
        if last_var not in self._declared_vars:
            self._declared_vars.add(last_var)
            self._global_state.append(f"static int {last_var} = HIGH;")

        cond = {
            'press':   f"_state == LOW  && {last_var} == HIGH",
            'release': f"_state == HIGH && {last_var} == LOW",
            'rising':  f"_state == HIGH && {last_var} == LOW",
            'falling': f"_state == LOW  && {last_var} == HIGH",
        }.get(node.event, f"_state != {last_var}")

        body: List[str] = [
            f"  int _state = digitalRead({node.pin}_PIN);",
            f"  if ({cond}) {{",
        ]
        for s in node.body:
            body.extend(self._stmt_lines(s, '    '))
        body.append('  }')
        body.append(f'  {last_var} = _state;')

        self._handler_fns.append(self._make_fn(
            'static void', fn_name, '', body,
        ))
        self._loop_calls.append(f"{fn_name}();")

    def _collect_on_threshold(self, node: OnThreshold) -> None:
        if not node.body:
            return
        fn_name = f"_iotift_threshold_{node.pin}"
        val = self._expr_c(node.value)
        body = [f"  if ({node.pin} {node.op} {val}) {{"]
        for s in node.body:
            body.extend(self._stmt_lines(s, '    '))
        body.append('  }')
        self._handler_fns.append(self._make_fn(
            'static void', fn_name, '', body,
        ))
        self._loop_calls.append(f"{fn_name}();")

    def _collect_every(self, node: EveryBlock) -> None:
        # Skip empty handlers
        if not node.body:
            return

        idx = self._every_count
        self._every_count += 1

        # Stable naming: use user label if available
        if node.label:
            fn_name = f"_iotift_every_{node.label}"
        else:
            fn_name = f"_iotift_every_{idx}"

        time_var = f"{fn_name}_last"
        active_var = f"{fn_name}_active" if node.label else None

        if active_var:
            self._global_state.append(f"static int {active_var} = 1;")
            self._every_labels[node.label] = active_var
        self._global_state.append(f"static unsigned long {time_var} = 0UL;")
        self._every_time_vars.append(time_var)

        if self._needs_scheduler(node.body):
            self._scheduler_needed = True

        inner: List[str] = [
            f"  unsigned long _now = millis();",
            f"  if ((_now - {time_var}) >= {node.interval}UL) {{",
            f"    {time_var} = _now;",
        ]
        for s in node.body:
            inner.extend(self._stmt_lines(s, '    '))
        inner.append('  }')

        if active_var:
            inner = [f"  if ({active_var}) {{"] + inner + ['  }']

        body = ['  ' + ln for ln in inner]
        self._handler_fns.append(self._make_fn(
            'static void', fn_name, '', body,
        ))
        self._loop_calls.append(f"{fn_name}();")

    def _collect_loop_block(self, node: LoopBlock) -> None:
        if not node.body:
            return
        body = [
            ln for s in node.body for ln in self._stmt_lines(s, '  ')
        ]
        self._handler_fns.append(self._make_fn(
            'static void', '_iotift_handle_loop', '', body,
        ))
        self._loop_calls.append('_iotift_handle_loop();')

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

    def _emit_includes(self) -> None:
        self._lines.append('#include <Arduino.h>')
        if self._uses_math:
            self._lines.append('#include <math.h>')
        for inc in sorted(self._includes):
            self._lines.append(inc)
        for code in self._header_blocks:
            self._lines.append(_dedent(code))
        if self._header_blocks:
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
        for name, pin in self._pins.items():
            # Use static const for type safety (not #define)
            if pin.direction in ('i2c',):
                self._lines.append(f'static const uint8_t {name}_PIN = {pin.number}U;')
            else:
                self._lines.append(f'static const uint8_t {name}_PIN = {pin.number}U;')
        self._lines.append('')

    def _emit_enums(self) -> None:
        if not self._enums:
            return
        self._section('ENUM DEFINITIONS')
        for name, enum in self._enums.items():
            bt = enum.backing_type or 'int'
            ct = _CTYPE.get(bt, bt)
            self._lines.append(f'typedef enum {{')
            for var_name, val in enum.variants:
                if val is not None:
                    self._lines.append(f'  {name}_{var_name} = {val},')
                else:
                    self._lines.append(f'  {name}_{var_name},')
            self._lines.append(f'}} {name};')
        self._lines.append('')

    def _emit_global_blocks(self) -> None:
        for code in self._global_blocks:
            self._lines.append(_dedent(code))
        if self._global_blocks:
            self._lines.append('')

    def _emit_global_state(self) -> None:
        if not self._global_state:
            return
        self._section('GLOBAL STATE')
        self._lines.extend(self._global_state)
        self._lines.append('')

    def _emit_scheduler(self) -> None:
        if not self._scheduler_needed:
            return
        self._section('INTERNAL SCHEDULER (deferred execution)')
        n = self._max_tasks
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
            f'#define IOTIFT_SCHEDULER_SLOTS    {n}U',
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
            '/**',
            ' * @brief  Schedule a deferred pin write (min-heap insert, O(log n)).',
            ' */',
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
            '  while (i > 0U) {',
            '    uint8_t parent = (i - 1U) >> 1U;',
            '    if (_iotift_scheduler[i].trigger_time >= _iotift_scheduler[parent].trigger_time) break;',
            '    _iotift_scheduler_swap(i, parent);',
            '    i = parent;',
            '  }',
            '}',
            '',
            '/**',
            ' * @brief  Schedule a deferred integer assignment (min-heap insert, O(log n)).',
            ' */',
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
            '  while (i > 0U) {',
            '    uint8_t parent = (i - 1U) >> 1U;',
            '    if (_iotift_scheduler[i].trigger_time >= _iotift_scheduler[parent].trigger_time) break;',
            '    _iotift_scheduler_swap(i, parent);',
            '    i = parent;',
            '  }',
            '}',
            '',
            '/**',
            ' * @brief  Process all due scheduled tasks (min-heap pop, O(log n) per task).',
            ' */',
            'static void _iotift_scheduler_tick(void) {',
            '  unsigned long now = millis();',
            '  while (_iotift_scheduler_size > 0U &&',
            '         _iotift_scheduler[0].trigger_time <= now) {',
            '    iotift_task_t task = _iotift_scheduler[0];',
            '    if (task.type == IOTIFT_TASK_PIN) {',
            '      digitalWrite(task.pin, task.pin_value);',
            '    } else if (task.type == IOTIFT_TASK_INT_VAR) {',
            '      *(task.var_ptr) = task.var_value;',
            '    }',
            '    _iotift_scheduler[0] = _iotift_scheduler[--_iotift_scheduler_size];',
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

    def _emit_user_fns(self) -> None:
        if not self._user_fns:
            return
        self._section('USER FUNCTIONS')
        for fn in self._user_fns:
            self._lines.extend(fn)
            self._lines.append('')

    def _emit_handler_fns(self) -> None:
        if not self._handler_fns:
            return
        self._section('EVENT & TIMER HANDLERS')
        for fn in self._handler_fns:
            self._lines.extend(fn)
            self._lines.append('')

    def _emit_setup(self) -> None:
        self._section('SETUP')
        self._lines.append('void setup(void) {')
        self._lines.append(f'  Serial.begin({self._baud}UL);')

        # ── digital / analog pins (skip PWM — uses LEDC, not pinMode) ──
        for name, pin in self._pins.items():
            if name in self._pwm_pins:
                continue
            dir_str = (
                'INPUT_PULLUP' if name in self._on_pins
                else _PIN_DIRECTION.get(pin.direction, 'OUTPUT')
            )
            self._lines.append(f'  pinMode({name}_PIN, {dir_str});')

        # ── PWM (LEDC) ──
        for pin_name, info in self._pwm_pins.items():
            ch = info['channel']
            freq = info['freq']
            res = info['resolution']
            num = info['number']
            self._lines.append(f'  ledcSetup({ch}U, {freq}, {res});')
            self._lines.append(f'  ledcAttachPin({num}U, {ch}U);')

        # ── initialise timer baselines ──
        for var in self._every_time_vars:
            self._lines.append(f'  {var} = millis();')

        # ── top-level statements ──
        for ln in self._setup_lines:
            self._lines.append('  ' + ln)

        # ── user c setup blocks ──
        for code in self._setup_blocks:
            for ln in _dedent(code).split('\n'):
                self._lines.append('  ' + ln)

        self._lines.append('}')
        self._lines.append('')

    def _emit_main_loop(self) -> None:
        self._section('MAIN LOOP')
        self._lines.append('void loop(void) {')
        for call in self._loop_calls:
            self._lines.append('  ' + call)
        for code in self._loop_blocks:
            for ln in _dedent(code).split('\n'):
                self._lines.append('  ' + ln)
        self._lines.append('  yield();')
        self._lines.append('}')
        self._lines.append('')

    # ─────────────────────────────────────────
    #  STATEMENT → LINES
    # ─────────────────────────────────────────

    def _stmt_lines(self, node: Node, indent: str = '') -> List[str]:
        """Convert any statement node to a list of indented C++ lines."""

        if isinstance(node, IfStmt):
            return self._if_lines(node, indent)
        if isinstance(node, WhileStmt):
            return self._while_lines(node, indent)
        if isinstance(node, ForStmt):
            return self._for_lines(node, indent)
        if isinstance(node, CBlockNode):
            return [
                (indent + ln) if ln else ''
                for ln in node.code.split('\n')
            ]
        if isinstance(node, ExprStmt):
            return [indent + self._expr_c(node.expr) + ';']
        if isinstance(node, DeferStmt):
            # Defer body is emitted at end of enclosing block.
            # For now, emit inline.
            lines: List[str] = []
            for s in node.body:
                lines.extend(self._stmt_lines(s, indent))
            return lines
        # Single-line statements
        return [indent + self._stmt_c(node)]

    def _stmt_c(self, node: Node) -> str:
        """Convert a single-line statement node to a C++ string."""

        # ── Assign ────────────────────────────
        if isinstance(node, Assign):
            target = self._target_c(node.target)

            # Digital-write short-cut for output pins.
            if isinstance(node.target, str) and node.target in self._pins \
                    and node.target not in self._pwm_pins:
                val = self._expr_c(node.value)
                if val in ('0', '1', 'true', 'false'):
                    level = 'HIGH' if val in ('1', 'true') else 'LOW'
                    return f'digitalWrite({node.target}_PIN, {level});'
                return f'digitalWrite({node.target}_PIN, ({val}) ? HIGH : LOW);'

            return f'{target} = {self._expr_c(node.value)};'

        # ── CompoundAssign ────────────────────
        if isinstance(node, CompoundAssign):
            return f'{node.target} {node.op} {self._expr_c(node.value)};'

        # ── AssignAfter ───────────────────────
        if isinstance(node, AssignAfter):
            val = self._expr_c(node.value)
            if node.target in self._pins and node.target not in self._pwm_pins:
                level = 'HIGH' if val in ('1', 'true') else 'LOW'
                return (
                    f'_iotift_schedule_pin({node.target}_PIN, {level}, {node.delay}UL);'
                )
            return (
                f'_iotift_schedule_int(&{node.target}, {val}, {node.delay}UL);'
            )

        # ── VarDecl ───────────────────────────
        if isinstance(node, VarDecl):
            return self._var_decl_c(node)

        # ── ArrayDecl ─────────────────────────
        if isinstance(node, ArrayDecl):
            ct = _CTYPE.get(node.vtype, node.vtype)
            return f'{ct} {node.name}[{node.size}];'

        # ── ReturnStmt ────────────────────────
        if isinstance(node, ReturnStmt):
            if node.value is None:
                return 'return;'
            return f'return {self._expr_c(node.value)};'

        # ── BreakStmt / ContinueStmt ──────────
        if isinstance(node, BreakStmt):
            return 'break;'
        if isinstance(node, ContinueStmt):
            return 'continue;'

        # ── PrintStmt ─────────────────────────
        if isinstance(node, PrintStmt):
            return self._print_c(node)

        # ── FnCall ────────────────────────────
        if isinstance(node, FnCall):
            args = ', '.join(self._expr_c(a) for a in node.args)
            if node.name == 'esp_restart':
                return 'ESP.restart();'
            if node.name == 'breakpoint':
                # Emit target-specific breakpoint instruction
                if self._device.startswith('esp32'):
                    return 'asm("break 0,0");'
                return '/* breakpoint */'
            return f'{node.name}({args});'

        # ── MethodCall ────────────────────────
        if isinstance(node, MethodCall):
            args = ', '.join(self._expr_c(a) for a in node.args)
            obj_str = self._expr_c(node.obj)
            return f'{obj_str}.{node.method}({args});'

        # ── PwmWrite ──────────────────────────
        if isinstance(node, PwmWrite):
            if node.pin in self._pwm_pins:
                ch = self._pwm_pins[node.pin]['channel']
                val = self._expr_c(node.value)
                return f'ledcWrite({ch}U, (uint32_t)({val}));'
            return f'// PWM write on unknown pin "{node.pin}"'

        # ── PwmSetup (inside a block) ─────────
        if isinstance(node, PwmSetup):
            freq = self._expr_c(node.freq)
            res = self._expr_c(node.resolution)
            return f'// {node.pin}.setup({freq}, {res}) — applied in setup()'

        # ── StopStmt ──────────────────────────
        if isinstance(node, StopStmt):
            if node.label in self._every_labels:
                active_var = self._every_labels[node.label]
                return f'{active_var} = 0;'
            return f'// stop {node.label}: label not found'

        raise CodeGenError(
            f'Line {getattr(node, "line", "?")}: '
            f'unhandled statement node {type(node).__name__}'
        )

    # ─────────────────────────────────────────
    #  COMPOUND STATEMENT HELPERS
    # ─────────────────────────────────────────

    def _if_lines(self, node: IfStmt, indent: str = '') -> List[str]:
        cond = self._expr_c(node.condition)
        lines = [f'{indent}if ({cond}) {{']
        for s in node.then_body:
            lines.extend(self._stmt_lines(s, indent + '  '))
        lines.append(f'{indent}}}')
        for ec, eb in node.elif_clauses:
            ec_str = self._expr_c(ec)
            lines.append(f'{indent}else if ({ec_str}) {{')
            for s in eb:
                lines.extend(self._stmt_lines(s, indent + '  '))
            lines.append(f'{indent}}}')
        if node.else_body:
            lines.append(f'{indent}else {{')
            for s in node.else_body:
                lines.extend(self._stmt_lines(s, indent + '  '))
            lines.append(f'{indent}}}')
        return lines

    def _while_lines(self, node: WhileStmt, indent: str = '') -> List[str]:
        cond = self._expr_c(node.condition)
        lines = [f'{indent}while ({cond}) {{']
        for s in node.body:
            lines.extend(self._stmt_lines(s, indent + '  '))
        lines.append(f'{indent}}}')
        return lines

    def _for_lines(self, node: ForStmt, indent: str = '') -> List[str]:
        init = self._stmt_c(node.init).rstrip(';') if node.init else ''
        cond = self._expr_c(node.condition) if node.condition else ''
        step = self._stmt_c(node.step).rstrip(';') if node.step else ''
        lines = [f'{indent}for ({init}; {cond}; {step}) {{']
        for s in node.body:
            lines.extend(self._stmt_lines(s, indent + '  '))
        lines.append(f'{indent}}}')
        return lines

    # ─────────────────────────────────────────
    #  EXPRESSION → STRING (with sane parenthesization)
    # ─────────────────────────────────────────

    # Precedence levels for minimal parenthesization.
    _PREC = {
        '||': 1, '&&': 2,
        '==': 3, '!=': 3, '<': 3, '>': 3, '<=': 3, '>=': 3,
        '+': 4, '-': 4,
        '*': 5, '/': 5, '%': 5,
        'unary': 6, 'call': 7, 'member': 7, 'index': 7,
    }

    def _prec_of(self, node: Any) -> int:
        if isinstance(node, BinOp):
            return self._PREC.get(node.op, 0)
        if isinstance(node, UnaryOp):
            return self._PREC['unary']
        if isinstance(node, (FnCall, MethodCall)):
            return self._PREC['call']
        if isinstance(node, (MemberAccess, ArrayAccess)):
            return self._PREC['member']
        return 99  # atoms

    def _expr_c(self, node: Any, parent_prec: int = 0) -> str:
        """Convert expression to C, parenthesizing only when needed."""
        if isinstance(node, Literal):
            if node.vtype == 'bool':
                return 'true' if node.value else 'false'
            if node.vtype == 'str':
                return f'"{node.value}"'
            if node.vtype == 'char':
                val = node.value
                if val == '\n':
                    return f"'\\n'"
                if val == '\t':
                    return f"'\\t'"
                if val == '\r':
                    return f"'\\r'"
                if val == '\\':
                    return f"'\\\\'"
                if val == '\'':
                    return f"'\\''"
                if isinstance(val, str) and len(val) == 1:
                    return f"'{val}'"
                return str(val)
            return str(node.value)

        if isinstance(node, Identifier):
            return node.name

        if isinstance(node, MillisExpr):
            return 'millis()'

        if isinstance(node, MathExpr):
            self._uses_math = True
            args = ', '.join(self._expr_c(a) for a in node.args)
            return f'{node.func}({args})'

        if isinstance(node, CastExpr):
            ct = _CTYPE.get(node.target_type, node.target_type)
            return f'(({ct})({self._expr_c(node.expr)}))'

        if isinstance(node, SizeOfExpr):
            if isinstance(node.target, str):
                ct = _CTYPE.get(node.target, node.target)
                return f'sizeof({ct})'
            return f'sizeof({self._expr_c(node.target)})'

        if isinstance(node, BinOp):
            my_prec = self._PREC.get(node.op, 0)
            # Left operand: parenthesize if strictly lower precedence
            left = self._expr_c(node.left, my_prec)
            # Right operand: for non-associative ops (-, /, %), force
            # parens on same-precedence children by bumping right_prec.
            # Otherwise a - b + c emits as (a - b) + c instead of a - (b + c).
            right_parent_prec = my_prec + 1 if node.op in ('-', '/', '%') else my_prec
            right = self._expr_c(node.right, right_parent_prec)
            result = f'{left} {node.op} {right}'
            if my_prec < parent_prec:
                return f'({result})'
            return result

        if isinstance(node, UnaryOp):
            inner = self._expr_c(node.operand, self._PREC['unary'])
            result = f'{node.op}{inner}'
            if self._PREC['unary'] < parent_prec:
                return f'({result})'
            return result

        if isinstance(node, MemberAccess):
            obj = self._expr_c(node.obj)
            result = f'{obj}.{node.member}'
            return result

        if isinstance(node, ArrayAccess):
            result = f'{node.name}[{self._expr_c(node.index)}]'
            return result

        if isinstance(node, FnCall):
            args = ', '.join(self._expr_c(a) for a in node.args)
            return f'{node.name}({args})'

        if isinstance(node, MethodCall):
            args = ', '.join(self._expr_c(a) for a in node.args)
            obj = self._expr_c(node.obj)
            return f'{obj}.{node.method}({args})'

        # Raw scalars
        if isinstance(node, (int, float)):
            return str(node)
        if isinstance(node, str):
            return node

        raise CodeGenError(
            f'Unhandled expression node: {type(node).__name__}'
        )

    # ─────────────────────────────────────────
    #  STRING INTERPOLATION
    # ─────────────────────────────────────────

    def _print_c(self, node: PrintStmt) -> str:
        """Generate print/println with string interpolation support."""
        func = 'Serial.println' if node.newline else 'Serial.print'
        val = node.value

        # Check for string interpolation: "temp: {x}"
        if isinstance(val, Literal) and val.vtype == 'str':
            s = val.value
            parts = re.split(r'\{(\w+)\}', s)
            if len(parts) > 1:
                # Interpolated string — emit multiple print calls
                # For now, emit as a comment + the interpolated form
                # Full interpolation needs multiple print calls
                return self._interpolate_string(s, func)

        # Check if string concatenation with +
        if isinstance(val, BinOp) and val.op == '+':
            left_is_str = (isinstance(val.left, Literal) and val.left.vtype == 'str')
            right_is_str = (isinstance(val.right, Literal) and val.right.vtype == 'str')
            if left_is_str or right_is_str:
                raise CodeGenError(
                    f'Line {getattr(node, "line", "?")}: '
                    f'String concatenation with + is not supported. '
                    f'Use interpolation: "text {{var}}" instead.'
                )

        return f'{func}({self._expr_c(val)});'

    def _interpolate_string(self, template: str, func: str) -> str:
        """Convert "temp: {x}°C" to Serial.print calls."""
        parts = re.split(r'\{(\w+)\}', template)
        if len(parts) == 1:
            return f'{func}("{parts[0]}");'

        calls: List[str] = []
        for i, part in enumerate(parts):
            if not part:
                continue
            if i % 2 == 0:
                # Literal text
                if i == len(parts) - 1:
                    # Last part uses println/print
                    calls.append(f'{func}("{part}");')
                else:
                    calls.append(f'Serial.print("{part}");')
            else:
                # Variable interpolation
                if i == len(parts) - 1:
                    calls.append(f'{func}({part});')
                else:
                    calls.append(f'Serial.print({part});')
        return ' '.join(calls)

    # ─────────────────────────────────────────
    #  HELPERS
    # ─────────────────────────────────────────

    def _var_decl_c(self, node: VarDecl) -> str:
        ctype = _CTYPE.get(node.vtype, node.vtype)
        quals = []
        if node.is_const:
            quals.append('const')
        if node.is_volatile:
            quals.append('volatile')
        if not node.is_mutable and not node.is_const:
            quals.append('const')  # `let` is immutable
        prefix = ' '.join(quals) + ' ' if quals else ''
        if node.init is None:
            return f'{prefix}{ctype} {node.name};'
        return f'{prefix}{ctype} {node.name} = {self._expr_c(node.init)};'

    def _target_c(self, target: Any) -> str:
        """Convert an assignment target to a C lvalue string."""
        if isinstance(target, str):
            return target
        if isinstance(target, ArrayAccess):
            return f'{target.name}[{self._expr_c(target.index)}]'
        if isinstance(target, MemberAccess):
            obj = self._expr_c(target.obj)
            return f'{obj}.{target.member}'
        return self._expr_c(target)

    def _make_fn(self, ret: str, name: str, params: str,
                 body_lines: List[str]) -> List[str]:
        sig = f'{ret} {name}({params}) {{'
        return [sig] + body_lines + ['}']

    def _section(self, title: str) -> None:
        self._lines.append('')
        self._lines.append(
            f'/* ========================================'
            f'============================================'
        )
        self._lines.append(
            f' *  {title}'
        )
        self._lines.append(
            f' * ========================================'
            f'============================================ */'
        )
        self._lines.append('')

    def _needs_scheduler(self, nodes: List[Node]) -> bool:
        """Return True if *nodes* (recursively) contain any AssignAfter."""
        for node in (nodes or []):
            if isinstance(node, AssignAfter):
                return True
            if isinstance(node, IfStmt):
                if (self._needs_scheduler(node.then_body)
                        or self._needs_scheduler(node.else_body or [])
                        or any(self._needs_scheduler(b) for _, b in node.elif_clauses)):
                    return True
            elif isinstance(node, (WhileStmt, ForStmt, LoopBlock,
                                   EveryBlock, VoidLoop, FnDecl, TickBlock)):
                if self._needs_scheduler(getattr(node, 'body', [])):
                    return True
        return False
