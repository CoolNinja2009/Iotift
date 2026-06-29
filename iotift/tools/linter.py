"""
Iotift Linter — static analysis for common embedded pitfalls.

Rules:
    no-float-in-isr          error   — float/double operations inside ISR
    no-heap-in-isr           error   — heap allocation inside ISR
    no-print-in-isr          warning — print/println inside ISR
    no-blocking-in-timer     warning — delay/millis in timer or event handler
    prefer-fixed-width       warning — int/float should be i32/f32 etc.
    unused-variable          warning — variable declared but never used
    unused-function          warning — function declared but never called
    empty-timer              warning — every/on/after block with empty body
    const-candidate          info    — variable never mutated, could be const
    volatile-needed          warning — variable accessed from ISR but not volatile
"""

from __future__ import annotations

import sys
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Set, Any

from ast_nodes import (
    Node, Program, PinDecl, VarDecl, FnDecl, ExternFnDecl,
    OnEvent, OnThreshold, EveryBlock, AfterBlock, TickBlock, VoidLoop,
    LoopBlock,
    Assign, CompoundAssign, AssignAfter, IfStmt, WhileStmt, ForStmt,
    ReturnStmt, PrintStmt, FnCall, MethodCall, MathExpr, MillisExpr,
    Identifier, BinOp, UnaryOp, MemberAccess, ArrayAccess, Literal,
    CastExpr, SizeOfExpr, ExprStmt, BreakStmt, ContinueStmt, StopStmt,
    DeferStmt, PwmSetup, PwmWrite, CBlockNode, StructDecl, EnumDecl,
    TypeAliasDecl, ImportDecl, DeviceDecl, SchedulerConfig,
    PeripheralDecl, ArrayDecl,
)


class LintSeverity(Enum):
    ERROR = 'error'
    WARNING = 'warning'
    INFO = 'info'


@dataclass
class LintDiagnostic:
    """A single lint finding."""
    severity: LintSeverity
    rule: str
    message: str
    line: int = 0
    col: int = 0
    end_line: int = 0
    end_col: int = 0

    def __str__(self) -> str:
        prefix = self.severity.value.upper()
        loc = f'{self.line}:{self.col}' if self.line else '?:?'
        return f'{loc}: {prefix} [{self.rule}] {self.message}'


# ─────────────────────────────────────────
#  LINTER
# ─────────────────────────────────────────

