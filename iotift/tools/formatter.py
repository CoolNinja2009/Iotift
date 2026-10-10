"""
Iotift Formatter — opinionated, zero-configuration code formatter.

Rules:
- 4-space indentation
- Opening brace on the same line, preceded by a space
- One blank line between top-level declarations
- `if x > 0 {` / `while x {` / `for init; cond; step {` (no parentheses)
- Parameters written as `name: type`
- Comments are kept (attached to the statement they precede or follow)
- Trailing whitespace stripped, single trailing newline

Safety: the formatter works from the AST, so before returning it re-parses
its own output and checks that the program and every comment survived
unchanged.  If not, it raises FormatError and the file is left alone — a
formatter must never change what a program means.
"""

from __future__ import annotations

import os
import re
from dataclasses import fields, is_dataclass
from typing import Any, List, Optional, Tuple

from ast_nodes import (
    Node, Program, DeviceDecl, SchedulerConfig, ImportDecl,
    CBlockNode, PinDecl, VarDecl, ArrayDecl, StructDecl, FnDecl,
    ExternFnDecl, EnumDecl, TypeAliasDecl,
    OnEvent, OnThreshold, EveryBlock, LoopBlock, VoidLoop, TickBlock,
    AfterBlock, PeripheralDecl,
    Assign, AssignAfter, CompoundAssign, IfStmt, WhileStmt, ForStmt,
    ReturnStmt, BreakStmt, ContinueStmt, StopStmt, StartStmt, PrintStmt,
    DeferStmt, ExprStmt,
    BinOp, UnaryOp, MemberAccess, ArrayAccess, Literal, Identifier,
    FnCall, MethodCall, PwmSetup, PwmWrite, MillisExpr, MathExpr,
    CastExpr, SizeOfExpr, PinConfig,
    WifiDecl,
)

INDENT = '    '  # 4 spaces
MAX_LINE_WIDTH = 100

_PREC = {
    '||': 1, '&&': 2, '|': 3, '^': 4, '&': 5,
    '==': 6, '!=': 6, '<': 7, '>': 7, '<=': 7, '>=': 7,
    '<<': 8, '>>': 8, '+': 9, '-': 9, '*': 10, '/': 10, '%': 10,
}
_UNARY = 11
_ATOM = 99

# Expression nodes that may appear as statements (need a trailing ';').
_EXPR_STMTS = (FnCall, MethodCall, MathExpr, PwmSetup, PwmWrite, MemberAccess,
               MillisExpr, Identifier, BinOp, UnaryOp)


class FormatError(Exception):
    """Raised when formatting fails."""
    pass


# ─────────────────────────────────────────
#  COMMENTS
# ─────────────────────────────────────────

class _Comment:
    __slots__ = ('line', 'end_line', 'text', 'own_line', 'used', 'blank_before')

    def __init__(self, line: int, end_line: int, text: str, own_line: bool):
        self.line, self.end_line, self.text, self.own_line = line, end_line, text, own_line
        self.used = False
        self.blank_before = False


_C_BLOCK_RE = re.compile(r'c\s+(header|global|setup|loop|isr)\b\s*\{')


def extract_comments(source: str) -> List[_Comment]:
    """Find `//` and `/* */` comments outside strings and raw C blocks."""
    out: List[_Comment] = []
    i, n, line = 0, len(source), 1
    line_start = 0

    def skip_quoted(j: int, q: str) -> Tuple[int, int]:
        nl = 0
        j += 1
        while j < n:
            if source[j] == '\\':
                j += 2
                continue
            if source[j] == '\n':
                nl += 1
            if source[j] == q:
                return j + 1, nl
            j += 1
        return j, nl

    while i < n:
        ch = source[i]
        if ch == '\n':
            line += 1
            line_start = i + 1
            i += 1
        elif ch in '"\'':
            i, nl = skip_quoted(i, ch)
            line += nl
        elif source.startswith('//', i):
            j = source.find('\n', i)
            j = n if j == -1 else j
            own = not source[line_start:i].strip()
            out.append(_Comment(line, line, source[i:j].rstrip(), own))
            i = j
        elif source.startswith('/*', i):
            j = source.find('*/', i + 2)
            j = n if j == -1 else j + 2
            text = source[i:j]
            own = not source[line_start:i].strip()
            out.append(_Comment(line, line + text.count('\n'), text, own))
            line += text.count('\n')
            if '\n' in text:
                line_start = i + text.rfind('\n') + 1
            i = j
        elif ch == 'c' and (i == 0 or not (source[i - 1].isalnum() or source[i - 1] == '_')) \
                and _C_BLOCK_RE.match(source, i):
            # Raw C: its comments belong to the C code and are kept verbatim.
            j = _C_BLOCK_RE.match(source, i).end()
            depth = 1
            while j < n and depth:
                c = source[j]
                if c in '"\'':
                    j, nl = skip_quoted(j, c)
                    line += nl
                    continue
                if source.startswith('//', j):
                    k = source.find('\n', j)
                    j = n if k == -1 else k
                    continue
                if source.startswith('/*', j):
                    k = source.find('*/', j + 2)
                    k = n if k == -1 else k + 2
                    line += source.count('\n', j, k)
                    j = k
                    continue
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                elif c == '\n':
                    line += 1
                    line_start = j + 1
                j += 1
            i = j
        else:
            i += 1
    src_lines = source.split('\n')
    for c in out:
        c.blank_before = c.own_line and c.line >= 2 and not src_lines[c.line - 2].strip()
    return out


