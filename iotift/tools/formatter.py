"""
Iotift Formatter — opinionated, zero-configuration code formatter.

Rules (non-negotiable):
- 4-space indentation
- Opening brace on same line, preceded by a space
- One blank line between top-level declarations
- Semicolons preserved
- Long lines (>100 chars) wrapped at logical break points
- Trailing whitespace stripped
- Single trailing newline
"""

from __future__ import annotations

import sys
import os
from typing import List, Optional

# Import AST nodes for type inspection
from ast_nodes import (
    Node, Program, DeviceDecl, SchedulerConfig, ImportDecl,
    CBlockNode, PinDecl, VarDecl, ArrayDecl, StructDecl, FnDecl,
    ExternFnDecl, EnumDecl, TypeAliasDecl,
    OnEvent, OnThreshold, EveryBlock, LoopBlock, VoidLoop, TickBlock,
    AfterBlock, PeripheralDecl,
    Assign, AssignAfter, CompoundAssign, IfStmt, WhileStmt, ForStmt,
    ReturnStmt, BreakStmt, ContinueStmt, StopStmt, PrintStmt,
    DeferStmt, ExprStmt,
    BinOp, UnaryOp, MemberAccess, ArrayAccess, Literal, Identifier,
    FnCall, MethodCall, PwmSetup, PwmWrite, MillisExpr, MathExpr,
    CastExpr, SizeOfExpr, PinConfig,
)

INDENT = '    '  # 4 spaces
MAX_LINE_WIDTH = 100


class FormatError(Exception):
    """Raised when formatting fails."""
    pass


# ─────────────────────────────────────────
#  FORMATTER STATE
# ─────────────────────────────────────────