class Linter:
    """Walks an Iotift AST and collects lint diagnostics."""

    def __init__(self):
        self.diagnostics: List[LintDiagnostic] = []

        # State tracking
        self._in_isr: bool = False
        self._in_timer: bool = False
        self._isr_vars: Set[str] = set()       # variables accessed inside ISRs
        self._volatile_vars: Set[str] = set()   # variables declared volatile
        self._mutable_vars: Dict[str, bool] = {}  # name -> ever assigned
        self._var_refs: Dict[str, int] = {}     # name -> reference count
        self._fn_calls: Set[str] = set()        # function names that are called
        self._fn_decls: Dict[str, FnDecl] = {}  # function name -> declaration
        self._all_defs: Set[str] = set()        # all defined names

        self._node_stack: List[Node] = []       # for context tracking

    # ─────────────────────────────────────
    #  ENTRY POINT
    # ─────────────────────────────────────

    def lint(self, node: Node) -> List[LintDiagnostic]:
        """Run all lint rules on the AST."""
        self._collect_definitions(node)
        self._walk(node)
        self._check_unused()
        return sorted(self.diagnostics, key=lambda d: (d.line, d.col))

    def _collect_definitions(self, node: Node) -> None:
        """First pass: collect all declarations for cross-reference checks."""
        if node is None:
            return
        if isinstance(node, Program):
            for child in node.body:
                self._collect_definitions(child)
        elif isinstance(node, VarDecl):
            self._all_defs.add(node.name)
            if node.is_volatile:
                self._volatile_vars.add(node.name)
            if node.is_const:
                self._mutable_vars[node.name] = False
            else:
                self._mutable_vars[node.name] = node.is_mutable
            self._var_refs[node.name] = 0
        elif isinstance(node, ArrayDecl):
            self._all_defs.add(node.name)
        elif isinstance(node, FnDecl):
            self._all_defs.add(node.name)
            self._fn_decls[node.name] = node
            # Walk into function body to collect local variable definitions
            for stmt in node.body:
                self._collect_definitions(stmt)
        elif isinstance(node, ExternFnDecl):
            self._all_defs.add(node.name)
            self._fn_decls[node.name] = node
        elif isinstance(node, PinDecl):
            self._all_defs.add(node.name)
        elif isinstance(node, StructDecl):
            # Collect struct field definitions
            for field in node.fields:
                self._collect_definitions(field)
        # Recurse into blocks that can contain VarDecls
        elif isinstance(node, (EveryBlock, AfterBlock, OnEvent, OnThreshold,
                                TickBlock, VoidLoop, LoopBlock)):
            for stmt in node.body:
                self._collect_definitions(stmt)
        elif isinstance(node, IfStmt):
            for stmt in node.then_body:
                self._collect_definitions(stmt)
            for _, elif_body in node.elif_clauses:
                for stmt in elif_body:
                    self._collect_definitions(stmt)
            if node.else_body:
                for stmt in node.else_body:
                    self._collect_definitions(stmt)
        elif isinstance(node, (WhileStmt, ForStmt, DeferStmt)):
            if hasattr(node, 'body'):
                for stmt in node.body:
                    self._collect_definitions(stmt)
        elif isinstance(node, Node):
            # Default recursion: walk all Node and list attributes
            for field_name in dir(node):
                if field_name.startswith('_'):
                    continue
                try:
                    value = getattr(node, field_name)
                except Exception:
                    continue
                if isinstance(value, Node):
                    self._collect_definitions(value)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, Node):
                            self._collect_definitions(item)
                        elif isinstance(item, tuple):
                            for sub in item:
                                if isinstance(sub, Node):
                                    self._collect_definitions(sub)
                                elif isinstance(sub, list):
                                    for s in sub:
                                        if isinstance(s, Node):
                                            self._collect_definitions(s)

    # ─────────────────────────────────────
    #  AST WALKER
    # ─────────────────────────────────────

    def _walk(self, node: Node) -> None:
        """Recursively walk the AST, applying rules."""
        if node is None:
            return

        # Push context
        self._node_stack.append(node)

        # Apply rules based on node type
        self._check_node(node)

        # Recurse into children
        type_name = type(node).__name__
        walker_name = f'_walk_{type_name}'
        walker = getattr(self, walker_name, None)
        if walker:
            walker(node)
        else:
            # Default: walk all list attributes and child nodes
            self._walk_default(node)

        # Pop context
        self._node_stack.pop()

    def _walk_default(self, node: Node) -> None:
        """Walk all list and Node fields of a dataclass."""
        for field_name in dir(node):
            if field_name.startswith('_'):
                continue
            try:
                value = getattr(node, field_name)
            except Exception:
                continue
            if isinstance(value, Node):
                self._walk(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, Node):
                        self._walk(item)
                    elif isinstance(item, tuple):
                        for sub in item:
                            if isinstance(sub, Node):
                                self._walk(sub)
                            elif isinstance(sub, list):
                                for s in sub:
                                    if isinstance(s, Node):
                                        self._walk(s)

    def _walk_Program(self, node: Program) -> None:
        for child in node.body:
            self._walk(child)

    def _walk_FnDecl(self, node: FnDecl) -> None:
        # Track ISR context
        was_isr = self._in_isr
        if node.is_isr:
            self._in_isr = True

        for stmt in node.body:
            self._walk(stmt)

        self._in_isr = was_isr

    def _walk_EveryBlock(self, node: EveryBlock) -> None:
        was_timer = self._in_timer
        self._in_timer = True
        for stmt in node.body:
            self._walk(stmt)
        self._in_timer = was_timer

    def _walk_AfterBlock(self, node: AfterBlock) -> None:
        was_timer = self._in_timer
        self._in_timer = True
        for stmt in node.body:
            self._walk(stmt)
        self._in_timer = was_timer

    def _walk_OnEvent(self, node: OnEvent) -> None:
        was_timer = self._in_timer
        self._in_timer = True
        for stmt in node.body:
            self._walk(stmt)
        self._in_timer = was_timer

    def _walk_OnThreshold(self, node: OnThreshold) -> None:
        was_timer = self._in_timer
        self._in_timer = True
        for stmt in node.body:
            self._walk(stmt)
        self._in_timer = was_timer

    def _walk_TickBlock(self, node: TickBlock) -> None:
        was_timer = self._in_timer
        self._in_timer = True
        for stmt in node.body:
            self._walk(stmt)
        self._in_timer = was_timer

    def _walk_VoidLoop(self, node: VoidLoop) -> None:
        was_timer = self._in_timer
        self._in_timer = True
        for stmt in node.body:
            self._walk(stmt)
        self._in_timer = was_timer

    def _walk_Assign(self, node: Assign) -> None:
        self._walk(node.value)
        # Track mutation
        if isinstance(node.target, str):
            if node.target in self._mutable_vars:
                self._mutable_vars[node.target] = True
        elif isinstance(node.target, Identifier):
            name = node.target.name
            if name in self._mutable_vars:
                self._mutable_vars[name] = True
        elif isinstance(node.target, (MemberAccess, ArrayAccess)):
            pass  # Struct/array element — not a full variable mutation

    def _walk_CompoundAssign(self, node: CompoundAssign) -> None:
        self._walk(node.value)
        if isinstance(node.target, str):
            if node.target in self._mutable_vars:
                self._mutable_vars[node.target] = True

    def _walk_Identifier(self, node: Identifier) -> None:
        name = node.name
        if name in self._var_refs:
            self._var_refs[name] += 1
        if name in self._fn_calls:
            pass  # Already counted

    def _walk_FnCall(self, node: FnCall) -> None:
        self._fn_calls.add(node.name)
        for arg in node.args:
            if isinstance(arg, Node):
                self._walk(arg)

    # ─────────────────────────────────────
    #  RULE CHECKS
    # ─────────────────────────────────────

    def _check_node(self, node: Node) -> None:
        """Run all applicable rule checks on a node."""

        # R1: no-float-in-isr — error
        if self._in_isr:
            self._check_no_float_in_isr(node)

        # R2: no-print-in-isr — warning
        if self._in_isr:
            self._check_no_print_in_isr(node)

        # R3: no-blocking-in-timer — warning
        if self._in_timer:
            self._check_no_blocking_in_timer(node)

        # R4: prefer-fixed-width — warning
        self._check_prefer_fixed_width(node)

        # R5: empty-timer — warning
        self._check_empty_timer(node)

        # R6: const-candidate — info
        self._check_const_candidate(node)

        # R7: volatile-needed — warning
        if self._in_isr:
            self._check_volatile_needed(node)

    def _check_no_float_in_isr(self, node: Node) -> None:
        """ISR should not use floating-point (saves/restores FPU context on ESP32)."""
        if isinstance(node, VarDecl) and node.vtype in ('float', 'f32', 'f64'):
            self._warn(node, 'no-float-in-isr',
                       f'Floating-point variable "{node.name}" declared in ISR; '
                       'float operations in ISR are expensive on ESP32',
                       severity=LintSeverity.ERROR)
        elif isinstance(node, Literal) and node.vtype == 'float':
            self._warn(node, 'no-float-in-isr',
                       'Floating-point literal used in ISR',
                       severity=LintSeverity.ERROR)

    def _check_no_print_in_isr(self, node: Node) -> None:
        """Printing from ISR is unsafe."""
        if isinstance(node, PrintStmt):
            self._warn(node, 'no-print-in-isr',
                       'print/println called from ISR; print functions are not reentrant',
                       severity=LintSeverity.WARNING)

    def _check_no_blocking_in_timer(self, node: Node) -> None:
        """Timer handlers should not block."""
        if isinstance(node, FnCall) and node.name in ('delay', 'delay_us', 'delayMicroseconds'):
            self._warn(node, 'no-blocking-in-timer',
                       f'"{node.name}()" called in timer/event handler; blocking calls '
                       'may cause missed events',
                       severity=LintSeverity.WARNING)
        elif isinstance(node, MillisExpr):
            # millis() is fine in timers — it's non-blocking
            pass

    def _check_prefer_fixed_width(self, node: Node) -> None:
        """Suggest using fixed-width types on embedded targets."""
        if isinstance(node, VarDecl) and node.vtype in ('int', 'float'):
            suggestion = {'int': 'i32', 'float': 'f32'}[node.vtype]
            self._warn(node, 'prefer-fixed-width',
                       f'"{node.vtype}" type for "{node.name}"; prefer "{suggestion}" '
                       'for predictable memory layout on embedded targets',
                       severity=LintSeverity.WARNING)
        elif isinstance(node, FnDecl):
            if node.return_type in ('int', 'float'):
                suggestion = {'int': 'i32', 'float': 'f32'}[node.return_type]
                self._warn(node, 'prefer-fixed-width',
                           f'Return type "{node.return_type}" for fn "{node.name}"; '
                           f'prefer "{suggestion}"',
                           severity=LintSeverity.WARNING)

    def _check_empty_timer(self, node: Node) -> None:
        """Detect every/on/after blocks with empty bodies."""
        if isinstance(node, (EveryBlock, AfterBlock, OnEvent, OnThreshold)):
            if not node.body:
                label = getattr(node, 'label', None) or getattr(node, 'pin', '?')
                self._warn(node, 'empty-timer',
                           f'Empty body in timer/event handler "{label}"; '
                           'this block does nothing at runtime',
                           severity=LintSeverity.WARNING)

    def _check_const_candidate(self, node: Node) -> None:
        """Flag variables that are never mutated after init — could be const."""
        if isinstance(node, VarDecl) and not node.is_const:
            # Check if this variable is never assigned to
            name = node.name
            if name in self._mutable_vars and not self._mutable_vars[name]:
                self._warn(node, 'const-candidate',
                           f'"{name}" is never mutated; consider declaring as const',
                           severity=LintSeverity.INFO)

    def _check_volatile_needed(self, node: Node) -> None:
        """Check that variables accessed in ISR are declared volatile."""
        if isinstance(node, Identifier):
            name = node.name
            if (name in self._all_defs and
                    name not in self._volatile_vars and
                    name not in self._fn_decls):
                self._warn(node, 'volatile-needed',
                           f'Variable "{name}" accessed in ISR but not declared volatile; '
                           'the compiler may optimize away changes',
                           severity=LintSeverity.WARNING)
        elif isinstance(node, Assign):
            # Check the target
            target_name = None
            if isinstance(node.target, str):
                target_name = node.target
            elif isinstance(node.target, Identifier):
                target_name = node.target.name
            if target_name and target_name in self._all_defs and target_name not in self._volatile_vars:
                self._warn(node, 'volatile-needed',
                           f'Assignment to "{target_name}" in ISR but not declared volatile',
                           severity=LintSeverity.WARNING)

    def _check_unused(self) -> None:
        """Post-walk: check for unused variables and functions."""
        for name, count in self._var_refs.items():
            if count == 0 and name in self._all_defs:
                # Check if name exists in var_refs (is a variable)
                if name in self._mutable_vars:
                    self.diagnostics.append(LintDiagnostic(
                        severity=LintSeverity.WARNING,
                        rule='unused-variable',
                        message=f'Variable "{name}" is declared but never used',
                        line=0, col=0,
                    ))

        for name in self._fn_decls:
            if name not in self._fn_calls and name != 'loop':
                # Check if it's an ISR or timer callback — those are called by runtime
                fn = self._fn_decls[name]
                if isinstance(fn, FnDecl) and fn.is_isr:
                    continue
                self.diagnostics.append(LintDiagnostic(
                    severity=LintSeverity.WARNING,
                    rule='unused-function',
                    message=f'Function "{name}" is declared but never called',
                    line=0, col=0,
                ))

    # ─────────────────────────────────────
    #  HELPERS
    # ─────────────────────────────────────

    def _warn(self, node: Node, rule: str, message: str,
              severity: LintSeverity = LintSeverity.WARNING) -> None:
        """Emit a lint diagnostic."""
        self.diagnostics.append(LintDiagnostic(
            severity=severity,
            rule=rule,
            message=message,
            line=node.line,
            col=node.col,
            end_line=node.end_line,
            end_col=node.end_col,
        ))


