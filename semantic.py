"""
IOTIFT Semantic Analyzer — Milestone 1

Four-pass semantic analysis over the AST:
  Pass 1: Symbol Table Construction — register all declarations
  Pass 2: Name Resolution — resolve every identifier to a symbol
  Pass 3: Type Checking — validate types, infer let types, check assignments
  Pass 4: Scope Analysis — tag storage class, detect unused symbols

Annotates AST nodes with dynamic _resolved_* attributes.
Zero changes to AST node definitions — full backward compatibility.
"""

from __future__ import annotations

from typing import Optional, List, Any, Set, Dict, Tuple
from ast_nodes import *
from symbol_table import (
    SymbolTable, SymbolKind, Symbol,
    W_UNUSED_VARIABLE, W_UNUSED_FUNCTION, W_USED_BEFORE_INIT,
    W_IMPLICIT_NARROWING, W_EMPTY_BODY, W_VOID_LOOP_DEPRECATED,
    W_WIFI_NO_PASSWORD, W_WIFI_SHORT_PASSWORD, W_WIFI_OPEN_AP,
    W_WIFI_UNSUPPORTED_TARGET, W_WIFI_DUAL_STA, W_WIFI_BLOCKING_IN_HANDLER,
    W_WIFI_SCAN_OUTSIDE_HANDLER, W_WIFI_STATIC_IP_INCOMPLETE,
    W_WIFI_INVALID_CHANNEL, W_WIFI_DUPLICATE_SSID,
    W_WIFI_UNUSED, W_WIFI_NO_CONNECT_HANDLER, W_WIFI_STATIC_IP_NO_DNS,
)
from type_system import (
    Type, TypeKind, VOID, BOOL, INT, UINT, FLOAT, STR, CHAR,
    I8, I16, I32, I64, U8, U16, U32, U64, F32, F64,
    resolve_builtin_type, is_integer_type, is_numeric_type,
    common_type, can_assign, ArrayType, StructType, EnumType, FnType,
)


# ─────────────────────────────────────────
#  TYPE INFERENCE MAP (literal vtype → Type)
# ─────────────────────────────────────────

_LITERAL_TYPE_MAP: Dict[str, Type] = {
    'int':   INT,
    'float': FLOAT,
    'bool':  BOOL,
    'str':   STR,
    'char':  CHAR,
    'u8':    U8,   'u16': U16, 'u32': U32, 'u64': U64,
    'i8':    I8,   'i16': I16, 'i32': I32, 'i64': I64,
    'f32':   F32,  'f64':  F64,
}


# ─────────────────────────────────────────
#  HELPER
# ─────────────────────────────────────────

def _type_from_literal(lit: Literal) -> Optional[Type]:
    """Map a Literal node's vtype string to a Type object."""
    return _LITERAL_TYPE_MAP.get(lit.vtype)


# ─────────────────────────────────────────
#  SEMANTIC ANALYZER
# ─────────────────────────────────────────

