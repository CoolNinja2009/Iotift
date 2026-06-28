"""
IOTIFT Code Generator - ESP32 Arduino Fixed Version (ESP32 Default)
"""

from ast_nodes import *
from typing import List, Any

# Arduino HAL
HAL = {
    'esp32'        : {'millis': 'millis()', 'high': 'HIGH', 'low': 'LOW'},
    'arduino_uno'  : {'millis': 'millis()', 'high': 'HIGH', 'low': 'LOW'},
    'arduino_nano' : {'millis': 'millis()', 'high': 'HIGH', 'low': 'LOW'},
    'rpi_pico'     : {'millis': 'to_ms_since_boot(get_absolute_time())', 'high': '1', 'low': '0'},
    'default'      : {'millis': 'millis()', 'high': 'HIGH', 'low': 'LOW'},
}

PIN_DIRECTION = {
    'output' : 'OUTPUT',
    'input'  : 'INPUT_PULLUP',
    'analog' : 'INPUT',
    'i2c'    : 'INPUT',
    'pwm'    : 'OUTPUT',
}


class CodeGen:
    def __init__(self, device: str = 'esp32'):
        self.device = device
        self.arduino = device in ('esp32', 'arduino_uno', 'arduino_nano')
        self.hal = HAL.get(device, HAL['default'])
        self.lines = []
        self.indent_level = 0
        self.pins = {}
        self.every_count = 0
        self.every_labels = {}
        self.every_time_vars = []
        self.scheduler_needed = False
        self.on_pins = set()
        self._declared_vars = set()
        self._global_blocks = []
        self._global_state = []
        self._handler_fns = []
        self._user_fns = []
        self._setup_lines = []
        self._setup_blocks = []
        self._loop_calls = []
        self._loop_blocks = []
        self._header_blocks = []

    def emit(self, line: str = ''):
        self.lines.append('    ' * self.indent_level + line)

    def section(self, title: str):
        self.lines.append('')
        self.lines.append(f'// {"─" * 10} {title} {"─" * 10}')

    def generate(self, program: Program) -> str:
        for node in program.body:
            self._collect(node)

        self._emit_header()
        self._emit_pin_macros()
        self._emit_global_blocks()
        self._emit_global_state()
        self._emit_scheduler()
        self._emit_handler_fns()
        self._emit_user_fns()
        self._emit_setup()
        self._emit_main_loop()

        return '\n'.join(self.lines)

    def _collect(self, node: Node):
        if isinstance(node, DeviceDecl):
            self.device = node.name
            self.arduino = node.name == 'esp32'
            self.hal = HAL.get(node.name, HAL['default'])
            return

        if isinstance(node, PinDecl):
            if node.name not in self.pins:
                self.pins[node.name] = node
            return

        if isinstance(node, VarDecl):
            self._global_state.append(self._var_decl_c(node))
            return

        if isinstance(node, CBlockNode):
            if not node.code.strip():
                return
            if node.scope == 'header':
                self._header_blocks.append(node.code)
            elif node.scope == 'global':
                self._global_blocks.append(node.code)
            elif node.scope == 'setup':
                self._setup_blocks.append(node.code)
            elif node.scope == 'loop':
                self._loop_blocks.append(node.code)
            else:
                self._global_blocks.append(node.code)
            return

        if isinstance(node, ExternFnDecl):
            if node.name == 'esp_restart' and self.arduino:
                return  # Arduino has ESP.restart()
            ret = node.return_type or 'void'
            params = ', '.join(f"{p.vtype} {p.name}" for p in node.params) or 'void'
            self._global_state.append(f"extern {ret} {node.name}({params});")
            return

        if isinstance(node, OnEvent):
            self._collect_on_event(node)
            return

        if isinstance(node, EveryBlock):
            self._collect_every(node)
            return

        if isinstance(node, VoidLoop):
            self._collect_void_loop(node)
            return

        if isinstance(node, AssignAfter):
            self.scheduler_needed = True
            self._setup_lines.extend(self._stmt_lines(node))
            return

        if isinstance(node, (Assign, CompoundAssign, FnCall, PrintStmt)):
            self._setup_lines.extend(self._stmt_lines(node))
            return

    def _needs_scheduler(self, nodes: List[Node]) -> bool:
        """Recursively check if any AssignAfter statement exists in the node tree."""
        if not nodes:
            return False
        for node in nodes:
            if isinstance(node, AssignAfter):
                return True
            # Check nested statements in IfStmt
            if isinstance(node, IfStmt):
                if self._needs_scheduler(node.then_body):
                    return True
                if self._needs_scheduler(node.else_body):
                    return True
                for _, elif_body in node.elif_clauses:
                    if self._needs_scheduler(elif_body):
                        return True
            # Check any node with a body attribute (future-proofing)
            elif hasattr(node, 'body') and isinstance(node.body, list):
                if self._needs_scheduler(node.body):
                    return True
        return False

    def _collect_on_event(self, node: OnEvent):
        self.on_pins.add(node.pin)
        if self._needs_scheduler(node.body):
            self.scheduler_needed = True
        fn_name = f"handle_{node.pin}_{node.event}"
        last_var = f"_last_{node.pin}_state"
        if last_var not in self._declared_vars:
            self._declared_vars.add(last_var)
            self._global_state.append(f"int {last_var} = HIGH;")
        body_lines = [f"int _state = digitalRead({node.pin}_PIN);"]
        if node.event == 'press':
            body_lines.append(f"if (_state == LOW && {last_var} == HIGH) {{")  # PULLUP pressed LOW
        elif node.event == 'release':
            body_lines.append(f"if (_state == HIGH && {last_var} == LOW) {{")
        else:
            body_lines.append(f"if (_state != {last_var}) {{")
        for stmt in node.body:
            body_lines.extend(self._stmt_lines(stmt, '    '))
        body_lines.append('}')
        body_lines.append(f"{last_var} = _state;")
        self._handler_fns.append(self._make_void_fn(fn_name, body_lines))
        self._loop_calls.append(f"{fn_name}();")

    def _collect_every(self, node: EveryBlock):
        idx = self.every_count
        self.every_count += 1
        fn_name = f"handle_every_{idx}"
        time_var = f"_every_{idx}_last"
        active_var = f"_every_{idx}_active" if node.label else None
        if active_var:
            self._global_state.append(f"int {active_var} = 1;")
            self.every_labels[node.label] = time_var
        self._global_state.append(f"unsigned long {time_var} = 0;")
        self.every_time_vars.append(time_var)
        if self._needs_scheduler(node.body):
            self.scheduler_needed = True
        body_lines = [f"unsigned long now = millis();"]
        body_lines.append(f"if (now - {time_var} >= {node.interval}UL) {{")
        body_lines.append(f"    {time_var} = now;")
        for stmt in node.body:
            body_lines.extend(self._stmt_lines(stmt, '    '))
        body_lines.append('}')
        if active_var:
            body_lines = [f"if ({active_var}) {{"] + ['    ' + l for l in body_lines] + ['}']
        self._handler_fns.append(self._make_void_fn(fn_name, body_lines))
        self._loop_calls.append(f"{fn_name}();")

    def _collect_void_loop(self, node: VoidLoop):
        body_lines = [line for stmt in node.body for line in self._stmt_lines(stmt)]
        self._user_fns.append(self._make_void_fn('user_loop', body_lines))
        self._loop_calls.append('user_loop();')

    def _emit_header(self):
        self.lines += [
            "// Generated by IOTIFT - ESP32 Arduino Production Ready",
            f"// Target: {self.device}",
            "",
        ]
        if self._header_blocks:
            for code in self._header_blocks:
                self.lines += code.split('\n')
            self.lines.append('')
        if self.arduino:
            self.lines.append('#include "Arduino.h"')
        else:
            self.lines += ['#include <stdio.h>', '#include <stdint.h>', '#include <stdlib.h>']
        self.lines.append('')

    def _emit_pin_macros(self):
        if self.pins:
            self.section('Pin Definitions')
            for name, pin in self.pins.items():
                self.lines.append(f"#define {name}_PIN {pin.number}")
            self.lines.append('')

    def _emit_global_blocks(self):
        if self._global_blocks:
            for code in self._global_blocks:
                self.lines += code.split('\n')
            self.lines.append('')

    def _emit_global_state(self):
        if self._global_state:
            self.section('Global State')
            self.lines += self._global_state
            self.lines.append('')

    def _emit_scheduler(self):
        if not self.arduino or not self.scheduler_needed:
            return
        self.section('Scheduler for after')
        self.lines += [
            'struct ScheduledTask {',
            '  unsigned long trigger_time;',
            '  int pin;',
            '  int value;',
            '  int active;',
            '};',
            'ScheduledTask scheduler[16];',
            '',
            'void schedule_after(int pin, int value, unsigned long ms) {',
            '  for (int i = 0; i < 16; i++) {',
            '    if (!scheduler[i].active) {',
            '      unsigned long now = millis();',
            '      scheduler[i].trigger_time = now + ms;',
            '      scheduler[i].pin = pin;',
            '      scheduler[i].value = value;',
            '      scheduler[i].active = 1;',
            '      return;',
            '    }',
            '  }',
            '}',
            '',
            'void check_scheduler() {',
            '  unsigned long now = millis();',
            '  for (int i = 0; i < 16; i++) {',
            '    if (scheduler[i].active && now >= scheduler[i].trigger_time) {',
            '      digitalWrite(scheduler[i].pin, scheduler[i].value ? HIGH : LOW);',
            '      scheduler[i].active = 0;',
            '    }',
            '  }',
            '}',
            ''
        ]
        self._loop_calls.append('check_scheduler();')

    def _emit_handler_fns(self):
        if self._handler_fns:
            self.section('Handlers')
            for fn in self._handler_fns:
                self.lines += fn
                self.lines.append('')

    def _emit_user_fns(self):
        if self._user_fns:
            self.section('User Functions')
            for fn in self._user_fns:
                self.lines += fn
                self.lines.append('')

    def _emit_setup(self):
        self.section('Setup')
        self.lines.append('void setup() {')
        if self.arduino:
            self.lines.append('  Serial.begin(115200);')
        for name, pin in self.pins.items():
            if name in self.on_pins:
                dir_str = 'INPUT_PULLUP'
            else:
                dir_str = PIN_DIRECTION.get(pin.direction, 'OUTPUT')
            self.lines.append(f'  pinMode({name}_PIN, {dir_str});')
        for var in self.every_time_vars:
            self.lines.append(f'  {var} = millis();')
        for line in self._setup_lines:
            self.lines.append('  ' + line)
        for code in self._setup_blocks:
            for line in code.split('\n'):
                self.lines.append('  ' + line)
        self.lines.append('}')
        self.lines.append('')

    def _emit_main_loop(self):
        self.section('Main Loop')
        self.lines.append('void loop() {')
        for call in self._loop_calls:
            self.lines.append('  ' + call)
        for code in self._loop_blocks:
            for line in code.split('\n'):
                self.lines.append('  ' + line)
        if self.arduino:
            self.lines += ['  yield();']
        self.lines += ['}']
        self.lines.append('')

    def _stmt_c(self, node: Node) -> str:
        if isinstance(node, Assign):
            target = self._target_c(node.target)
            if isinstance(node.target, str) and node.target in self.pins:
                val_expr = self._expr_c(node.value)
                if val_expr in ('0', '1', 'true', 'false'):
                    level = 'HIGH' if val_expr in ('1', 'true') else 'LOW'
                    return f"digitalWrite({node.target}_PIN, {level});"
                else:
                    return f"digitalWrite({node.target}_PIN, ({val_expr} ? HIGH : LOW));"
            return f"{target} = {self._expr_c(node.value)};"

        if isinstance(node, FnCall):
            args = ', '.join(self._expr_c(a) for a in node.args)
            if node.name == 'esp_restart' and self.arduino:
                return 'ESP.restart();'
            return f"{node.name}({args});"

        if isinstance(node, PrintStmt):
            val_str = self._expr_c(node.value)
            if self.arduino:
                return f"Serial.println({val_str});"
            return f'printf("%d\\n", {val_str});'

        if isinstance(node, AssignAfter):
            return f"schedule_after({node.target}_PIN, {self._expr_c(node.value)}, {node.delay});"

        if isinstance(node, CompoundAssign):
            return f"{node.target} {node.op} {self._expr_c(node.value)};"

        if isinstance(node, StopStmt):
            if node.label in self.every_labels:
                idx = self.every_labels[node.label].split('_')[2]
                return f"_every_{idx}_active = 0;"
            return f"// stop {node.label}"

        return f"/* {type(node).__name__} */;"

    def _target_c(self, target):
        if isinstance(target, str):
            return target
        return str(target) if hasattr(target, 'name') else self._expr_c(target)

    def _stmt_lines(self, node: Node, indent: str = '') -> List[str]:
        if isinstance(node, IfStmt):
            return self._if_lines(node, indent)
        if isinstance(node, CBlockNode):
            return [(indent + line) if line != '' else '' for line in node.code.split('\n')]
        stmt = self._stmt_c(node)
        return [indent + stmt]

    def _var_decl_c(self, node: VarDecl) -> str:
        ctype = {'int': 'int', 'float': 'float', 'bool': 'bool'}.get(node.vtype, node.vtype)
        if node.init is None:
            return f"{ctype} {node.name};"
        return f"{ctype} {node.name} = {self._expr_c(node.init)};"

    def _make_void_fn(self, name, body_lines):
        return [f"void {name}() {{"] + ['  ' + l for l in body_lines] + ["}"]

    def _if_lines(self, node: IfStmt, indent: str = '') -> List[str]:
        cond = self._expr_c(node.condition)
        lines = [f"{indent}if ({cond}) {{"]
        
        for stmt in node.then_body:
            lines.extend(self._stmt_lines(stmt, indent + '  '))
        
        lines.append(f"{indent}}}")
        
        for elif_cond, elif_body in node.elif_clauses:
            elif_cond_str = self._expr_c(elif_cond)
            lines.append(f"{indent}else if ({elif_cond_str}) {{")
            for stmt in elif_body:
                lines.extend(self._stmt_lines(stmt, indent + '  '))
            lines.append(f"{indent}}}")
        
        if node.else_body:
            lines.append(f"{indent}else {{")
            for stmt in node.else_body:
                lines.extend(self._stmt_lines(stmt, indent + '  '))
            lines.append(f"{indent}}}")
        
        return lines

    def _expr_c(self, node):
        if isinstance(node, Literal):
            if node.vtype == 'bool':
                return 'true' if node.value else 'false'
            elif node.vtype == 'str':
                return f'"{node.value}"'
            return str(node.value)
        if isinstance(node, Identifier):
            return node.name
        if isinstance(node, MillisExpr):
            return 'millis()'
        if isinstance(node, BinOp):
            return f"({self._expr_c(node.left)} {node.op} {self._expr_c(node.right)})"
        return '0'