class Formatter:
    """Pretty-prints an Iotift AST back to source code."""

    def __init__(self):
        self.lines: List[str] = []
        self.indent_level: int = 0
        self.current_line: str = ''
        self._top_level_count: int = 0  # track top-level decls for blank-line spacing

    @property
    def indent(self) -> str:
        return INDENT * self.indent_level

    def _emit(self, text: str) -> None:
        """Append text to the current line."""
        self.current_line += text

    def _emit_line(self, text: str = '') -> None:
        """Finalize the current line and start a new one."""
        line = (self.indent + self.current_line + text).rstrip()
        self.lines.append(line)
        self.current_line = ''

    def _emit_raw_line(self, text: str) -> None:
        """Emit a pre-formatted line (used for C block content)."""
        self.lines.append(text)

    def _blank_line(self) -> None:
        """Insert a blank line if the previous line isn't already blank."""
        if self.lines and self.lines[-1] != '':
            self.lines.append('')

    def _needs_space(self) -> bool:
        """Check if current line ends with a character that needs a space separator."""
        if not self.current_line:
            return False
        last = self.current_line[-1]
        return last not in ('(', '[', '{', ' ', '\n', ';', ',')

    def _maybe_space(self) -> None:
        """Emit a space if the current line doesn't already end with a separator."""
        if self._needs_space():
            self._emit(' ')

    def _render(self) -> str:
        """Return the final formatted source."""
        # Strip trailing blank lines, ensure exactly one trailing newline
        while self.lines and self.lines[-1] == '':
            self.lines.pop()
        return '\n'.join(self.lines) + '\n'

    # ─────────────────────────────────────
    #  TOP-LEVEL DISPATCH
    # ─────────────────────────────────────

    def format(self, node: Node) -> str:
        """Format an AST node tree into source code."""
        self._format_node(node)
        return self._render()

    def _format_node(self, node: Node) -> None:
        """Dispatch to the correct format method based on node type."""
        if node is None:
            return

        type_name = type(node).__name__
        method_name = f'_fmt_{type_name}'
        method = getattr(self, method_name, None)

        if method:
            method(node)
        else:
            raise FormatError(f'No formatter for node type: {type_name}')

    # ─────────────────────────────────────
    #  PROGRAM
    # ─────────────────────────────────────

    def _fmt_Program(self, node: Program) -> None:
        # Separate top-level nodes by type for blank-line insertion
        body = node.body
        for i, child in enumerate(body):
            if i > 0:
                # Blank line between different top-level declaration groups
                prev_type = type(body[i - 1]).__name__
                curr_type = type(child).__name__
                # Don't blank-line between consecutive C blocks of same scope
                if not (prev_type == 'CBlockNode' and curr_type == 'CBlockNode'):
                    self._blank_line()
            self._format_node(child)
            self._emit_line()

    # ─────────────────────────────────────
    #  TOP-LEVEL DECLARATIONS
    # ─────────────────────────────────────

    def _fmt_DeviceDecl(self, node: DeviceDecl) -> None:
        self._emit(f'@device {node.name}')

    def _fmt_SchedulerConfig(self, node: SchedulerConfig) -> None:
        self._emit(f'@config {node.key} = {self._fmt_value(node.value)};')

    def _fmt_ImportDecl(self, node: ImportDecl) -> None:
        if node.selected_names is not None:
            names = ', '.join(node.selected_names)
            self._emit(f'import {{ {names} }} from "{node.path}";')
        else:
            self._emit(f'import "{node.path}";')

    def _fmt_CBlockNode(self, node: CBlockNode) -> None:
        """Preserve C block content formatting as-is."""
        self._emit(f'c {node.scope} {{')
        self._emit_line()
        # Preserve internal formatting of C code
        code = node.code
        if code:
            for line in code.split('\n'):
                self._emit_raw_line(line)
        self._emit('}')

    def _fmt_PinDecl(self, node: PinDecl) -> None:
        self._emit(f'pin {node.name} = {node.direction} {self._fmt_value(node.number)}')
        # Optional config
        config = node.config
        has_config = (config.pull is not None or
                      config.debounce_ms is not None or
                      config.initial is not None)
        if has_config:
            parts = []
            if config.pull is not None:
                parts.append(f'pull: {config.pull}')
            if config.debounce_ms is not None:
                parts.append(f'debounce: {self._fmt_time_literal(config.debounce_ms)}')
            if config.initial is not None:
                parts.append(f'initial: {self._fmt_value(config.initial)}')
            self._emit(f' {{ {", ".join(parts)} }}')
        # Optional PWM settings
        if node.pwm_freq is not None:
            self._emit(f' freq {self._fmt_value(node.pwm_freq)}')
        if node.pwm_resolution is not None:
            self._emit(f' resolution {self._fmt_value(node.pwm_resolution)}')
        self._emit(';')

    def _fmt_VarDecl(self, node: VarDecl, end_line: bool = True) -> None:
        # Special path for struct fields: emit TYPE NAME
        if self._in_struct_field if hasattr(self, '_in_struct_field') and self._in_struct_field else False:
            if node.vtype:
                self._emit(f'{node.vtype} {node.name}')
            elif node.is_const:
                self._emit(f'const {node.vtype or ""} {node.name}'.replace('  ', ' '))
            else:
                self._emit(f'{node.vtype or "int"} {node.name}')
            if node.init is not None:
                self._emit(' = ')
                self._fmt_expression(node.init)
            if end_line:
                self._emit_line(';')
            else:
                self._emit(';')
            return

        if node.is_const:
            if node.vtype:
                self._emit(f'const {node.vtype} {node.name}')
            else:
                self._emit(f'const {node.name}')
        elif node.vtype and not node.is_mutable:
            # let-style: let x: type = init (explicit let/immutable)
            self._emit(f'let {node.name}')
            if node.vtype:
                self._emit(f': {node.vtype}')
        elif node.vtype:
            # old-style: type name = init (default for type-name declarations)
            self._emit(f'{node.vtype} {node.name}')
        else:
            # let with inferred type
            self._emit(f'let {node.name}')

        if node.is_volatile:
            self._maybe_space()
            self._emit('volatile')

        if node.init is not None:
            self._emit(' = ')
            self._fmt_expression(node.init)
        if end_line:
            self._emit_line(';')
        else:
            self._emit(';')

    def _fmt_ArrayDecl(self, node: ArrayDecl) -> None:
        if node.is_mutable:
            self._emit(f'var {node.name}: [{self._fmt_value(node.size)}]')
        else:
            self._emit(f'let {node.name}: [{self._fmt_value(node.size)}]')
        if node.elem_type:
            self._emit(node.elem_type)
        elif node.vtype:
            self._emit(node.vtype)
        if node.init is not None:
            self._emit(' = ')
            self._fmt_expression(node.init)
        self._emit(';')

    def _fmt_StructDecl(self, node: StructDecl) -> None:
        self._emit(f'struct {node.name} {{')
        self._emit_line()
        self.indent_level += 1
        self._in_struct_field = True
        for field in node.fields:
            self._format_node(field)
        self._in_struct_field = False
        self.indent_level -= 1
        self._emit('}')

    def _fmt_FnDecl(self, node: FnDecl) -> None:
        if node.is_isr:
            self._emit('isr ')
        if node.is_extern:
            self._emit('extern ')
        self._emit('fn ')
        self._emit(node.name)
        self._emit('(')
        for i, param in enumerate(node.params):
            if i > 0:
                self._emit(', ')
            self._fmt_param(param)
        self._emit(')')
        if node.return_type and not node.is_void:
            self._emit(f' -> {node.return_type}')
        if node.is_extern:
            self._emit(';')
        else:
            self._emit(' {')
            self._emit_line()
            self.indent_level += 1
            for stmt in node.body:
                self._format_node(stmt)
            self.indent_level -= 1
            self._emit('}')

    def _fmt_ExternFnDecl(self, node: ExternFnDecl) -> None:
        self._emit(f'extern fn {node.name}(')
        for i, param in enumerate(node.params):
            if i > 0:
                self._emit(', ')
            self._fmt_param(param)
        self._emit(')')
        if node.return_type:
            self._emit(f' -> {node.return_type}')
        self._emit(';')

    def _fmt_EnumDecl(self, node: EnumDecl) -> None:
        self._emit(f'enum {node.name}')
        if node.backing_type:
            self._emit(f': {node.backing_type}')
        self._emit(' {')
        self._emit_line()
        self.indent_level += 1
        for variant_name, variant_value in node.variants:
            if variant_value is not None:
                self._emit(f'{variant_name} = {self._fmt_value(variant_value)}')
            else:
                self._emit(variant_name)
            self._emit_line(',')
        self.indent_level -= 1
        self._emit('}')

    def _fmt_TypeAliasDecl(self, node: TypeAliasDecl) -> None:
        self._emit(f'type {node.name} = {node.aliased_type};')

    # ─────────────────────────────────────
    #  EVENTS & TIMERS
    # ─────────────────────────────────────

    def _fmt_OnEvent(self, node: OnEvent) -> None:
        self._emit(f'on {node.pin}.{node.event} {{')
        self._emit_line()
        self.indent_level += 1
        for stmt in node.body:
            self._format_node(stmt)
        self.indent_level -= 1
        self._emit('}')

    def _fmt_OnThreshold(self, node: OnThreshold) -> None:
        self._emit(f'on {node.pin} {node.op} ')
        self._fmt_expression(node.value)
        self._emit(' {')
        self._emit_line()
        self.indent_level += 1
        for stmt in node.body:
            self._format_node(stmt)
        self.indent_level -= 1
        self._emit('}')

    def _fmt_EveryBlock(self, node: EveryBlock) -> None:
        self._emit('every ')
        self._emit(self._fmt_time_literal(node.interval))
        if node.label:
            self._emit(f' as {node.label}')
        if node.offset_ms is not None:
            self._emit(f' offset {self._fmt_time_literal(node.offset_ms)}')
        self._emit(' {')
        self._emit_line()
        self.indent_level += 1
        for stmt in node.body:
            self._format_node(stmt)
        self.indent_level -= 1
        self._emit('}')

    def _fmt_LoopBlock(self, node: LoopBlock) -> None:
        self._emit('loop {')
        self._emit_line()
        self.indent_level += 1
        for stmt in node.body:
            self._format_node(stmt)
        self.indent_level -= 1
        self._emit('}')

    def _fmt_VoidLoop(self, node: VoidLoop) -> None:
        self._emit('void loop() {')
        self._emit_line()
        self.indent_level += 1
        for stmt in node.body:
            self._format_node(stmt)
        self.indent_level -= 1
        self._emit('}')

    def _fmt_TickBlock(self, node: TickBlock) -> None:
        self._emit('tick {')
        self._emit_line()
        self.indent_level += 1
        for stmt in node.body:
            self._format_node(stmt)
        self.indent_level -= 1
        self._emit('}')

    def _fmt_AfterBlock(self, node: AfterBlock) -> None:
        self._emit('after ')
        self._emit(self._fmt_time_literal(node.interval))
        self._emit(' {')
        self._emit_line()
        self.indent_level += 1
        for stmt in node.body:
            self._format_node(stmt)
        self.indent_level -= 1
        self._emit('}')

    def _fmt_PeripheralDecl(self, node: PeripheralDecl) -> None:
        self._emit(f'{node.periph_type} {node.name} {{')
        config_items = []
        for key, val in node.config.items():
            config_items.append(f'{key}: {self._fmt_value(val)}')
        self._emit(', '.join(config_items))
        self._emit('};')

    # ─────────────────────────────────────
    #  STATEMENTS
    # ─────────────────────────────────────

    def _fmt_Assign(self, node: Assign) -> None:
        self._fmt_expression(node.target)
        self._emit(' = ')
        self._fmt_expression(node.value)
        self._emit_line(';')

    def _fmt_AssignAfter(self, node: AssignAfter) -> None:
        self._fmt_expression(node.target)
        self._emit(' = ')
        self._fmt_expression(node.value)
        self._emit(f' after {self._fmt_time_literal(node.delay)}')
        self._emit_line(';')

    def _fmt_CompoundAssign(self, node: CompoundAssign) -> None:
        self._fmt_expression(node.target)
        self._emit(f' {node.op} ')
        self._fmt_expression(node.value)
        self._emit_line(';')

    def _fmt_IfStmt(self, node: IfStmt) -> None:
        self._emit('if ')
        self._fmt_expression(node.condition)
        self._emit(' {')
        self._emit_line()
        self.indent_level += 1
        for stmt in node.then_body:
            self._format_node(stmt)
        self.indent_level -= 1
        # elif clauses
        for cond, body in node.elif_clauses:
            self._emit('} else if ')
            self._fmt_expression(cond)
            self._emit(' {')
            self._emit_line()
            self.indent_level += 1
            for stmt in body:
                self._format_node(stmt)
            self.indent_level -= 1
        # else
        if node.else_body is not None:
            self._emit('} else {')
            self._emit_line()
            self.indent_level += 1
            for stmt in node.else_body:
                self._format_node(stmt)
            self.indent_level -= 1
        self._emit('}')

    def _fmt_WhileStmt(self, node: WhileStmt) -> None:
        self._emit('while ')
        self._fmt_expression(node.condition)
        self._emit(' {')
        self._emit_line()
        self.indent_level += 1
        for stmt in node.body:
            self._format_node(stmt)
        self.indent_level -= 1
        self._emit('}')

    def _fmt_ForStmt(self, node: ForStmt) -> None:
        self._emit('for ')
        if node.init:
            # Format init without trailing newline
            fmt = Formatter()
            fmt.indent_level = 0
            fmt._format_node(node.init)
            init_str = fmt._render().strip().rstrip(';')
            self._emit(init_str)
            self._emit(' ')
        self._fmt_expression(node.condition)
        self._emit('; ')
        if node.step:
            fmt = Formatter()
            fmt.indent_level = 0
            fmt._format_node(node.step)
            step_str = fmt._render().strip().rstrip(';')
            self._emit(step_str)
        self._emit(' {')
        self._emit_line()
        self.indent_level += 1
        for stmt in node.body:
            self._format_node(stmt)
        self.indent_level -= 1
        self._emit('}')

    def _fmt_ReturnStmt(self, node: ReturnStmt) -> None:
        if node.value is not None:
            self._emit('return ')
            self._fmt_expression(node.value)
        else:
            self._emit('return')
        self._emit_line(';')

    def _fmt_BreakStmt(self, node: BreakStmt) -> None:
        self._emit_line('break;')

    def _fmt_ContinueStmt(self, node: ContinueStmt) -> None:
        self._emit_line('continue;')

    def _fmt_StopStmt(self, node: StopStmt) -> None:
        self._emit_line(f'stop {node.label};')

    def _fmt_PrintStmt(self, node: PrintStmt) -> None:
        if node.newline:
            self._emit('println(')
        else:
            self._emit('print(')
        self._fmt_expression(node.value)
        self._emit(')')
        self._emit_line(';')

    def _fmt_DeferStmt(self, node: DeferStmt) -> None:
        self._emit('defer {')
        self._emit_line()
        self.indent_level += 1
        for stmt in node.body:
            self._format_node(stmt)
        self.indent_level -= 1
        self._emit('}')

    def _fmt_ExprStmt(self, node: ExprStmt) -> None:
        self._fmt_expression(node.expr)
        self._emit_line(';')

    # ─────────────────────────────────────
    #  EXPRESSIONS
    # ─────────────────────────────────────

    def _fmt_expression(self, expr) -> None:
        """Format any expression node inline (no line break)."""
        if expr is None:
            return
        if isinstance(expr, str):
            # String literal target (variable name)
            self._emit(expr)
            return
        self._format_node(expr)

    def _fmt_BinOp(self, node: BinOp) -> None:
        self._fmt_expression(node.left)
        self._emit(f' {node.op} ')
        self._fmt_expression(node.right)

    def _fmt_UnaryOp(self, node: UnaryOp) -> None:
        self._emit(node.op)
        # No space for ! and ~ prefix operators
        if node.op not in ('!', '~', '-'):
            self._emit(' ')
        self._fmt_expression(node.operand)

    def _fmt_MemberAccess(self, node: MemberAccess) -> None:
        if isinstance(node.obj, str):
            self._emit(f'{node.obj}.{node.member}')
        else:
            self._fmt_expression(node.obj)
            self._emit(f'.{node.member}')

    def _fmt_ArrayAccess(self, node: ArrayAccess) -> None:
        self._emit(f'{node.name}[')
        self._fmt_expression(node.index)
        self._emit(']')

    def _fmt_Literal(self, node: Literal) -> None:
        self._emit(self._fmt_value(node.value))

    def _fmt_Identifier(self, node: Identifier) -> None:
        self._emit(node.name)

    def _fmt_FnCall(self, node: FnCall) -> None:
        self._emit(node.name)
        self._emit('(')
        for i, arg in enumerate(node.args):
            if i > 0:
                self._emit(', ')
            self._fmt_expression(arg)
        self._emit(')')

    def _fmt_MethodCall(self, node: MethodCall) -> None:
        self._fmt_expression(node.obj)
        self._emit(f'.{node.method}(')
        for i, arg in enumerate(node.args):
            if i > 0:
                self._emit(', ')
            self._fmt_expression(arg)
        self._emit(')')

    def _fmt_PwmSetup(self, node: PwmSetup) -> None:
        self._emit(f'{node.pin}.setup(')
        self._fmt_expression(node.freq)
        self._emit(', ')
        self._fmt_expression(node.resolution)
        self._emit(')')

    def _fmt_PwmWrite(self, node: PwmWrite) -> None:
        self._emit(f'{node.pin}.write(')
        self._fmt_expression(node.value)
        self._emit(')')

    def _fmt_MillisExpr(self, node: MillisExpr) -> None:
        self._emit('millis()')

    def _fmt_MathExpr(self, node: MathExpr) -> None:
        self._emit(f'{node.func}(')
        for i, arg in enumerate(node.args):
            if i > 0:
                self._emit(', ')
            self._fmt_expression(arg)
        self._emit(')')

    def _fmt_CastExpr(self, node: CastExpr) -> None:
        self._fmt_expression(node.expr)
        self._emit(f' as {node.target_type}')

    def _fmt_SizeOfExpr(self, node: SizeOfExpr) -> None:
        if isinstance(node.target, str):
            self._emit(f'sizeof({node.target})')
        else:
            self._emit('sizeof(')
            self._fmt_expression(node.target)
            self._emit(')')

    # ─────────────────────────────────────
    #  HELPERS
    # ─────────────────────────────────────

    def _fmt_param(self, param: VarDecl) -> None:
        """Format a function parameter."""
        if param.vtype:
            self._emit(f'{param.name}: {param.vtype}')
        else:
            # let-style without type
            self._emit(param.name)
            if param.vtype:
                self._emit(f': {param.vtype}')

    def _fmt_value(self, value) -> str:
        """Format a literal value for display."""
        if isinstance(value, str):
            return f'"{value}"'
        elif isinstance(value, bool):
            return 'true' if value else 'false'
        elif isinstance(value, float):
            # Keep float representation clean
            if value == int(value):
                return f'{int(value)}.0'
            return repr(value)
        else:
            return str(value)

    def _fmt_time_literal(self, ms: int) -> str:
        """Format a time value (milliseconds) in its most readable form."""
        if ms >= 60000 and ms % 60000 == 0:
            return f'{ms // 60000}m'
        elif ms >= 1000 and ms % 1000 == 0:
            return f'{ms // 1000}s'
        elif ms > 0 and ms % 1000 != 0:
            return f'{ms}ms'
        else:
            return str(ms)


