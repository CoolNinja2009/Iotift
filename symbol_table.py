"""
IOTIFT Symbol Table

Hierarchical symbol table with proper scoping.
Tracks variables, functions, types, pins, timers, and labels.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Set, Any
from enum import Enum as PyEnum


# Forward reference for Type
from type_system import Type, VOID


class SymbolKind(PyEnum):
    """What kind of entity a symbol represents."""
    VAR        = 'var'         # local/global variable
    CONST      = 'const'       # compile-time constant
    PARAM      = 'param'       # function parameter
    FN         = 'fn'          # user-defined function
    EXTERN_FN  = 'extern_fn'   # external C function
    STRUCT     = 'struct'      # struct type
    ENUM       = 'enum'        # enum type
    ENUM_VARIANT = 'enum_variant'
    PIN        = 'pin'         # hardware pin
    TIMER      = 'timer'       # every-block
    LABEL      = 'label'       # named timer label
    TYPE       = 'type'        # type alias
    PERIPHERAL = 'peripheral'  # i2c/spi/uart peripheral


@dataclass
class Symbol:
    """A single entry in the symbol table."""
    name: str
    kind: SymbolKind
    type: Optional[Type] = None
    line: int = 0
    # Metadata depending on kind
    is_mutable: bool = True
    is_global: bool = False
    is_volatile: bool = False
    is_isr: bool = False          # for ISR functions
    is_public: bool = False       # for module exports
    init_value: Any = None        # for const evaluation
    param_index: int = -1         # for function params
    pin_number: int = 0           # for pins
    timer_interval: int = 0       # for timers
    c_name: str = ""              # generated C name override
    owner_scope: Optional['Scope'] = None

    def __repr__(self) -> str:
        return f"Symbol({self.name}, {self.kind.value}, {self.type})"


@dataclass
class Scope:
    """A single scope level in the symbol table."""
    parent: Optional['Scope'] = None
    symbols: Dict[str, Symbol] = field(default_factory=dict)
    children: List['Scope'] = field(default_factory=list)
    name: str = ""                 # "global", "fn:blink", "block:12"
    depth: int = 0
    # For function scopes
    return_type: Optional[Type] = None
    in_loop: bool = False

    def define(self, sym: Symbol) -> Symbol:
        """Insert a symbol into this scope. Returns the symbol."""
        if sym.name in self.symbols:
            existing = self.symbols[sym.name]
            if existing.kind != sym.kind:
                raise NameError(
                    f"Line {sym.line}: '{sym.name}' already defined as "
                    f"{existing.kind.value} at line {existing.line}"
                )
        self.symbols[sym.name] = sym
        sym.owner_scope = self
        return sym

    def lookup(self, name: str, recursive: bool = True) -> Optional[Symbol]:
        """Find a symbol in this scope or ancestors."""
        if name in self.symbols:
            return self.symbols[name]
        if recursive and self.parent:
            return self.parent.lookup(name, recursive=True)
        return None

    def lookup_local(self, name: str) -> Optional[Symbol]:
        """Find a symbol in this scope only (no recursion)."""
        return self.symbols.get(name)

    def contains(self, name: str) -> bool:
        return name in self.symbols

    def all_symbols(self, recursive: bool = True) -> List[Symbol]:
        """Return all symbols in this scope and optionally children."""
        result = list(self.symbols.values())
        if recursive:
            for child in self.children:
                result.extend(child.all_symbols(recursive=True))
        return result

    def create_child(self, name: str = "") -> 'Scope':
        child = Scope(parent=self, name=name, depth=self.depth + 1,
                      in_loop=self.in_loop)
        self.children.append(child)
        return child


# Warning name constants
W_UNUSED_VARIABLE = 'unused-variable'
W_UNUSED_FUNCTION = 'unused-function'
W_USED_BEFORE_INIT = 'used-before-init'
W_IMPLICIT_NARROWING = 'implicit-narrowing'
W_EMPTY_BODY = 'empty-body'
W_VOID_LOOP_DEPRECATED = 'void-loop-deprecated'


class SymbolTable:
    """Top-level symbol table manager."""

    def __init__(self):
        self.global_scope = Scope(name='global', depth=0)
        self.current_scope = self.global_scope
        self._anon_counter = 0
        # Type registry
        self.types: Dict[str, Type] = {}        # user-defined type name → Type
        self.structs: Dict[str, Any] = {}       # struct name → StructType
        self.enums: Dict[str, Any] = {}         # enum name → EnumType
        # Pin registry
        self.pins: Dict[str, Symbol] = {}
        self.pwm_pins: Dict[str, Dict] = {}
        self.pwm_channel: int = 0
        # Import tracking
        self.imports: List[str] = []
        # Warnings collected during analysis
        self.warnings: List[str] = []
        self.errors: List[str] = []
        # Warning control
        self.werror: bool = False
        self.disabled_warnings: set = set()
        # Unused tracking (set in Pass 1, checked in Pass 4)
        self._unused_vars: Dict[str, Symbol] = {}
        self._unused_fns: Dict[str, Symbol] = {}
        # Current function context for return type checking
        self._current_fn_return_type: Optional[Type] = None
        self._in_loop: bool = False
        # ISR context tracking for safety checks (Phase 3.5 / 6)
        self._in_isr: bool = False

    def enter_scope(self, name: str = "", in_loop: bool = False) -> Scope:
        """Create and enter a new child scope."""
        if name == "":
            self._anon_counter += 1
            name = f"block:{self._anon_counter}"
        child = self.current_scope.create_child(name)
        child.in_loop = in_loop or self.current_scope.in_loop
        self.current_scope = child
        return child

    def leave_scope(self) -> Scope:
        """Leave current scope and return to parent."""
        if self.current_scope.parent:
            self.current_scope = self.current_scope.parent
        return self.current_scope

    def define(self, name: str, kind: SymbolKind, type: Optional[Type] = None,
               **kwargs) -> Symbol:
        """Define a symbol in the current scope."""
        sym = Symbol(name=name, kind=kind, type=type, **kwargs)
        try:
            return self.current_scope.define(sym)
        except NameError as e:
            self.error(sym.line, str(e))
            # Return a placeholder symbol so the caller can continue
            return sym

    def lookup(self, name: str) -> Optional[Symbol]:
        """Look up a symbol from current scope upward."""
        return self.current_scope.lookup(name)

    def add_type(self, name: str, typ: Type) -> None:
        """Register a user-defined type."""
        self.types[name] = typ

    def get_type(self, name: str) -> Optional[Type]:
        """Look up a user-defined type by name."""
        return self.types.get(name)

    def warn(self, line: int, message: str, wname: str = 'general') -> None:
        """Emit a warning. If werror, promotes to error. Skips disabled warnings."""
        if wname in self.disabled_warnings:
            return
        formatted = f"Line {line}: warning: {message} [{wname}]"
        if self.werror:
            self.errors.append(formatted.replace("warning:", "error:"))
        else:
            self.warnings.append(formatted)

    def error(self, line: int, message: str) -> None:
        self.errors.append(f"Line {line}: error: {message}")

    def has_errors(self) -> bool:
        return len(self.errors) > 0

    def in_global_scope(self) -> bool:
        return self.current_scope.parent is None

    def in_loop(self) -> bool:
        return self.current_scope.in_loop

    @property
    def in_isr(self) -> bool:
        """Whether we're currently analyzing inside an ISR function body."""
        return self._in_isr

    @in_isr.setter
    def in_isr(self, value: bool) -> None:
        self._in_isr = value

    def track_unused_var(self, name: str, sym: Symbol) -> None:
        """Register a variable as potentially unused (Pass 1)."""
        self._unused_vars[name] = sym

    def track_unused_fn(self, name: str, sym: Symbol) -> None:
        """Register a function as potentially unused (Pass 1)."""
        self._unused_fns[name] = sym

    def mark_used(self, name: str) -> None:
        """Mark a symbol as used (Pass 2), removing from unused tracking."""
        self._unused_vars.pop(name, None)
        self._unused_fns.pop(name, None)

    def get_unused_vars(self) -> List[Symbol]:
        """Return list of variables that were never referenced."""
        return list(self._unused_vars.values())

    def get_unused_fns(self) -> List[Symbol]:
        """Return list of functions that were never called."""
        return list(self._unused_fns.values())
