"""
IOTIFT Code Generator — direct AST → C++ (Arduino framework).

This is the default backend.  It walks the AST and emits *structured*,
readable C++ (real ``if`` / ``while`` / ``for``, no goto spaghetti) and lets
the C++ compiler do the optimising.

Design rules (each one exists because breaking it produced silently-wrong
firmware in earlier versions):

  * Every construct either compiles to working code or raises
    ``CodeGenError``.  The generator never emits a comment, a placeholder or
    raw Iotift source in place of code it does not understand.
  * Declarations are registered in a first pass, so the order of
    declarations in the source file does not matter (a ``stop label`` that
    appears before ``every ... as label`` still works).
  * Everything that runs "in the background" (timers, pin events, threshold
    events, deferred writes, WiFi events) is polled from ``loop()``.  User code
    never runs inside an interrupt or inside the WiFi driver task, so it can
    safely print, allocate or call any Arduino API.
  * The output only uses APIs that exist in the Arduino core.  Platform
    differences (ESP32 LEDC vs. analogWrite, ESP32 core 2.x vs. 3.x) are
    handled with the preprocessor in the emitted helpers rather than guessed.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from ast_nodes import *  # noqa: F401,F403

__version__ = "2.2.0"


class CodeGenError(Exception):
    """Raised when the program cannot be translated to correct C++."""


# ─────────────────────────────────────────
#  TYPES
# ─────────────────────────────────────────

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
    'uint64': 'uint64_t',
    'ulong': 'unsigned long',
}

_FLOAT_TYPES = {'float', 'f32', 'f64'}
_INT_TYPES = {'int', 'u8', 'u16', 'u32', 'u64', 'i8', 'i16', 'i32', 'i64',
              'uint', 'uint64', 'ulong', 'char'}

# Functions the Arduino core / libm already declare.  An ``extern fn`` for
# one of these must NOT be re-declared: a declaration with different
# parameter types creates a new overload that is never defined (link error)
# or conflicts with the real one (compile error).
_PLATFORM_FUNCTIONS = {
    'millis', 'micros', 'delay', 'delayMicroseconds', 'delay_us',
    'digitalRead', 'digitalWrite', 'pinMode', 'analogRead', 'analogWrite',
    'attachInterrupt', 'detachInterrupt', 'random', 'randomSeed', 'map',
    'constrain', 'yield', 'tone', 'noTone', 'pulseIn', 'shiftIn', 'shiftOut',
    'sin', 'cos', 'tan', 'asin', 'acos', 'atan', 'atan2', 'sqrt', 'abs',
    'fabs', 'fabsf', 'pow', 'floor', 'ceil', 'round', 'log', 'log10', 'exp',
    'min', 'max', 'esp_restart', 'ledcSetup', 'ledcAttachPin', 'ledcWrite',
    'dacWrite', 'touchRead', 'hallRead', 'temperatureRead',
}

# Return types of well-known functions, used for printing and arithmetic.
_BUILTIN_RET = {
    'millis': 'ulong', 'micros': 'ulong', 'analogRead': 'int',
    'digitalRead': 'int', 'random': 'int', 'atan2': 'float', 'asin': 'float',
    'acos': 'float', 'atan': 'float', 'log10': 'float',
    'scan_result_count': 'int', 'scan_result_ssid': 'str',
    'scan_result_rssi': 'int', 'scan_result_channel': 'int',
}

_MATH_FLOAT_FUNCS = {'sin', 'cos', 'tan', 'sqrt', 'pow', 'floor', 'ceil',
                     'round', 'log', 'exp', 'asin', 'acos', 'atan', 'atan2',
                     'log10'}

_WIFI_EVENTS = ('connect', 'disconnect', 'got_ip', 'scan_done',
                'client_join', 'client_leave')
_WIFI_STA_EVENTS = {'connect', 'disconnect', 'got_ip', 'scan_done'}
_WIFI_AP_EVENTS = {'client_join', 'client_leave'}

_PIN_EVENTS = {'press', 'release', 'rising', 'falling', 'change',
               'high', 'low'}

# C operator precedence (higher binds tighter).
_PREC = {
    '||': 1, '&&': 2, '|': 3, '^': 4, '&': 5,
    '==': 6, '!=': 6,
    '<': 7, '>': 7, '<=': 7, '>=': 7,
    '<<': 8, '>>': 8,
    '+': 9, '-': 9,
    '*': 10, '/': 10, '%': 10,
}
_UNARY_PREC = 11
_ATOM_PREC = 99

_DEFAULT_INPUT_DEBOUNCE_MS = 25

# Names that Arduino.h (or the C library it pulls in) defines as *macros*.
# A variable/function/enum value with one of these names is rewritten by the
# preprocessor and fails to compile on the device with a baffling error, so
# reject it up front.
_RESERVED_MACROS = {
    'PI', 'HALF_PI', 'TWO_PI', 'DEG_TO_RAD', 'RAD_TO_DEG', 'EULER',
    'HIGH', 'LOW', 'INPUT', 'OUTPUT', 'INPUT_PULLUP', 'INPUT_PULLDOWN',
    'RISING', 'FALLING', 'CHANGE', 'ONLOW', 'ONHIGH',
    'LSBFIRST', 'MSBFIRST', 'DEC', 'HEX', 'OCT', 'BIN',
    'SERIAL', 'DISPLAY', 'DEFAULT', 'EXTERNAL', 'INTERNAL',
    'NULL', 'EOF', 'BUFSIZ', 'RAND_MAX', 'INT_MAX', 'INT_MIN', 'UINT_MAX',
    'M_PI', 'M_E', 'INFINITY', 'NAN', 'FLT_MAX', 'FLT_MIN',
    'bit', 'lowByte', 'highByte', 'bitRead', 'bitSet', 'bitClear', 'bitWrite',
    'radians', 'degrees', 'sq', 'constrain', 'interrupts', 'noInterrupts',
    'digitalPinToInterrupt', 'F', 'assert',
}


def c_string(s: str) -> str:
    """Return *s* as a valid C string literal (with quotes)."""
    out = []
    for ch in s:
        if ch == '\\':
            out.append('\\\\')
        elif ch == '"':
            out.append('\\"')
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\r':
            out.append('\\r')
        elif ch == '\t':
            out.append('\\t')
        elif ch == '\0':
            out.append('\\0')
        elif ord(ch) < 0x20 or ord(ch) == 0x7f:
            # Octal escapes never swallow following hex-looking characters.
            out.append('\\%03o' % ord(ch))
        else:
            out.append(ch)
    return '"' + ''.join(out) + '"'


def c_char(ch: Any) -> str:
    if isinstance(ch, int):
        return str(ch)
    esc = {'\n': '\\n', '\t': '\\t', '\r': '\\r', '\\': '\\\\',
           "'": "\\'", '\0': '\\0'}
    if ch in esc:
        return f"'{esc[ch]}'"
    if len(ch) == 1 and (ord(ch) < 0x20 or ord(ch) == 0x7f):
        return "'\\%03o'" % ord(ch)
    return f"'{ch}'"


def _dedent(text: str) -> str:
    """Remove the longest common leading whitespace from all non-empty lines."""
    lines = text.split('\n')
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    non_empty = [ln for ln in lines if ln.strip()]
    if not non_empty:
        return ''
    common = min(len(ln) - len(ln.lstrip()) for ln in non_empty)
    return '\n'.join(ln[common:] if ln.strip() else '' for ln in lines)


def _float_lit(v: float) -> str:
    s = repr(float(v))
    if 'inf' in s or 'nan' in s:
        raise CodeGenError(f'invalid float literal {v}')
    if '.' not in s and 'e' not in s:
        s += '.0'
    return s + 'f'


class _Fn:
    """Per-function generation context."""

    def __init__(self, name: str, ret: str = 'void', is_isr: bool = False):
        self.name = name
        self.ret = ret
        self.is_isr = is_isr
        self.defers: List[List[Node]] = []
        self.tmp = 0


class CodeGen:
    """AST → C++ for Arduino-framework microcontrollers (ESP32 first)."""

    def __init__(self, device: str = 'esp32',
                 baud_rate: int = 115200,
                 scheduler_slots: int = 16) -> None:
        self._device = device
        self._baud = baud_rate
        self._max_tasks = scheduler_slots
        self.warnings: List[str] = []

        # ── registries (filled by the first pass) ──
        self._pins: Dict[str, PinDecl] = {}
        self._pwm: Dict[str, dict] = {}
        self._enums: Dict[str, EnumDecl] = {}
        self._enum_variant: Dict[str, str] = {}      # variant → enum name
        self._structs: Dict[str, Dict[str, str]] = {}
        self._aliases: Dict[str, str] = {}
        self._fns: Dict[str, FnDecl] = {}
        self._externs: Dict[str, ExternFnDecl] = {}
        self._globals: Dict[str, str] = {}           # name → iotift type
        self._arrays: Dict[str, str] = {}            # name → element type
        self._timers: Dict[str, str] = {}            # label → base C name
        self._wifis: Dict[str, WifiDecl] = {}
        self._pin_events: Dict[str, List[OnEvent]] = {}
        self._wifi_events: Dict[Tuple[str, str], List[Node]] = {}

        # ── generation state ──
        self._scopes: List[Dict[str, str]] = []
        self._fn: Optional[_Fn] = None
        self._loop_depth = 0
        self._needs: Set[str] = set()                # runtime helpers used
        self._after_count = 0
        self._every_count = 0
        self._threshold_count = 0

        # ── output buffers ──
        self._type_decls: List[str] = []
        self._global_vars: List[str] = []
        self._state_vars: List[str] = []
        self._header_blocks: List[str] = []
        self._global_blocks: List[str] = []
        self._setup_blocks: List[str] = []
        self._loop_blocks: List[str] = []
        self._prototypes: List[str] = []
        self._user_fns: List[List[str]] = []
        self._handler_fns: List[List[str]] = []
        self._setup_body: List[str] = []       # top-level statements, in order
        self._setup_late: List[str] = []       # timer baselines, after user code
        self._loop_calls: List[str] = []

    # ═════════════════════════════════════════
    #  PUBLIC ENTRY
    # ═════════════════════════════════════════

    def generate(self, program: Any) -> str:
        body = program.body if hasattr(program, 'body') else list(program)

        for node in body:
            self._register(node)
        self._validate_registry()

        self._scopes = [dict(self._globals)]
        for node in body:
            self._emit_top(node)

        self._emit_pin_event_pollers()
        self._emit_wifi()

        return self._assemble()

    # ═════════════════════════════════════════
    #  PASS 1 — REGISTER DECLARATIONS
    # ═════════════════════════════════════════

    def _register(self, node: Node) -> None:
        if isinstance(node, DeviceDecl):
            self._device = node.name
        elif isinstance(node, SchedulerConfig):
            if node.key == 'scheduler_slots':
                self._max_tasks = int(node.value)
        elif isinstance(node, PinDecl):
            if node.name in self._pins:
                raise CodeGenError(f'Line {node.line}: pin {node.name!r} declared twice')
            self._pins[node.name] = node
            if node.direction == 'pwm':
                self._pwm[node.name] = {
                    'channel': len(self._pwm),
                    'freq': str(node.pwm_freq or 5000),
                    'res': str(node.pwm_resolution or 8),
                }
        elif isinstance(node, VarDecl):
            self._check_name(node.name, 'variable', node.line)
            self._globals[node.name] = self._decl_type(node)
        elif isinstance(node, ArrayDecl):
            self._check_name(node.name, 'array', node.line)
            self._arrays[node.name] = node.vtype or 'int'
            self._globals[node.name] = (node.vtype or 'int') + '[]'
        elif isinstance(node, StructDecl):
            self._structs[node.name] = {f.name: f.vtype for f in node.fields}
        elif isinstance(node, EnumDecl):
            self._enums[node.name] = node
            for vname, _ in node.variants:
                self._check_name(vname, 'enum value', node.line)
                if vname in self._enum_variant:
                    raise CodeGenError(
                        f'Line {node.line}: enum value {vname!r} is defined in both '
                        f'{self._enum_variant[vname]!r} and {node.name!r}')
                self._enum_variant[vname] = node.name
        elif isinstance(node, TypeAliasDecl):
            self._aliases[node.name] = node.aliased_type
        elif isinstance(node, FnDecl):
            self._check_name(node.name, 'function', node.line)
            for prm in node.params:
                self._check_name(prm.name, 'parameter', node.line)
            if node.name in self._fns:
                raise CodeGenError(f'Line {node.line}: function {node.name!r} defined twice')
            self._fns[node.name] = node
        elif isinstance(node, ExternFnDecl):
            self._externs[node.name] = node
        elif isinstance(node, WifiDecl):
            if node.name in self._wifis:
                raise CodeGenError(f'Line {node.line}: wifi {node.name!r} declared twice')
            self._wifis[node.name] = node
        elif isinstance(node, EveryBlock):
            if node.label:
                if node.label in self._timers:
                    raise CodeGenError(f'Line {node.line}: timer label {node.label!r} used twice')
                self._timers[node.label] = f'_iotift_every_{node.label}'
        elif isinstance(node, OnEvent):
            if node.target in self._wifis or node.event in _WIFI_EVENTS and node.target not in self._pins:
                self._wifi_events.setdefault((node.target, node.event), []).extend(node.body)
            else:
                self._pin_events.setdefault(node.target, []).append(node)

    @staticmethod
    def _check_name(name: str, what: str, line: Any) -> None:
        if name in _RESERVED_MACROS:
            raise CodeGenError(
                f'Line {line}: {what} {name!r} clashes with a macro defined by Arduino.h; '
                f'pick another name' + (' (PI is already available)' if name == 'PI' else ''))
        if name.startswith('_iotift'):
            raise CodeGenError(f'Line {line}: {what} {name!r}: names starting with _iotift are reserved')

    def _validate_registry(self) -> None:
        # WiFi events must refer to declared wifi blocks with a matching mode.
        for (target, event), _ in self._wifi_events.items():
            wd = self._wifis.get(target)
            if wd is None:
                raise CodeGenError(f'on {target}.{event}: {target!r} is not a declared wifi interface')
            if event not in _WIFI_EVENTS:
                raise CodeGenError(f'on {target}.{event}: unknown wifi event (expected one of {", ".join(_WIFI_EVENTS)})')
            if wd.mode == 'ap' and event in _WIFI_STA_EVENTS:
                raise CodeGenError(f'on {target}.{event}: {event!r} is a station event but {target!r} is an access point')
            if wd.mode == 'sta' and event in _WIFI_AP_EVENTS:
                raise CodeGenError(f'on {target}.{event}: {event!r} is an access-point event but {target!r} is a station')
        for target, evs in self._pin_events.items():
            if target not in self._pins:
                raise CodeGenError(f'Line {evs[0].line}: on {target}.{evs[0].event}: {target!r} is not a declared pin')
            pin = self._pins[target]
            for ev in evs:
                if ev.event not in _PIN_EVENTS:
                    raise CodeGenError(
                        f'Line {ev.line}: on {target}.{ev.event}: unknown pin event '
                        f'(expected one of {", ".join(sorted(_PIN_EVENTS))})')
                if pin.direction not in ('input', 'output'):
                    raise CodeGenError(
                        f'Line {ev.line}: on {target}.{ev.event}: edge events need a digital '
                        f'input/output pin, {target!r} is {pin.direction}')
        by_gpio: Dict[int, str] = {}
        for name, pin in self._pins.items():
            other = by_gpio.get(pin.number)
            if other is not None:
                raise CodeGenError(
                    f'Line {pin.line}: pins {other!r} and {name!r} are both GPIO {pin.number}')
            by_gpio[pin.number] = name
        stas = [w for w in self._wifis.values() if w.mode == 'sta']
        aps = [w for w in self._wifis.values() if w.mode == 'ap']
        if len(stas) > 1:
            raise CodeGenError('only one station-mode wifi block is supported (the radio has one STA interface)')
        if len(aps) > 1:
            raise CodeGenError('only one access-point wifi block is supported')
        for wd in self._wifis.values():
            cfg = wd.config
            if not cfg.get('ssid'):
                raise CodeGenError(f'Line {wd.line}: wifi {wd.name!r}: ssid is required')
            pw = cfg.get('password', '')
            if wd.mode == 'ap' and pw and len(pw) < 8:
                raise CodeGenError(
                    f'Line {wd.line}: wifi {wd.name!r}: access-point password must be at least '
                    f'8 characters (or omitted for an open network); the radio rejects shorter ones')
        if self._wifis and not self._is_esp32():
            raise CodeGenError(f'wifi blocks are only supported on ESP32 targets (device is {self._device!r})')

    # ═════════════════════════════════════════
    #  PASS 2 — TOP-LEVEL NODES
    # ═════════════════════════════════════════

    def _emit_top(self, node: Node) -> None:
        imported = getattr(node, '_imported_from', None)

        if isinstance(node, (DeviceDecl, SchedulerConfig, PinDecl, WifiDecl)):
            return
        if isinstance(node, ImportDecl):
            raise CodeGenError(f'Line {node.line}: import "{node.path}" was not resolved')
        if isinstance(node, PwmSetup):
            # Top-level R.setup(f, r) configures the channel before setup().
            if node.pin not in self._pwm:
                raise CodeGenError(f'Line {node.line}: {node.pin}.setup(): {node.pin!r} is not a pwm pin')
            self._pwm[node.pin]['freq'] = self._expr(node.freq)
            self._pwm[node.pin]['res'] = self._expr(node.resolution)
            return
        if isinstance(node, MethodCall) and node.method == 'setup' and node.obj in self._pwm:
            self._pwm[node.obj]['freq'] = self._expr(node.args[0]) if node.args else '5000'
            self._pwm[node.obj]['res'] = self._expr(node.args[1]) if len(node.args) > 1 else '8'
            return

        if isinstance(node, VarDecl):
            self._global_vars.append(self._var_decl(node, is_global=True) + ';')
        elif isinstance(node, ArrayDecl):
            self._global_vars.append(self._array_decl(node) + ';')
        elif isinstance(node, StructDecl):
            lines = [f'struct {node.name} {{']
            for f in node.fields:
                lines.append(f'  {self._ctype(f.vtype)} {f.name};')
            lines.append('};')
            self._type_decls.append('\n'.join(lines))
        elif isinstance(node, EnumDecl):
            bt = self._ctype(node.backing_type) if node.backing_type else None
            head = 'typedef enum' + (f' : {bt}' if bt else '') + ' {'
            items = []
            for vname, val in node.variants:
                items.append(f'  {vname}' + (f' = {val}' if val is not None else '') + ',')
            self._type_decls.append('\n'.join([head] + items + [f'}} {node.name};']))
        elif isinstance(node, TypeAliasDecl):
            self._type_decls.append(f'typedef {self._ctype(node.aliased_type)} {node.name};')
        elif isinstance(node, PeripheralDecl):
            raise CodeGenError(
                f'Line {node.line}: {node.periph_type} peripheral blocks are not implemented '
                f'by the code generator yet; configure the bus in a `c setup {{ }}` block')
        elif isinstance(node, FnDecl):
            self._emit_fn(node)
        elif isinstance(node, ExternFnDecl):
            if imported or node.name in _PLATFORM_FUNCTIONS:
                return  # provided by Arduino.h / the stdlib headers
            ret = self._ctype(node.return_type or 'void')
            params = ', '.join(f'{self._ctype(p.vtype)} {p.name}' for p in node.params) or 'void'
            self._prototypes.append(f'extern {ret} {node.name}({params});')
        elif isinstance(node, CBlockNode):
            code = _dedent(node.code)
            if not code:
                return
            if node.scope == 'setup':
                # Runs in source order with the other top-level statements.
                self._setup_body += ['  ' + ln if ln.strip() else '' for ln in code.split('\n')]
                return
            {'header': self._header_blocks, 'global': self._global_blocks,
             'loop': self._loop_blocks,
             }.get(node.scope, self._global_blocks).append(code)
        elif isinstance(node, OnEvent):
            if (node.target, node.event) in self._wifi_events:
                return  # emitted with the wifi runtime
            return      # pin events are emitted per pin after this pass
        elif isinstance(node, OnThreshold):
            self._emit_threshold(node)
        elif isinstance(node, EveryBlock):
            self._emit_every(node)
        elif isinstance(node, AfterBlock):
            fn = self._emit_after_fn(node)
            self._needs.add('scheduler')
            self._setup_late.append(f'_iotift_schedule_fn({fn}, {node.interval}UL);')
        elif isinstance(node, (LoopBlock, TickBlock, VoidLoop)):
            if not node.body:
                return
            name = {LoopBlock: '_iotift_loop_block', TickBlock: '_iotift_tick',
                    VoidLoop: 'user_loop'}[type(node)]
            name = self._unique_fn_name(name)
            self._handler_fns.append(self._fn_body('static void', name, 'void', node.body, _Fn(name)))
            if isinstance(node, TickBlock):
                # `tick` runs once, at the end of setup() (matches both
                # previous backends and the examples).
                self._setup_late.append(f'{name}();')
            else:
                self._loop_calls.append(f'{name}();')
        elif isinstance(node, DeferStmt):
            self._warn(f'Line {node.line}: top-level `defer` has no effect: firmware never '
                       f'exits, so there is no point at which it could run (ignored)')
        else:
            # Any other statement at top level runs once, in setup(), in order.
            self._fn = _Fn('setup')
            self._setup_body.extend(self._stmt(node, '  '))
            self._fn = None

    def _unique_fn_name(self, base: str) -> str:
        existing = {fn[0] for fn in self._handler_fns}
        name, i = base, 1
        while any(f' {name}(' in sig for sig in existing):
            i += 1
            name = f'{base}_{i}'
        return name

    # ── functions ──────────────────────────────

    def _emit_fn(self, node: FnDecl) -> None:
        ret = self._ctype(node.return_type or 'void')
        params = ', '.join(f'{self._ctype(p.vtype)} {p.name}' for p in node.params)
        attr = 'IRAM_ATTR ' if node.is_isr else ''
        sig = f'{ret} {attr}{node.name}({params or "void"})'
        self._prototypes.append(sig + ';')
        ctx = _Fn(node.name, node.return_type or 'void', node.is_isr)
        param_scope = {p.name: p.vtype for p in node.params}
        self._user_fns.append(self._fn_body(f'{ret} {attr}'.rstrip(), node.name,
                                            params or 'void', node.body, ctx, param_scope))

    def _fn_body(self, ret: str, name: str, params: str, body: List[Node],
                 ctx: _Fn, scope: Optional[Dict[str, str]] = None,
                 prologue: Optional[List[str]] = None) -> List[str]:
        saved_fn, saved_depth = self._fn, self._loop_depth
        self._fn, self._loop_depth = ctx, 0
        self._scopes.append(dict(scope or {}))
        try:
            lines = list(prologue or [])
            lines += self._block(body, '  ')
            if ctx.defers and not self._ends_with_return(body):
                lines += self._defer_lines('  ')
        finally:
            self._scopes.pop()
            self._fn, self._loop_depth = saved_fn, saved_depth
        return [f'{ret} {name}({params}) {{'] + lines + ['}']

    @staticmethod
    def _ends_with_return(body: List[Node]) -> bool:
        return bool(body) and isinstance(body[-1], ReturnStmt)

    # ── every ──────────────────────────────────

    def _emit_every(self, node: EveryBlock) -> None:
        if node.interval <= 0:
            raise CodeGenError(f'Line {node.line}: every interval must be > 0 ms')
        if node.label:
            base = self._timers[node.label]
        else:
            if not node.body:
                return
            base = f'_iotift_every_{self._every_count}'
            self._every_count += 1
        last, active = f'{base}_last', f'{base}_active'
        iv = f'{node.interval}UL'
        self._state_vars.append(f'static unsigned long {last} = 0UL;')
        self._state_vars.append(f'static bool {active} = true;')
        # First fire happens after one interval, or after `offset` if given.
        if node.offset_ms is not None:
            self._setup_late.append(f'{last} = millis() - {iv} + {node.offset_ms}UL;')
        else:
            self._setup_late.append(f'{last} = millis();')
        prologue = [
            f'  if (!{active}) return;',
            '  unsigned long _now = millis();',
            f'  if (_now - {last} < {iv}) return;',
            f'  {last} += {iv};',
            f'  if (_now - {last} >= {iv}) {last} = _now;  // fell behind: resync, no burst',
        ]
        self._handler_fns.append(self._fn_body('static void', base, 'void', node.body,
                                               _Fn(base), prologue=prologue))
        self._loop_calls.append(f'{base}();')

    # ── after ──────────────────────────────────

    def _emit_after_fn(self, node: AfterBlock) -> str:
        if node.interval < 0:
            raise CodeGenError(f'Line {node.line}: after delay must be >= 0 ms')
        # The body runs later, from loop(); it cannot see locals of the code
        # that scheduled it.
        captured = self._captured_locals(node.body)
        if captured:
            raise CodeGenError(
                f'Line {node.line}: `after` block uses local variable(s) '
                f'{", ".join(sorted(captured))}; the block runs later, after the '
                f'enclosing code has returned, so it can only use globals')
        name = f'_iotift_after_{self._after_count}'
        self._after_count += 1
        saved = self._scopes
        self._scopes = [self._scopes[0]]
        try:
            self._handler_fns.append(self._fn_body('static void', name, 'void', node.body, _Fn(name)))
        finally:
            self._scopes = saved
        return name

    def _captured_locals(self, body: List[Node]) -> Set[str]:
        local_names: Set[str] = set()
        for scope in self._scopes[1:]:
            local_names |= set(scope)
        if not local_names:
            return set()
        used = set()
        _collect_identifiers(body, used)
        return used & local_names - set(self._globals)

    # ── thresholds ─────────────────────────────

    def _emit_threshold(self, node: OnThreshold) -> None:
        pin = self._pins.get(node.pin)
        if pin is None:
            raise CodeGenError(f'Line {node.line}: on {node.pin} {node.op} ...: {node.pin!r} is not a declared pin')
        if node.op not in ('>', '<', '>=', '<=', '==', '!='):
            raise CodeGenError(f'Line {node.line}: unsupported threshold operator {node.op!r}')
        if not node.body:
            return
        idx = self._threshold_count
        self._threshold_count += 1
        name = f'_iotift_threshold_{node.pin}_{idx}'
        state = f'{name}_armed'
        self._state_vars.append(f'static bool {state} = false;')
        prologue = [
            f'  bool _hit = ({self._pin_read(node.pin)} {node.op} {self._expr(node.value, _PREC[node.op] + 1)});',
            f'  bool _was = {state};',
            f'  {state} = _hit;',
            '  if (!_hit || _was) return;  // fire once each time the condition becomes true',
        ]
        self._handler_fns.append(self._fn_body('static void', name, 'void', node.body,
                                               _Fn(name), prologue=prologue))
        self._loop_calls.append(f'{name}();')

    # ── pin edge events (polled + debounced) ──

    def _emit_pin_event_pollers(self) -> None:
        for pin_name, events in self._pin_events.items():
            events = [e for e in events if e.body]
            if not events:
                continue
            pin = self._pins[pin_name]
            pull = pin.config.pull if pin.config else None
            active_low = pull != 'down'
            if pin.direction == 'input':
                deb = pin.config.debounce_ms if pin.config and pin.config.debounce_ms is not None \
                    else _DEFAULT_INPUT_DEBOUNCE_MS
            else:
                deb = pin.config.debounce_ms if pin.config and pin.config.debounce_ms is not None else 0
            raw, stable, changed = (f'_iotift_{pin_name}_raw', f'_iotift_{pin_name}_stable',
                                    f'_iotift_{pin_name}_changed')
            self._state_vars += [
                f'static uint8_t {raw} = HIGH;',
                f'static uint8_t {stable} = HIGH;',
                f'static unsigned long {changed} = 0UL;',
            ]
            self._setup_late.append(f'{raw} = {stable} = digitalRead({pin_name}_PIN);')

            on_rise, on_fall, on_change = [], [], []
            counts: Dict[str, int] = {}
            for ev in events:
                n = counts.get(ev.event, 0)
                counts[ev.event] = n + 1
                fname = f'_iotift_on_{pin_name}_{ev.event}' + (f'_{n + 1}' if n else '')
                self._handler_fns.append(self._fn_body('static void', fname, 'void', ev.body, _Fn(fname)))
                call = f'{fname}();'
                kind = ev.event
                if kind == 'press':
                    kind = 'falling' if active_low else 'rising'
                elif kind == 'release':
                    kind = 'rising' if active_low else 'falling'
                elif kind == 'high':
                    kind = 'rising'
                elif kind == 'low':
                    kind = 'falling'
                {'rising': on_rise, 'falling': on_fall, 'change': on_change}[kind].append(call)

            poll = f'_iotift_poll_{pin_name}'
            body = [
                f'static void {poll}(void) {{',
                f'  uint8_t _r = digitalRead({pin_name}_PIN);',
                '  unsigned long _now = millis();',
                f'  if (_r != {raw}) {{ {raw} = _r; {changed} = _now; }}',
                f'  if (_r == {stable} || _now - {changed} < {deb}UL) return;',
                f'  {stable} = _r;',
            ]
            if on_rise:
                body.append(f'  if (_r == HIGH) {{ {" ".join(on_rise)} }}')
            if on_fall:
                body.append(f'  if (_r == LOW) {{ {" ".join(on_fall)} }}')
            body += [f'  {c}' for c in on_change]
            body.append('}')
            self._handler_fns.append(body)
            self._loop_calls.insert(0, f'{poll}();')

    # ═════════════════════════════════════════
    #  STATEMENTS
    # ═════════════════════════════════════════

    def _block(self, stmts: List[Node], indent: str) -> List[str]:
        self._scopes.append({})
        try:
            out: List[str] = []
            for s in stmts:
                out += self._stmt(s, indent)
            return out
        finally:
            self._scopes.pop()

    def _stmt(self, node: Node, ind: str) -> List[str]:
        line = getattr(node, 'line', '?')

        if isinstance(node, IfStmt):
            out = [f'{ind}if ({self._cond(node.condition)}) {{']
            out += self._block(node.then_body, ind + '  ')
            for cond, body in node.elif_clauses:
                out.append(f'{ind}}} else if ({self._cond(cond)}) {{')
                out += self._block(body, ind + '  ')
            if node.else_body:
                out.append(f'{ind}}} else {{')
                out += self._block(node.else_body, ind + '  ')
            out.append(f'{ind}}}')
            return out

        if isinstance(node, WhileStmt):
            return self._loop(f'{ind}while ({self._cond(node.condition)}) {{', node.body, ind)

        if isinstance(node, LoopBlock):
            return self._loop(f'{ind}while (true) {{', node.body, ind)

        if isinstance(node, ForStmt):
            self._scopes.append({})
            try:
                init = self._simple(node.init) if node.init else ''
                cond = self._cond(node.condition) if node.condition is not None else ''
                step = self._simple(node.step) if node.step else ''
                return self._loop(f'{ind}for ({init}; {cond}; {step}) {{', node.body, ind)
            finally:
                self._scopes.pop()

        if isinstance(node, BreakStmt):
            if not self._loop_depth:
                raise CodeGenError(f'Line {line}: `break` outside of a loop')
            return [f'{ind}break;']
        if isinstance(node, ContinueStmt):
            if not self._loop_depth:
                raise CodeGenError(f'Line {line}: `continue` outside of a loop')
            return [f'{ind}continue;']

        if isinstance(node, ReturnStmt):
            return self._return(node, ind)

        if isinstance(node, DeferStmt):
            if self._fn is None or self._fn.name == 'setup':
                self._warn(f'Line {line}: `defer` outside a function has no effect (ignored)')
                return []
            self._fn.defers.append(node.body)
            return []

        if isinstance(node, PrintStmt):
            return [ind + ln for ln in self._print(node)]

        if isinstance(node, CBlockNode):
            code = _dedent(node.code)
            return [(ind + ln) if ln.strip() else '' for ln in code.split('\n')] if code else []

        if isinstance(node, AfterBlock):
            fn = self._emit_after_fn(node)
            self._needs.add('scheduler')
            return [f'{ind}_iotift_schedule_fn({fn}, {node.interval}UL);']

        if isinstance(node, EveryBlock):
            raise CodeGenError(f'Line {line}: `every` must be declared at top level')

        if isinstance(node, (OnEvent, OnThreshold, FnDecl, WifiDecl, PinDecl)):
            raise CodeGenError(f'Line {line}: {type(node).__name__} must be declared at top level')

        if isinstance(node, (StructDecl, EnumDecl)):
            raise CodeGenError(f'Line {line}: types must be declared at top level')

        if isinstance(node, StopStmt):
            return [f'{ind}{self._timer_base(node.label, line)}_active = false;']
        if isinstance(node, StartStmt):
            base = self._timer_base(node.label, line)
            return [f'{ind}{base}_active = true; {base}_last = millis();']

        if isinstance(node, ExternFnDecl):
            raise CodeGenError(f'Line {line}: extern declarations must be at top level')

        return [f'{ind}{self._simple(node)};']

    def _loop(self, head: str, body: List[Node], ind: str) -> List[str]:
        self._loop_depth += 1
        try:
            return [head] + self._block(body, ind + '  ') + [f'{ind}}}']
        finally:
            self._loop_depth -= 1

    def _return(self, node: ReturnStmt, ind: str) -> List[str]:
        fn = self._fn
        if fn is None or fn.name == 'setup':
            raise CodeGenError(f'Line {node.line}: `return` outside of a function')
        if node.value is None:
            if fn.ret not in (None, 'void'):
                raise CodeGenError(f'Line {node.line}: {fn.name}() must return a {fn.ret}')
            if fn.defers:
                return [f'{ind}{{'] + self._defer_lines(ind + '  ') + [f'{ind}  return;', f'{ind}}}']
            return [f'{ind}return;']
        if fn.ret in (None, 'void'):
            raise CodeGenError(f'Line {node.line}: {fn.name}() has no return type but returns a value')
        val = self._expr(node.value)
        if fn.defers:
            # Evaluate the result first, then run deferred blocks (LIFO).
            fn.tmp += 1
            tmp = f'_iotift_ret{fn.tmp}'
            return ([f'{ind}{{', f'{ind}  {self._ctype(fn.ret)} {tmp} = {val};']
                    + self._defer_lines(ind + '  ')
                    + [f'{ind}  return {tmp};', f'{ind}}}'])
        return [f'{ind}return {val};']

    def _defer_lines(self, ind: str) -> List[str]:
        out: List[str] = []
        fn = self._fn
        assert fn is not None
        pending, fn.defers = fn.defers, []    # a defer body may not re-trigger defers
        try:
            for body in reversed(pending):
                out += self._block(body, ind)
        finally:
            fn.defers = pending
        return out

    def _timer_base(self, label: str, line: Any) -> str:
        if label not in self._timers:
            known = ', '.join(sorted(self._timers)) or 'none declared'
            raise CodeGenError(f'Line {line}: unknown timer {label!r} (labelled timers: {known})')
        return self._timers[label]

    # ── single-line statements (no trailing ';') ──

    def _simple(self, node: Node) -> str:
        line = getattr(node, 'line', '?')

        if isinstance(node, VarDecl):
            self._check_name(node.name, 'variable', line)
            if node.name in self._pins:
                raise CodeGenError(f'Line {line}: variable {node.name!r} shadows a pin')
            decl = self._var_decl(node, is_global=False)
            self._scopes[-1][node.name] = self._decl_type(node)
            return decl

        if isinstance(node, ArrayDecl):
            decl = self._array_decl(node)
            self._scopes[-1][node.name] = (node.vtype or 'int') + '[]'
            return decl

        if isinstance(node, Assign):
            return self._assign(node)

        if isinstance(node, CompoundAssign):
            if node.target in self._pins:
                raise CodeGenError(f'Line {line}: compound assignment to pin {node.target!r}')
            self._check_assignable(node.target, line)
            return f'{node.target} {node.op} {self._expr(node.value)}'

        if isinstance(node, AssignAfter):
            return self._assign_after(node)

        if isinstance(node, PwmWrite):
            return self._pwm_write(node.pin, node.value, line)

        if isinstance(node, PwmSetup):
            return self._pwm_runtime_setup(node.pin, node.freq, node.resolution, line)

        if isinstance(node, ExprStmt):
            return self._expr(node.expr)

        if isinstance(node, (FnCall, MethodCall, MathExpr)):
            return self._expr(node)

        if isinstance(node, MemberAccess):
            raise CodeGenError(f'Line {line}: `{self._expr(node)}` on its own does nothing')

        raise CodeGenError(f'Line {line}: unsupported statement {type(node).__name__}')

    def _check_assignable(self, name: str, line: Any) -> None:
        if name in self._wifis:
            raise CodeGenError(f'Line {line}: cannot assign to wifi interface {name!r}')
        if name in self._timers:
            raise CodeGenError(f'Line {line}: cannot assign to timer {name!r}; use start/stop')
        if name in self._enum_variant:
            raise CodeGenError(f'Line {line}: cannot assign to enum value {name!r}')

    def _assign(self, node: Assign) -> str:
        line = node.line
        tgt = node.target
        if isinstance(tgt, str):
            if tgt in self._pins:
                return self._pin_assign(tgt, node.value, line)
            self._check_assignable(tgt, line)
            return f'{tgt} = {self._expr(node.value)}'
        if isinstance(tgt, MemberAccess):
            if isinstance(tgt.obj, str) and tgt.obj in self._wifis:
                raise CodeGenError(f'Line {line}: {tgt.obj}.{tgt.member} is read-only')
            if isinstance(tgt.obj, str) and (tgt.obj in self._pins or tgt.obj in self._timers):
                raise CodeGenError(f'Line {line}: cannot assign to {tgt.obj}.{tgt.member}')
            return f'{self._expr(tgt)} = {self._expr(node.value)}'
        if isinstance(tgt, ArrayAccess):
            return f'{self._expr(tgt)} = {self._expr(node.value)}'
        raise CodeGenError(f'Line {line}: invalid assignment target')

    def _pin_assign(self, pin: str, value: Any, line: Any) -> str:
        d = self._pins[pin].direction
        if d == 'pwm':
            return self._pwm_write(pin, value, line)
        if d != 'output':
            raise CodeGenError(f'Line {line}: cannot write to {d} pin {pin!r}')
        lvl = self._literal_level(value)
        if lvl is not None:
            return f'digitalWrite({pin}_PIN, {lvl})'
        t = self._type_of(value)
        if t == 'bool' or self._is_digital_read(value):
            return f'digitalWrite({pin}_PIN, ({self._expr(value)}) ? HIGH : LOW)'
        # A numeric, non-boolean value on a digital pin: PWM-style output.
        return f'analogWrite({pin}_PIN, (int)({self._expr(value)}))'

    def _is_digital_read(self, value: Any) -> bool:
        """True for `BTN` / `BTN.read()` where BTN is a digital pin."""
        name = None
        if isinstance(value, Identifier):
            name = value.name
        elif isinstance(value, MethodCall) and value.method == 'read' and isinstance(value.obj, str):
            name = value.obj
        return name in self._pins and self._pins[name].direction in ('input', 'output')

    @staticmethod
    def _literal_level(value: Any) -> Optional[str]:
        if isinstance(value, Literal) and value.vtype in ('int', 'bool'):
            if value.value in (0, False):
                return 'LOW'
            if value.value in (1, True):
                return 'HIGH'
        if isinstance(value, Identifier) and value.name in ('HIGH', 'LOW'):
            return value.name
        return None

    def _assign_after(self, node: AssignAfter) -> str:
        self._needs.add('scheduler')
        tgt, line = node.target, node.line
        if tgt in self._pins:
            if self._pins[tgt].direction != 'output':
                raise CodeGenError(f'Line {line}: `{tgt} = ... after` needs a digital output pin')
            lvl = self._literal_level(node.value) or f'(({self._expr(node.value)}) ? HIGH : LOW)'
            return f'_iotift_schedule_pin({tgt}_PIN, {lvl}, {node.delay}UL)'
        t = self._lookup(tgt)
        if t is None:
            raise CodeGenError(f'Line {line}: unknown variable {tgt!r}')
        if len(self._scopes) > 1 and any(tgt in s for s in self._scopes[1:]):
            raise CodeGenError(f'Line {line}: `{tgt} = ... after` on a local variable; the '
                               f'write happens after the function has returned')
        if t not in ('int', 'bool', 'i32', 'u8', 'u16', 'i8', 'i16') and t not in self._enums:
            raise CodeGenError(f'Line {line}: `= ... after` supports int/bool variables and output pins (got {t})')
        return (f'_iotift_schedule_int((volatile int*)&{tgt}, (int)({self._expr(node.value)}), '
                f'{node.delay}UL)') if t == 'int' else self._typed_after(tgt, t, node)

    def _typed_after(self, tgt: str, t: str, node: AssignAfter) -> str:
        # Non-int targets get a tiny generated setter scheduled as a callback.
        name = f'_iotift_set_{tgt}_{self._after_count}'
        self._after_count += 1
        val_name = f'{name}_val'
        self._state_vars.append(f'static {self._ctype(t)} {val_name};')
        self._handler_fns.append([f'static void {name}(void) {{', f'  {tgt} = {val_name};', '}'])
        return f'{val_name} = {self._expr(node.value)}; _iotift_schedule_fn({name}, {node.delay}UL)'

    # ── PWM ──

    def _pwm_info(self, pin: str, line: Any) -> dict:
        if pin not in self._pwm:
            raise CodeGenError(f'Line {line}: {pin!r} is not a pwm pin')
        return self._pwm[pin]

    def _pwm_write(self, pin: str, value: Any, line: Any) -> str:
        info = self._pwm_info(pin, line)
        self._needs.add('pwm')
        return f'_iotift_pwm_write({info["channel"]}, {pin}_PIN, {self._expr(value)})'

    def _pwm_runtime_setup(self, pin: str, freq: Any, res: Any, line: Any) -> str:
        info = self._pwm_info(pin, line)
        self._needs.add('pwm')
        return (f'_iotift_pwm_setup({info["channel"]}, {pin}_PIN, {self._expr(freq)}, '
                f'{self._expr(res)})')

    # ── print ──

    def _print(self, node: PrintStmt) -> List[str]:
        pieces = self._print_pieces(node.value, node.line)
        calls: List[str] = []
        for kind, val in pieces:
            calls.append(f'Serial.print({val});')
        if node.newline:
            if calls and pieces[-1][0] == 'lit':
                calls[-1] = 'Serial.println' + calls[-1][len('Serial.print'):]
            else:
                calls.append('Serial.println();')
        if not calls:
            return []
        return [' '.join(calls)]

    def _print_pieces(self, value: Any, line: Any) -> List[Tuple[str, str]]:
        # "a" + x + "b"  → print each part (no heap String concatenation).
        if isinstance(value, BinOp) and value.op == '+' and self._is_str_concat(value):
            return self._print_pieces(value.left, line) + self._print_pieces(value.right, line)
        if isinstance(value, Literal) and value.vtype == 'str':
            return self._interpolate(value.value, line)
        return [('expr', self._printable(value))]

    def _is_str_concat(self, node: BinOp) -> bool:
        def is_str(n: Any) -> bool:
            if isinstance(n, BinOp) and n.op == '+':
                return is_str(n.left) or is_str(n.right)
            return self._type_of(n) == 'str'
        return is_str(node)

    def _printable(self, expr: Any) -> str:
        t = self._type_of(expr)
        c = self._expr(expr)
        if t == 'bool':
            return f'({c}) ? "true" : "false"'
        if t in self._structs:
            raise CodeGenError(f'cannot print struct value `{c}`; print its fields')
        if t and t.endswith('[]'):
            raise CodeGenError(f'cannot print array `{c}`; print its elements')
        return c

    def _interpolate(self, s: str, line: Any) -> List[Tuple[str, str]]:
        """Split "temp {x} C" into literal and expression pieces.

        ``{{`` and ``}}`` produce literal braces.  A ``{...}`` whose contents
        do not parse as an expression is kept as literal text.
        """
        from lexer import tokenize, LexError
        from parser import Parser, ParseError

        pieces: List[Tuple[str, str]] = []
        buf: List[str] = []
        i = 0
        while i < len(s):
            ch = s[i]
            if ch == '{' and s.startswith('{{', i):
                buf.append('{')
                i += 2
                continue
            if ch == '}' and s.startswith('}}', i):
                buf.append('}')
                i += 2
                continue
            if ch == '{':
                j = s.find('}', i + 1)
                frag = s[i + 1:j] if j != -1 else ''
                expr = None
                if j != -1 and frag.strip():
                    try:
                        toks = tokenize(frag)
                        p = Parser(toks)
                        p.pwm_pins = set(self._pwm)
                        expr = p._parse_expr()
                        if not p._at_end():
                            expr = None
                    except (LexError, ParseError, Exception):
                        expr = None
                if expr is not None:
                    if buf:
                        pieces.append(('lit', c_string(''.join(buf))))
                        buf = []
                    pieces.append(('expr', self._printable(expr)))
                    i = j + 1
                    continue
            buf.append(ch)
            i += 1
        if buf:
            pieces.append(('lit', c_string(''.join(buf))))
        return pieces

    # ═════════════════════════════════════════
    #  EXPRESSIONS
    # ═════════════════════════════════════════

    def _cond(self, node: Any) -> str:
        return self._expr(node)

    def _expr(self, node: Any, parent_prec: int = 0) -> str:
        s, prec = self._expr_p(node)
        return f'({s})' if prec < parent_prec else s

    def _expr_p(self, node: Any) -> Tuple[str, int]:
        line = getattr(node, 'line', '?')

        if isinstance(node, Literal):
            return self._literal(node), _ATOM_PREC

        if isinstance(node, Identifier):
            return self._ident(node.name, line), _ATOM_PREC

        if isinstance(node, str):            # bare name used by some nodes
            return self._ident(node, line), _ATOM_PREC

        if isinstance(node, bool):
            return ('true' if node else 'false'), _ATOM_PREC
        if isinstance(node, int):
            return str(node), _ATOM_PREC
        if isinstance(node, float):
            return _float_lit(node), _ATOM_PREC

        if isinstance(node, MillisExpr):
            return 'millis()', _ATOM_PREC

        if isinstance(node, BinOp):
            if node.op == '+' and self._is_str_concat(node):
                raise CodeGenError(
                    f'Line {line}: string concatenation with + is only supported inside '
                    f'print()/println(); use interpolation "text {{value}}" there')
            p = _PREC.get(node.op)
            if p is None:
                raise CodeGenError(f'Line {line}: unknown operator {node.op!r}')
            left = self._expr(node.left, p)
            right = self._expr(node.right, p + 1)   # C binary ops are left-assoc
            if node.op in ('&', '|', '^', '<<', '>>'):
                # Mixed bitwise/shift/arithmetic is a classic misreading; spell it out.
                if isinstance(node.left, BinOp) and node.left.op != node.op and not left.startswith('('):
                    left = f'({left})'
                if isinstance(node.right, BinOp) and not right.startswith('('):
                    right = f'({right})'
            if node.op == '||':
                # Spell out `a || (b && c)`: same meaning, but readable.
                if isinstance(node.left, BinOp) and node.left.op == '&&':
                    left = f'({left})'
                if isinstance(node.right, BinOp) and node.right.op == '&&':
                    right = f'({right})'
            return f'{left} {node.op} {right}', p

        if isinstance(node, UnaryOp):
            if node.op not in ('!', '-', '~'):
                raise CodeGenError(f'Line {line}: unknown unary operator {node.op!r}')
            inner = self._expr(node.operand, _UNARY_PREC)
            if node.op == '-' and inner.startswith('-'):
                inner = f'({inner})'
            return f'{node.op}{inner}', _UNARY_PREC

        if isinstance(node, CastExpr):
            ct = self._ctype(node.target_type)
            return f'({ct})({self._expr(node.expr)})', _UNARY_PREC

        if isinstance(node, SizeOfExpr):
            if isinstance(node.target, str) and not self._lookup(node.target):
                return f'sizeof({self._ctype(node.target)})', _ATOM_PREC
            return f'sizeof({self._expr(node.target)})', _ATOM_PREC

        if isinstance(node, ArrayAccess):
            if node.name in self._pins:
                raise CodeGenError(f'Line {line}: pin {node.name!r} is not an array')
            return f'{node.name}[{self._expr(node.index)}]', _ATOM_PREC

        if isinstance(node, MemberAccess):
            return self._member(node), _ATOM_PREC

        if isinstance(node, MethodCall):
            return self._method(node), _ATOM_PREC

        if isinstance(node, MathExpr):
            return self._call(node.func, node.args, line), _ATOM_PREC

        if isinstance(node, FnCall):
            return self._call(node.name, node.args, line), _ATOM_PREC

        if isinstance(node, PwmWrite):
            return self._pwm_write(node.pin, node.value, line), _ATOM_PREC

        raise CodeGenError(f'Line {line}: unsupported expression {type(node).__name__}')

    def _literal(self, node: Literal) -> str:
        v, t = node.value, node.vtype
        if t == 'bool':
            return 'true' if v else 'false'
        if t == 'str':
            return c_string(str(v))
        if t == 'char':
            return c_char(v)
        if t in _FLOAT_TYPES or isinstance(v, float):
            return _float_lit(v)
        if isinstance(v, bool):
            return 'true' if v else 'false'
        if isinstance(v, int):
            if v > 0x7FFFFFFF:
                return f'{v}ULL' if v > 0xFFFFFFFF else f'{v}UL'
            return str(v)
        raise CodeGenError(f'Line {node.line}: unsupported literal {v!r}')

    def _ident(self, name: str, line: Any) -> str:
        if name in self._pins:
            return self._pin_read(name)
        if name in self._wifis:
            raise CodeGenError(f'Line {line}: wifi interface {name!r} used as a value; use {name}.connected, {name}.ip, ...')
        if name in self._timers and self._lookup(name) is None:
            raise CodeGenError(f'Line {line}: timer {name!r} used as a value; use {name}.running')
        if name in ('true', 'false'):
            return name
        return name

    def _pin_read(self, pin: str) -> str:
        d = self._pins[pin].direction
        if d == 'analog':
            return f'analogRead({pin}_PIN)'
        if d == 'pwm':
            self._needs.add('pwm')
            return f'_iotift_pwm_duty[{self._pwm[pin]["channel"]}]'
        return f'digitalRead({pin}_PIN)'

    def _member(self, node: MemberAccess) -> str:
        obj, m, line = node.obj, node.member, node.line
        if isinstance(obj, str):
            if obj in self._wifis:
                return self._wifi_prop(obj, m, line)
            if obj in self._timers and self._lookup(obj) is None:
                if m in ('running', 'active'):
                    return f'{self._timers[obj]}_active'
                raise CodeGenError(f'Line {line}: timers have .running, .start(), .stop() (not .{m})')
            if obj in self._enums:
                if m not in {v for v, _ in self._enums[obj].variants}:
                    raise CodeGenError(f'Line {line}: enum {obj} has no value {m!r}')
                return m
            if obj == 'WifiState':
                states = {'IDLE', 'CONNECTING', 'CONNECTED', 'DISCONNECTED'}
                if m.upper() not in states:
                    raise CodeGenError(f'Line {line}: WifiState has no value {m!r}')
                return f'WIFI_STATE_{m.upper()}'
            if obj in self._pins:
                if m in ('value', 'state'):
                    return self._pin_read(obj)
                raise CodeGenError(f'Line {line}: pins have no property .{m}; use {obj}.read()')
            return f'{obj}.{m}'
        return f'{self._expr(obj, _ATOM_PREC)}.{m}'

    def _method(self, node: MethodCall) -> str:
        obj, m, args, line = node.obj, node.method, node.args, node.line
        if isinstance(obj, str):
            if obj in self._pins:
                return self._pin_method(obj, m, args, line)
            if obj in self._wifis:
                return self._wifi_method(obj, m, args, line)
            if obj in self._timers and self._lookup(obj) is None:
                base = self._timers[obj]
                if args:
                    raise CodeGenError(f'Line {line}: {obj}.{m}() takes no arguments')
                if m == 'stop':
                    return f'({base}_active = false)'
                if m == 'start':
                    return f'({base}_active = true, {base}_last = millis())'
                raise CodeGenError(f'Line {line}: timers have .start() and .stop() (not .{m}())')
            obj_c = obj
        else:
            obj_c = self._expr(obj, _ATOM_PREC)
        a = ', '.join(self._expr(x) for x in args)
        return f'{obj_c}.{m}({a})'

    def _pin_method(self, pin: str, m: str, args: List[Any], line: Any) -> str:
        d = self._pins[pin].direction

        def nargs(n: int) -> None:
            if len(args) != n:
                raise CodeGenError(f'Line {line}: {pin}.{m}() takes {n} argument(s), got {len(args)}')

        if m in ('high', 'low', 'toggle', 'on', 'off'):
            nargs(0)
            if d != 'output':
                raise CodeGenError(f'Line {line}: {pin}.{m}() needs an output pin ({pin!r} is {d})')
            if m in ('high', 'on'):
                return f'digitalWrite({pin}_PIN, HIGH)'
            if m in ('low', 'off'):
                return f'digitalWrite({pin}_PIN, LOW)'
            return f'digitalWrite({pin}_PIN, !digitalRead({pin}_PIN))'
        if m == 'read':
            nargs(0)
            return self._pin_read(pin)
        if m == 'write':
            nargs(1)
            if d == 'pwm':
                return self._pwm_write(pin, args[0], line)
            if d == 'output':
                return self._pin_assign(pin, args[0], line)
            if d == 'analog' and self._is_esp32():
                return f'dacWrite({pin}_PIN, (uint8_t)({self._expr(args[0])}))'
            raise CodeGenError(f'Line {line}: cannot write to {d} pin {pin!r}')
        if m == 'setup':
            if d != 'pwm':
                raise CodeGenError(f'Line {line}: {pin}.setup() is only for pwm pins')
            if len(args) not in (1, 2):
                raise CodeGenError(f'Line {line}: {pin}.setup(freq, resolution) takes 1–2 arguments')
            res = args[1] if len(args) > 1 else 8
            return self._pwm_runtime_setup(pin, args[0], res, line)
        raise CodeGenError(
            f'Line {line}: unknown pin method {pin}.{m}() '
            f'(pins have high, low, toggle, read, write' + (', setup' if d == 'pwm' else '') + ')')

    def _call(self, name: str, args: List[Any], line: Any) -> str:
        a = [self._expr(x) for x in args]
        joined = ', '.join(a)

        if name in self._fns:
            fn = self._fns[name]
            if len(fn.params) != len(args):
                raise CodeGenError(f'Line {line}: {name}() takes {len(fn.params)} argument(s), got {len(args)}')
            return f'{name}({joined})'
        if name in self._pins or name in self._wifis or name in self._timers:
            raise CodeGenError(f'Line {line}: {name!r} is not a function')

        if name == 'abs':
            if len(a) != 1:
                raise CodeGenError(f'Line {line}: abs() takes 1 argument')
            return f'fabsf({a[0]})' if self._type_of(args[0]) in _FLOAT_TYPES else f'abs({a[0]})'
        if name in ('min', 'max'):
            if len(a) != 2:
                raise CodeGenError(f'Line {line}: {name}() takes 2 arguments')
            self._needs.add('minmax')
            return f'_iotift_{name}({joined})'
        if name == 'clamp':
            if len(a) != 3:
                raise CodeGenError(f'Line {line}: clamp(value, lo, hi) takes 3 arguments')
            self._needs.add('minmax')
            return f'_iotift_clamp({joined})'
        if name == 'map':
            if len(a) != 5:
                raise CodeGenError(f'Line {line}: map(x, in_lo, in_hi, out_lo, out_hi) takes 5 arguments')
            self._needs.add('map')
            return f'_iotift_map({joined})'
        if name == 'delay_us':
            return f'delayMicroseconds({joined})'
        if name == 'esp_restart':
            return 'ESP.restart()' if self._is_esp32() else 'NVIC_SystemReset()'
        if name == 'breakpoint':
            return 'asm("break 0,0")' if self._is_esp32() else 'asm("bkpt")'
        if name in ('millis', 'micros'):
            return f'{name}()'
        if name in ('delay', 'delayMicroseconds') and self._fn and self._fn.is_isr:
            raise CodeGenError(f'Line {line}: {name}() cannot be called inside an isr fn')
        if name.startswith('scan_result_') and name[len('scan_result_'):] in ('count', 'ssid', 'rssi', 'channel'):
            if not any(w.mode == 'sta' for w in self._wifis.values()):
                raise CodeGenError(f'Line {line}: {name}() needs a station-mode wifi block')
            return f'_iotift_wifi_{name}({joined})'
        if name in self._externs or name in _PLATFORM_FUNCTIONS or name in _MATH_FLOAT_FUNCS:
            return f'{name}({joined})'
        # Unknown name: may be provided by a `c global` / `c header` block.
        return f'{name}({joined})'

    # ═════════════════════════════════════════
    #  TYPE INFERENCE  (just enough to print and pick int vs float ops)
    # ═════════════════════════════════════════

    def _lookup(self, name: str) -> Optional[str]:
        for scope in reversed(self._scopes):
            if name in scope:
                return scope[name]
        return self._globals.get(name)

    def _resolve_alias(self, t: Optional[str]) -> Optional[str]:
        seen = set()
        while t in self._aliases and t not in seen:
            seen.add(t)
            t = self._aliases[t]
        return t

    def _type_of(self, node: Any) -> Optional[str]:
        t = self._type_of_raw(node)
        return self._resolve_alias(t)

    def _type_of_raw(self, node: Any) -> Optional[str]:
        if isinstance(node, Literal):
            return 'float' if node.vtype in _FLOAT_TYPES else node.vtype
        if isinstance(node, bool):
            return 'bool'
        if isinstance(node, int):
            return 'int'
        if isinstance(node, float):
            return 'float'
        if isinstance(node, (Identifier, str)):
            name = node.name if isinstance(node, Identifier) else node
            if name in self._pins:
                return 'int'
            if name in self._enum_variant:
                return 'int'
            if name in ('true', 'false'):
                return 'bool'
            return self._lookup(name)
        if isinstance(node, MillisExpr):
            return 'ulong'
        if isinstance(node, BinOp):
            if node.op in ('&&', '||', '==', '!=', '<', '>', '<=', '>='):
                return 'bool'
            lt, rt = self._type_of(node.left), self._type_of(node.right)
            if node.op == '+' and 'str' in (lt, rt):
                return 'str'
            if lt in _FLOAT_TYPES or rt in _FLOAT_TYPES:
                return 'float'
            if 'ulong' in (lt, rt):
                return 'ulong'
            return 'int'
        if isinstance(node, UnaryOp):
            if node.op == '!':
                return 'bool'
            return self._type_of(node.operand)
        if isinstance(node, CastExpr):
            return node.target_type
        if isinstance(node, SizeOfExpr):
            return 'int'
        if isinstance(node, ArrayAccess):
            return self._arrays.get(node.name) or (self._lookup(node.name) or '').replace('[]', '') or None
        if isinstance(node, MemberAccess):
            obj = node.obj
            if isinstance(obj, str):
                if obj in self._wifis:
                    return {'connected': 'bool', 'ip': 'str', 'mac': 'str', 'ssid': 'str',
                            'rssi': 'int', 'channel': 'int', 'clients': 'int',
                            'state': 'int'}.get(node.member)
                if obj in self._timers:
                    return 'bool'
                if obj in self._enums:
                    return 'int'
                st = self._lookup(obj)
                if st in self._structs:
                    return self._structs[st].get(node.member)
            return None
        if isinstance(node, MethodCall):
            obj = node.obj
            if isinstance(obj, str) and obj in self._pins:
                return 'int' if node.method == 'read' else 'void'
            return None
        if isinstance(node, (FnCall, MathExpr)):
            name = node.name if isinstance(node, FnCall) else node.func
            if name in self._fns:
                return self._fns[name].return_type or 'void'
            if name in self._externs:
                return self._externs[name].return_type or 'void'
            if name in _MATH_FLOAT_FUNCS:
                return 'float'
            if name in ('abs', 'min', 'max', 'clamp'):
                ts = [self._type_of(a) for a in node.args]
                return 'float' if any(t in _FLOAT_TYPES for t in ts) else 'int'
            if name == 'map':
                return 'float'
            return _BUILTIN_RET.get(name)
        return None

    def _decl_type(self, node: VarDecl) -> str:
        if node.vtype:
            return node.vtype
        t = self._type_of(node.init) if node.init is not None else None
        return t or 'int'

    # ═════════════════════════════════════════
    #  DECLARATION HELPERS
    # ═════════════════════════════════════════

    def _ctype(self, t: Optional[str]) -> str:
        if t is None:
            return 'auto'
        return _CTYPE.get(t, t)

    def _var_decl(self, node: VarDecl, is_global: bool) -> str:
        quals = []
        if node.is_const or not node.is_mutable:
            quals.append('const')
        if node.is_volatile:
            quals.append('volatile')
        if node.vtype:
            ct = self._ctype(node.vtype)
        else:
            inferred = self._type_of(node.init) if node.init is not None else None
            if inferred == 'ulong':
                ct = 'unsigned long'
            elif inferred in ('str',):
                ct = 'const char*'
            elif inferred:
                ct = self._ctype(inferred)
            else:
                ct = 'int'
        if node.vtype == 'str' and node.is_const:
            ct = 'const char* const'
            quals = [q for q in quals if q != 'const']
        prefix = ' '.join(quals) + ' ' if quals else ''
        if node.init is None:
            if 'const' in quals:
                raise CodeGenError(f'Line {node.line}: constant {node.name!r} needs a value')
            # Locals are zero-initialised too, so the program never reads garbage.
            return f'{prefix}{ct} {node.name}' + ('' if is_global else '{}')
        if isinstance(node.init, BinOp) and node.init.op == '+' and self._is_str_concat(node.init):
            raise CodeGenError(
                f'Line {node.line}: cannot build a string with + (no heap strings); '
                f'print the parts with print()/println() instead')
        return f'{prefix}{ct} {node.name} = {self._expr(node.init)}'

    def _array_decl(self, node: ArrayDecl) -> str:
        if node.size <= 0:
            raise CodeGenError(f'Line {node.line}: array {node.name!r} must have a positive size')
        ct = self._ctype(node.vtype or 'int')
        if node.init is not None:
            if isinstance(node.init, list):
                return f'{ct} {node.name}[{node.size}] = {{{", ".join(self._expr(x) for x in node.init)}}}'
            raise CodeGenError(f'Line {node.line}: unsupported array initialiser')
        return f'{ct} {node.name}[{node.size}] = {{}}'

    def _is_esp32(self) -> bool:
        return self._device.lower().startswith('esp32')

    def _warn(self, msg: str) -> None:
        self.warnings.append(msg)
        print(f'warning: {msg}', file=sys.stderr)

    # ═════════════════════════════════════════
    #  WIFI RUNTIME
    # ═════════════════════════════════════════

    def _wifi_prop(self, name: str, prop: str, line: Any) -> str:
        wd = self._wifis[name]
        p = f'_iotift_wifi_{name}'
        table = {
            'state': f'{p}_state', 'connected': f'{p}_connected', 'ip': f'{p}_ip',
            'mac': f'{p}_mac', 'channel': f'{p}_channel',
            'ssid': c_string(wd.config.get('ssid', '')),
        }
        if wd.mode == 'sta':
            table['rssi'] = f'{p}_rssi_now()'
        else:
            table['clients'] = f'{p}_client_count'
        if prop not in table:
            raise CodeGenError(f'Line {line}: {name}.{prop}: unknown property for a '
                               f'{"station" if wd.mode == "sta" else "access point"} '
                               f'(available: {", ".join(sorted(table))})')
        return table[prop]

    def _wifi_method(self, name: str, m: str, args: List[Any], line: Any) -> str:
        wd = self._wifis[name]
        if args:
            raise CodeGenError(f'Line {line}: {name}.{m}() takes no arguments')
        if m == 'scan':
            if wd.mode != 'sta':
                raise CodeGenError(f'Line {line}: scan() is only available on station-mode wifi')
            return f'_iotift_wifi_{name}_scan_start()'
        if m == 'disconnect':
            return f'_iotift_wifi_{name}_disconnect()'
        if m in ('reconnect', 'connect'):
            if wd.mode != 'sta':
                raise CodeGenError(f'Line {line}: {m}() is only available on station-mode wifi')
            return f'_iotift_wifi_{name}_reconnect()'
        raise CodeGenError(f'Line {line}: unknown wifi method {name}.{m}() (scan, disconnect, reconnect)')

    @staticmethod
    def _retry_policy(cfg: dict) -> Tuple[int, int, int, bool]:
        """Return (max_retries or -1 for unlimited, base_ms, max_ms, exponential)."""
        r = cfg.get('retry') or {'kind': 'fixed'}
        kind = r.get('kind', 'fixed')
        if kind == 'none':
            return 0, 0, 0, False
        if kind == 'fixed':
            return 3, 5000, 5000, False
        if kind == 'forever':
            return -1, 5000, 5000, False
        if kind == 'exponential':
            return -1, 1000, 60000, True
        if kind == 'custom':
            return (int(r.get('count', 3)), int(r.get('interval_ms', 5000)),
                    int(r.get('max_interval_ms', 60000)), r.get('backoff') == 'exponential')
        return 3, 5000, 5000, False

    def _emit_wifi(self) -> None:
        if not self._wifis:
            return
        S: List[str] = self._state_vars
        S += [
            'typedef enum {',
            '  WIFI_STATE_IDLE = 0,',
            '  WIFI_STATE_CONNECTING,',
            '  WIFI_STATE_CONNECTED,',
            '  WIFI_STATE_DISCONNECTED,',
            '} wifi_state_t;',
            'static bool _iotift_wifi_system_initialized = false;',
        ]
        sta = next((w for w in self._wifis.values() if w.mode == 'sta'), None)
        ap = next((w for w in self._wifis.values() if w.mode == 'ap'), None)

        for wd in self._wifis.values():
            p = f'_iotift_wifi_{wd.name}'
            S += [
                f'static wifi_state_t {p}_state = WIFI_STATE_IDLE;',
                f'static bool {p}_connected = false;',
                f'static char {p}_ip[16] = "0.0.0.0";',
                f'static char {p}_mac[18] = "";',
                f'static int {p}_channel = 0;',
            ]
            if wd.mode == 'sta':
                S += [
                    f'static volatile bool {p}_ev_got_ip = false;',
                    f'static volatile bool {p}_ev_lost = false;',
                    f'static int {p}_retry_count = 0;',
                    f'static bool {p}_retry_pending = false;',
                    f'static bool {p}_manual_off = false;',
                    f'static unsigned long {p}_attempt_ms = 0UL;',
                    f'static unsigned long {p}_next_retry_ms = 0UL;',
                    f'static bool {p}_scan_requested = false;',
                ]
            else:
                S += [
                    f'static int {p}_client_count = 0;',
                    f'static volatile uint8_t {p}_ev_join = 0;',
                    f'static volatile uint8_t {p}_ev_leave = 0;',
                ]
        if sta:
            S += [
                '#define IOTIFT_WIFI_SCAN_MAX 16',
                'static char _iotift_wifi_scan_ssids[IOTIFT_WIFI_SCAN_MAX][33];',
                'static int _iotift_wifi_scan_rssis[IOTIFT_WIFI_SCAN_MAX];',
                'static int _iotift_wifi_scan_channels[IOTIFT_WIFI_SCAN_MAX];',
                'static int _iotift_wifi_scan_count = 0;',
            ]

        H = self._handler_fns
        # User event handlers.
        for (target, event), body in self._wifi_events.items():
            if body:
                fname = f'_iotift_wifi_{target}_on_{event}'
                H.append(self._fn_body('static void', fname, 'void', body, _Fn(fname)))

        def call(target: str, event: str) -> List[str]:
            if self._wifi_events.get((target, event)):
                return [f'_iotift_wifi_{target}_on_{event}();']
            return []

        # Driver callback: runs in the WiFi task, so it only sets flags.
        cb = ['static void _iotift_wifi_on_event(WiFiEvent_t event, WiFiEventInfo_t info) {',
              '  (void)info;',
              '  switch (event) {']
        if sta:
            p = f'_iotift_wifi_{sta.name}'
            cb += [f'    case ARDUINO_EVENT_WIFI_STA_GOT_IP: {p}_ev_got_ip = true; break;',
                   f'    case ARDUINO_EVENT_WIFI_STA_DISCONNECTED: {p}_ev_lost = true; break;']
        if ap:
            p = f'_iotift_wifi_{ap.name}'
            cb += [f'    case ARDUINO_EVENT_WIFI_AP_STACONNECTED: {p}_ev_join++; break;',
                   f'    case ARDUINO_EVENT_WIFI_AP_STADISCONNECTED: {p}_ev_leave++; break;']
        cb += ['    default: break;', '  }', '}']
        H.append(cb)

        if sta:
            self._emit_wifi_sta(sta, call)
        if ap:
            self._emit_wifi_ap(ap, call)

        # Scan accessors (always available for a STA interface).
        if sta:
            H.append(['static int _iotift_wifi_scan_result_count(void) {',
                      '  return _iotift_wifi_scan_count;', '}'])
            H.append(['static const char* _iotift_wifi_scan_result_ssid(int i) {',
                      '  return (i >= 0 && i < _iotift_wifi_scan_count) ? _iotift_wifi_scan_ssids[i] : "";', '}'])
            H.append(['static int _iotift_wifi_scan_result_rssi(int i) {',
                      '  return (i >= 0 && i < _iotift_wifi_scan_count) ? _iotift_wifi_scan_rssis[i] : 0;', '}'])
            H.append(['static int _iotift_wifi_scan_result_channel(int i) {',
                      '  return (i >= 0 && i < _iotift_wifi_scan_count) ? _iotift_wifi_scan_channels[i] : 0;', '}'])

        # System init.
        init = ['static void _iotift_wifi_system_init(void) {',
                '  if (_iotift_wifi_system_initialized) return;',
                '  _iotift_wifi_system_initialized = true;',
                '  WiFi.onEvent(_iotift_wifi_on_event);']
        if sta and sta.config.get('hostname'):
            # Must be set before the interface is started.
            init.append(f'  WiFi.setHostname({c_string(sta.config["hostname"])});')
        mode = 'WIFI_AP_STA' if (sta and ap) else ('WIFI_AP' if ap else 'WIFI_STA')
        init.append(f'  WiFi.mode({mode});')
        if sta:
            cfg = sta.config
            init.append('  WiFi.setAutoReconnect(false);  // reconnects follow the declared retry policy')
            ps = cfg.get('power_save')
            if ps == 'none':
                init.append('  WiFi.setSleep(false);')
            elif ps == 'light':
                init.append('  WiFi.setSleep(true);')
            elif ps == 'deep':
                init.append('  WiFi.setSleep(WIFI_PS_MAX_MODEM);')
            if cfg.get('static_ip'):
                if not (cfg.get('gateway') and cfg.get('subnet')):
                    raise CodeGenError(f'wifi {sta.name}: static_ip also needs gateway and subnet')
                ips = [cfg['static_ip'], cfg['gateway'], cfg['subnet'], cfg.get('dns', cfg['gateway'])]
                for ip in ips:
                    if not re.fullmatch(r'(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})', str(ip)) or \
                            any(int(x) > 255 for x in str(ip).split('.')):
                        raise CodeGenError(f'wifi {sta.name}: {ip!r} is not a valid IPv4 address')
                args = ', '.join(f'IPAddress({ip.replace(".", ", ")})' for ip in ips)
                init.append(f'  WiFi.config({args});')
        if ap:
            cfg = ap.config
            pw = cfg.get('password')
            p = f'_iotift_wifi_{ap.name}'
            init += [
                f'  if (WiFi.softAP({c_string(cfg["ssid"])}, {c_string(pw) if pw else "NULL"}, '
                f'{int(cfg.get("channel", 1))}, {1 if cfg.get("hidden") else 0}, {int(cfg.get("max_clients", 4))})) {{',
                f'    {p}_state = WIFI_STATE_CONNECTED;',
                f'    {p}_connected = true;',
                f'    strncpy({p}_ip, WiFi.softAPIP().toString().c_str(), sizeof({p}_ip) - 1);',
                f'    strncpy({p}_mac, WiFi.softAPmacAddress().c_str(), sizeof({p}_mac) - 1);',
                f'    {p}_channel = {int(cfg.get("channel", 1))};',
                '  } else {',
                f'    Serial.println("[iotift] wifi {ap.name}: failed to start access point");',
                '  }',
            ]
        if sta:
            init.append(f'  _iotift_wifi_{sta.name}_begin();')
        init.append('}')
        H.append(init)
        self._setup_body.insert(0, '  _iotift_wifi_system_init();')

        # loop() dispatch: one per interface (names kept stable for tooling).
        for wd in self._wifis.values():
            self._loop_calls.append(f'_iotift_wifi_{wd.name}_dispatch();')

    def _emit_wifi_sta(self, wd: WifiDecl, call) -> None:
        H = self._handler_fns
        n = wd.name
        p = f'_iotift_wifi_{n}'
        cfg = wd.config
        max_r, base_ms, max_ms, expo = self._retry_policy(cfg)
        timeout = int(cfg.get('connect_timeout', 30000))
        pw = cfg.get('password')

        H.append([f'static void {p}_begin(void) {{',
                  f'  WiFi.begin({c_string(cfg["ssid"])}' + (f', {c_string(pw)}' if pw else '') + ');',
                  f'  {p}_state = WIFI_STATE_CONNECTING;',
                  f'  {p}_attempt_ms = millis();',
                  '}'])
        if expo:
            delay_expr = (f'  unsigned long _d = {base_ms}UL;\n'
                          f'  for (int _i = 1; _i < {p}_retry_count && _d < {max_ms}UL; _i++) _d *= 2UL;\n'
                          f'  if (_d > {max_ms}UL) _d = {max_ms}UL;')
        else:
            delay_expr = f'  unsigned long _d = {base_ms}UL;'
        limit = 'true' if max_r < 0 else f'{p}_retry_count < {max_r}'
        H.append([f'/* retry policy: {(cfg.get("retry") or {"kind": "fixed"}).get("kind")} */',
                  f'static bool {p}_schedule_retry(void) {{',
                  f'  if ({p}_manual_off || !({limit})) return false;',
                  f'  {p}_retry_count++;'] + delay_expr.split('\n') + [
                  f'  {p}_next_retry_ms = millis() + _d;',
                  f'  {p}_retry_pending = true;',
                  '  return true;',
                  '}'])
        H.append([f'static int {p}_rssi_now(void) {{',
                  f'  return {p}_connected ? (int)WiFi.RSSI() : 0;', '}'])
        H.append([f'static void {p}_scan_start(void) {{',
                  '  if (WiFi.scanComplete() == WIFI_SCAN_RUNNING) return;',
                  '  WiFi.scanDelete();',
                  '  if (WiFi.scanNetworks(true) == WIFI_SCAN_FAILED) return;',
                  f'  {p}_scan_requested = true;', '}'])
        H.append([f'static void {p}_disconnect(void) {{',
                  f'  {p}_manual_off = true;',
                  f'  {p}_retry_pending = false;',
                  f'  bool _was = {p}_connected;',
                  '  WiFi.disconnect(false);',
                  f'  {p}_state = WIFI_STATE_DISCONNECTED;',
                  f'  {p}_connected = false;',
                  f'  strcpy({p}_ip, "0.0.0.0");',
                  f'  if (_was) {{ {" ".join(call(n, "disconnect"))} }}' if call(n, 'disconnect') else '  (void)_was;',
                  '}'])
        H.append([f'static void {p}_reconnect(void) {{',
                  f'  {p}_manual_off = false;',
                  f'  {p}_retry_count = 0;',
                  f'  if ({p}_state != WIFI_STATE_CONNECTED && {p}_state != WIFI_STATE_CONNECTING) {p}_begin();',
                  '}'])

        d = [f'static void {p}_dispatch(void) {{',
             '  unsigned long _now = millis();',
             f'  if ({p}_ev_got_ip) {{',
             f'    {p}_ev_got_ip = false;',
             f'    {p}_state = WIFI_STATE_CONNECTED;',
             f'    {p}_connected = true;',
             f'    {p}_retry_count = 0;',
             f'    {p}_retry_pending = false;',
             f'    strncpy({p}_ip, WiFi.localIP().toString().c_str(), sizeof({p}_ip) - 1);',
             f'    strncpy({p}_mac, WiFi.macAddress().c_str(), sizeof({p}_mac) - 1);',
             f'    {p}_channel = WiFi.channel();']
        d += ['    ' + c for c in call(n, 'got_ip') + call(n, 'connect')]
        d += ['  }',
              f'  if ({p}_ev_lost) {{',
              f'    {p}_ev_lost = false;',
              f'    bool _was = {p}_connected;',
              f'    if ({p}_state == WIFI_STATE_CONNECTED || {p}_state == WIFI_STATE_CONNECTING) {{',
              f'      {p}_state = WIFI_STATE_DISCONNECTED;',
              f'      {p}_connected = false;',
              f'      strcpy({p}_ip, "0.0.0.0");',
              f'      {p}_schedule_retry();',
              '    }']
        if call(n, 'disconnect'):
            d.append(f'    if (_was) {{ {" ".join(call(n, "disconnect"))} }}')
        else:
            d.append('    (void)_was;')
        d += ['  }',
              f'  if ({p}_state == WIFI_STATE_CONNECTING && _now - {p}_attempt_ms >= {timeout}UL) {{',
              '    // attempt timed out',
              f'    {p}_state = WIFI_STATE_DISCONNECTED;',
              '    WiFi.disconnect(false);',
              f'    {p}_schedule_retry();',
              '  }',
              f'  if ({p}_retry_pending && {p}_state == WIFI_STATE_DISCONNECTED &&',
              f'      (long)(_now - {p}_next_retry_ms) >= 0) {{',
              f'    {p}_retry_pending = false;',
              f'    {p}_begin();',
              '  }',
              f'  if ({p}_scan_requested) {{',
              '    int _n = WiFi.scanComplete();',
              '    if (_n != WIFI_SCAN_RUNNING) {',
              f'      {p}_scan_requested = false;',
              '      if (_n < 0) _n = 0;',
              '      if (_n > IOTIFT_WIFI_SCAN_MAX) _n = IOTIFT_WIFI_SCAN_MAX;',
              '      for (int _i = 0; _i < _n; _i++) {',
              '        strncpy(_iotift_wifi_scan_ssids[_i], WiFi.SSID(_i).c_str(), 32);',
              '        _iotift_wifi_scan_ssids[_i][32] = 0;',
              '        _iotift_wifi_scan_rssis[_i] = WiFi.RSSI(_i);',
              '        _iotift_wifi_scan_channels[_i] = WiFi.channel(_i);',
              '      }',
              '      _iotift_wifi_scan_count = _n;',
              '      WiFi.scanDelete();']
        d += ['      ' + c for c in call(n, 'scan_done')]
        d += ['    }', '  }', '}']
        H.append(d)

    def _emit_wifi_ap(self, wd: WifiDecl, call) -> None:
        n = wd.name
        p = f'_iotift_wifi_{n}'
        H = self._handler_fns
        H.append([f'static void {p}_disconnect(void) {{',
                  '  WiFi.softAPdisconnect(true);',
                  f'  {p}_state = WIFI_STATE_DISCONNECTED;',
                  f'  {p}_connected = false;',
                  f'  {p}_client_count = 0;', '}'])
        d = [f'static void {p}_dispatch(void) {{',
             f'  while ({p}_ev_join) {{',
             f'    {p}_ev_join--;',
             f'    {p}_client_count = WiFi.softAPgetStationNum();']
        d += ['    ' + c for c in call(n, 'client_join')]
        d += ['  }',
              f'  while ({p}_ev_leave) {{',
              f'    {p}_ev_leave--;',
              f'    {p}_client_count = WiFi.softAPgetStationNum();']
        d += ['    ' + c for c in call(n, 'client_leave')]
        d += ['  }', '}']
        H.append(d)

    # ═════════════════════════════════════════
    #  ASSEMBLY
    # ═════════════════════════════════════════

    def _assemble(self) -> str:
        L: List[str] = []
        now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        L += ['/**',
              ' * @file    generated.cpp',
              f' * @brief   Auto-generated by Iotift Compiler v{__version__}',
              f' * @date    {now}',
              f' * @target  {self._device} (Arduino framework)',
              ' * @warning This file is auto-generated.  Edits will be overwritten.',
              ' */',
              '',
              '#include <Arduino.h>',
              '#include <math.h>']
        if self._wifis:
            L.append('#include <WiFi.h>')
        L.append('')
        for code in self._header_blocks:
            L += [code, '']
        L += ['#ifndef IRAM_ATTR',
              '#define IRAM_ATTR',
              '#endif',
              '',
              '#ifndef IOTIFT_BAUD_RATE',
              f'#define IOTIFT_BAUD_RATE          {self._baud}UL',
              '#endif',
              '']

        if self._pins:
            self._section(L, 'PIN DEFINITIONS')
            for name, pin in self._pins.items():
                num = f'{pin.number}U' if isinstance(pin.number, int) else str(pin.number)
                L.append(f'static const uint8_t {name}_PIN = {num};')
            L.append('')

        if self._type_decls:
            self._section(L, 'TYPES')
            for t in self._type_decls:
                L += [t, '']

        if self._global_vars:
            self._section(L, 'GLOBAL STATE')
            L += self._global_vars
            L.append('')

        runtime = self._runtime_helpers()
        if runtime or self._state_vars:
            self._section(L, 'RUNTIME')
            L += self._state_vars
            if self._state_vars:
                L.append('')
            L += runtime

        # Prototype every generated function so definition order never matters.
        handler_protos = []
        for fn in self._handler_fns:
            sig = next((ln for ln in fn if not ln.lstrip().startswith(('/*', '//'))), '')
            if sig.startswith('static ') and sig.rstrip().endswith('{'):
                handler_protos.append(sig.rstrip()[:-1].rstrip() + ';')
        if self._prototypes or handler_protos:
            self._section(L, 'FORWARD DECLARATIONS')
            L += self._prototypes + handler_protos
            L.append('')

        if self._global_blocks:
            self._section(L, 'RAW C (global)')
            for code in self._global_blocks:
                L += [code, '']

        if self._user_fns:
            self._section(L, 'USER FUNCTIONS')
            for fn in self._user_fns:
                L += fn + ['']

        if self._handler_fns:
            self._section(L, 'EVENT & TIMER HANDLERS')
            for fn in self._handler_fns:
                L += fn + ['']

        self._section(L, 'SETUP')
        L += ['void setup(void) {', '  Serial.begin(IOTIFT_BAUD_RATE);']
        for name, pin in self._pins.items():
            if pin.direction == 'pwm':
                continue
            if pin.direction == 'input':
                pull = pin.config.pull if pin.config else None
                mode = {'down': 'INPUT_PULLDOWN', 'none': 'INPUT', 'off': 'INPUT'}.get(pull or '', 'INPUT_PULLUP')
            elif pin.direction == 'output':
                mode = 'OUTPUT'
            elif pin.direction == 'analog':
                mode = None   # ADC pins need no pinMode; INPUT would disable the pull-ups only
            else:
                mode = 'INPUT'
            if mode:
                L.append(f'  pinMode({name}_PIN, {mode});')
            if pin.direction == 'output' and pin.config and pin.config.initial is not None:
                init = pin.config.initial
                lvl = 'HIGH' if str(init).lower() in ('1', 'high', 'true', 'on') else 'LOW'
                L.append(f'  digitalWrite({name}_PIN, {lvl});')
        for name, info in self._pwm.items():
            self._needs.add('pwm')
            L.append(f'  _iotift_pwm_setup({info["channel"]}, {name}_PIN, {info["freq"]}, {info["res"]});')
        L += self._setup_body
        for code in self._setup_blocks:
            L += ['  ' + ln if ln.strip() else '' for ln in code.split('\n')]
        L += ['  ' + s for s in self._setup_late]
        L += ['}', '']

        self._section(L, 'MAIN LOOP')
        L.append('void loop(void) {')
        L += ['  ' + c for c in self._loop_calls]
        if 'scheduler' in self._needs:
            L.append('  _iotift_scheduler_tick();')
        for code in self._loop_blocks:
            # A `return` inside a c loop block must not skip yield().
            L.append('  [&]() {')
            L += ['    ' + ln if ln.strip() else '' for ln in code.split('\n')]
            L.append('  }();')
        L += ['  yield();', '}', '']

        # Helpers are discovered while emitting setup(); re-run if new ones appeared.
        out = '\n'.join(L)
        if runtime != self._runtime_helpers():
            return self._assemble()
        return out

    @staticmethod
    def _section(L: List[str], title: str) -> None:
        L += ['/* ' + '=' * 76, f' *  {title}', ' * ' + '=' * 76 + ' */', '']

    def _runtime_helpers(self) -> List[str]:
        R: List[str] = []
        if 'minmax' in self._needs:
            R += ['template <typename A, typename B>',
                  'static inline auto _iotift_min(A a, B b) -> decltype(a + b) { return a < b ? a : b; }',
                  'template <typename A, typename B>',
                  'static inline auto _iotift_max(A a, B b) -> decltype(a + b) { return a > b ? a : b; }',
                  'template <typename V, typename L, typename H>',
                  'static inline auto _iotift_clamp(V v, L lo, H hi) -> decltype(v + lo + hi) {',
                  '  return v < lo ? lo : (v > hi ? hi : v);',
                  '}', '']
        if 'map' in self._needs:
            R += ['static inline float _iotift_map(float x, float in_lo, float in_hi, float out_lo, float out_hi) {',
                  '  if (in_hi == in_lo) return out_lo;',
                  '  return (x - in_lo) * (out_hi - out_lo) / (in_hi - in_lo) + out_lo;',
                  '}', '']
        if 'pwm' in self._needs or self._pwm:
            n = max(1, len(self._pwm))
            R += [f'static float _iotift_pwm_duty[{n}];',
                  f'static uint32_t _iotift_pwm_max[{n}];',
                  'static void _iotift_pwm_setup(uint8_t ch, uint8_t pin, uint32_t freq, uint8_t bits) {',
                  '  _iotift_pwm_max[ch] = (1UL << bits) - 1UL;',
                  '#if defined(ARDUINO_ARCH_ESP32) && defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3',
                  '  (void)ch;',
                  '  ledcAttach(pin, freq, bits);',
                  '#elif defined(ARDUINO_ARCH_ESP32)',
                  '  ledcSetup(ch, freq, bits);',
                  '  ledcAttachPin(pin, ch);',
                  '#else',
                  '  (void)freq; _iotift_pwm_max[ch] = 255UL;  // analogWrite is 8-bit here',
                  '  pinMode(pin, OUTPUT);',
                  '#endif',
                  '}',
                  'static void _iotift_pwm_write(uint8_t ch, uint8_t pin, float duty) {',
                  '  if (!(duty > 0.0f)) duty = 0.0f;  // also catches NaN',
                  '  if (duty > (float)_iotift_pwm_max[ch]) duty = (float)_iotift_pwm_max[ch];',
                  '  _iotift_pwm_duty[ch] = duty;',
                  '  uint32_t d = (uint32_t)(duty + 0.5f);',
                  '#if defined(ARDUINO_ARCH_ESP32) && defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3',
                  '  ledcWrite(pin, d);',
                  '#elif defined(ARDUINO_ARCH_ESP32)',
                  '  (void)pin;',
                  '  ledcWrite(ch, d);',
                  '#else',
                  '  analogWrite(pin, (int)d);',
                  '#endif',
                  '}', '']
        if 'scheduler' in self._needs:
            n = self._max_tasks
            R += ['/* Deferred actions (`x = v after t`, `after t { }`): fixed-size min-heap. */',
                  '#ifndef IOTIFT_SCHEDULER_SLOTS',
                  f'#define IOTIFT_SCHEDULER_SLOTS    {n}U',
                  '#endif',
                  'typedef enum { IOTIFT_TASK_PIN, IOTIFT_TASK_INT, IOTIFT_TASK_FN } iotift_task_type_t;',
                  'typedef struct {',
                  '  iotift_task_type_t type;',
                  '  unsigned long      due;',
                  '  uint8_t            pin;',
                  '  uint8_t            pin_value;',
                  '  volatile int *     var_ptr;',
                  '  int                var_value;',
                  '  void (*fn)(void);',
                  '} iotift_task_t;',
                  'static iotift_task_t _iotift_scheduler[IOTIFT_SCHEDULER_SLOTS];',
                  'static uint8_t _iotift_scheduler_size = 0U;',
                  'static bool _iotift_scheduler_overflow = false;',
                  '',
                  '// Wrap-safe "a is due before b" (millis() wraps after ~49 days).',
                  'static inline bool _iotift_before(unsigned long a, unsigned long b) { return (long)(a - b) < 0; }',
                  'static void _iotift_scheduler_swap(uint8_t i, uint8_t j) {',
                  '  iotift_task_t t = _iotift_scheduler[i];',
                  '  _iotift_scheduler[i] = _iotift_scheduler[j];',
                  '  _iotift_scheduler[j] = t;',
                  '}',
                  'static void _iotift_scheduler_push(iotift_task_t task) {',
                  '  if (_iotift_scheduler_size >= IOTIFT_SCHEDULER_SLOTS) {',
                  '    if (!_iotift_scheduler_overflow) Serial.println("[iotift] scheduler full: deferred action dropped (raise --scheduler-slots)");',
                  '    _iotift_scheduler_overflow = true;',
                  '    return;',
                  '  }',
                  '  uint8_t i = _iotift_scheduler_size++;',
                  '  _iotift_scheduler[i] = task;',
                  '  while (i > 0U) {',
                  '    uint8_t parent = (uint8_t)((i - 1U) >> 1U);',
                  '    if (!_iotift_before(_iotift_scheduler[i].due, _iotift_scheduler[parent].due)) break;',
                  '    _iotift_scheduler_swap(i, parent);',
                  '    i = parent;',
                  '  }',
                  '}',
                  'static void _iotift_schedule_pin(uint8_t pin, uint8_t value, unsigned long delay_ms) {',
                  '  iotift_task_t t = {};',
                  '  t.type = IOTIFT_TASK_PIN; t.due = millis() + delay_ms; t.pin = pin; t.pin_value = value;',
                  '  _iotift_scheduler_push(t);',
                  '}',
                  'static void _iotift_schedule_int(volatile int *var, int value, unsigned long delay_ms) {',
                  '  iotift_task_t t = {};',
                  '  t.type = IOTIFT_TASK_INT; t.due = millis() + delay_ms; t.var_ptr = var; t.var_value = value;',
                  '  _iotift_scheduler_push(t);',
                  '}',
                  'static void _iotift_schedule_fn(void (*fn)(void), unsigned long delay_ms) {',
                  '  iotift_task_t t = {};',
                  '  t.type = IOTIFT_TASK_FN; t.due = millis() + delay_ms; t.fn = fn;',
                  '  _iotift_scheduler_push(t);',
                  '}',
                  'static void _iotift_scheduler_tick(void) {',
                  '  unsigned long now = millis();',
                  '  while (_iotift_scheduler_size > 0U && !_iotift_before(now, _iotift_scheduler[0].due)) {',
                  '    iotift_task_t task = _iotift_scheduler[0];',
                  '    _iotift_scheduler[0] = _iotift_scheduler[--_iotift_scheduler_size];',
                  '    uint8_t i = 0U;',
                  '    for (;;) {',
                  '      uint8_t s = i, l = (uint8_t)(2U * i + 1U), r = (uint8_t)(2U * i + 2U);',
                  '      if (l < _iotift_scheduler_size && _iotift_before(_iotift_scheduler[l].due, _iotift_scheduler[s].due)) s = l;',
                  '      if (r < _iotift_scheduler_size && _iotift_before(_iotift_scheduler[r].due, _iotift_scheduler[s].due)) s = r;',
                  '      if (s == i) break;',
                  '      _iotift_scheduler_swap(i, s);',
                  '      i = s;',
                  '    }',
                  '    // Run after the heap is consistent: the action may schedule more work.',
                  '    if (task.type == IOTIFT_TASK_PIN) digitalWrite(task.pin, task.pin_value);',
                  '    else if (task.type == IOTIFT_TASK_INT) *task.var_ptr = task.var_value;',
                  '    else if (task.fn) task.fn();',
                  '  }',
                  '}', '']
        return R


def _collect_identifiers(obj: Any, out: Set[str]) -> None:
    """Collect every identifier name referenced anywhere inside *obj*."""
    if isinstance(obj, list):
        for x in obj:
            _collect_identifiers(x, out)
        return
    if isinstance(obj, tuple):
        for x in obj:
            _collect_identifiers(x, out)
        return
    if isinstance(obj, Identifier):
        out.add(obj.name)
        return
    if isinstance(obj, Literal) and obj.vtype == 'str' and '{' in str(obj.value):
        # Identifiers used inside "{...}" interpolation.
        for frag in re.findall(r'\{([^{}]+)\}', str(obj.value)):
            out.update(re.findall(r'[A-Za-z_]\w*', frag))
        return
    if isinstance(obj, Node):
        for k, v in vars(obj).items():
            if k in ('line', 'col', 'end_line', 'end_col'):
                continue
            if k in ('target', 'obj', 'name') and isinstance(v, str) and not isinstance(obj, (FnCall, VarDecl)):
                out.add(v)
            else:
                _collect_identifiers(v, out)