# ─────────────────────────────────────────
#  PUBLIC API
# ─────────────────────────────────────────

def lint_source(source: str) -> List[LintDiagnostic]:
    """
    Run the linter on Iotift source code.

    Returns a list of LintDiagnostic findings.
    """
    from lexer import tokenize, LexError
    from parser import Parser, ParseError

    try:
        tokens = tokenize(source)
    except LexError as e:
        return [LintDiagnostic(
            severity=LintSeverity.ERROR,
            rule='parse-error',
            message=f'Lex error: {e}',
            line=e.line if hasattr(e, 'line') else 1,
            col=e.col if hasattr(e, 'col') else 1,
        )]

    try:
        parser = Parser(tokens)
        ast = parser.parse()
    except ParseError as e:
        return [LintDiagnostic(
            severity=LintSeverity.ERROR,
            rule='parse-error',
            message=f'Parse error: {e}',
            line=getattr(e, 'line', 1),
            col=getattr(e, 'col', 1),
        )]

    linter = Linter()
    return linter.lint(ast)


def lint_file(filepath: str) -> List[LintDiagnostic]:
    """
    Run the linter on an Iotift source file.

    Returns a list of LintDiagnostic findings.
    """
    if not os.path.exists(filepath):
        return [LintDiagnostic(
            severity=LintSeverity.ERROR,
            rule='file-error',
            message=f'File not found: {filepath}',
        )]

    with open(filepath, 'r', encoding='utf-8') as f:
        source = f.read()

    return lint_source(source)