# ─────────────────────────────────────────
#  FORMATTER
# ─────────────────────────────────────────

class Formatter:
    """Pretty-prints an Iotift AST back to source code."""

    def __init__(self, comments: Optional[List[_Comment]] = None):
        self.lines: List[str] = []
        self.indent_level: int = 0
        self._comments: List[_Comment] = list(comments or [])
        self._stmt_line = 0

    @property
    def indent(self) -> str:
        return INDENT * self.indent_level

    # ── output primitives ──

    def _line(self, text: str = '') -> None:
        if text:
            trailing = self._take_trailing(self._stmt_line)
            if trailing:
                text = f'{text}  {trailing}'
            self.lines.append((self.indent + text).rstrip())
        else:
            self.lines.append('')

    def _blank_line(self) -> None:
        if self.lines and self.lines[-1] != '':
            self.lines.append('')

    def _render(self) -> str:
        while self.lines and self.lines[-1] == '':
            self.lines.pop()
        while self.lines and self.lines[0] == '':
            self.lines.pop(0)
        return '\n'.join(self.lines) + '\n'

    # ── comments ──

    def _take_trailing(self, line: int) -> Optional[str]:
        if not line:
            return None
        for c in self._comments:
            if not c.used and not c.own_line and c.line == line and '\n' not in c.text:
                c.used = True
                return c.text
        return None

    def _flush_comments(self, before_line: Optional[int]) -> None:
        """Emit every unused comment that starts before *before_line* (None = all)."""
        for c in self._comments:
            if c.used or (before_line is not None and c.line >= before_line):
                continue
            c.used = True
            if c.blank_before and self.lines and not self.lines[-1].rstrip().endswith('{'):
                self._blank_line()
            text_lines = c.text.split('\n')
            self.lines.append((self.indent + text_lines[0]).rstrip())
            self.lines.extend(text_lines[1:])

    # ── entry points ──

    def format(self, node: Node) -> str:
        if isinstance(node, Program):
            self._program(node)
        else:
            self._stmt(node)
        self._flush_comments(None)
        return self._render()

    def _program(self, node: Program) -> None:
        for i, child in enumerate(node.body):
            if i > 0 and not (isinstance(child, CBlockNode) and isinstance(node.body[i - 1], CBlockNode)
                              and child.scope == node.body[i - 1].scope):
                self._blank_line()
            self._stmt(child)

    # ── statements & declarations ──

    def _body(self, stmts: List[Node], end_line: int = 0) -> None:
        self.indent_level += 1
        for s in stmts:
            self._stmt(s)
        if end_line:
            self._flush_comments(end_line)
        self.indent_level -= 1

    def _block(self, header: str, body: List[Node], node: Node, close: str = '}') -> None:
        self._line(header + ' {')
        self._body(body, getattr(node, 'end_line', 0))
        self._stmt_line = 0
        self._line(close)

    def _stmt(self, node: Node) -> None:
        line = getattr(node, 'line', 0)
        if line:
            self._flush_comments(line)
            self._stmt_line = line
        method = getattr(self, f'_fmt_{type(node).__name__}', None)
        if method is not None:
            method(node)
        elif isinstance(node, _EXPR_STMTS):
            self._line(self._expr(node) + ';')
        else:
            raise FormatError(f'No formatter for node type: {type(node).__name__}')

    def _fmt_DeviceDecl(self, node: DeviceDecl) -> None:
        self._line(f'@device {node.name}')

    def _fmt_SchedulerConfig(self, node: SchedulerConfig) -> None:
        self._line(f'@config {node.key} = {node.value};')

    def _fmt_ImportDecl(self, node: ImportDecl) -> None:
        if node.selected_names is not None:
            self._line(f'import {{ {", ".join(node.selected_names)} }} from {_quote(node.path)};')
        else:
            self._line(f'import {_quote(node.path)};')

    def _fmt_CBlockNode(self, node: CBlockNode) -> None:
        # Raw C is reproduced verbatim (including its own indentation).
        self._line(f'c {node.scope} {{')
        if node.code:
            self.lines.extend(node.code.split('\n'))
        self._stmt_line = 0
        self._line('}')

    def _fmt_PinDecl(self, node: PinDecl) -> None:
        s = f'pin {node.name} = {node.direction} {node.number}'
        if node.pwm_freq is not None:
            s += f' freq {node.pwm_freq}'
        if node.pwm_resolution is not None:
            s += f' resolution {node.pwm_resolution}'
        cfg = node.config or PinConfig()
        parts = []
        if cfg.pull is not None:
            parts.append(f'pull: {cfg.pull}')
        if cfg.debounce_ms is not None:
            parts.append(f'debounce: {_time(cfg.debounce_ms)}')
        if cfg.initial is not None:
            parts.append(f'initial: {cfg.initial}')
        if parts:
            s += f' {{ {", ".join(parts)} }}'
        self._line(s + ';')

    def _var_decl_text(self, node: VarDecl) -> str:
        vol = 'volatile ' if node.is_volatile else ''
        init = f' = {self._expr(node.init)}' if node.init is not None else ''
        if node.is_const:
            return f'const {vol}{node.vtype or "int"} {node.name}{init}'
        if not node.is_mutable:
            t = f': {node.vtype}' if node.vtype else ''
            return f'let {vol}{node.name}{t}{init}'
        if node.vtype is None:
            return f'var {vol}{node.name}{init}'
        return f'{vol}{node.vtype} {node.name}{init}'

    def _fmt_VarDecl(self, node: VarDecl) -> None:
        self._line(self._var_decl_text(node) + ';')

    def _fmt_ArrayDecl(self, node: ArrayDecl) -> None:
        self._line(f'{node.vtype or node.elem_type or "int"} {node.name}[{node.size}];')

    def _fmt_StructDecl(self, node: StructDecl) -> None:
        self._line(f'struct {node.name} {{')
        self.indent_level += 1
        for f in node.fields:
            self._stmt(f)
        self._flush_comments(node.end_line or None) if node.end_line else None
        self.indent_level -= 1
        self._stmt_line = 0
        self._line('}')

    def _params(self, params: List[VarDecl]) -> str:
        return ', '.join(f'{p.name}: {p.vtype}' for p in params)

    def _fmt_FnDecl(self, node: FnDecl) -> None:
        head = ('isr ' if node.is_isr else '') + f'fn {node.name}({self._params(node.params)})'
        if node.return_type:
            head += f' -> {node.return_type}'
        self._block(head, node.body, node)

    def _fmt_ExternFnDecl(self, node: ExternFnDecl) -> None:
        s = f'extern fn {node.name}({self._params(node.params)})'
        if node.return_type:
            s += f' -> {node.return_type}'
        self._line(s + ';')

    def _fmt_EnumDecl(self, node: EnumDecl) -> None:
        head = f'enum {node.name}' + (f': {node.backing_type}' if node.backing_type else '')
        self._line(head + ' {')
        self.indent_level += 1
        for i, (name, value) in enumerate(node.variants):
            self._line(name + (f' = {value}' if value is not None else '')
                       + (',' if i < len(node.variants) - 1 else ''))
        self.indent_level -= 1
        self._line('}')

    def _fmt_TypeAliasDecl(self, node: TypeAliasDecl) -> None:
        self._line(f'type {node.name} = {node.aliased_type};')

    def _fmt_OnEvent(self, node: OnEvent) -> None:
        self._block(f'on {node.target}.{node.event}', node.body, node)

    def _fmt_OnThreshold(self, node: OnThreshold) -> None:
        self._block(f'on {node.pin} {node.op} {self._expr(node.value, _PREC["+"])}', node.body, node)

    def _fmt_EveryBlock(self, node: EveryBlock) -> None:
        head = f'every {_time(node.interval)}'
        if node.label:
            head += f' as {node.label}'
        if node.offset_ms is not None:
            head += f' offset {_time(node.offset_ms)}'
        self._block(head, node.body, node)

    def _fmt_LoopBlock(self, node: LoopBlock) -> None:
        self._block('loop', node.body, node)

    def _fmt_VoidLoop(self, node: VoidLoop) -> None:
        self._block('void loop()', node.body, node)

    def _fmt_TickBlock(self, node: TickBlock) -> None:
        self._block('tick', node.body, node)

    def _fmt_AfterBlock(self, node: AfterBlock) -> None:
        self._block(f'after {_time(node.interval)}', node.body, node)

    def _fmt_DeferStmt(self, node: DeferStmt) -> None:
        self._block('defer', node.body, node)

    def _fmt_PeripheralDecl(self, node: PeripheralDecl) -> None:
        items = ', '.join(f'{k}: {v}' for k, v in node.config.items())
        self._line(f'{node.periph_type} {node.name} {{ {items} }};')

    def _fmt_WifiDecl(self, node: WifiDecl) -> None:
        items = []
        for key, val in node.config.items():
            if key == 'retry' and isinstance(val, dict):
                kind = val.get('kind', 'fixed')
                if kind == 'custom':
                    inner = [f'count: {val.get("count", 3)}',
                             f'interval: {_time(val.get("interval_ms", 5000))}',
                             f'max_interval: {_time(val.get("max_interval_ms", 60000))}',
                             f'backoff: {val.get("backoff", "fixed")}']
                    items.append(f'retry: custom {{ {", ".join(inner)} }}')
                else:
                    items.append(f'retry: {kind}')
            elif key == 'connect_timeout':
                items.append(f'{key}: {_time(val)}')
            elif key in ('mode', 'power_save'):
                items.append(f'{key}: {val}')
            elif isinstance(val, bool):
                items.append(f'{key}: {"true" if val else "false"}')
            elif isinstance(val, int):
                items.append(f'{key}: {val}')
            else:
                items.append(f'{key}: {_quote(str(val))}')
        self._line(f'wifi {node.name} {{')
        self.indent_level += 1
        for i, it in enumerate(items):
            self._line(it + (',' if i < len(items) - 1 else ''))
        self.indent_level -= 1
        self._stmt_line = 0
        self._line('};')

    # ── simple statements ──

    def _simple(self, node: Node) -> str:
        """A statement without its trailing ';' (used inside `for` headers)."""
        if isinstance(node, VarDecl):
            return self._var_decl_text(node)
        if isinstance(node, Assign):
            return f'{self._target(node.target)} = {self._expr(node.value)}'
        if isinstance(node, CompoundAssign):
            return f'{node.target} {node.op} {self._expr(node.value)}'
        if isinstance(node, AssignAfter):
            return f'{node.target} = {self._expr(node.value)} after {_time(node.delay)}'
        return self._expr(node)

    def _fmt_Assign(self, node: Assign) -> None:
        self._line(self._simple(node) + ';')

    def _fmt_AssignAfter(self, node: AssignAfter) -> None:
        self._line(self._simple(node) + ';')

    def _fmt_CompoundAssign(self, node: CompoundAssign) -> None:
        self._line(self._simple(node) + ';')

    def _fmt_ExprStmt(self, node: ExprStmt) -> None:
        self._line(self._expr(node.expr) + ';')

    def _fmt_IfStmt(self, node: IfStmt) -> None:
        self._line(f'if {self._expr(node.condition)} {{')
        self._body(node.then_body)
        for cond, body in node.elif_clauses:
            self._stmt_line = 0
            self._line(f'}} else if {self._expr(cond)} {{')
            self._body(body)
        if node.else_body is not None:
            self._stmt_line = 0
            self._line('} else {')
            self._body(node.else_body)
        self._flush_inner(node)
        self._stmt_line = 0
        self._line('}')

    def _flush_inner(self, node: Node) -> None:
        if getattr(node, 'end_line', 0):
            self.indent_level += 1
            self._flush_comments(node.end_line)
            self.indent_level -= 1

    def _fmt_WhileStmt(self, node: WhileStmt) -> None:
        self._block(f'while {self._expr(node.condition)}', node.body, node)

    def _fmt_ForStmt(self, node: ForStmt) -> None:
        init = self._simple(node.init) if node.init else ''
        cond = self._expr(node.condition) if node.condition is not None else ''
        step = self._simple(node.step) if node.step else ''
        head = f'for {init}; {cond}; {step}'.replace('  ', ' ').rstrip()
        self._block(head, node.body, node)

    def _fmt_ReturnStmt(self, node: ReturnStmt) -> None:
        self._line('return;' if node.value is None else f'return {self._expr(node.value)};')

    def _fmt_BreakStmt(self, node: BreakStmt) -> None:
        self._line('break;')

    def _fmt_ContinueStmt(self, node: ContinueStmt) -> None:
        self._line('continue;')

    def _fmt_StopStmt(self, node: StopStmt) -> None:
        self._line(f'stop {node.label};')

    def _fmt_StartStmt(self, node: StartStmt) -> None:
        self._line(f'start {node.label};')

    def _fmt_PrintStmt(self, node: PrintStmt) -> None:
        self._line(f'{"println" if node.newline else "print"}({self._expr(node.value)});')

    # ── expressions ──

    def _target(self, t: Any) -> str:
        return t if isinstance(t, str) else self._expr(t)

    def _expr(self, node: Any, parent: int = 0) -> str:
        s, prec = self._expr_p(node)
        return f'({s})' if prec < parent else s

    def _expr_p(self, node: Any) -> Tuple[str, int]:
        if isinstance(node, str):
            return node, _ATOM
        if isinstance(node, Literal):
            return _literal(node), _ATOM
        if isinstance(node, Identifier):
            return node.name, _ATOM
        if isinstance(node, MillisExpr):
            return 'millis()', _ATOM
        if isinstance(node, BinOp):
            p = _PREC[node.op]
            return f'{self._expr(node.left, p)} {node.op} {self._expr(node.right, p + 1)}', p
        if isinstance(node, UnaryOp):
            inner = self._expr(node.operand, _UNARY)
            if node.op == '-' and inner.startswith('-'):
                inner = f'({inner})'
            return f'{node.op}{inner}', _UNARY
        if isinstance(node, CastExpr):
            # `as` binds to a primary expression only: `-(x) as int` is not `(-x) as int`.
            return f'{self._expr(node.expr, _ATOM)} as {node.target_type}', _UNARY + 1
        if isinstance(node, SizeOfExpr):
            t = node.target if isinstance(node.target, str) else self._expr(node.target)
            return f'sizeof({t})', _ATOM
        if isinstance(node, MemberAccess):
            obj = node.obj if isinstance(node.obj, str) else self._expr(node.obj, _ATOM)
            return f'{obj}.{node.member}', _ATOM
        if isinstance(node, ArrayAccess):
            return f'{node.name}[{self._expr(node.index)}]', _ATOM
        if isinstance(node, FnCall):
            return f'{node.name}({self._args(node.args)})', _ATOM
        if isinstance(node, MathExpr):
            return f'{node.func}({self._args(node.args)})', _ATOM
        if isinstance(node, MethodCall):
            obj = node.obj if isinstance(node.obj, str) else self._expr(node.obj, _ATOM)
            return f'{obj}.{node.method}({self._args(node.args)})', _ATOM
        if isinstance(node, PwmSetup):
            return f'{node.pin}.setup({self._expr(node.freq)}, {self._expr(node.resolution)})', _ATOM
        if isinstance(node, PwmWrite):
            return f'{node.pin}.write({self._expr(node.value)})', _ATOM
        if isinstance(node, bool):
            return ('true' if node else 'false'), _ATOM
        if isinstance(node, (int, float)):
            return _number(node), _ATOM
        raise FormatError(f'No formatter for expression {type(node).__name__}')

    def _args(self, args: List[Any]) -> str:
        return ', '.join(self._expr(a) for a in args)


