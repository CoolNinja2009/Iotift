"""
IOTIFT Code Generator
Single source of all C/C++ knowledge in the compiler.
"""

from ast_nodes import *
from typing    import List, Any


class CodeGenError(Exception):
    pass


# ─────────────────────────────────────────
#  HARDWARE ABSTRACTION
# ─────────────────────────────────────────

HAL = {
    'esp32'        : {'millis': 'millis()', 'high': 'HIGH', 'low': 'LOW'},
    'arduino_uno'  : {'millis': 'millis()', 'high': 'HIGH', 'low': 'LOW'},
    'arduino_nano' : {'millis': 'millis()', 'high': 'HIGH', 'low': 'LOW'},
    'rpi_pico'     : {'millis': 'to_ms_since_boot(get_absolute_time())', 'high': '1', 'low': '0'},
    'default'      : {'millis': 'millis()', 'high': 'HIGH', 'low': 'LOW'},
}

PIN_DIRECTION = {
    'output': 'OUTPUT',
    'input' : 'INPUT_PULLUP',
    'analog': 'INPUT',
    'i2c'   : 'INPUT',
    'pwm'   : 'OUTPUT',   # only used for non-ESP32 fallback; ESP32 skips pinMode for PWM
}

CTYPE = {
    'int'  : 'int',
    'float': 'float',
    'bool' : 'bool',
    'str'  : 'const char*',
}


