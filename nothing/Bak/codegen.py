"""
IOTIFT Code Generator
Walks the AST and emits C code.
"""

from ast_nodes import *
from typing import List, Any


# HAL mapping per device target
HAL = {
    'esp32'        : {'millis': 'esp_timer_get_time() / 1000', 'sleep': 'vTaskDelay(1 / portTICK_PERIOD_MS)'},
    'arduino_uno'  : {'millis': 'millis()',                    'sleep': 'delay(1)'},
    'arduino_nano' : {'millis': 'millis()',                    'sleep': 'delay(1)'},
    'rpi_pico'     : {'millis': 'to_ms_since_boot(get_absolute_time())', 'sleep': 'sleep_ms(1)'},
    'default'      : {'millis': 'millis()',                    'sleep': 'delay(1)'},
}

PIN_DIRECTION = {
    'output' : 'OUTPUT',
    'input'  : 'INPUT',
    'analog' : 'INPUT',
    'i2c'    : 'INPUT',   # handled separately in real HAL
    'pwm'    : 'OUTPUT',
}


class CodeGen:
    def __init__(self, device: str = 'default'):
        self.device       = device
        self.hal          = HAL.get(device, HAL['default'])
        self.lines        = []
        self.indent_level = 0
        self.pins         = {}    # name → PinDecl
        self.every_count  = 0     # for generating unique timer var names
        self.every_labels = {}    # label → var name
        self.after_count  = 0     # for unique scheduled-after state vars
        self.on_pins      = []    # list of (pin, event, fn_name)
        self._declared_vars = set()  # track global state vars already declared

        # collected sections
        self._pin_macros   = []
        self._global_state = []
        self._handler_fns  = []
        self._user_fns     = []
        self._setup_lines  = []
        self._loop_calls   = []

    # ─────────────────────────────────────────
    #  INDENTED OUTPUT
    # ─────────────────────────────────────────

    def emit(self, line: str = ''):
        self.lines.append('    ' * self.indent_level + line)

    def section(self, title: str):
        self.lines.append('')
        self.lines.append(f'// {"─" * 10} {title} {"─" * 10}')

    # ─────────────────────────────────────────
    #  ENTRY POINT
    # ─────────────────────────────────────────

    def generate(self, program: Program) -> str:
        # first pass — collect everything
        for node in program.body:
            self._collect(node)

        # now assemble the C file
        self._emit_header()
        self._emit_pin_macros()
        self._emit_global_state()
        self._emit_millis()
        self._emit_hal_stubs()
        self._emit_handler_fns()
        self._emit_user_fns()
        self._emit_setup()
        self._emit_main_loop()

        return '\n'.join(self.lines)

    # ─────────────────────────────────────────
    #  COLLECT PASS — categorise top-level nodes
    # ─────────────────────────────────────────

    def _collect(self, node: Node):
        if isinstance(node, DeviceDecl):
            self.device = node.name
            self.hal    = HAL.get(node.name, HAL['default'])

        elif isinstance(node, PinDecl):
            self.pins[node.name] = node
            self._pin_macros.append(f"#define {node.name}_PIN {node.number}")

        elif isinstance(node, VarDecl):
            self._global_state.append(self._var_decl_c(node))

        elif isinstance(node, ArrayDecl):
            self._global_state.append(f"{node.vtype} {node.name}[{node.size}];")

        elif isinstance(node, ExternFnDecl):
            ret = node.return_type or 'void'
            params = ', '.join(f"{p.vtype} {p.name}" for p in node.params) or 'void'
            self._global_state.append(f"extern {ret} {node.name}({params});")

        elif isinstance(node, StructDecl):
            self._emit_struct(node)

        elif isinstance(node, FnDecl):
            self._user_fns.append(self._fn_decl_c(node))

        elif isinstance(node, OnEvent):
            self._collect_on_event(node)

        elif isinstance(node, OnThreshold):
            self._collect_on_threshold(node)

        elif isinstance(node, EveryBlock):
            self._collect_every(node)

        elif isinstance(node, LoopBlock):
            self._collect_loop_block(node)

        elif isinstance(node, VoidLoop):
            self._collect_void_loop(node)

        # bare top-level statements go into setup
        elif isinstance(node, (Assign, AssignAfter, CompoundAssign, FnCall, PrintStmt)):
            self._setup_lines.append(self._stmt_c(node))

    # ─────────────────────────────────────────
    #  EVENT HANDLERS
    # ─────────────────────────────────────────

    def _collect_on_event(self, node: OnEvent):
        fn_name = f"handle_{node.pin}_{node.event}"
        last_var = f"_last_{node.pin}_state"

        if last_var not in self._declared_vars:
            self._declared_vars.add(last_var)
            self._global_state.append(f"int {last_var} = 0;")
        self.on_pins.append((node.pin, node.event, fn_name))

        body_lines = []
        body_lines.append(f"int _state = gpio_get_level({node.pin}_PIN);")

        if node.event == 'press':
            body_lines.append(f"if (_state == 1 && {last_var} == 0) {{")
        elif node.event == 'release':
            body_lines.append(f"if (_state == 0 && {last_var} == 1) {{")
        else:  # change
            body_lines.append(f"if (_state != {last_var}) {{")

        for stmt in node.body:
            body_lines.append('    ' + self._stmt_c(stmt))
        body_lines.append('}')
        body_lines.append(f"{last_var} = _state;")

        fn_code = self._make_void_fn(fn_name, body_lines)
        self._handler_fns.append(fn_code)
        self._loop_calls.append(f"{fn_name}();")

    def _collect_on_threshold(self, node: OnThreshold):
        fn_name = f"handle_threshold_{node.pin}"
        body_lines = [f"if (gpio_get_level({node.pin}_PIN) {node.op} {self._expr_c(node.value)}) {{"]
        for stmt in node.body:
            body_lines.append('    ' + self._stmt_c(stmt))
        body_lines.append('}')

        fn_code = self._make_void_fn(fn_name, body_lines)
        self._handler_fns.append(fn_code)
        self._loop_calls.append(f"{fn_name}();")

    # ─────────────────────────────────────────
    #  EVERY / LOOP
    # ─────────────────────────────────────────

    def _collect_every(self, node: EveryBlock):
        idx      = self.every_count
        self.every_count += 1
        fn_name  = f"handle_every_{idx}"
        time_var = f"_every_{idx}_last"

        if node.label:
            self.every_labels[node.label] = time_var
            active_var = f"_every_{idx}_active"
            self._global_state.append(f"int {active_var} = 1;")

        self._global_state.append(f"uint32_t {time_var} = 0;")

        body_lines = [f"if ({self.hal['millis']} - {time_var} >= {node.interval}U) {{"]
        body_lines.append(f"    {time_var} = {self.hal['millis']};")

        for stmt in node.body:
            # stop ticker → set active flag false
            if isinstance(stmt, StopStmt) and node.label and stmt.label == node.label:
                body_lines.append(f"    {active_var} = 0;")
            else:
                body_lines.append('    ' + self._stmt_c(stmt))

        body_lines.append('}')

        if node.label:
            wrapped = [f"if ({active_var}) {{"]
            for l in body_lines:
                wrapped.append('    ' + l)
            wrapped.append('}')
            body_lines = wrapped

        fn_code = self._make_void_fn(fn_name, body_lines)
        self._handler_fns.append(fn_code)
        self._loop_calls.append(f"{fn_name}();")

    def _collect_loop_block(self, node: LoopBlock):
        # bare loop {} → goes into main while(1) directly
        for stmt in node.body:
            self._loop_calls.append(self._stmt_c(stmt))

    def _collect_void_loop(self, node: VoidLoop):
        fn_name = 'user_loop'
        body_lines = [self._stmt_c(s) for s in node.body]
        fn_code = self._make_void_fn(fn_name, body_lines)
        self._user_fns.append(fn_code)
        self._loop_calls.append(f"{fn_name}();")

    # ─────────────────────────────────────────
    #  EMIT SECTIONS
    # ─────────────────────────────────────────

    def _emit_header(self):
        self.lines += [
            "// ════════════════════════════════════════",
            "//  Generated by IOTIFT compiler",
            f"//  Target: {self.device}",
            "// ════════════════════════════════════════",
            "",
            "#include <stdio.h>",
            "#include <stdint.h>",
            "#include <stdlib.h>",
            "",
        ]

    def _emit_pin_macros(self):
        if not self._pin_macros:
            return
        self.lines.append("// ── Pin Definitions ──")
        self.lines += self._pin_macros
        self.lines.append("")

    def _emit_global_state(self):
        if not self._global_state:
            return
        self.lines.append("// ── Global State ──")
        self.lines += self._global_state
        self.lines.append("")

    def _emit_millis(self):
        self.lines += [
            "// ── Time ──",
            "uint32_t millis() {",
            "    // replace with platform millis",
            "    return 0;",
            "}",
            "",
        ]

    def _emit_hal_stubs(self):
        self.lines += [
            "// ── HAL Stubs (replace with real HAL) ──",
            "void gpio_set_level(int pin, int val) {}",
            "int  gpio_get_level(int pin)          { return 0; }",
            "void schedule_after(int pin, int val, int ms) {}",
            "",
        ]

    def _emit_handler_fns(self):
        if not self._handler_fns:
            return
        self.lines.append("// ── Event & Timer Handlers ──")
        for fn in self._handler_fns:
            self.lines += fn
            self.lines.append("")

    def _emit_user_fns(self):
        if not self._user_fns:
            return
        self.lines.append("// ── User Functions ──")
        for fn in self._user_fns:
            self.lines += fn
            self.lines.append("")

    def _emit_setup(self):
        self.lines.append("// ── Setup ──")
        self.lines.append("void setup() {")
        # pinMode for all pins
        for name, pin in self.pins.items():
            direction = PIN_DIRECTION.get(pin.direction, 'OUTPUT')
            self.lines.append(f"    pinMode({name}_PIN, {direction});")
        for line in self._setup_lines:
            self.lines.append('    ' + line)
        self.lines.append("}")
        self.lines.append("")

    def _emit_main_loop(self):
        self.lines.append("// ── Main Loop ──")
        self.lines.append("void loop() {")
        for call in self._loop_calls:
            self.lines.append('    ' + call)
        self.lines.append("}")
        self.lines.append("")

    # ─────────────────────────────────────────
    #  STATEMENT → C STRING
    # ─────────────────────────────────────────

    def _stmt_c(self, node: Node) -> str:
        if isinstance(node, Assign):
            target = self._target_c(node.target)
            # pin assign → gpio_set_level
            if isinstance(node.target, str) and node.target in self.pins:
                return f"gpio_set_level({node.target}_PIN, {self._expr_c(node.value)});"
            return f"{target} = {self._expr_c(node.value)};"

        if isinstance(node, AssignAfter):
            if node.target in self.pins:
                return f"schedule_after({node.target}_PIN, {self._expr_c(node.value)}, {node.delay});"
            return f"schedule_after_var(&{node.target}, {self._expr_c(node.value)}, {node.delay});"

        if isinstance(node, CompoundAssign):
            return f"{node.target} {node.op} {self._expr_c(node.value)};"

        if isinstance(node, VarDecl):
            return self._var_decl_c(node)

        if isinstance(node, FnCall):
            args = ', '.join(self._expr_c(a) for a in node.args)
            return f"{node.name}({args});"

        if isinstance(node, PrintStmt):
            val = node.value
            if isinstance(val, Literal) and val.vtype == 'str':
                return f'printf("%s\\n", "{val.value}");'
            return f'printf("%d\\n", {self._expr_c(val)});'

        if isinstance(node, IfStmt):
            return self._if_c(node)

        if isinstance(node, WhileStmt):
            return self._while_c(node)

        if isinstance(node, ForStmt):
            return self._for_c(node)

        if isinstance(node, ReturnStmt):
            if node.value is None:
                return "return;"
            return f"return {self._expr_c(node.value)};"

        if isinstance(node, BreakStmt):
            return "break;"

        if isinstance(node, ContinueStmt):
            return "continue;"

        if isinstance(node, StopStmt):
            # resolved in _collect_every; bare stop outside every is a no-op
            return f"// stop {node.label};"

        if isinstance(node, LoopBlock):
            inner = '\n    '.join(self._stmt_c(s) for s in node.body)
            return f"while (1) {{\n    {inner}\n}}"

        return f"/* unhandled: {type(node).__name__} */"

    def _if_c(self, node: IfStmt) -> str:
        cond = self._expr_c(node.condition)
        body = self._block_c(node.then_body)
        out  = f"if ({cond}) {{\n{body}\n}}"
        for ec, eb in node.elif_clauses:
            out += f" else if ({self._expr_c(ec)}) {{\n{self._block_c(eb)}\n}}"
        if node.else_body is not None:
            out += f" else {{\n{self._block_c(node.else_body)}\n}}"
        return out

    def _while_c(self, node: WhileStmt) -> str:
        cond = self._expr_c(node.condition)
        body = self._block_c(node.body)
        return f"while ({cond}) {{\n{body}\n}}"

    def _for_c(self, node: ForStmt) -> str:
        init = self._stmt_c(node.init).rstrip(';') if node.init else ''
        cond = self._expr_c(node.condition) if node.condition else ''
        step = self._stmt_c(node.step).rstrip(';') if node.step else ''
        body = self._block_c(node.body)
        return f"for ({init}; {cond}; {step}) {{\n{body}\n}}"

    def _block_c(self, stmts: list) -> str:
        return '\n'.join('    ' + self._stmt_c(s) for s in stmts)

    # ─────────────────────────────────────────
    #  EXPRESSION → C STRING
    # ─────────────────────────────────────────

    def _expr_c(self, node: Any) -> str:
        if isinstance(node, Literal):
            if node.vtype == 'bool':
                return '1' if node.value else '0'
            if node.vtype == 'str':
                return f'"{node.value}"'
            return str(node.value)

        if isinstance(node, Identifier):
            return node.name

        if isinstance(node, BinOp):
            l = self._expr_c(node.left)
            r = self._expr_c(node.right)
            return f"({l} {node.op} {r})"

        if isinstance(node, UnaryOp):
            return f"{node.op}{self._expr_c(node.operand)}"

        if isinstance(node, MemberAccess):
            return f"{node.obj}.{node.member}"

        if isinstance(node, ArrayAccess):
            return f"{node.name}[{self._expr_c(node.index)}]"

        if isinstance(node, FnCall):
            args = ', '.join(self._expr_c(a) for a in node.args)
            return f"{node.name}({args})"

        # bare Python primitives (from init values)
        if isinstance(node, bool):
            return '1' if node else '0'
        if isinstance(node, (int, float)):
            return str(node)
        if isinstance(node, str):
            return node

        return f"/* expr:{type(node).__name__} */"

    # ─────────────────────────────────────────
    #  HELPERS
    # ─────────────────────────────────────────

    def _target_c(self, target) -> str:
        if isinstance(target, ArrayAccess):
            return f"{target.name}[{self._expr_c(target.index)}]"
        return str(target)

    def _var_decl_c(self, node: VarDecl) -> str:
        prefix = 'const ' if node.is_const else ''
        ctype  = {'int': 'int', 'float': 'float', 'bool': 'int', 'str': 'char*'}.get(node.vtype, node.vtype)
        if node.init is not None:
            return f"{prefix}{ctype} {node.name} = {self._expr_c(node.init)};"
        return f"{prefix}{ctype} {node.name};"

    def _make_void_fn(self, name: str, body_lines: list) -> list:
        out = [f"void {name}() {{"]
        for l in body_lines:
            out.append('    ' + l)
        out.append("}")
        return out

    def _emit_struct(self, node: StructDecl):
        self._global_state.append(f"typedef struct {{")
        for f in node.fields:
            self._global_state.append('    ' + self._var_decl_c(f))
        self._global_state.append(f"}} {node.name};")