# ─────────────────────────────────────────
#  PUBLIC API
# ─────────────────────────────────────────

def format_source(source: str) -> str:
    """
    Format Iotift source code and return the formatted result.

    Raises FormatError on parse or format errors.
    """
    from lexer import tokenize, LexError
    from parser import Parser, ParseError

    try:
        tokens = tokenize(source)
    except LexError as e:
        raise FormatError(f'Lex error: {e}')

    try:
        parser = Parser(tokens)
        ast = parser.parse()
    except ParseError as e:
        raise FormatError(f'Parse error: {e}')

    fmt = Formatter()
    return fmt.format(ast)


def format_file(filepath: str, in_place: bool = False) -> str:
    """
    Format an Iotift source file.

    Args:
        filepath: Path to the .iot file.
        in_place: If True, write the formatted result back to the file.

    Returns:
        The formatted source code.

    Raises FormatError on errors, FileNotFoundError if file doesn't exist.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f'File not found: {filepath}')

    with open(filepath, 'r', encoding='utf-8') as f:
        source = f.read()

    formatted = format_source(source)

    if in_place:
        # Only write if changed
        if formatted != source:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(formatted)

    return formatted


def check_format(filepath: str) -> bool:
    """
    Check if a file is correctly formatted.

    Returns:
        True if the file matches the formatter output, False otherwise.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        source = f.read()
    formatted = format_source(source)
    return source == formatted