class CodeGen:
    def __init__(self, device: str = 'esp32'):
        self.device  = device
        self.arduino = device in ('esp32', 'arduino_uno', 'arduino_nano')
        self.hal     = HAL.get(device, HAL['default'])

        self.lines        = []
        self.pins         = {}   # name → PinDecl
        self.pwm_pins     = {}   # name → {number, channel, freq, resolution}
        self._pwm_channel = 0    # tracked counter

        self.every_count    = 0
        self.every_labels   = {}  # label → time_var name
        self.every_time_vars= []
        self.scheduler_needed = False
        self.on_pins        = set()

        self._declared_vars  = set()
        self._header_blocks  = []
        self._global_blocks  = []
        self._global_state   = []   # lines for the global section
        self._user_fns       = []   # list of line-lists
        self._handler_fns    = []
        self._setup_lines    = []
        self._setup_blocks   = []
        self._loop_calls     = []
        self._loop_blocks    = []
        self.includes        = set()

    # ─────────────────────────────────────────
    #  PUBLIC ENTRY
    # ─────────────────────────────────────────

    def generate(self, program: Program) -> str:
        for node in program.body:
            self._collect(node)

        self._emit_header()
        self._emit_pin_macros()
        self._emit_global_blocks()
        self._emit_global_state()
        self._emit_scheduler()
        self._emit_user_fns()
        self._emit_handler_fns()
        self._emit_setup()
        self._emit_main_loop()

        return '\n'.join(self.lines)

    # ─────────────────────────────────────────
    #  COLLECT PASS  (first pass over AST)
    # ─────────────────────────────────────────

    def _collect(self, node: Node):
        if isinstance(node, DeviceDecl):
            self.device  = node.name
            self.arduino = node.name in ('esp32', 'arduino_uno', 'arduino_nano')
            self.hal     = HAL.get(node.name, HAL['default'])

        elif isinstance(node, ImportDecl):
            import sys
            print(f"Warning: import \"{node.path}\" is not yet resolved — skipping.", file=sys.stderr)
            self._global_state.append(f'// import "{node.path}" (unresolved)')

        elif isinstance(node, PinDecl):
            if node.name not in self.pins:
                self.pins[node.name] = node
            if node.direction == 'pwm':
                ch = self._pwm_channel
                self._pwm_channel += 1
                self.pwm_pins[node.name] = {
                    'number'    : node.number,
                    'channel'   : ch,
                    'freq'      : node.pwm_freq      or 5000,
                    'resolution': node.pwm_resolution or 8,
                }

        elif isinstance(node, VarDecl):
            self._global_state.append(self._var_decl_c(node))

        elif isinstance(node, ArrayDecl):
            ctype = CTYPE.get(node.vtype, node.vtype)
            self._global_state.append(f"{ctype} {node.name}[{node.size}];")

        elif isinstance(node, StructDecl):
            lines = [f"struct {node.name} {{"]
            for f in node.fields:
                ct = CTYPE.get(f.vtype, f.vtype)
                lines.append(f"  {ct} {f.name};")
            lines.append("};")
            self._global_state.extend(lines)

        elif isinstance(node, FnDecl):
            self._collect_fn_decl(node)

        elif isinstance(node, ExternFnDecl):
            if node.name == 'esp_restart' and self.arduino:
                return
            ret    = node.return_type or 'void'
            params = ', '.join(f"{CTYPE.get(p.vtype,p.vtype)} {p.name}" for p in node.params) or 'void'
            self._global_state.append(f"extern {ret} {node.name}({params});")

        elif isinstance(node, CBlockNode):
            if not node.code.strip():
                return
            target = {
                'header': self._header_blocks,
                'global': self._global_blocks,
                'setup' : self._setup_blocks,
                'loop'  : self._loop_blocks,
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
            body_lines = [ln for s in node.body for ln in self._stmt_lines(s)]
            self._user_fns.append(self._make_fn('void', 'user_loop', '', body_lines))
            self._loop_calls.append('user_loop();')

        # PwmSetup at top-level overrides defaults before setup() is emitted
        elif isinstance(node, PwmSetup):
            if node.pin in self.pwm_pins:
                self.pwm_pins[node.pin]['freq']       = self._expr_c(node.freq)
                self.pwm_pins[node.pin]['resolution']  = self._expr_c(node.resolution)

        elif isinstance(node, (Assign, CompoundAssign, FnCall, MethodCall,
                                PrintStmt, PwmWrite)):
            self._setup_lines.extend(self._stmt_lines(node))

        elif isinstance(node, AssignAfter):
            self.scheduler_needed = True
            self._setup_lines.extend(self._stmt_lines(node))

    # ─────────────────────────────────────────
    #  COLLECTORS
    # ─────────────────────────────────────────

    def _collect_fn_decl(self, node: FnDecl):
        ret    = node.return_type or 'void'
        params = ', '.join(
            f"{CTYPE.get(p.vtype, p.vtype)} {p.name}" for p in node.params
        ) if node.params else ''
        body_lines = [ln for s in node.body for ln in self._stmt_lines(s, '  ')]
        self._user_fns.append(self._make_fn(ret, node.name, params, body_lines))

    def _collect_on_event(self, node: OnEvent):
        self.on_pins.add(node.pin)
        if self._needs_scheduler(node.body):
            self.scheduler_needed = True
        fn_name  = f"handle_{node.pin}_{node.event}"
        last_var = f"_last_{node.pin}_state"
        if last_var not in self._declared_vars:
            self._declared_vars.add(last_var)
            self._global_state.append(f"int {last_var} = HIGH;")
        cond = {
            'press'  : f"_state == LOW && {last_var} == HIGH",
            'release': f"_state == HIGH && {last_var} == LOW",
        }.get(node.event, f"_state != {last_var}")
        body = [
            f"int _state = digitalRead({node.pin}_PIN);",
            f"if ({cond}) {{",
        ]
        for s in node.body:
            body.extend(self._stmt_lines(s, '    '))
        body += ['}', f"{last_var} = _state;"]
        self._handler_fns.append(self._make_fn('void', fn_name, '', body))
        self._loop_calls.append(f"{fn_name}();")

    def _collect_on_threshold(self, node: OnThreshold):
        fn_name = f"handle_threshold_{node.pin}"
        val     = self._expr_c(node.value)
        body    = [f"if ({node.pin} {node.op} {val}) {{"]
        for s in node.body:
            body.extend(self._stmt_lines(s, '    '))
        body.append('}')
        self._handler_fns.append(self._make_fn('void', fn_name, '', body))
        self._loop_calls.append(f"{fn_name}();")

    def _collect_every(self, node: EveryBlock):
        idx        = self.every_count
        self.every_count += 1
        fn_name    = f"handle_every_{idx}"
        time_var   = f"_every_{idx}_last"
        active_var = f"_every_{idx}_active" if node.label else None

        if active_var:
            self._global_state.append(f"int {active_var} = 1;")
            self.every_labels[node.label] = time_var
        self._global_state.append(f"unsigned long {time_var} = 0;")
        self.every_time_vars.append(time_var)

        if self._needs_scheduler(node.body):
            self.scheduler_needed = True

        inner = [
            "unsigned long now = millis();",
            f"if (now - {time_var} >= {node.interval}UL) {{",
            f"    {time_var} = now;",
        ]
        for s in node.body:
            inner.extend(self._stmt_lines(s, '    '))
        inner.append('}')

        if active_var:
            inner = [f"if ({active_var}) {{"] + ['    ' + ln for ln in inner] + ['}']

        body = ['  ' + ln for ln in inner]
        self._handler_fns.append(self._make_fn('void', fn_name, '', body))
        self._loop_calls.append(f"{fn_name}();")

    def _collect_loop_block(self, node: LoopBlock):
        body = [ln for s in node.body for ln in self._stmt_lines(s, '  ')]
        self._handler_fns.append(self._make_fn('void', 'handle_loop', '', body))
        self._loop_calls.append('handle_loop();')

    # ─────────────────────────────────────────
    #  EMIT SECTIONS
    # ─────────────────────────────────────────

    def _emit_header(self):
        self.lines += [
            "// Compiled by The IOTIFT Compiler - ESP32 Ready",
            f"// Target: {self.device}",
            "",
        ]
        for code in self._header_blocks:
            self.lines += code.split('\n')
        if self._header_blocks:
            self.lines.append('')
        if self.arduino:
            self.lines.append('#include "Arduino.h"')
        else:
            self.lines += ['#include <stdio.h>', '#include <stdint.h>', '#include <stdlib.h>']
        for inc in sorted(self.includes):
            self.lines.append(inc)
        self.lines.append('')

    def _emit_pin_macros(self):
        if not self.pins:
            return
        self._section('Pin Definitions')
        for name, pin in self.pins.items():
            self.lines.append(f"#define {name}_PIN {pin.number}")
        self.lines.append('')

    def _emit_global_blocks(self):
        for code in self._global_blocks:
            self.lines += code.split('\n')
        if self._global_blocks:
            self.lines.append('')

    def _emit_global_state(self):
        if not self._global_state:
            return
        self._section('Global State')
        self.lines += self._global_state
        self.lines.append('')

    def _emit_scheduler(self):
        if not self.arduino or not self.scheduler_needed:
            return
        self._section('Scheduler (after keyword)')
        self.lines += [
            'struct ScheduledTask {',
            '  unsigned long trigger_time;',
            '  int pin;',
            '  int value;',
            '  int active;',
            '};',
            'ScheduledTask _scheduler[16];',
            '',
            'void _schedule_after(int pin, int value, unsigned long ms) {',
            '  for (int i = 0; i < 16; i++) {',
            '    if (!_scheduler[i].active) {',
            '      _scheduler[i].trigger_time = millis() + ms;',
            '      _scheduler[i].pin = pin;',
            '      _scheduler[i].value = value;',
            '      _scheduler[i].active = 1;',
            '      return;',
            '    }',
            '  }',
            '}',
            '',
            'void _check_scheduler() {',
            '  unsigned long now = millis();',
            '  for (int i = 0; i < 16; i++) {',
            '    if (_scheduler[i].active && now >= _scheduler[i].trigger_time) {',
            '      digitalWrite(_scheduler[i].pin, _scheduler[i].value ? HIGH : LOW);',
            '      _scheduler[i].active = 0;',
            '    }',
            '  }',
            '}',
            '',
        ]
        self._loop_calls.append('_check_scheduler();')

    def _emit_user_fns(self):
        if not self._user_fns:
            return
        self._section('User Functions')
        for fn in self._user_fns:
            self.lines += fn
            self.lines.append('')

    def _emit_handler_fns(self):
        if not self._handler_fns:
            return
        self._section('Handlers')
        for fn in self._handler_fns:
            self.lines += fn
            self.lines.append('')

    def _emit_setup(self):
        self._section('Setup')
        self.lines.append('void setup() {')
        if self.arduino:
            self.lines.append('  Serial.begin(115200);')

        # Normal pins — skip PWM (they use ledc, not pinMode)
        for name, pin in self.pins.items():
            if name in self.pwm_pins:
                continue
            dir_str = 'INPUT_PULLUP' if name in self.on_pins else PIN_DIRECTION.get(pin.direction, 'OUTPUT')
            self.lines.append(f'  pinMode({name}_PIN, {dir_str});')

        # PWM pins
        for pin_name, info in self.pwm_pins.items():
            ch   = info['channel']
            freq = info['freq']
            res  = info['resolution']
            num  = info['number']
            self.lines.append(f'  ledcSetup({ch}, {freq}, {res});')
            self.lines.append(f'  ledcAttachPin({num}, {ch});')

        for var in self.every_time_vars:
            self.lines.append(f'  {var} = millis();')
        for ln in self._setup_lines:
            self.lines.append('  ' + ln)
        for code in self._setup_blocks:
            for ln in code.split('\n'):
                self.lines.append('  ' + ln)
        self.lines.append('}')
        self.lines.append('')

    def _emit_main_loop(self):
        self._section('Main Loop')
        self.lines.append('void loop() {')
        for call in self._loop_calls:
            self.lines.append('  ' + call)
        for code in self._loop_blocks:
            for ln in code.split('\n'):
                self.lines.append('  ' + ln)
        if self.arduino:
            self.lines.append('  yield();')
        self.lines.append('}')
        self.lines.append('')

    # ─────────────────────────────────────────
    #  STATEMENT → LINES
    # ─────────────────────────────────────────

    def _stmt_lines(self, node: Node, indent: str = '') -> List[str]:
        """Convert any statement node to a list of C++ lines."""

        if isinstance(node, IfStmt):
            return self._if_lines(node, indent)

        if isinstance(node, WhileStmt):
            return self._while_lines(node, indent)

        if isinstance(node, ForStmt):
            return self._for_lines(node, indent)

        if isinstance(node, CBlockNode):
            return [(indent + ln) if ln else '' for ln in node.code.split('\n')]

        # Single-line statements
        return [indent + self._stmt_c(node)]

    def _stmt_c(self, node: Node) -> str:
        """Convert a single-line statement node to a C++ string."""

        if isinstance(node, Assign):
            target = self._target_c(node.target)
            # Pin digital write shortcut
            if isinstance(node.target, str) and node.target in self.pins \
                    and node.target not in self.pwm_pins:
                val = self._expr_c(node.value)
                if val in ('0', '1', 'true', 'false'):
                    level = 'HIGH' if val in ('1', 'true') else 'LOW'
                    return f"digitalWrite({node.target}_PIN, {level});"
                return f"digitalWrite({node.target}_PIN, ({val} ? HIGH : LOW));"
            return f"{target} = {self._expr_c(node.value)};"

        if isinstance(node, CompoundAssign):
            return f"{node.target} {node.op} {self._expr_c(node.value)};"

        if isinstance(node, AssignAfter):
            return (f"_schedule_after({node.target}_PIN, "
                    f"{self._expr_c(node.value)}, {node.delay});")

        if isinstance(node, VarDecl):
            return self._var_decl_c(node)

        if isinstance(node, ArrayDecl):
            ctype = CTYPE.get(node.vtype, node.vtype)
            return f"{ctype} {node.name}[{node.size}];"

        if isinstance(node, ReturnStmt):
            if node.value is None:
                return "return;"
            return f"return {self._expr_c(node.value)};"

        if isinstance(node, BreakStmt):
            return "break;"

        if isinstance(node, ContinueStmt):
            return "continue;"

        if isinstance(node, PrintStmt):
            val = self._expr_c(node.value)
            if self.arduino:
                return f"Serial.println({val});"
            return f'printf("%s\\n", String({val}).c_str());'

        if isinstance(node, FnCall):
            args = ', '.join(self._expr_c(a) for a in node.args)
            if node.name == 'esp_restart' and self.arduino:
                return 'ESP.restart();'
            return f"{node.name}({args});"

        if isinstance(node, MethodCall):
            args = ', '.join(self._expr_c(a) for a in node.args)
            return f"{node.obj}.{node.method}({args});"

        if isinstance(node, PwmWrite):
            if node.pin in self.pwm_pins:
                ch  = self.pwm_pins[node.pin]['channel']
                val = self._expr_c(node.value)
                return f"ledcWrite({ch}, (uint32_t)({val}));"
            return f"// PWM write on unknown pin {node.pin}"

        if isinstance(node, PwmSetup):
            # At statement level inside a block, PwmSetup is a no-op in code output
            # (values are captured in _collect and applied to ledcSetup in _emit_setup)
            freq = self._expr_c(node.freq)
            res  = self._expr_c(node.resolution)
            return f"// {node.pin}.setup({freq}, {res}) applied in setup()"

        if isinstance(node, StopStmt):
            if node.label in self.every_labels:
                time_var = self.every_labels[node.label]
                idx = time_var.split('_')[2]
                return f"_every_{idx}_active = 0;"
            return f"// stop {node.label} (label not found)"

        raise CodeGenError(
            f"Line {getattr(node, 'line', '?')}: Unhandled statement node {type(node).__name__}"
        )

    def _if_lines(self, node: IfStmt, indent: str = '') -> List[str]:
        lines = [f"{indent}if ({self._expr_c(node.condition)}) {{"]
        for s in node.then_body:
            lines.extend(self._stmt_lines(s, indent + '  '))
        lines.append(f"{indent}}}")
        for ec, eb in node.elif_clauses:
            lines.append(f"{indent}else if ({self._expr_c(ec)}) {{")
            for s in eb:
                lines.extend(self._stmt_lines(s, indent + '  '))
            lines.append(f"{indent}}}")
        if node.else_body:
            lines.append(f"{indent}else {{")
            for s in node.else_body:
                lines.extend(self._stmt_lines(s, indent + '  '))
            lines.append(f"{indent}}}")
        return lines

    def _while_lines(self, node: WhileStmt, indent: str = '') -> List[str]:
        lines = [f"{indent}while ({self._expr_c(node.condition)}) {{"]
        for s in node.body:
            lines.extend(self._stmt_lines(s, indent + '  '))
        lines.append(f"{indent}}}")
        return lines

    def _for_lines(self, node: ForStmt, indent: str = '') -> List[str]:
        init = self._stmt_c(node.init).rstrip(';') if node.init else ''
        cond = self._expr_c(node.condition)         if node.condition else ''
        step = self._stmt_c(node.step).rstrip(';')  if node.step else ''
        lines = [f"{indent}for ({init}; {cond}; {step}) {{"]
        for s in node.body:
            lines.extend(self._stmt_lines(s, indent + '  '))
        lines.append(f"{indent}}}")
        return lines

    # ─────────────────────────────────────────
    #  EXPRESSION → STRING
    # ─────────────────────────────────────────

    def _expr_c(self, node) -> str:
        if isinstance(node, Literal):
            if node.vtype == 'bool':
                return 'true' if node.value else 'false'
            if node.vtype == 'str':
                return f'"{node.value}"'
            return str(node.value)

        if isinstance(node, Identifier):
            return node.name

        if isinstance(node, MillisExpr):
            return 'millis()'

        if isinstance(node, MathExpr):
            self.includes.add('#include <math.h>')
            args = ', '.join(self._expr_c(a) for a in node.args)
            return f'{node.func}({args})'

        if isinstance(node, BinOp):
            return f"({self._expr_c(node.left)} {node.op} {self._expr_c(node.right)})"

        if isinstance(node, UnaryOp):
            return f"({node.op}{self._expr_c(node.operand)})"

        if isinstance(node, MemberAccess):
            return f"{node.obj}.{node.member}"

        if isinstance(node, ArrayAccess):
            return f"{node.name}[{self._expr_c(node.index)}]"

        if isinstance(node, FnCall):
            args = ', '.join(self._expr_c(a) for a in node.args)
            return f"{node.name}({args})"

        if isinstance(node, MethodCall):
            args = ', '.join(self._expr_c(a) for a in node.args)
            return f"{node.obj}.{node.method}({args})"

        # Raw int/float/str passed directly (e.g. from PwmSetup freq/resolution)
        if isinstance(node, (int, float)):
            return str(node)
        if isinstance(node, str):
            return node

        raise CodeGenError(
            f"Unhandled expression node: {type(node).__name__}"
        )

    # ─────────────────────────────────────────
    #  HELPERS
    # ─────────────────────────────────────────

    def _var_decl_c(self, node: VarDecl) -> str:
        ctype = CTYPE.get(node.vtype, node.vtype)
        if node.is_const:
            ctype = 'const ' + ctype
        if node.init is None:
            return f"{ctype} {node.name};"
        return f"{ctype} {node.name} = {self._expr_c(node.init)};"

    def _target_c(self, target) -> str:
        if isinstance(target, str):
            return target
        if isinstance(target, ArrayAccess):
            return f"{target.name}[{self._expr_c(target.index)}]"
        return self._expr_c(target)

    def _make_fn(self, ret: str, name: str, params: str, body_lines: List[str]) -> List[str]:
        sig = f"{ret} {name}({params})" + " {"
        return [sig] + body_lines + ["}"]

    def _section(self, title: str):
        self.lines.append('')
        self.lines.append(f'// {"─" * 10} {title} {"─" * 10}')

    def _needs_scheduler(self, nodes: List[Node]) -> bool:
        for node in (nodes or []):
            if isinstance(node, AssignAfter):
                return True
            if isinstance(node, IfStmt):
                if (self._needs_scheduler(node.then_body) or
                        self._needs_scheduler(node.else_body) or
                        any(self._needs_scheduler(b) for _, b in node.elif_clauses)):
                    return True
            elif hasattr(node, 'body') and isinstance(getattr(node, 'body', None), list):
                if self._needs_scheduler(node.body):
                    return True
        return False