# ─────────────────────────────────────────
#  VALUE HELPERS
# ─────────────────────────────────────────

def _quote(s: str) -> str:
    out = []
    for ch in s:
        if ch == '\\':
            out.append('\\\\')
        elif ch == '"':
            out.append('\\"')
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\t':
            out.append('\\t')
        elif ch == '\r':
            out.append('\\r')
        elif ch == '\0':
            out.append('\\0')
        elif ord(ch) < 0x20:
            out.append('\\x%02x' % ord(ch))
        else:
            out.append(ch)
    return '"' + ''.join(out) + '"'


def _number(v: Any) -> str:
    if isinstance(v, float):
        r = repr(v)
        if 'e' in r or 'E' in r:            # the lexer has no exponent-only floats
            r = format(v, '.20f').rstrip('0')
        if '.' not in r:
            r += '.0'
        if r.endswith('.'):
            r += '0'
        return r
    return str(v)


def _literal(node: Literal) -> str:
    v, t = node.value, node.vtype
    if t == 'str':
        return _quote(str(v))
    if t == 'char':
        if isinstance(v, int):
            return str(v)
        esc = {'\n': '\\n', '\t': '\\t', '\r': '\\r', '\\': '\\\\', "'": "\\'", '\0': '\\0'}
        return f"'{esc.get(v, v)}'"
    if t == 'bool' or isinstance(v, bool):
        return 'true' if v else 'false'
    return _number(v)