class SemanticAnalyzer:
    """Four-pass semantic analysis over an Iotift AST."""

    def __init__(self, werror: bool = False,
                 disabled_warnings: Optional[Set[str]] = None) -> None:
        self.symbols = SymbolTable()
        self.symbols.werror = werror
        self.symbols.disabled_warnings = disabled_warnings or set()
        # Track initialized local variables per scope (for used-before-init)
        self._initialized: Set[str] = set()
        # Does the program have C-block injection?
        self._has_c_blocks: bool = False
        # Track which variables should be skipped in unused tracking
        # (pins, timers, builtins are always "used")
        self._builtin_names: Set[str] = {
            'millis', 'micros', 'sin', 'cos', 'tan', 'sqrt', 'abs',
            'pow', 'floor', 'ceil', 'round', 'log', 'exp',
            'min', 'max', 'clamp', 'map',
            'print', 'println',
            'HIGH', 'LOW',
        }
        # WiFi tracking (Milestone 8)
        self._wifi_decls: Dict[str, 'WifiDecl'] = {}
        self._wifi_state_enum_type: Optional[Type] = None
        # Is the current scope inside a scan_done handler?
        self._in_scan_done: bool = False

    # ─────────────────────────────────────────
    #  PUBLIC API
    # ─────────────────────────────────────────

    def analyze(self, program: Program) -> None:
        """Run all 4 semantic passes in sequence."""
        self._pass1_declare(program)
        self._pass2_resolve(program)
        self._pass3_check(program)
        self._pass4_scope(program)

    def has_errors(self) -> bool:
        return self.symbols.has_errors()

    def errors(self) -> List[str]:
        return self.symbols.errors

    def warnings(self) -> List[str]:
        return self.symbols.warnings

    # ─────────────────────────────────────────
    #  TYPE RESOLUTION HELPERS
    # ─────────────────────────────────────────

    def _resolve_type_name(self, type_name: Optional[str]) -> Optional[Type]:
        """Resolve a type name string to a Type object."""
        if type_name is None:
            return None
        t = resolve_builtin_type(type_name)
        if t is not None:
            return t
        return self.symbols.get_type(type_name)

    def _node_type(self, node: Any) -> Optional[Type]:
        """Read the _resolved_type from a node, if set."""
        return getattr(node, '_resolved_type', None)

    def _set_type(self, node: Any, t: Optional[Type]) -> None:
        node._resolved_type = t  # type: ignore[attr-defined]

    def _node_symbol(self, node: Any) -> Optional[Symbol]:
        """Read the _resolved_symbol from a node, if set."""
        return getattr(node, '_resolved_symbol', None)

    def _set_symbol(self, node: Any, sym: Symbol) -> None:
        node._resolved_symbol = sym  # type: ignore[attr-defined]

    # ═════════════════════════════════════════
    #  PASS 1 — SYMBOL TABLE CONSTRUCTION
    # ═════════════════════════════════════════

    def _pass1_declare(self, program: Program) -> None:
        """Walk the AST and register every declaration in the symbol table."""
        for node in program.body:
            self._p1_node(node)

    def _p1_node(self, node: Node) -> None:
        """Dispatch Pass 1 to the appropriate handler."""
        if isinstance(node, DeviceDecl):
            pass
        elif isinstance(node, ImportDecl):
            pass
        elif isinstance(node, CBlockNode):
            self._has_c_blocks = True
        elif isinstance(node, PinDecl):
            self._p1_pin(node)
        elif isinstance(node, VarDecl):
            self._p1_var(node)
        elif isinstance(node, ArrayDecl):
            self._p1_array(node)
        elif isinstance(node, StructDecl):
            self._p1_struct(node)
        elif isinstance(node, FnDecl):
            self._p1_fn(node)
        elif isinstance(node, ExternFnDecl):
            self._p1_extern_fn(node)
        elif isinstance(node, EnumDecl):
            self._p1_enum(node)
        elif isinstance(node, TypeAliasDecl):
            self._p1_type_alias(node)
        elif isinstance(node, EveryBlock):
            self._p1_every(node)
        elif isinstance(node, VoidLoop):
            self._p1_void_loop(node)
        elif isinstance(node, TickBlock):
            self._p1_tick(node)
        elif isinstance(node, LoopBlock):
            pass
        elif isinstance(node, OnEvent):
            self._p1_on_event(node)
        elif isinstance(node, OnThreshold):
            pass
        elif isinstance(node, PeripheralDecl):
            self._p1_peripheral(node)
        elif isinstance(node, AfterBlock):
            self._p1_after_block(node)
        elif isinstance(node, WifiDecl):
            self._p1_wifi(node)
        elif isinstance(node, SchedulerConfig):
            pass  # no symbol registration needed; read by codegen
        elif isinstance(node, (Assign, CompoundAssign, FnCall, MethodCall,
                               PrintStmt, PwmWrite, ExprStmt, PwmSetup)):
            pass  # top-level setup statements — skip
        elif isinstance(node, AssignAfter):
            pass

    def _p1_pin(self, node: PinDecl) -> None:
        sym = self.symbols.define(
            node.name, SymbolKind.PIN, type=U8, line=node.line,
            pin_number=node.number, is_mutable=False,
        )
        self.symbols.pins[node.name] = sym
        if node.direction == 'pwm':
            ch = self.symbols.pwm_channel
            self.symbols.pwm_channel += 1
            self.symbols.pwm_pins[node.name] = {
                'number':     node.number,
                'channel':    ch,
                'freq':       node.pwm_freq or 5000,
                'resolution': node.pwm_resolution or 8,
            }

    def _p1_var(self, node: VarDecl) -> None:
        # Resolve or infer type
        if node.vtype is not None:
            vtype = self._resolve_type_name(node.vtype)
        elif isinstance(node.init, Literal):
            vtype = _type_from_literal(node.init)
        else:
            vtype = None  # will be resolved in Pass 3

        if vtype is None and node.init is None and node.vtype is None:
            self.symbols.error(
                node.line,
                f"cannot infer type of '{node.name}'; "
                f"provide a type annotation or initializer",
            )
            return

        kind = SymbolKind.CONST if node.is_const else SymbolKind.VAR
        sym = self.symbols.define(
            node.name, kind, type=vtype, line=node.line,
            is_mutable=node.is_mutable and not node.is_const,
            is_volatile=node.is_volatile,
            is_global=self.symbols.in_global_scope(),
        )
        if node.init is not None:
            self._initialized.add(node.name)
        # Track for unused-variable warning (top-level only)
        if self.symbols.in_global_scope() and node.name not in self._builtin_names:
            self.symbols.track_unused_var(node.name, sym)

    def _p1_array(self, node: ArrayDecl) -> None:
        elem_type = self._resolve_type_name(node.elem_type or node.vtype)
        arr_type = ArrayType(elem_type or INT, node.size)
        sym = self.symbols.define(
            node.name, SymbolKind.VAR, type=arr_type, line=node.line,
            is_mutable=node.is_mutable, is_global=self.symbols.in_global_scope(),
        )
        if self.symbols.in_global_scope() and node.name not in self._builtin_names:
            self.symbols.track_unused_var(node.name, sym)

    def _p1_struct(self, node: StructDecl) -> None:
        field_types: List[Tuple[str, Type]] = []
        for f in node.fields:
            ft = self._resolve_type_name(f.vtype)
            if ft is None:
                self.symbols.error(
                    f.line,
                    f"unknown type '{f.vtype}' in struct field '{f.name}'",
                )
                ft = INT  # error recovery fallback
            field_types.append((f.name, ft))
        st = StructType(node.name, field_types)
        self.symbols.add_type(node.name, st)
        self.symbols.structs[node.name] = st
        self.symbols.define(
            node.name, SymbolKind.STRUCT, type=st, line=node.line,
        )

    def _p1_fn(self, node: FnDecl) -> None:
        ret_type = self._resolve_type_name(node.return_type) or VOID
        fn_type = FnType(
            param_types=[],  # filled after params registered
            return_type=ret_type,
        )
        sym = self.symbols.define(
            node.name, SymbolKind.FN, type=fn_type, line=node.line,
            is_isr=node.is_isr,
        )
        if node.name not in self._builtin_names:
            self.symbols.track_unused_fn(node.name, sym)

        # Enter function scope, register params
        self.symbols.enter_scope(f"fn:{node.name}")
        self.symbols._current_fn_return_type = ret_type
        node._pass1_scope = self.symbols.current_scope  # type: ignore[attr-defined]

        param_types: List[Type] = []
        for i, p in enumerate(node.params):
            pt = self._resolve_type_name(p.vtype) or INT
            param_types.append(pt)
            self.symbols.define(
                p.name, SymbolKind.PARAM, type=pt, line=p.line,
                param_index=i,
            )
            self._initialized.add(p.name)

        # Update the function type with param types
        fn_type.param_types = param_types

        # Walk body for inner declarations
        for stmt in node.body:
            self._p1_stmt(stmt)

        self.symbols.leave_scope()
        self.symbols._current_fn_return_type = None

    def _p1_extern_fn(self, node: ExternFnDecl) -> None:
        ret_type = self._resolve_type_name(node.return_type) or VOID
        param_types: List[Type] = []
        for p in node.params:
            pt = self._resolve_type_name(p.vtype) or INT
            param_types.append(pt)
        fn_type = FnType(param_types=param_types, return_type=ret_type)
        self.symbols.define(
            node.name, SymbolKind.EXTERN_FN, type=fn_type, line=node.line,
        )

    def _p1_enum(self, node: EnumDecl) -> None:
        bt = self._resolve_type_name(node.backing_type or 'int') or INT
        variants: List[Tuple[str, int]] = []
        next_val = 0
        for vname, val in node.variants:
            disc = val if val is not None else next_val
            variants.append((vname, disc))
            next_val = disc + 1
            # Register variant
            self.symbols.define(
                vname, SymbolKind.ENUM_VARIANT, type=bt, line=node.line,
                init_value=disc,
            )
        et = EnumType(node.name, variants, backing_type=bt)
        self.symbols.add_type(node.name, et)
        self.symbols.enums[node.name] = et
        self.symbols.define(
            node.name, SymbolKind.ENUM, type=et, line=node.line,
        )

    def _p1_type_alias(self, node: TypeAliasDecl) -> None:
        aliased = self._resolve_type_name(node.aliased_type)
        if aliased is None:
            self.symbols.error(
                node.line,
                f"unknown type '{node.aliased_type}' in type alias",
            )
            return
        self.symbols.add_type(node.name, aliased)
        self.symbols.define(
            node.name, SymbolKind.TYPE, type=aliased, line=node.line,
        )

    def _p1_every(self, node: EveryBlock) -> None:
        if node.label:
            sym = self.symbols.define(
                node.label, SymbolKind.TIMER, line=node.line,
                timer_interval=node.interval,
            )
            # Named timers are used by the runtime
            self.symbols.mark_used(node.label)
        # Walk body for inner declarations
        self.symbols.enter_scope(f"every:{node.label or 'anon'}", in_loop=True)
        node._pass1_scope = self.symbols.current_scope  # type: ignore[attr-defined]
        for stmt in node.body:
            self._p1_stmt(stmt)
        self.symbols.leave_scope()

    def _p1_void_loop(self, node: VoidLoop) -> None:
        self.symbols.warn(
            node.line,
            "'void loop()' is deprecated; use 'tick { ... }' instead",
            W_VOID_LOOP_DEPRECATED,
        )
        self.symbols.enter_scope("fn:user_loop")
        node._pass1_scope = self.symbols.current_scope  # type: ignore[attr-defined]
        for stmt in node.body:
            self._p1_stmt(stmt)
        self.symbols.leave_scope()

    def _p1_tick(self, node: TickBlock) -> None:
        self.symbols.enter_scope("fn:_iotift_tick")
        node._pass1_scope = self.symbols.current_scope  # type: ignore[attr-defined]
        for stmt in node.body:
            self._p1_stmt(stmt)
        self.symbols.leave_scope()

    def _p1_on_event(self, node: OnEvent) -> None:
        self.symbols.enter_scope(f"on:{node.target}.{node.event}")
        node._pass1_scope = self.symbols.current_scope  # type: ignore[attr-defined]
        self.symbols._in_loop = True
        # Track if we're inside a scan_done handler
        old_scan = self._in_scan_done
        if node.event == 'scan_done':
            self._in_scan_done = True
        for stmt in node.body:
            self._p1_stmt(stmt)
        self._in_scan_done = old_scan
        self.symbols.leave_scope()

    def _p1_after_block(self, node: AfterBlock) -> None:
        """after 5s { ... } — one-shot timer block."""
        self.symbols.enter_scope(f"after:{node.interval}ms", in_loop=True)
        node._pass1_scope = self.symbols.current_scope  # type: ignore[attr-defined]
        for stmt in node.body:
            self._p1_stmt(stmt)
        self.symbols.leave_scope()

    def _p1_peripheral(self, node: PeripheralDecl) -> None:
        """Register a peripheral declaration as a symbol."""
        self.symbols.define(
            node.name, SymbolKind.PERIPHERAL, line=node.line,
            is_mutable=False, is_global=True,
        )

    def _p1_wifi(self, node: WifiDecl) -> None:
        """Register a wifi declaration and validate config."""
        # Store for later passes
        self._wifi_decls[node.name] = node
        self.symbols.wifi_decls[node.name] = node

        sym = self.symbols.define(
            node.name, SymbolKind.WIFI, line=node.line,
            is_mutable=False, is_global=True,
        )

        # Generate WifiState enum once per compilation unit
        if not self.symbols._wifi_state_enum_generated:
            self.symbols._wifi_state_enum_generated = True
            variants = [
                ('WifiState_Idle', 0),
                ('WifiState_Connecting', 1),
                ('WifiState_Connected', 2),
                ('WifiState_Disconnected', 3),
            ]
            et = EnumType('WifiState', variants, backing_type=INT)
            self.symbols.add_type('WifiState', et)
            self.symbols.enums['WifiState'] = et
            self.symbols.define(
                'WifiState', SymbolKind.ENUM, type=et, line=node.line,
            )
            for vname, val in variants:
                self.symbols.define(
                    vname, SymbolKind.ENUM_VARIANT, type=et, line=node.line,
                    init_value=val,
                )

        # Validate mode
        mode = node.mode
        if mode not in ('sta', 'ap'):
            self.symbols.error(node.line, f"invalid wifi mode '{mode}'; expected 'sta' or 'ap'")

        cfg = node.config

        # STA requires ssid
        if mode == 'sta' and 'ssid' not in cfg:
            self.symbols.error(node.line, "STA mode requires 'ssid' config key")

        # AP requires ssid
        if mode == 'ap' and 'ssid' not in cfg:
            self.symbols.error(node.line, "AP mode requires 'ssid' config key")

        # Password checks
        if mode == 'sta' and 'password' not in cfg:
            self.symbols.warn(
                node.line,
                f"STA wifi '{node.name}' declared without password (open network)",
                W_WIFI_NO_PASSWORD,
            )
        if 'password' in cfg:
            pw = cfg['password']
            if isinstance(pw, str) and len(pw) < 8:
                self.symbols.warn(
                    node.line,
                    f"WiFi password is less than 8 characters (WPA2 minimum)",
                    W_WIFI_SHORT_PASSWORD,
                )
        if mode == 'ap' and 'password' not in cfg:
            self.symbols.warn(
                node.line,
                f"AP wifi '{node.name}' declared without password (open network)",
                W_WIFI_OPEN_AP,
            )

        # Static IP validation
        if 'static_ip' in cfg:
            if 'gateway' not in cfg or 'subnet' not in cfg:
                self.symbols.error(
                    node.line,
                    f"'static_ip' requires 'gateway' and 'subnet'",
                )
            if 'dns' not in cfg:
                self.symbols.warn(
                    node.line,
                    f"static IP without DNS server specified",
                    W_WIFI_STATIC_IP_NO_DNS,
                )

        # Channel validation
        if 'channel' in cfg:
            ch = cfg['channel']
            if isinstance(ch, int) and (ch < 1 or ch > 13):
                self.symbols.warn(
                    node.line,
                    f"WiFi channel {ch} is outside valid range 1-13",
                    W_WIFI_INVALID_CHANNEL,
                )

        # Multi-WiFi validation: check for dual STA
        for other_name, other_decl in self._wifi_decls.items():
            if other_name != node.name:
                if node.mode == 'sta' and other_decl.mode == 'sta':
                    self.symbols.error(
                        node.line,
                        f"two STA wifi declarations ('{node.name}' and '{other_name}') "
                        f"— only one STA interface supported",
                    )
                if node.mode == 'ap' and other_decl.mode == 'ap':
                    self.symbols.error(
                        node.line,
                        f"two AP wifi declarations ('{node.name}' and '{other_name}') "
                        f"— only one AP interface supported",
                    )
                # Check for duplicate SSID on AP
                if node.mode == 'ap' and other_decl.mode == 'ap':
                    if cfg.get('ssid') == other_decl.config.get('ssid'):
                        self.symbols.warn(
                            node.line,
                            f"two AP declarations with same SSID '{cfg['ssid']}'",
                            W_WIFI_DUPLICATE_SSID,
                        )

    def _p1_stmt(self, node: Node) -> None:
        """Walk a statement node for inner declarations (Pass 1)."""
        if isinstance(node, VarDecl):
            # Local variable inside a function/block
            vtype = self._resolve_type_name(node.vtype) if node.vtype else None
            if vtype is None and isinstance(node.init, Literal):
                vtype = _type_from_literal(node.init)
            if vtype is None and node.init is None and node.vtype is None:
                self.symbols.error(
                    node.line,
                    f"cannot infer type of '{node.name}'; "
                    f"provide a type annotation or initializer",
                )
                return
            sym = self.symbols.define(
                node.name, SymbolKind.VAR, type=vtype, line=node.line,
                is_mutable=node.is_mutable and not node.is_const,
                is_global=False,
            )
            if node.init is not None:
                self._initialized.add(node.name)
        elif isinstance(node, IfStmt):
            self.symbols.enter_scope()
            node._pass1_scope = self.symbols.current_scope  # type: ignore[attr-defined]
            for s in node.then_body:
                self._p1_stmt(s)
            for _, elif_body in node.elif_clauses:
                self.symbols.enter_scope()
                for s in elif_body:
                    self._p1_stmt(s)
                self.symbols.leave_scope()
            self.symbols.leave_scope()
            if node.else_body:
                self.symbols.enter_scope()
                for s in node.else_body:
                    self._p1_stmt(s)
                self.symbols.leave_scope()
        elif isinstance(node, (WhileStmt, LoopBlock)):
            self.symbols.enter_scope(in_loop=True)
            node._pass1_scope = self.symbols.current_scope  # type: ignore[attr-defined]
            for s in node.body:
                self._p1_stmt(s)
            self.symbols.leave_scope()
        elif isinstance(node, ForStmt):
            self.symbols.enter_scope(in_loop=True)
            node._pass1_scope = self.symbols.current_scope  # type: ignore[attr-defined]
            if node.init:
                self._p1_stmt(node.init)
            for s in node.body:
                self._p1_stmt(s)
            self.symbols.leave_scope()
        elif isinstance(node, DeferStmt):
            for s in node.body:
                self._p1_stmt(s)
        elif isinstance(node, OnEvent):
            self._p1_on_event(node)
        elif isinstance(node, OnThreshold):
            self.symbols.enter_scope(in_loop=True)
            for s in node.body:
                self._p1_stmt(s)
            self.symbols.leave_scope()
        elif isinstance(node, EveryBlock):
            self._p1_every(node)
        elif isinstance(node, AfterBlock):
            self._p1_after_block(node)
        # Other statement types don't introduce declarations

    # ═════════════════════════════════════════
    #  PASS 2 — NAME RESOLUTION
    # ═════════════════════════════════════════

    def _pass2_resolve(self, program: Program) -> None:
        """Walk the AST and resolve every identifier to a Symbol."""
        for node in program.body:
            self._p2_node(node)

    def _p2_node(self, node: Node) -> None:
        """Dispatch Pass 2 to the appropriate handler."""
        if isinstance(node, Program):
            for child in node.body:
                self._p2_node(child)

        # Declarations with bodies to walk
        elif isinstance(node, FnDecl):
            self._p2_fn_decl(node)
        elif isinstance(node, VoidLoop):
            self._p2_enter_scope_from_node(node, node.body)
        elif isinstance(node, TickBlock):
            self._p2_enter_scope_from_node(node, node.body)
        elif isinstance(node, OnEvent):
            self._p2_enter_scope_from_node(node, node.body)
        elif isinstance(node, OnThreshold):
            self._p2_enter_scope_from_node(node, node.body)
        elif isinstance(node, EveryBlock):
            self._p2_enter_scope_from_node(node, node.body)
        elif isinstance(node, LoopBlock):
            self._p2_enter_scope_from_node(node, node.body)
        elif isinstance(node, AfterBlock):
            self._p2_enter_scope_from_node(node, node.body)

        # Statements
        elif isinstance(node, VarDecl):
            self._p2_var_decl(node)
        elif isinstance(node, Assign):
            self._p2_assign(node)
        elif isinstance(node, CompoundAssign):
            self._p2_compound_assign(node)
        elif isinstance(node, AssignAfter):
            self._p2_assign_after(node)
        elif isinstance(node, IfStmt):
            self._p2_if(node)
        elif isinstance(node, WhileStmt):
            self._p2_while(node)
        elif isinstance(node, ForStmt):
            self._p2_for(node)
        elif isinstance(node, ReturnStmt):
            self._p2_expr(node.value, allow_none=True)
        elif isinstance(node, PrintStmt):
            self._p2_expr(node.value)
        elif isinstance(node, StopStmt):
            self._p2_stop(node)
        elif isinstance(node, DeferStmt):
            self._p2_walk_body(node.body)
        elif isinstance(node, ExprStmt):
            self._p2_expr(node.expr)

        # Expressions as top-level setup stmts
        elif isinstance(node, PwmSetup):
            self._p2_pwm_setup(node)
        elif isinstance(node, PwmWrite):
            self._p2_pwm_write(node)
        elif isinstance(node, FnCall):
            self._p2_expr(node)
        elif isinstance(node, MethodCall):
            self._p2_expr(node)

        # WiFi — skip (handled in Pass 1)
        elif isinstance(node, WifiDecl):
            pass

    def _p2_fn_decl(self, node: FnDecl) -> None:
        self._p2_enter_scope_from_node(node, node.body)

    def _p2_enter_block(self, scope_name: str, body: List[Node],
                        in_loop: bool = False) -> None:
        """Enter a scope, walk a body, and leave the scope."""
        self.symbols.enter_scope(scope_name, in_loop=in_loop)
        self._p2_walk_body(body)
        self.symbols.leave_scope()

    def _p2_enter_scope_from_node(self, node: Node, body: List[Node]) -> None:
        """If Pass 1 stored a scope on this node, re-enter it for Pass 2.
        Otherwise, create a temporary scope."""
        saved_scope = getattr(node, '_pass1_scope', None)
        if saved_scope is not None:
            old_scope = self.symbols.current_scope
            self.symbols.current_scope = saved_scope
            self._p2_walk_body(body)
            self.symbols.current_scope = old_scope
        else:
            self._p2_walk_body(body)

    def _p2_walk_body(self, body: List[Node]) -> None:
        for stmt in body:
            self._p2_node(stmt)

    def _p2_var_decl(self, node: VarDecl) -> None:
        if node.init is not None:
            self._p2_expr(node.init)

    def _p2_assign(self, node: Assign) -> None:
        self._p2_expr(node.value)
        # Resolve target if it's a simple name
        if isinstance(node.target, str):
            sym = self.symbols.lookup(node.target)
            if sym is None:
                self.symbols.error(
                    node.line,
                    f"undefined variable '{node.target}'",
                )
            else:
                self._set_symbol(node, sym)
                self.symbols.mark_used(node.target)
        elif isinstance(node.target, (ArrayAccess, MemberAccess)):
            self._p2_expr(node.target)

    def _p2_compound_assign(self, node: CompoundAssign) -> None:
        self._p2_expr(node.value)
        if isinstance(node.target, str):
            sym = self.symbols.lookup(node.target)
            if sym is None:
                self.symbols.error(
                    node.line,
                    f"undefined variable '{node.target}'",
                )
            else:
                self._set_symbol(node, sym)
                self.symbols.mark_used(node.target)

    def _p2_assign_after(self, node: AssignAfter) -> None:
        self._p2_expr(node.value)
        sym = self.symbols.lookup(node.target)
        if sym is None:
            self.symbols.error(
                node.line,
                f"undefined variable '{node.target}' in deferred assignment",
            )
        else:
            self._set_symbol(node, sym)
            self.symbols.mark_used(node.target)

    def _p2_if(self, node: IfStmt) -> None:
        self._p2_expr(node.condition)
        self._p2_enter_scope_from_node(node, node.then_body)
        for cond, body in node.elif_clauses:
            self._p2_expr(cond)
            self._p2_walk_body(body)
        if node.else_body:
            self._p2_walk_body(node.else_body)

    def _p2_while(self, node: WhileStmt) -> None:
        self._p2_expr(node.condition)
        self._p2_enter_scope_from_node(node, node.body)

    def _p2_for(self, node: ForStmt) -> None:
        # Enter the for-loop's scope (created in Pass 1)
        saved_scope = getattr(node, '_pass1_scope', None)
        old = self.symbols.current_scope
        if saved_scope is not None:
            self.symbols.current_scope = saved_scope
        if node.init:
            self._p2_node(node.init)
        if node.condition:
            self._p2_expr(node.condition)
        if node.step:
            self._p2_node(node.step)
        self._p2_walk_body(node.body)
        self.symbols.current_scope = old

    def _p2_stop(self, node: StopStmt) -> None:
        sym = self.symbols.lookup(node.label)
        if sym is None:
            self.symbols.error(
                node.line,
                f"undefined timer label '{node.label}' in stop",
            )
        elif sym.kind not in (SymbolKind.TIMER, SymbolKind.LABEL):
            self.symbols.error(
                node.line,
                f"'{node.label}' is not a timer (cannot stop)",
            )
        else:
            self._set_symbol(node, sym)

    def _p2_pwm_setup(self, node: PwmSetup) -> None:
        sym = self.symbols.lookup(node.pin)
        if sym is None or sym.kind != SymbolKind.PIN:
            self.symbols.error(
                node.line,
                f"undefined pin '{node.pin}' in PWM setup",
            )
        else:
            self._set_symbol(node, sym)
            self.symbols.mark_used(node.pin)
        self._p2_expr(node.freq)
        self._p2_expr(node.resolution)

    def _p2_pwm_write(self, node: PwmWrite) -> None:
        sym = self.symbols.lookup(node.pin)
        if sym is None or sym.kind != SymbolKind.PIN:
            self.symbols.error(
                node.line,
                f"undefined pin '{node.pin}' in PWM write",
            )
        else:
            self._set_symbol(node, sym)
            self.symbols.mark_used(node.pin)
        self._p2_expr(node.value)

    def _p2_expr(self, node: Any, allow_none: bool = False) -> None:
        """Walk an expression node for name resolution."""
        if node is None:
            if not allow_none:
                return
            return

        if isinstance(node, Identifier):
            sym = self.symbols.lookup(node.name)
            if sym is None:
                if node.name not in self._builtin_names:
                    self.symbols.error(
                        node.line,
                        f"undefined name '{node.name}'",
                    )
            else:
                self._set_symbol(node, sym)
                self.symbols.mark_used(node.name)

        elif isinstance(node, Literal):
            pass  # literals don't need resolution

        elif isinstance(node, BinOp):
            self._p2_expr(node.left)
            self._p2_expr(node.right)

        elif isinstance(node, UnaryOp):
            self._p2_expr(node.operand)

        elif isinstance(node, MemberAccess):
            if isinstance(node.obj, str):
                sym = self.symbols.lookup(node.obj)
                if sym is None:
                    self.symbols.error(
                        node.line,
                        f"undefined name '{node.obj}'",
                    )
                else:
                    self._set_symbol(node, sym)
                    self.symbols.mark_used(node.obj)
                    # Validate timer members: only 'running' is valid
                    if sym.kind == SymbolKind.TIMER:
                        if node.member != 'running':
                            self.symbols.error(
                                node.line,
                                f"timer '{node.obj}' has no member '{node.member}' "
                                f"(did you mean 'running'?)",
                            )
                    elif sym.kind == SymbolKind.PERIPHERAL:
                        # Member access on peripherals is validated in Pass 3
                        pass
                    elif sym.kind == SymbolKind.WIFI:
                        # Validate WiFi property names
                        _WIFI_PROPS = {
                            'state', 'connected', 'ip', 'rssi', 'channel',
                            'mac', 'clients', 'ssid',
                        }
                        if node.member not in _WIFI_PROPS:
                            self.symbols.error(
                                node.line,
                                f"wifi '{node.obj}' has no property '{node.member}' "
                                f"(valid: {', '.join(sorted(_WIFI_PROPS))})",
                            )
            else:
                self._p2_expr(node.obj)

        elif isinstance(node, ArrayAccess):
            sym = self.symbols.lookup(node.name)
            if sym is None:
                self.symbols.error(
                    node.line,
                    f"undefined array '{node.name}'",
                )
            else:
                self._set_symbol(node, sym)
                self.symbols.mark_used(node.name)
            self._p2_expr(node.index)

        elif isinstance(node, FnCall):
            sym = self.symbols.lookup(node.name)
            if sym is None:
                if node.name not in self._builtin_names:
                    self.symbols.error(
                        node.line,
                        f"undefined function '{node.name}'",
                    )
            elif sym.kind not in (SymbolKind.FN, SymbolKind.EXTERN_FN):
                self.symbols.error(
                    node.line,
                    f"'{node.name}' is not callable (is {sym.kind.value})",
                )
            else:
                self._set_symbol(node, sym)
                self.symbols.mark_used(node.name)
            for arg in node.args:
                self._p2_expr(arg)

        elif isinstance(node, MethodCall):
            self._p2_expr(node.obj)
            # Validate timer methods: .stop() and .start()
            obj_sym = self._node_symbol(node.obj) if hasattr(node.obj, 'name') else None
            if obj_sym is None and isinstance(node.obj, str):
                obj_sym = self.symbols.lookup(node.obj)
            if obj_sym is not None and obj_sym.kind == SymbolKind.TIMER:
                if node.method not in ('stop', 'start'):
                    self.symbols.error(
                        node.line,
                        f"timer '{obj_sym.name}' has no method '{node.method}' "
                        f"(valid: stop, start)",
                    )
            elif obj_sym is not None and obj_sym.kind == SymbolKind.WIFI:
                _WIFI_METHODS = {'scan', 'disconnect'}
                if node.method not in _WIFI_METHODS:
                    self.symbols.error(
                        node.line,
                        f"wifi '{obj_sym.name}' has no method '{node.method}' "
                        f"(valid: {', '.join(sorted(_WIFI_METHODS))})",
                    )
            for arg in node.args:
                self._p2_expr(arg)

        elif isinstance(node, MathExpr):
            for arg in node.args:
                self._p2_expr(arg)

        elif isinstance(node, MillisExpr):
            pass  # no args, no resolution needed

        elif isinstance(node, CastExpr):
            self._p2_expr(node.expr)

        elif isinstance(node, SizeOfExpr):
            # sizeof target could be a type name (str) or an expression
            if not isinstance(node.target, str):
                self._p2_expr(node.target)

        elif isinstance(node, (PwmSetup, PwmWrite)):
            pass  # handled at stmt level

        elif isinstance(node, ExprStmt):
            self._p2_expr(node.expr)

    # ═════════════════════════════════════════
    #  PASS 3 — TYPE CHECKING
    # ═════════════════════════════════════════

    def _pass3_check(self, program: Program) -> None:
        """Walk the AST and validate types, infer let types, check assignments."""
        for node in program.body:
            self._p3_node(node)

    def _p3_node(self, node: Node) -> None:
        """Dispatch Pass 3 to the appropriate handler."""
        if isinstance(node, Program):
            for child in node.body:
                self._p3_node(child)

        # Declarations
        elif isinstance(node, VarDecl):
            self._p3_var_decl(node)
        elif isinstance(node, FnDecl):
            self._p3_fn_decl(node)
        elif isinstance(node, VoidLoop):
            self._p3_walk_body(node.body)
        elif isinstance(node, TickBlock):
            self._p3_walk_body(node.body)
        elif isinstance(node, OnEvent):
            self._p3_on_event(node)
        elif isinstance(node, OnThreshold):
            self._p3_on_threshold(node)
        elif isinstance(node, EveryBlock):
            self._p3_every(node)
        elif isinstance(node, LoopBlock):
            self._p3_loop(node)
        elif isinstance(node, AfterBlock):
            self._p3_after(node)

        # Statements
        elif isinstance(node, Assign):
            self._p3_assign(node)
        elif isinstance(node, CompoundAssign):
            self._p3_compound_assign(node)
        elif isinstance(node, AssignAfter):
            self._p3_assign_after(node)
        elif isinstance(node, IfStmt):
            self._p3_if(node)
        elif isinstance(node, WhileStmt):
            self._p3_while(node)
        elif isinstance(node, ForStmt):
            self._p3_for(node)
        elif isinstance(node, ReturnStmt):
            self._p3_return(node)
        elif isinstance(node, BreakStmt):
            self._p3_break(node)
        elif isinstance(node, ContinueStmt):
            self._p3_continue(node)
        elif isinstance(node, PrintStmt):
            self._p3_print(node)
        elif isinstance(node, StopStmt):
            pass  # resolved in Pass 2
        elif isinstance(node, DeferStmt):
            self._p3_walk_body(node.body)
        elif isinstance(node, ExprStmt):
            self._p3_compute_expr(node.expr)
        elif isinstance(node, PwmSetup):
            self._p3_pwm_setup(node)
        elif isinstance(node, PwmWrite):
            self._p3_pwm_write(node)
        elif isinstance(node, FnCall):
            self._p3_compute_expr(node)
        elif isinstance(node, MethodCall):
            self._p3_compute_expr(node)

        # Skip top-level declarations that don't need type checking
        elif isinstance(node, (DeviceDecl, ImportDecl, CBlockNode, PinDecl,
                               ArrayDecl, StructDecl, EnumDecl, TypeAliasDecl,
                               ExternFnDecl, PeripheralDecl, WifiDecl)):
            pass

    def _p3_walk_body(self, body: List[Node]) -> None:
        for stmt in body:
            self._p3_node(stmt)

    # ── declarations ──

    def _p3_var_decl(self, node: VarDecl) -> None:
        # Compute init type
        init_type = None
        if node.init is not None:
            init_type = self._p3_compute_expr(node.init)

        # Determine declared type
        if node.vtype is not None:
            declared_type = self._resolve_type_name(node.vtype)
        elif isinstance(node.init, Literal):
            declared_type = _type_from_literal(node.init)
        elif init_type is not None:
            declared_type = init_type
        else:
            declared_type = None

        # Update the symbol with the resolved type
        sym = self.symbols.lookup(node.name)
        if sym and declared_type is not None:
            sym.type = declared_type

        self._set_type(node, declared_type)

        # Check assignment compatibility
        if init_type is not None and declared_type is not None:
            if not can_assign(declared_type, init_type):
                if is_numeric_type(declared_type) and is_numeric_type(init_type):
                    self.symbols.warn(
                        node.line,
                        f"implicit narrowing conversion: "
                        f"'{init_type.name}' to '{declared_type.name}'",
                        W_IMPLICIT_NARROWING,
                    )
                else:
                    self.symbols.error(
                        node.line,
                        f"cannot assign '{init_type.name}' to "
                        f"variable of type '{declared_type.name}'",
                    )

    def _p3_fn_decl(self, node: FnDecl) -> None:
        saved_scope = getattr(node, '_pass1_scope', None)
        if saved_scope is not None:
            old_scope = self.symbols.current_scope
            self.symbols.current_scope = saved_scope
        old_ret = self.symbols._current_fn_return_type
        ret_type = self._resolve_type_name(node.return_type) or VOID
        self.symbols._current_fn_return_type = ret_type

        # Enter ISR context for safety checks
        old_isr = self.symbols.in_isr
        if node.is_isr:
            self.symbols.in_isr = True

        for stmt in node.body:
            self._p3_node(stmt)

        # Restore ISR context
        self.symbols.in_isr = old_isr

        self.symbols._current_fn_return_type = old_ret
        if saved_scope is not None:
            self.symbols.current_scope = old_scope

    # ── events / timers ──

    def _p3_on_event(self, node: OnEvent) -> None:
        if not node.body:
            self.symbols.warn(
                node.line,
                f"empty event handler 'on {node.target}.{node.event}'",
                W_EMPTY_BODY,
            )

        # WiFi event mode-specific validation
        target_sym = self.symbols.lookup(node.target)
        if target_sym and target_sym.kind == SymbolKind.WIFI:
            wifi_decl = self._wifi_decls.get(node.target)
            if wifi_decl:
                mode = wifi_decl.mode
                sta_events = {'connect', 'disconnect', 'got_ip', 'scan_done'}
                ap_events = {'client_join', 'client_leave'}

                if node.event in sta_events and mode == 'ap':
                    self.symbols.error(
                        node.line,
                        f"event '{node.event}' is not valid for AP mode wifi '{node.target}' "
                        f"(valid: client_join, client_leave)",
                    )
                if node.event in ap_events and mode == 'sta':
                    self.symbols.error(
                        node.line,
                        f"event '{node.event}' is not valid for STA mode wifi '{node.target}' "
                        f"(valid: connect, disconnect, got_ip, scan_done)",
                    )

        # Track scan_done context
        old_scan = self._in_scan_done
        if node.event == 'scan_done':
            self._in_scan_done = True

        self._p3_walk_body(node.body)

        self._in_scan_done = old_scan

    def _p3_on_threshold(self, node: OnThreshold) -> None:
        if not node.body:
            self.symbols.warn(
                node.line,
                f"empty threshold handler 'on {node.pin} {node.op} ...'",
                W_EMPTY_BODY,
            )
        self._p3_walk_body(node.body)

    def _p3_every(self, node: EveryBlock) -> None:
        if not node.body:
            self.symbols.warn(
                node.line,
                f"empty every-block (interval={node.interval}ms)",
                W_EMPTY_BODY,
            )
        self._p3_walk_body(node.body)

    def _p3_after(self, node: AfterBlock) -> None:
        if not node.body:
            self.symbols.warn(
                node.line,
                f"empty after-block (interval={node.interval}ms)",
                W_EMPTY_BODY,
            )
        self._p3_walk_body(node.body)

    def _p3_loop(self, node: LoopBlock) -> None:
        self._p3_walk_body(node.body)

    # ── statements ──

    def _p3_assign(self, node: Assign) -> None:
        val_type = self._p3_compute_expr(node.value)
        target_sym = self._node_symbol(node)

        # ISR safety: check volatile on assignment target
        if self.symbols.in_isr and target_sym:
            if not target_sym.is_volatile and \
               target_sym.kind in (SymbolKind.VAR, SymbolKind.PARAM):
                self.symbols.error(
                    node.line,
                    f"ISR function writes to non-volatile variable "
                    f"'{target_sym.name}' — declare it 'volatile {target_sym.type.name if target_sym.type else 'int'} {target_sym.name}'",
                )

        # If target is a simple name, check type compatibility
        if target_sym and target_sym.type and val_type:
            self._check_assignment(node.line, target_sym, val_type)

        # Check mutability
        if target_sym and target_sym.kind == SymbolKind.CONST:
            self.symbols.error(
                node.line,
                f"cannot assign to const '{target_sym.name}'",
            )
        elif target_sym and not target_sym.is_mutable and \
                target_sym.kind == SymbolKind.VAR:
            self.symbols.error(
                node.line,
                f"cannot assign to immutable variable '{target_sym.name}' "
                f"(declared with 'let')",
            )
        elif target_sym and target_sym.kind == SymbolKind.PIN:
            # Pin assignments are always allowed (they use digitalWrite)
            pass

        # Mark as initialized
        if isinstance(node.target, str):
            self._initialized.add(node.target)

    def _p3_compound_assign(self, node: CompoundAssign) -> None:
        val_type = self._p3_compute_expr(node.value)
        target_sym = self._node_symbol(node)

        # ISR safety: check volatile on compound-assign target
        if self.symbols.in_isr and target_sym:
            if not target_sym.is_volatile and \
               target_sym.kind in (SymbolKind.VAR, SymbolKind.PARAM):
                self.symbols.error(
                    node.line,
                    f"ISR function writes to non-volatile variable "
                    f"'{target_sym.name}' — declare it 'volatile "
                    f"{target_sym.type.name if target_sym.type else 'int'} "
                    f"{target_sym.name}'",
                )

        if target_sym and not target_sym.is_mutable and \
                target_sym.kind != SymbolKind.PIN:
            self.symbols.error(
                node.line,
                f"cannot modify immutable variable '{target_sym.name}'",
            )

        if target_sym and target_sym.type and val_type:
            # Compound ops require numeric operands
            if not is_numeric_type(target_sym.type):
                self.symbols.error(
                    node.line,
                    f"compound assignment requires numeric type, "
                    f"got '{target_sym.type.name}'",
                )

    def _p3_assign_after(self, node: AssignAfter) -> None:
        val_type = self._p3_compute_expr(node.value)
        target_sym = self._node_symbol(node)

        if target_sym and target_sym.type and val_type:
            self._check_assignment(node.line, target_sym, val_type)

    def _p3_if(self, node: IfStmt) -> None:
        cond_type = self._p3_compute_expr(node.condition)
        if cond_type and cond_type.kind != TypeKind.BOOL:
            self.symbols.warn(
                node.line,
                f"if condition is '{cond_type.name}' (not bool); "
                f"will be implicitly converted",
                W_IMPLICIT_NARROWING,
            )
        self._p3_walk_body(node.then_body)
        for cond, body in node.elif_clauses:
            self._p3_compute_expr(cond)
            self._p3_walk_body(body)
        if node.else_body:
            self._p3_walk_body(node.else_body)

    def _p3_while(self, node: WhileStmt) -> None:
        cond_type = self._p3_compute_expr(node.condition)
        if cond_type and cond_type.kind != TypeKind.BOOL:
            self.symbols.warn(
                node.line,
                f"while condition is '{cond_type.name}' (not bool)",
                W_IMPLICIT_NARROWING,
            )
        self._p3_walk_body(node.body)

    def _p3_for(self, node: ForStmt) -> None:
        if node.init:
            self._p3_node(node.init)
        if node.condition:
            cond_type = self._p3_compute_expr(node.condition)
            if cond_type and cond_type.kind != TypeKind.BOOL:
                self.symbols.warn(
                    node.line,
                    f"for condition is '{cond_type.name}' (not bool)",
                    W_IMPLICIT_NARROWING,
                )
        if node.step:
            self._p3_node(node.step)
        self._p3_walk_body(node.body)

    def _p3_return(self, node: ReturnStmt) -> None:
        ret_type = self.symbols._current_fn_return_type
        if node.value is not None:
            val_type = self._p3_compute_expr(node.value)
            if ret_type and ret_type.kind == TypeKind.VOID:
                self.symbols.error(
                    node.line,
                    "void function should not return a value",
                )
            elif ret_type and val_type and not can_assign(ret_type, val_type):
                self.symbols.error(
                    node.line,
                    f"return type mismatch: expected '{ret_type.name}', "
                    f"got '{val_type.name}'",
                )
        else:
            if ret_type and ret_type.kind != TypeKind.VOID:
                self.symbols.error(
                    node.line,
                    f"non-void function must return a value of type "
                    f"'{ret_type.name}'",
                )

    def _p3_break(self, node: BreakStmt) -> None:
        if not self.symbols.in_loop():
            self.symbols.error(
                node.line,
                "'break' outside of loop",
            )

    def _p3_continue(self, node: ContinueStmt) -> None:
        if not self.symbols.in_loop():
            self.symbols.error(
                node.line,
                "'continue' outside of loop",
            )

    def _p3_print(self, node: PrintStmt) -> None:
        self._p3_compute_expr(node.value)
        # ISR safety: print/println are forbidden in ISR context
        if self.symbols.in_isr:
            self.symbols.error(
                node.line,
                "cannot call 'print()' / 'println()' inside an ISR function — "
                "ISR functions must be non-blocking",
            )

    def _p3_pwm_setup(self, node: PwmSetup) -> None:
        freq_type = self._p3_compute_expr(node.freq)
        res_type = self._p3_compute_expr(node.resolution)
        for t, name in [(freq_type, 'frequency'), (res_type, 'resolution')]:
            if t and not is_numeric_type(t):
                self.symbols.error(
                    node.line,
                    f"PWM {name} must be numeric, got '{t.name}'",
                )

    def _p3_pwm_write(self, node: PwmWrite) -> None:
        val_type = self._p3_compute_expr(node.value)
        if val_type and not is_numeric_type(val_type):
            self.symbols.error(
                node.line,
                f"PWM write value must be numeric, got '{val_type.name}'",
            )

    # ── expression type computation ──

    def _p3_compute_expr(self, node: Any) -> Optional[Type]:
        """Compute the type of an expression node. Annotates node._resolved_type."""
        if node is None:
            return None

        if isinstance(node, Literal):
            t = _type_from_literal(node)
            self._set_type(node, t)
            return t

        elif isinstance(node, Identifier):
            sym = self._node_symbol(node)
            if sym and sym.type:
                self._set_type(node, sym.type)
                # Check used before init
                if sym.name not in self._initialized and \
                   sym.kind == SymbolKind.VAR and not sym.is_global:
                    self.symbols.warn(
                        node.line,
                        f"variable '{sym.name}' may be used before initialization",
                        W_USED_BEFORE_INIT,
                    )
                # ISR safety: enforce volatile on accessed variables
                if self.symbols.in_isr and not sym.is_volatile:
                    if sym.kind in (SymbolKind.VAR, SymbolKind.PARAM):
                        self.symbols.error(
                            node.line,
                            f"ISR function accesses non-volatile variable "
                            f"'{sym.name}' — declare it 'volatile {sym.type.name if sym.type else 'int'} {sym.name}'",
                        )
                return sym.type
            self._set_type(node, INT)  # error recovery
            return INT

        elif isinstance(node, BinOp):
            return self._p3_binop(node)

        elif isinstance(node, UnaryOp):
            return self._p3_unary(node)

        elif isinstance(node, MemberAccess):
            return self._p3_member_access(node)

        elif isinstance(node, ArrayAccess):
            return self._p3_array_access(node)

        elif isinstance(node, FnCall):
            return self._p3_fn_call(node)

        elif isinstance(node, MethodCall):
            return self._p3_method_call(node)

        elif isinstance(node, MillisExpr):
            self._set_type(node, U32)
            return U32

        elif isinstance(node, MathExpr):
            return self._p3_math_expr(node)

        elif isinstance(node, CastExpr):
            target = self._resolve_type_name(node.target_type)
            if target is None:
                self.symbols.error(
                    node.line,
                    f"unknown type '{node.target_type}' in cast",
                )
                target = INT
            self._p3_compute_expr(node.expr)
            self._set_type(node, target)
            return target

        elif isinstance(node, SizeOfExpr):
            self._set_type(node, INT)
            return INT

        elif isinstance(node, PwmSetup):
            self._set_type(node, VOID)
            return VOID

        elif isinstance(node, PwmWrite):
            self._p3_compute_expr(node.value)
            self._set_type(node, VOID)
            return VOID

        elif isinstance(node, ExprStmt):
            return self._p3_compute_expr(node.expr)

        return None

    def _p3_binop(self, node: BinOp) -> Optional[Type]:
        left_t = self._p3_compute_expr(node.left)
        right_t = self._p3_compute_expr(node.right)

        if left_t is None or right_t is None:
            return None

        op = node.op

        # Logical ops: both bool, result bool
        if op in ('&&', '||'):
            if left_t.kind != TypeKind.BOOL or right_t.kind != TypeKind.BOOL:
                self.symbols.error(
                    node.line,
                    f"logical operator '{op}' requires bool operands, "
                    f"got '{left_t.name}' and '{right_t.name}'",
                )
            self._set_type(node, BOOL)
            return BOOL

        # Comparison ops: compatible types, result bool
        if op in ('==', '!=', '<', '>', '<=', '>='):
            self._set_type(node, BOOL)
            return BOOL

        # Arithmetic ops: both numeric, result = common type
        if op in ('+', '-', '*', '/', '%'):
            if not is_numeric_type(left_t) or not is_numeric_type(right_t):
                self.symbols.error(
                    node.line,
                    f"arithmetic operator '{op}' requires numeric operands, "
                    f"got '{left_t.name}' and '{right_t.name}'",
                )
                self._set_type(node, INT)
                return INT
            ct = common_type(left_t, right_t) or left_t
            self._set_type(node, ct)
            return ct

        # Bitwise ops: both integer, result = common type
        if op in ('&', '|', '^', '<<', '>>'):
            if not is_integer_type(left_t) or not is_integer_type(right_t):
                self.symbols.error(
                    node.line,
                    f"bitwise operator '{op}' requires integer operands, "
                    f"got '{left_t.name}' and '{right_t.name}'",
                )
                self._set_type(node, INT)
                return INT
            ct = common_type(left_t, right_t) or left_t
            self._set_type(node, ct)
            return ct

        return None

    def _p3_unary(self, node: UnaryOp) -> Optional[Type]:
        operand_t = self._p3_compute_expr(node.operand)
        if operand_t is None:
            return None

        if node.op == '!':
            # Allow ! on integers (idiomatic embedded C for pin toggling)
            if operand_t.kind != TypeKind.BOOL:
                if not is_integer_type(operand_t):
                    self.symbols.warn(
                        node.line,
                        f"logical not '!' on non-bool type '{operand_t.name}'",
                        W_IMPLICIT_NARROWING,
                    )
            self._set_type(node, BOOL)
            return BOOL
        elif node.op == '-':
            if not is_numeric_type(operand_t):
                self.symbols.error(
                    node.line,
                    f"unary '-' requires numeric operand, got '{operand_t.name}'",
                )
            self._set_type(node, operand_t)
            return operand_t
        elif node.op == '~':
            if not is_integer_type(operand_t):
                self.symbols.error(
                    node.line,
                    f"bitwise not '~' requires integer operand, "
                    f"got '{operand_t.name}'",
                )
            self._set_type(node, operand_t)
            return operand_t

        self._set_type(node, operand_t)
        return operand_t

    def _p3_member_access(self, node: MemberAccess) -> Optional[Type]:
        obj_sym = self._node_symbol(node)
        # Try struct field access
        if obj_sym and obj_sym.type and obj_sym.type.kind == TypeKind.STRUCT:
            st: StructType = obj_sym.type  # type: ignore[assignment]
            ft = st.field_type(node.member)
            if ft is None:
                self.symbols.error(
                    node.line,
                    f"struct '{obj_sym.name}' has no field '{node.member}'",
                )
                self._set_type(node, INT)
                return INT
            self._set_type(node, ft)
            return ft
        # Timer .running → bool
        if obj_sym and obj_sym.kind == SymbolKind.TIMER:
            if node.member == 'running':
                self._set_type(node, BOOL)
                return BOOL
            self._set_type(node, VOID)
            return VOID
        # Peripheral member access
        if obj_sym and obj_sym.kind == SymbolKind.PERIPHERAL:
            # Validated in Pass 2; type depends on specific member
            self._set_type(node, VOID)
            return VOID
        # WiFi property access
        if obj_sym and obj_sym.kind == SymbolKind.WIFI:
            wifi_decl = self._wifi_decls.get(obj_sym.name)
            mode = wifi_decl.mode if wifi_decl else 'sta'

            # Mode-specific validation
            if node.member in ('clients',) and mode != 'ap':
                self.symbols.error(
                    node.line,
                    f"property '.{node.member}' is only valid for AP mode wifi "
                    f"(wifi '{obj_sym.name}' is {mode.upper()})",
                )
                self._set_type(node, INT)
                return INT
            if node.member in ('ip', 'rssi') and mode != 'sta':
                self.symbols.error(
                    node.line,
                    f"property '.{node.member}' is only valid for STA mode wifi "
                    f"(wifi '{obj_sym.name}' is {mode.upper()})",
                )
                self._set_type(node, STR if node.member == 'ip' else INT)
                return STR if node.member == 'ip' else INT

            # Type resolution
            _WIFI_PROP_TYPES: Dict[str, Type] = {
                'state':     self.symbols.get_type('WifiState') or INT,
                'connected': BOOL,
                'ip':        STR,
                'rssi':      INT,
                'channel':   INT,
                'mac':       STR,
                'clients':   INT,
                'ssid':      STR,
            }
            t = _WIFI_PROP_TYPES.get(node.member, VOID)
            self._set_type(node, t)
            return t
        # Fallback: pin member access (.press, .release, etc.)
        # No type needed for these — they're event identifiers
        self._set_type(node, VOID)
        return VOID

    def _p3_array_access(self, node: ArrayAccess) -> Optional[Type]:
        idx_type = self._p3_compute_expr(node.index)
        if idx_type and not is_integer_type(idx_type):
            self.symbols.error(
                node.line,
                f"array index must be integer, got '{idx_type.name}'",
            )

        arr_sym = self._node_symbol(node)
        if arr_sym and arr_sym.type and arr_sym.type.kind == TypeKind.ARRAY:
            at: ArrayType = arr_sym.type  # type: ignore[assignment]
            self._set_type(node, at.elem_type)
            return at.elem_type

        self._set_type(node, INT)  # error recovery
        return INT

    def _p3_fn_call(self, node: FnCall) -> Optional[Type]:
        for arg in node.args:
            self._p3_compute_expr(arg)

        # ISR safety: forbid blocking/serial/peripheral calls
        if self.symbols.in_isr:
            _ISR_FORBIDDEN = frozenset({
                'print', 'println', 'delay', 'delayMicroseconds',
                'Serial.begin', 'Serial.print', 'Serial.println',
                'Wire.begin', 'Wire.beginTransmission', 'Wire.requestFrom',
                'SPI.begin', 'SPI.transfer',
            })
            if node.name in _ISR_FORBIDDEN:
                self.symbols.error(
                    node.line,
                    f"cannot call '{node.name}()' inside an ISR function — "
                    f"ISR functions must be non-blocking",
                )

        sym = self._node_symbol(node)
        if sym and sym.type and sym.type.kind == TypeKind.FN:
            ft: FnType = sym.type  # type: ignore[assignment]
            # Check argument count
            if len(node.args) != len(ft.param_types):
                self.symbols.error(
                    node.line,
                    f"'{node.name}' expects {len(ft.param_types)} arguments, "
                    f"got {len(node.args)}",
                )
            else:
                # Check argument types
                for i, arg in enumerate(node.args):
                    arg_type = self._node_type(arg)
                    if arg_type and not can_assign(ft.param_types[i], arg_type):
                        self.symbols.error(
                            node.line,
                            f"argument {i+1} to '{node.name}': "
                            f"expected '{ft.param_types[i].name}', "
                            f"got '{arg_type.name}'",
                        )
            self._set_type(node, ft.return_type)
            return ft.return_type

        # Scan result functions — only valid inside scan_done handler
        _SCAN_RESULT_FUNCS = frozenset({
            'scan_result_count', 'scan_result_ssid',
            'scan_result_rssi', 'scan_result_channel',
        })
        if node.name in _SCAN_RESULT_FUNCS:
            if not self._in_scan_done:
                self.symbols.error(
                    node.line,
                    f"'{node.name}()' is only valid inside a 'scan_done' event handler",
                )
            if node.name == 'scan_result_count':
                self._set_type(node, INT)
                return INT
            elif node.name in ('scan_result_ssid',):
                self._set_type(node, STR)
                return STR
            elif node.name in ('scan_result_rssi', 'scan_result_channel'):
                self._set_type(node, INT)
                return INT

        # Builtin functions (print, millis, etc.)
        # print: returns VOID
        if node.name in ('print', 'println'):
            self._set_type(node, VOID)
            return VOID
        # Math functions: return FLOAT
        if node.name in ('sin', 'cos', 'tan', 'sqrt', 'abs', 'pow',
                         'floor', 'ceil', 'round', 'log', 'exp'):
            self._set_type(node, FLOAT)
            return FLOAT
        # millis/micros: return U32
        if node.name in ('millis', 'micros'):
            self._set_type(node, U32)
            return U32
        # min/max/clamp/map: return type depends on args
        if node.name in ('min', 'max', 'clamp', 'map'):
            t = self._node_type(node.args[0]) if node.args else INT
            self._set_type(node, t)
            return t
        # digitalRead: returns int
        if node.name in ('digitalRead', 'analogRead'):
            self._set_type(node, INT)
            return INT
        # Serial.begin, digitalWrite, etc.: return VOID
        voider = {'digitalWrite', 'pinMode', 'delay', 'delayMicroseconds',
                   'Serial.begin', 'Serial.print', 'Serial.println',
                   'ledcSetup', 'ledcAttachPin', 'ledcWrite',
                   'attachInterrupt', 'detachInterrupt'}
        if node.name in voider:
            self._set_type(node, VOID)
            return VOID

        # Unknown function — assume INT for error recovery
        self._set_type(node, INT)
        return INT

    def _p3_method_call(self, node: MethodCall) -> Optional[Type]:
        obj_type = self._p3_compute_expr(node.obj)
        for arg in node.args:
            self._p3_compute_expr(arg)

        # Resolve object symbol for timer/peripheral dispatch
        obj_sym = None
        if isinstance(node.obj, str):
            obj_sym = self.symbols.lookup(node.obj)
        else:
            obj_sym = self._node_symbol(node.obj)

        # Timer methods: .stop() and .start() return void
        if obj_sym and obj_sym.kind == SymbolKind.TIMER:
            if node.method in ('stop', 'start'):
                self._set_type(node, VOID)
                return VOID

        # Peripheral methods: validated in Pass 2
        if obj_sym and obj_sym.kind == SymbolKind.PERIPHERAL:
            self._set_type(node, VOID)
            return VOID

        # WiFi methods
        if obj_sym and obj_sym.kind == SymbolKind.WIFI:
            wifi_decl = self._wifi_decls.get(obj_sym.name)
            mode = wifi_decl.mode if wifi_decl else 'sta'

            if node.method == 'scan' and mode != 'sta':
                self.symbols.error(
                    node.line,
                    f"method '.scan()' is only valid for STA mode wifi "
                    f"(wifi '{obj_sym.name}' is {mode.upper()})",
                )
            # Both .scan() and .disconnect() return void
            self._set_type(node, VOID)
            return VOID

        # PWM methods (setup, write) return void
        self._set_type(node, VOID)
        return VOID

    def _p3_math_expr(self, node: MathExpr) -> Optional[Type]:
        for arg in node.args:
            self._p3_compute_expr(arg)
        # Math functions return float
        self._set_type(node, FLOAT)
        return FLOAT

    # ── helper ──

    def _check_assignment(self, line: int, target_sym: Symbol,
                          val_type: Type) -> None:
        """Validate assignment compatibility."""
        if target_sym.type is None:
            return
        if can_assign(target_sym.type, val_type):
            return
        # Allow implicit numeric conversions with a warning
        # (for backward compatibility with existing .iot code)
        if is_numeric_type(target_sym.type) and is_numeric_type(val_type):
            self.symbols.warn(
                line,
                f"implicit narrowing conversion: "
                f"'{val_type.name}' to '{target_sym.type.name}'",
                W_IMPLICIT_NARROWING,
            )
            return
        # Total mismatch
        self.symbols.error(
            line,
            f"cannot assign '{val_type.name}' to "
            f"variable of type '{target_sym.type.name}'",
        )

    # ═════════════════════════════════════════
    #  PASS 4 — SCOPE ANALYSIS
    # ═════════════════════════════════════════

    def _pass4_scope(self, program: Program) -> None:
        """Tag variables with storage class, detect unused symbols."""
        for node in program.body:
            self._p4_tag(node, is_global=True)

        # Emit unused-variable warnings
        for sym in self.symbols.get_unused_vars():
            if sym.name in self._builtin_names:
                continue
            # In files with C blocks, const variables may be used in C code
            if self._has_c_blocks and sym.kind == SymbolKind.CONST:
                continue
            self.symbols.warn(
                sym.line,
                f"unused variable '{sym.name}'",
                W_UNUSED_VARIABLE,
            )

        # Emit unused-function warnings
        for sym in self.symbols.get_unused_fns():
            if sym.name in self._builtin_names:
                continue
            self.symbols.warn(
                sym.line,
                f"unused function '{sym.name}'",
                W_UNUSED_FUNCTION,
            )

    def _p4_tag(self, node: Node, is_global: bool = False) -> None:
        """Recursively tag variables with storage class."""
        if isinstance(node, Program):
            for child in node.body:
                self._p4_tag(child, is_global=True)

        elif isinstance(node, VarDecl):
            node._storage_class = 'global' if is_global else 'local'  # type: ignore[attr-defined]

        elif isinstance(node, ArrayDecl):
            node._storage_class = 'global' if is_global else 'local'  # type: ignore[attr-defined]

        elif isinstance(node, FnDecl):
            for stmt in node.body:
                self._p4_tag(stmt, is_global=False)

        elif isinstance(node, (VoidLoop, TickBlock, LoopBlock)):
            for stmt in node.body:
                self._p4_tag(stmt, is_global=False)

        elif isinstance(node, WifiDecl):
            pass  # WiFi declarations are always global; no body to walk

        elif isinstance(node, (OnEvent, OnThreshold, EveryBlock)):
            for stmt in node.body:
                self._p4_tag(stmt, is_global=False)

        elif isinstance(node, IfStmt):
            self._p4_tag_stmt_list(node.then_body, is_global)
            for _, body in node.elif_clauses:
                self._p4_tag_stmt_list(body, is_global)
            if node.else_body:
                self._p4_tag_stmt_list(node.else_body, is_global)

        elif isinstance(node, (WhileStmt, ForStmt)):
            if isinstance(node, ForStmt) and node.init:
                self._p4_tag(node.init, is_global)
            self._p4_tag_stmt_list(node.body, is_global)

        elif isinstance(node, DeferStmt):
            self._p4_tag_stmt_list(node.body, is_global)

    def _p4_tag_stmt_list(self, stmts: List[Node], is_global: bool) -> None:
        for stmt in stmts:
            self._p4_tag(stmt, is_global)