def _time(ms: int) -> str:
    """Milliseconds in their most readable time-literal form."""
    if ms >= 3600000 and ms % 3600000 == 0:
        return f'{ms // 3600000}h'
    if ms >= 60000 and ms % 60000 == 0:
        return f'{ms // 60000}m'
    if ms >= 1000 and ms % 1000 == 0:
        return f'{ms // 1000}s'
    if ms > 0:
        return f'{ms}ms'
    return str(ms)


# ─────────────────────────────────────────
#  ROUND-TRIP CHECK
# ─────────────────────────────────────────

_IGNORED_FIELDS = {'line', 'col', 'end_line', 'end_col'}


def _normalize(obj: Any) -> Any:
    """AST → plain nested tuples, without source positions."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return (type(obj).__name__,) + tuple(
            (f.name, _normalize(getattr(obj, f.name)))
            for f in fields(obj) if f.name not in _IGNORED_FIELDS)
    if isinstance(obj, (list, tuple)):
        return tuple(_normalize(x) for x in obj)
    if isinstance(obj, dict):
        return tuple(sorted((k, _normalize(v)) for k, v in obj.items()))
    if isinstance(obj, float):
        return ('float', obj)
    return obj


def _parse(source: str):
    from lexer import tokenize, LexError
    from parser import Parser, ParseError
    import contextlib
    import io
    try:
        tokens = tokenize(source)
    except LexError as e:
        raise FormatError(f'Lex error: {e}')
    parser = Parser(tokens)
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            ast = parser.parse()
    except ParseError as e:
        raise FormatError(f'Parse error: {e}')
    if parser._had_error:
        raise FormatError('Parse error: ' + '; '.join(parser._errors))
    return ast


# ─────────────────────────────────────────
#  PUBLIC API
# ─────────────────────────────────────────

def format_source(source: str) -> str:
    """
    Format Iotift source code and return the formatted result.

    Raises FormatError on parse errors, or if formatting would change the
    program or lose a comment (a formatter bug — the input is never modified).
    """
    ast = _parse(source)
    comments = extract_comments(source)
    formatted = Formatter(comments).format(ast)

    try:
        reparsed = _parse(formatted)
    except FormatError as e:
        raise FormatError(f'internal formatter error, file left unchanged (output does not parse: {e})')
    if _normalize(reparsed) != _normalize(ast):
        raise FormatError('internal formatter error, file left unchanged '
                          '(formatting would change the meaning of the program)')
    before = sorted(c.text.strip() for c in comments)
    after = sorted(c.text.strip() for c in extract_comments(formatted))
    if before != after:
        raise FormatError('internal formatter error, file left unchanged (a comment would be lost)')
    return formatted


def format_file(filepath: str, in_place: bool = False) -> str:
    """
    Format an Iotift source file.  With *in_place*, write the result back
    (only if it changed).  Raises FormatError / FileNotFoundError.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f'File not found: {filepath}')
    with open(filepath, 'r', encoding='utf-8') as f:
        source = f.read()
    formatted = format_source(source)
    if in_place and formatted != source:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(formatted)
    return formatted


def check_format(filepath: str) -> bool:
    """True if the file is already formatted."""
    with open(filepath, 'r', encoding='utf-8') as f:
        source = f.read()
    return source == format_source(source)
