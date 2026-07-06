"""
IOTIFT AST → IR Lowering — Milestone 2

Walks the AST and produces an IRModule with TAC instructions.
Handles expressions, statements, control flow, and Iotift-specific constructs.
"""

from __future__ import annotations
from typing import Optional, List, Any, Dict, Tuple
from ast_nodes import *
from ir import (
    IRModule, IRFunction, IRGlobal, IRStruct, IREnum, IRTypeAlias,
    BasicBlock, IRValue,
    IRLabel, IRBinary, IRUnary, IRCopy, IRLoad, IRStore,
    IRCall, IRCallIndirect, IRBranch, IRJump, IRReturn,
    IRCast, IRArrayAccess, IRMemberAccess,
    _tv, _cv, _vv, _gv, _pv, _lv, _void,
)
from type_system import Type, TypeKind


# C type mapping (same as codegen.py)
_CTYPE: Dict[str, str] = {
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


def to_ctype(name: str) -> str:
    """Map Iotift type name to C type."""
    return _CTYPE.get(name, name)


class IRLoweringError(Exception):
    """Raised when lowering encounters an unsupported node."""
    pass


# ─────────────────────────────────────────
#  IR BUILDER  (manages current block, temporaries)
# ─────────────────────────────────────────

class IRBuilder:
    """Helper for building IR within a function."""

    def __init__(self, module: IRModule, func: IRFunction) -> None:
        self.module = module
        self.func = func
        self._current_line: int = 0  # Track current AST source line
        self._loop_stack: List[Tuple[str, str]] = []  # (continue_label, break_label)

    def emit(self, instr) -> None:
        """Append an instruction to the current block."""
        # Set line info if available and not already set
        if self._current_line > 0 and getattr(instr, 'line', 0) == 0:
            instr.line = self._current_line
        # Find the current (last) block
        if not self.func.blocks:
            self.func.new_block(self.func.entry_block or 'entry')
        self.func.blocks[-1].append(instr)

    def new_block(self, label: str = '') -> BasicBlock:
        bb = self.func.new_block(label)
        return bb

    def new_label(self, prefix: str = 'L') -> str:
        return self.module.new_label(prefix)

    def new_temp(self, prefix: str = 't', ctype: str = 'int') -> IRValue:
        return self.module.new_temp(prefix, ctype)

    @property
    def current_block(self) -> Optional[BasicBlock]:
        return self.func.blocks[-1] if self.func.blocks else None


# ─────────────────────────────────────────
#  AST → IR LOWERING
# ─────────────────────────────────────────

class IRLowering:
    """Walks the AST and lowers it to an IRModule."""

    def __init__(self, scheduler_slots: int = 16):
        self.module: Optional[IRModule] = None
        self.builder: Optional[IRBuilder] = None
        self._default_scheduler_slots = scheduler_slots

        # Pin registry (during lowering)
        self._pins: Dict[str, Any] = {}
        self._pwm_pins: Dict[str, Dict] = {}
        self._on_pins: set = set()

        # Every / timer metadata
        self._every_count: int = 0
        self._every_labels: Dict[str, str] = {}  # label → active var name

        # All declared vars (for stack promotion)
        self._declared_vars: Dict[str, IRGlobal] = {}

        # WiFi tracking (Milestone 8)
        self._wifi_decls: List[Any] = []  # list of WifiDecl nodes
        self._wifi_names: set = set()

    # ─────────────────────────────────────────
    #  TOP-LEVEL ENTRY
    # ─────────────────────────────────────────

    def lower(self, program: Program) -> IRModule:
        """Convert a Program AST to an IRModule."""
        self.module = IRModule()
        self.module.scheduler_slots = self._default_scheduler_slots

        for node in program.body:
            self._lower_top_level(node)

        return self.module

    def _lower_top_level(self, node: Node) -> None:
        """Lower a top-level AST node, registering in the module."""

        if isinstance(node, DeviceDecl):
            self.module.device = node.name

        elif isinstance(node, ImportDecl):
            self.module.global_blocks.append(
                f'// import "{node.path}" (unresolved)'
            )

        elif isinstance(node, PinDecl):
            self._lower_pin_decl(node)

        elif isinstance(node, VarDecl):
            self._lower_var_decl_global(node)

        elif isinstance(node, ArrayDecl):
            ct = to_ctype(node.vtype)
            self.module.add_global(IRGlobal(
                name=node.name, ctype=ct,
                is_static=True, is_const=not node.is_mutable,
                array_size=node.size,
            ))

        elif isinstance(node, StructDecl):
            fields = [
                IRValue('var', f.name, to_ctype(f.vtype))
                for f in node.fields
            ]
            self.module.add_struct(IRStruct(name=node.name, fields=fields))

        elif isinstance(node, EnumDecl):
            self.module.add_enum(IREnum(
                name=node.name,
                backing_type=node.backing_type or 'int',
                variants=node.variants,
            ))

        elif isinstance(node, TypeAliasDecl):
            self.module.add_type_alias(IRTypeAlias(
                name=node.name,
                aliased_type=to_ctype(node.aliased_type),
            ))

        elif isinstance(node, PeripheralDecl):
            cfg_str = ', '.join(f'{k}: {v}' for k, v in node.config.items())
            self.module.global_blocks.append(
                f'// {node.periph_type} {node.name} {{ {cfg_str} }}'
            )

        elif isinstance(node, FnDecl):
            self._lower_fn_decl(node)

        elif isinstance(node, ExternFnDecl):
            # Extern function: just register as global declaration
            ret = to_ctype(node.return_type or 'void')
            params = ', '.join(
                f'{to_ctype(p.vtype)} {p.name}' for p in node.params
            ) or 'void'
            self.module.global_blocks.append(
                f'extern {ret} {node.name}({params});'
            )

        elif isinstance(node, CBlockNode):
            if not node.code.strip():
                return
            target = {
                'header': self.module.header_blocks,
                'global': self.module.global_blocks,
                'setup':  self.module.setup_blocks,
                'loop':   self.module.loop_blocks,
            }.get(node.scope, self.module.global_blocks)
            target.append(node.code)

        elif isinstance(node, WifiDecl):
            self._lower_wifi_decl(node)

        elif isinstance(node, OnEvent):
            self._lower_on_event(node)

        elif isinstance(node, OnThreshold):
            self._lower_on_threshold(node)

        elif isinstance(node, EveryBlock):
            self._lower_every_block(node)

        elif isinstance(node, LoopBlock):
            self._lower_loop_block(node)

        elif isinstance(node, VoidLoop):
            self._lower_void_loop(node)

        elif isinstance(node, TickBlock):
            self._lower_tick_block(node)

        elif isinstance(node, AfterBlock):
            self._lower_after_block(node)

        elif isinstance(node, SchedulerConfig):
            if node.key == 'scheduler_slots':
                self.module.scheduler_slots = int(node.value)

        elif isinstance(node, PwmSetup):
            if node.pin in self._pwm_pins:
                self._pwm_pins[node.pin]['freq'] = self._lower_expr_const(node.freq)
                self._pwm_pins[node.pin]['resolution'] = self._lower_expr_const(node.resolution)

        elif isinstance(node, (Assign, CompoundAssign, FnCall, MethodCall,
                                PrintStmt, PwmWrite, ExprStmt, AssignAfter)):
            # Top-level statements → lower into a setup function
            fn = self.module.functions[-1] if self.module.functions else None
            if fn is None or fn.name != '_iotift_setup':
                fn = IRFunction(
                    name='_iotift_setup',
                    return_type='void',
                    entry_block='entry',
                    is_static=True,
                )
                fn.new_block('entry')
                self.module.add_function(fn)
            self.builder = IRBuilder(self.module, fn)
            instrs = self._lower_stmt(node)
            for instr in instrs:
                self.builder.emit(instr)

    # ─────────────────────────────────────────
    #  PIN DECLARATION
    # ─────────────────────────────────────────

    def _lower_pin_decl(self, node: PinDecl) -> None:
        self._pins[node.name] = node
        self.module.pins[node.name] = node.number
        self.module.pin_directions[node.name] = node.direction

        if node.direction == 'pwm':
            ch = self.module.allocate_pwm_channel()
            self.module.pwm_pins[node.name] = {
                'number':     node.number,
                'channel':    ch,
                'freq':       node.pwm_freq or 5000,
                'resolution': node.pwm_resolution or 8,
            }
            self._pwm_pins[node.name] = self.module.pwm_pins[node.name]

    def _lower_wifi_decl(self, node: WifiDecl) -> None:
        """Record WiFi declaration and emit boilerplate global state blocks."""
        self._wifi_decls.append(node)
        self._wifi_names.add(node.name)
        self.module.has_wifi = True

        name = node.name
        cfg = node.config
        mode = node.mode

        # Per-declaration state variables
        self.module.add_global(IRGlobal(
            name=f'_iotift_wifi_{name}_state', ctype='int', init=0,
            is_static=True,
        ))
        self.module.add_global(IRGlobal(
            name=f'_iotift_wifi_{name}_connected', ctype='bool', init=0,
            is_static=True,
        ))
        self.module.add_global(IRGlobal(
            name=f'_iotift_wifi_{name}_ip', ctype='const char*', init='""',
            is_static=True,
        ))
        self.module.add_global(IRGlobal(
            name=f'_iotift_wifi_{name}_rssi', ctype='int', init=0,
            is_static=True,
        ))
        self.module.add_global(IRGlobal(
            name=f'_iotift_wifi_{name}_channel', ctype='int', init=0,
            is_static=True,
        ))
        self.module.add_global(IRGlobal(
            name=f'_iotift_wifi_{name}_mac', ctype='const char*', init='""',
            is_static=True,
        ))
        # Client count (AP mode only, but declare unconditionally for simplicity)
        self.module.add_global(IRGlobal(
            name=f'_iotift_wifi_{name}_client_count', ctype='int', init=0,
            is_static=True,
        ))

        # Event pending flags for each event type
        for ev in ['connect', 'disconnect', 'got_ip', 'scan_done',
                    'client_join', 'client_leave']:
            self.module.add_global(IRGlobal(
                name=f'_iotift_wifi_{name}_event_{ev}', ctype='bool', init=0,
                is_static=True,
            ))

        # Retry state
        self.module.add_global(IRGlobal(
            name=f'_iotift_wifi_{name}_retry_count', ctype='int', init=0,
            is_static=True,
        ))
        self.module.add_global(IRGlobal(
            name=f'_iotift_wifi_{name}_last_retry_ms', ctype='unsigned long', init=0,
            is_static=True,
        ))

        # Add WiFi init to setup_blocks
        ssid = cfg.get('ssid', '')
        password = cfg.get('password', '')
        if mode == 'sta':
            self.module.setup_blocks.append(
                f'WiFi.mode(WIFI_STA);\n'
                f'  WiFi.begin("{ssid}", "{password}");'
            )
        elif mode == 'ap':
            self.module.setup_blocks.append(
                f'WiFi.mode(WIFI_AP);\n'
                f'  WiFi.softAP("{ssid}"{", " + chr(34) + password + chr(34) if password else ""});'
            )
        self.module.setup_blocks.append(
            f'/* WiFi "{name}" ({mode}) initialized */'
        )

    # ─────────────────────────────────────────
    #  GLOBAL VARIABLE
    # ─────────────────────────────────────────

    def _lower_var_decl_global(self, node: VarDecl) -> None:
        ctype = to_ctype(node.vtype)
        init_val = None
        if node.init is not None:
            if isinstance(node.init, Literal):
                init_val = node.init.value
            elif isinstance(node.init, (int, float, str)):
                init_val = node.init
        is_const = node.is_const or (not node.is_mutable)

        g = IRGlobal(
            name=node.name, ctype=ctype,
            init=init_val, is_const=is_const,
            is_static=True, is_volatile=node.is_volatile,
        )
        self.module.add_global(g)
        self._declared_vars[node.name] = g

    # ─────────────────────────────────────────
    #  FUNCTION DECLARATION
    # ─────────────────────────────────────────

    def _lower_fn_decl(self, node: FnDecl) -> None:
        ret = to_ctype(node.return_type or 'void')
        params = [
            _pv(p.name, to_ctype(p.vtype))
            for p in node.params
        ]
        fn = IRFunction(
            name=node.name,
            params=params,
            return_type=ret,
            entry_block='entry',
            is_static=True,
            is_isr=node.is_isr,
            attrs='IRAM_ATTR ' if node.is_isr else '',
        )
        fn.new_block('entry')
        self.module.add_function(fn)

        self.builder = IRBuilder(self.module, fn)

        # Lower body
        for stmt in node.body:
            instrs = self._lower_stmt(stmt)
            for instr in instrs:
                self.builder.emit(instr)

        # Add implicit return if missing
        if not fn.blocks[-1].is_terminated:
            if ret == 'void':
                self.builder.emit(IRReturn())
            else:
                self.builder.emit(IRReturn(_cv(0, ret)))

    # ─────────────────────────────────────────
    #  EVENT HANDLERS
    # ─────────────────────────────────────────

    # Map Iotift event names to Arduino interrupt modes
    _EDGE_MODE = {
        'press':   'FALLING',   # INPUT_PULLUP, press = LOW
        'release': 'RISING',
        'rising':  'RISING',
        'falling': 'FALLING',
        'change':  'CHANGE',
    }

    def _lower_on_event(self, node: OnEvent) -> None:
        if not node.body:
            return

        # WiFi events: skip pin ISR creation (WiFi events dispatch from event loop)
        if node.target in self._wifi_names or hasattr(node, 'target') and node.target in self._wifi_names:
            self._lower_wifi_event(node)
            return

        self._on_pins.add(node.pin)
        edge_mode = self._EDGE_MODE.get(node.event, 'CHANGE')

        # ── 1. Volatile flag variable ──
        flag_var = f'_iotift_{node.pin}_{node.event}_flag'
        self.module.add_global(IRGlobal(
            name=flag_var, ctype='bool', init=0, is_static=True, is_volatile=True,
        ))

        # ── 2. ISR function (minimal — just sets flag) ──
        isr_name = f'_iotift_{node.pin}_{node.event}_isr'
        isr_fn = IRFunction(
            name=isr_name, return_type='void',
            entry_block='entry', is_static=True,
            attrs='IRAM_ATTR ',
        )
        isr_fn.new_block('entry')
        isr_builder = IRBuilder(self.module, isr_fn)
        isr_builder.emit(IRCopy(_cv(1, 'int'), _gv(flag_var, 'bool')))
        isr_builder.emit(IRReturn())
        isr_fn.new_block('exit')  # ensure epilogue
        self.module.add_function(isr_fn)

        # ── 3. Debounce tracking (if configured) ──
        debounce_ms = 0
        pin_node = self._pins.get(node.pin)
        if pin_node and pin_node.config and pin_node.config.debounce_ms:
            debounce_ms = pin_node.config.debounce_ms

        # ── 4. Handler function (runs in loop, checks flag + debounce) ──
        fn_name = f'_iotift_on_{node.pin}_{node.event}'
        fn = IRFunction(
            name=fn_name, return_type='void',
            entry_block='entry', is_static=True,
        )
        fn.new_block('entry')
        self.module.add_function(fn)
        self.builder = IRBuilder(self.module, fn)

        # Check if flag is set
        flag_cond = self.builder.new_temp('flag_cond', 'bool')
        self.builder.emit(IRBinary('!=', _gv(flag_var, 'bool'), _cv(0, 'int'), dest=flag_cond))
        body_label = self.builder.new_label('body')
        end_label = self.builder.new_label('end')
        self.builder.emit(IRBranch(flag_cond, body_label, end_label))

        self.builder.new_block(body_label)

        # Clear the flag
        self.builder.emit(IRCopy(_cv(0, 'int'), _gv(flag_var, 'bool')))

        # Debounce check (if configured)
        if debounce_ms > 0:
            last_var = f'_iotift_{node.pin}_{node.event}_last'
            self.module.add_global(IRGlobal(
                name=last_var, ctype='unsigned long', init=0, is_static=True,
            ))
            now_temp = self.builder.new_temp('debounce_now', 'unsigned long')
            self.builder.emit(IRCall('millis', [], dest=now_temp))
            diff_temp = self.builder.new_temp('debounce_diff', 'unsigned long')
            self.builder.emit(IRBinary('-', now_temp, _gv(last_var, 'unsigned long'), dest=diff_temp))
            debounce_cond = self.builder.new_temp('debounce_cond', 'bool')
            self.builder.emit(IRBinary('>=', diff_temp, _cv(debounce_ms, 'unsigned long'), dest=debounce_cond))
            fire_label = self.builder.new_label('fire')
            self.builder.emit(IRBranch(debounce_cond, fire_label, end_label))
            self.builder.new_block(fire_label)
            self.builder.emit(IRCopy(now_temp, _gv(last_var, 'unsigned long')))

        # Emit user body
        for stmt in node.body:
            stmt_lines = self._lower_stmt(stmt)
            for instr in stmt_lines:
                self.builder.emit(instr)

        self.builder.emit(IRJump(end_label))
        self.builder.new_block(end_label)
        self.builder.emit(IRReturn())

        # ── 5. Register interrupt metadata ──
        self.module.interrupts.append({
            'pin': node.pin,
            'mode': edge_mode,
            'isr_name': isr_name,
        })

        # ── 6. Register handler for loop dispatch ──
        self.module.on_event_handlers.append({
            'name': fn_name,
            'pin': node.pin,
            'event': node.event,
            'has_body': True,
        })

    def _lower_wifi_event(self, node: OnEvent) -> None:
        """Lower a WiFi on-event handler (no ISR, dispatched from loop)."""
        if not node.body:
            return

        fn_name = f'_iotift_wifi_{node.target}_on_{node.event}'
        fn = IRFunction(
            name=fn_name, return_type='void',
            entry_block='entry', is_static=True,
        )
        fn.new_block('entry')
        self.module.add_function(fn)
        self.builder = IRBuilder(self.module, fn)

        # Guard: only execute body if the event flag is set
        flag_var = f'_iotift_wifi_{node.target}_event_{node.event}'
        flag_val = self.builder.new_temp('flag', 'bool')
        self.builder.emit(IRBinary('!=', _gv(flag_var, 'bool'), _cv(0, 'int'), dest=flag_val))
        body_label = self.builder.new_label('body')
        end_label = self.builder.new_label('end')
        self.builder.emit(IRBranch(flag_val, body_label, end_label))

        # Body: clear flag, then execute user body
        self.builder.new_block(body_label)
        self.builder.emit(IRCopy(_cv(0, 'int'), _gv(flag_var, 'bool')))
        for stmt in node.body:
            for instr in self._lower_stmt(stmt):
                self.builder.emit(instr)
        self.builder.emit(IRJump(end_label))

        self.builder.new_block(end_label)
        self.builder.emit(IRReturn())

        # Register as handler for loop dispatch
        self.module.on_event_handlers.append({
            'name': fn_name,
            'pin': '',  # No pin for WiFi events
            'event': node.event,
            'has_body': True,
            'is_wifi': True,
            'wifi_name': node.target,
        })

    def _lower_on_threshold(self, node: OnThreshold) -> None:
        if not node.body:
            return

        # Include operator + value to make name unique for multiple thresholds on same pin
        val_str = str(hash(str(node.value))) if node.value else '0'
        fn_name = f'_iotift_threshold_{node.pin}_{node.op}_{val_str}'
        fn = IRFunction(
            name=fn_name, return_type='void',
            entry_block='entry', is_static=True,
        )
        fn.new_block('entry')
        self.module.add_function(fn)

        self.builder = IRBuilder(self.module, fn)

        val, val_instrs = self._lower_expr(node.value)
        for instr in val_instrs:
            self.builder.emit(instr)

        # Read the pin value first — use analogRead for analog pins, digitalRead for digital pins
        pin_decl = self._pins.get(node.pin)
        if pin_decl and pin_decl.direction == 'analog':
            pin_val = self.builder.new_temp(f'{node.pin}_val', 'int')
            self.builder.emit(IRCall('analogRead',
                [_cv(f'{node.pin}_PIN', 'uint8_t')], dest=pin_val))
        else:
            pin_val = self.builder.new_temp(f'{node.pin}_val', 'int')
            self.builder.emit(IRCall('digitalRead',
                [_cv(f'{node.pin}_PIN', 'uint8_t')], dest=pin_val))

        # Condition
        cond = self.builder.new_temp('cond', 'bool')
        self.builder.emit(IRBinary(
            op=node.op,
            left=pin_val,
            right=val,
            dest=cond,
        ))

        then_label = self.builder.new_label('then')
        end_label = self.builder.new_label('end')
        self.builder.emit(IRBranch(cond, then_label, end_label))

        self.builder.new_block(then_label)
        for stmt in node.body:
            stmt_instrs = self._lower_stmt(stmt)
            for instr in stmt_instrs:
                self.builder.emit(instr)
        self.builder.emit(IRJump(end_label))

        self.builder.new_block(end_label)
        self.builder.emit(IRReturn())

        self.module.on_threshold_handlers.append({
            'name': fn_name,
            'pin': node.pin,
            'op': node.op,
        })

    # ─────────────────────────────────────────
    #  EVERY BLOCK
    # ─────────────────────────────────────────

    def _lower_every_block(self, node: EveryBlock) -> None:
        if not node.body:
            return

        idx = self._every_count
        self._every_count += 1

        if node.label:
            fn_name = f'_iotift_every_{node.label}'
        else:
            fn_name = f'_iotift_every_{idx}'

        time_var = f'{fn_name}_last'
        active_var = f'{fn_name}_active' if node.label else None

        # Register globals for timer tracking
        # With offset_ms: init = offset - interval so first fire occurs at offset
        # Uses unsigned wraparound: (unsigned long)(offset - interval) delays first fire
        time_init = 0
        if node.offset_ms is not None:
            time_init = node.offset_ms - node.interval
        self.module.add_global(IRGlobal(
            name=time_var, ctype='unsigned long', init=time_init, is_static=True,
        ))
        if active_var:
            self.module.add_global(IRGlobal(
                name=active_var, ctype='int', init=1, is_static=True,
            ))
            self._every_labels[node.label] = active_var

        fn = IRFunction(
            name=fn_name, return_type='void',
            entry_block='entry', is_static=True,
        )
        fn.new_block('entry')
        self.module.add_function(fn)

        self.builder = IRBuilder(self.module, fn)

        # Emit timer check preamble
        millis_temp = self.builder.new_temp('now', 'unsigned long')
        self.builder.emit(IRCall('millis', [], dest=millis_temp))

        diff_temp = self.builder.new_temp('diff', 'unsigned long')
        self.builder.emit(IRBinary('-', millis_temp, _gv(time_var, 'unsigned long'), dest=diff_temp))
        cond = self.builder.new_temp('cond', 'bool')
        self.builder.emit(IRBinary('>=', diff_temp, _cv(node.interval, 'unsigned long'), dest=cond))

        # Active check for named timers
        if active_var:
            active_cond = self.builder.new_temp('active_cond', 'bool')
            self.builder.emit(IRBinary('&&', cond, _gv(active_var, 'int'), dest=active_cond))
            cond = active_cond

        body_label = self.builder.new_label('body')
        end_label = self.builder.new_label('end')
        self.builder.emit(IRBranch(cond, body_label, end_label))

        # Body
        self.builder.new_block(body_label)
        self.builder.emit(IRCopy(millis_temp, _gv(time_var, 'unsigned long')))
        for stmt in node.body:
            stmt_instrs = self._lower_stmt(stmt)
            for instr in stmt_instrs:
                self.builder.emit(instr)
        self.builder.emit(IRJump(end_label))

        self.builder.new_block(end_label)
        self.builder.emit(IRReturn())

        self.module.every_handlers.append({
            'name': fn_name,
            'interval': node.interval,
            'label': node.label,
            'active_var': active_var,
            'time_var': time_var,
            'has_body': True,
        })

        # Scheduler needed if body has AssignAfter
        if self._body_has_assign_after(node.body):
            self.module.scheduler_needed = True

    def _lower_after_block(self, node: AfterBlock) -> None:
        """lower after 5s { ... } → one-shot timer with done flag."""
        if not node.body:
            return

        idx = self._every_count
        self._every_count += 1
        fn_name = f'_iotift_after_{idx}'
        done_var = f'{fn_name}_done'
        time_var = f'{fn_name}_last'

        # Register globals for one-shot tracking
        self.module.add_global(IRGlobal(
            name=done_var, ctype='bool', init=0, is_static=True,
        ))
        self.module.add_global(IRGlobal(
            name=time_var, ctype='unsigned long', init=0, is_static=True,
        ))

        fn = IRFunction(
            name=fn_name, return_type='void',
            entry_block='entry', is_static=True,
        )
        fn.new_block('entry')
        self.module.add_function(fn)
        self.builder = IRBuilder(self.module, fn)

        # Check done flag
        done_cond = self.builder.new_temp('done_cond', 'bool')
        self.builder.emit(IRBinary('==', _gv(done_var, 'bool'), _cv(1, 'int'), dest=done_cond))
        body_label = self.builder.new_label('body')
        end_label = self.builder.new_label('end')
        self.builder.emit(IRBranch(done_cond, end_label, body_label))

        # Body: check millis timer
        self.builder.new_block(body_label)
        millis_temp = self.builder.new_temp('now', 'unsigned long')
        self.builder.emit(IRCall('millis', [], dest=millis_temp))
        diff_temp = self.builder.new_temp('diff', 'unsigned long')
        self.builder.emit(IRBinary('-', millis_temp, _gv(time_var, 'unsigned long'), dest=diff_temp))
        timer_cond = self.builder.new_temp('timer_cond', 'bool')
        self.builder.emit(IRBinary('>=', diff_temp, _cv(node.interval, 'unsigned long'), dest=timer_cond))

        fire_label = self.builder.new_label('fire')
        self.builder.emit(IRBranch(timer_cond, fire_label, end_label))

        # Fire: set done, run body
        self.builder.new_block(fire_label)
        self.builder.emit(IRCopy(_cv(1, 'int'), _gv(done_var, 'bool')))
        for stmt in node.body:
            stmt_instrs = self._lower_stmt(stmt)
            for instr in stmt_instrs:
                self.builder.emit(instr)
        self.builder.emit(IRJump(end_label))

        self.builder.new_block(end_label)
        self.builder.emit(IRReturn())

        # Register as handler (will be called from loop())
        self.module.every_handlers.append({
            'name': fn_name,
            'interval': node.interval,
            'label': None,
            'active_var': done_var,
            'time_var': time_var,
            'has_body': True,
            'is_one_shot': True,
        })
    # ─────────────────────────────────────────

    def _lower_loop_block(self, node: LoopBlock) -> None:
        if not node.body:
            return
        fn = IRFunction(
            name='_iotift_handle_loop', return_type='void',
            entry_block='entry', is_static=True,
        )
        fn.new_block('entry')
        self.module.add_function(fn)
        self.builder = IRBuilder(self.module, fn)

        # Create proper infinite loop structure so break/continue have valid targets
        body_label = self.module.new_label('loop_body')
        end_label = self.module.new_label('loop_end')
        self.builder._loop_stack.append((body_label, end_label))

        # Jump to body (entry point for infinite loop)
        self.builder.emit(IRJump(body_label))
        self.builder.new_block(body_label)

        for stmt in node.body:
            for instr in self._lower_stmt(stmt):
                self.builder.emit(instr)

        # Back to body for infinite loop
        self.builder.emit(IRJump(body_label))
        self.builder.new_block(end_label)
        self.builder._loop_stack.pop()

        if not fn.blocks[-1].is_terminated:
            self.builder.emit(IRReturn())

    def _lower_void_loop(self, node: VoidLoop) -> None:
        if not node.body:
            return
        fn = IRFunction(
            name='user_loop', return_type='void',
            entry_block='entry', is_static=True,
        )
        fn.new_block('entry')
        self.module.add_function(fn)
        self.builder = IRBuilder(self.module, fn)

        for stmt in node.body:
            for instr in self._lower_stmt(stmt):
                self.builder.emit(instr)
        if not fn.blocks[-1].is_terminated:
            self.builder.emit(IRReturn())

    def _lower_tick_block(self, node: TickBlock) -> None:
        if not node.body:
            return
        fn = IRFunction(
            name='_iotift_tick', return_type='void',
            entry_block='entry', is_static=True,
        )
        fn.new_block('entry')
        self.module.add_function(fn)
        self.builder = IRBuilder(self.module, fn)

        for stmt in node.body:
            for instr in self._lower_stmt(stmt):
                self.builder.emit(instr)
        if not fn.blocks[-1].is_terminated:
            self.builder.emit(IRReturn())

    # ─────────────────────────────────────────
    #  STATEMENT LOWERING
    # ─────────────────────────────────────────

    def _lower_stmt(self, node: Node) -> List:
        """Lower a statement node to a list of IR instructions."""
        # Track source line for source map generation (Milestone 5)
        if hasattr(node, 'line') and node.line > 0 and self.builder:
            self.builder._current_line = node.line

        if isinstance(node, Assign):
            return self._lower_assign(node)
        if isinstance(node, CompoundAssign):
            return self._lower_compound_assign(node)
        if isinstance(node, AssignAfter):
            return self._lower_assign_after(node)
        if isinstance(node, IfStmt):
            return self._lower_if(node)
        if isinstance(node, WhileStmt):
            return self._lower_while(node)
        if isinstance(node, ForStmt):
            return self._lower_for(node)
        if isinstance(node, VarDecl):
            return self._lower_var_decl_local(node)
        if isinstance(node, ReturnStmt):
            return self._lower_return(node)
        if isinstance(node, BreakStmt):
            if self.builder._loop_stack:
                return [IRJump(self.builder._loop_stack[-1][1])]  # break → loop end
            return [IRJump('__break__')]  # fallback
        if isinstance(node, ContinueStmt):
            if self.builder._loop_stack:
                return [IRJump(self.builder._loop_stack[-1][0])]  # continue → loop cond
            return [IRJump('__continue__')]  # fallback
        if isinstance(node, PrintStmt):
            return self._lower_print(node)
        if isinstance(node, FnCall):
            val, instrs = self._lower_expr(node, None)
            return instrs
        if isinstance(node, MethodCall):
            val, instrs = self._lower_expr(node, None)
            return instrs
        if isinstance(node, PwmWrite):
            return self._lower_pwm_write(node)
        if isinstance(node, PwmSetup):
            return self._lower_pwm_setup(node)
        if isinstance(node, StopStmt):
            return self._lower_stop(node)
        # StartStmt not yet in AST — handled via direct string check
        if hasattr(node, '__class__') and node.__class__.__name__ == 'StartStmt':
            return self._lower_start(node)
        if isinstance(node, ExprStmt):
            val, instrs = self._lower_expr(node.expr, None)
            return instrs
        if isinstance(node, DeferStmt):
            result = []
            for s in node.body:
                result.extend(self._lower_stmt(s))
            return result
        if isinstance(node, CBlockNode):
            # Raw C in function bodies — emit as a pseudo-instruction
            return [IRCallIndirect(
                func_expr=f'/* C block: {node.scope} */\n{node.code}',
                args=[], dest=None,
            )]

        return []

    # ─────────────────────────────────────────
    #  ASSIGNMENT LOWERING
    # ─────────────────────────────────────────

    def _lower_assign(self, node: Assign) -> List:
        val, val_instrs = self._lower_expr(node.value)
        instrs = []
        instrs.extend(val_instrs)

        if isinstance(node.target, str):
            # Check if it's a pin
            if node.target in self._pins and node.target not in self._pwm_pins:
                # digitalWrite shortcut
                level = 'HIGH' if self._is_truthy(node.value) else 'LOW'
                instrs.append(IRCallIndirect(
                    func_expr=f'digitalWrite({node.target}_PIN, {level})',
                    args=[], dest=None,
                ))
            else:
                instrs.append(IRCopy(val, _vv(node.target, val.ctype)))
        elif isinstance(node.target, ArrayAccess):
            # Emit array[index] = val by encoding index in the dest name
            idx, idx_instrs = self._lower_expr(node.target.index)
            instrs.extend(idx_instrs)
            dest_name = f'{node.target.name}[{idx.name}]'
            instrs.append(IRStore(val, _vv(dest_name, val.ctype)))
        elif isinstance(node.target, MemberAccess):
            # Handle raw-string obj (parser stores obj as str for simple cases)
            if isinstance(node.target.obj, str):
                obj_name = node.target.obj
            else:
                obj, obj_instrs = self._lower_expr(node.target.obj)
                instrs.extend(obj_instrs)
                obj_name = obj.name
            instrs.append(IRCopy(val, _vv(f'{obj_name}.{node.target.member}', val.ctype)))
        else:
            instrs.append(IRCopy(val, _vv(str(node.target), val.ctype)))

        return instrs

    def _lower_compound_assign(self, node: CompoundAssign) -> List:
        val, val_instrs = self._lower_expr(node.value)
        op_map = {
            '+=': '+', '-=': '-', '*=': '*', '/=': '/', '%=': '%',
            '&=': '&', '|=': '|', '^=': '^',
        }
        op = op_map.get(node.op, '+')
        dest = _vv(node.target, val.ctype)
        instrs = []
        instrs.extend(val_instrs)
        instrs.append(IRBinary(op, dest, val, dest))
        return instrs

    def _lower_assign_after(self, node: AssignAfter) -> List:
        val, val_instrs = self._lower_expr(node.value)
        instrs = []
        instrs.extend(val_instrs)

        if node.target in self._pins and node.target not in self._pwm_pins:
            level = 'HIGH' if self._is_truthy(node.value) else 'LOW'
            instrs.append(IRCall(
                '_iotift_schedule_pin',
                [_cv(node.target + '_PIN', 'uint8_t'),
                 _cv(level, 'int'),
                 _cv(node.delay, 'unsigned long')],
                dest=None,
            ))
        else:
            instrs.append(IRCall(
                '_iotift_schedule_int',
                [_vv('&' + node.target, 'int*'),
                 val,
                 _cv(node.delay, 'unsigned long')],
                dest=None,
            ))

        if not self.module.scheduler_needed:
            self.module.scheduler_needed = True

        return instrs

    # ─────────────────────────────────────────
    #  CONTROL FLOW LOWERING
    # ─────────────────────────────────────────

    def _lower_if(self, node: IfStmt) -> List:
        """Lower if/elif/else by emitting condition+branch DIRECTLY into the
        current block BEFORE creating new blocks. Returns empty list because
        everything is emitted inside this method at the correct time.

        Block structure produced (goto-based, blocks in creation order):
          [calling block]  condition check + IRBranch  (emitted first)
          [then block]     then body + IRJump endif
          [elif_test_N]    elif condition + IRBranch
          [elif_body_N]    elif body + IRJump endif
          [else_body]      else body + IRJump endif
          [endif]          continuation after if statement
        """
        cond, cond_instrs = self._lower_expr(node.condition)

        # ── EMIT condition check into the CURRENT block IMMEDIATELY ──
        for instr in cond_instrs:
            self.builder.emit(instr)

        end_label = self.builder.new_label('endif')
        has_else_chain = bool(node.elif_clauses or node.else_body)

        if not has_else_chain:
            # Simple if-then (no else/elif)
            then_label = self.builder.new_label('then')
            self.builder.emit(IRBranch(cond, then_label, end_label))

            self.builder.new_block(then_label)
            for s in node.then_body:
                for inst in self._lower_stmt(s):
                    self.builder.emit(inst)
            self.builder.emit(IRJump(end_label))
        else:
            # if/elif/else chain — create proper cascade
            then_label = self.builder.new_label('then')
            first_else_label = self.builder.new_label('elif_chain')
            self.builder.emit(IRBranch(cond, then_label, first_else_label))

            # Then block
            self.builder.new_block(then_label)
            for s in node.then_body:
                for inst in self._lower_stmt(s):
                    self.builder.emit(inst)
            self.builder.emit(IRJump(end_label))

            # Elif chain
            current_label = first_else_label
            self.builder.new_block(current_label)

            num_elifs = len(node.elif_clauses)
            for i, (ec, eb) in enumerate(node.elif_clauses):
                ec_val, ec_instrs = self._lower_expr(ec)
                for inst in ec_instrs:
                    self.builder.emit(inst)

                is_last = (i + 1 == num_elifs)
                has_else = bool(node.else_body)

                if is_last and has_else:
                    # Last elif with else: false_label → else_body
                    else_body_label = self.builder.new_label('else_body')
                    body_label = self.builder.new_label('elif_body')
                    self.builder.emit(IRBranch(ec_val, body_label, else_body_label))

                    self.builder.new_block(body_label)
                    for s in eb:
                        for inst in self._lower_stmt(s):
                            self.builder.emit(inst)
                    self.builder.emit(IRJump(end_label))

                    # Else body block
                    self.builder.new_block(else_body_label)
                    for s in node.else_body:
                        for inst in self._lower_stmt(s):
                            self.builder.emit(inst)
                    self.builder.emit(IRJump(end_label))
                elif is_last:
                    # Last elif, no else — branch to body or end
                    body_label = self.builder.new_label('elif_body')
                    self.builder.emit(IRBranch(ec_val, body_label, end_label))

                    self.builder.new_block(body_label)
                    for s in eb:
                        for inst in self._lower_stmt(s):
                            self.builder.emit(inst)
                    self.builder.emit(IRJump(end_label))
                else:
                    # Not last elif — continue chain
                    next_test_label = self.builder.new_label('elif_chain')
                    body_label = self.builder.new_label('elif_body')
                    self.builder.emit(IRBranch(ec_val, body_label, next_test_label))

                    # Elif body block
                    self.builder.new_block(body_label)
                    for s in eb:
                        for inst in self._lower_stmt(s):
                            self.builder.emit(inst)
                    self.builder.emit(IRJump(end_label))

                    # Continue chain
                    current_label = next_test_label
                    self.builder.new_block(current_label)

            # If no elifs but has else: simple if/else
            if num_elifs == 0 and node.else_body:
                # The current block is first_else_label (the path taken when
                # condition is false). Jump to else_body from here.
                else_body_label = self.builder.new_label('else_body')
                self.builder.emit(IRJump(else_body_label))
                self.builder.new_block(else_body_label)
                for s in node.else_body:
                    for inst in self._lower_stmt(s):
                        self.builder.emit(inst)
                self.builder.emit(IRJump(end_label))

        # End block (continuation after the if)
        self.builder.new_block(end_label)
        return []  # All instructions emitted directly — nothing to return

    def _lower_while(self, node: WhileStmt) -> List:
        cond_label = self.builder.new_label('while_cond')
        body_label = self.builder.new_label('while_body')
        end_label = self.builder.new_label('while_end')

        # Push loop labels for break/continue
        self.builder._loop_stack.append((cond_label, end_label))

        # Emit jump to condition BEFORE creating new blocks
        self.builder.emit(IRJump(cond_label))

        # Condition check
        self.builder.new_block(cond_label)
        cond, cond_instrs = self._lower_expr(node.condition)
        for instr in cond_instrs:
            self.builder.emit(instr)
        self.builder.emit(IRBranch(cond, body_label, end_label))

        # Body
        self.builder.new_block(body_label)
        for s in node.body:
            stmt_instrs = self._lower_stmt(s)
            for instr in stmt_instrs:
                self.builder.emit(instr)
        self.builder.emit(IRJump(cond_label))

        # End (NOT terminated — continuation after loop)
        self.builder.new_block(end_label)

        # Pop loop labels
        self.builder._loop_stack.pop()

        return []  # All emitted directly

    def _lower_for(self, node: ForStmt) -> List:
        # Init — emitted BEFORE creating new blocks
        if node.init:
            init_instrs = self._lower_stmt(node.init)
            for instr in init_instrs:
                self.builder.emit(instr)

        cond_label = self.builder.new_label('for_cond')
        body_label = self.builder.new_label('for_body')
        step_label = self.builder.new_label('for_step')
        end_label = self.builder.new_label('for_end')

        # Push loop labels for break/continue
        self.builder._loop_stack.append((step_label, end_label))

        self.builder.emit(IRJump(cond_label))

        # Condition check
        self.builder.new_block(cond_label)
        if node.condition:
            cond, cond_instrs = self._lower_expr(node.condition)
            for instr in cond_instrs:
                self.builder.emit(instr)
            self.builder.emit(IRBranch(cond, body_label, end_label))
        else:
            self.builder.emit(IRJump(body_label))

        # Body
        self.builder.new_block(body_label)
        for s in node.body:
            stmt_lines = self._lower_stmt(s)
            for instr in stmt_lines:
                self.builder.emit(instr)
        self.builder.emit(IRJump(step_label))

        # Step
        self.builder.new_block(step_label)
        if node.step:
            step_instrs = self._lower_stmt(node.step)
            for instr in step_instrs:
                self.builder.emit(instr)
        self.builder.emit(IRJump(cond_label))

        # End
        self.builder.new_block(end_label)

        # Pop loop labels
        self.builder._loop_stack.pop()

        return []  # All emitted directly

    def _lower_return(self, node: ReturnStmt) -> List:
        if node.value is not None:
            val, val_instrs = self._lower_expr(node.value)
            instrs = []
            instrs.extend(val_instrs)
            instrs.append(IRReturn(val))
            return instrs
        return [IRReturn()]

    # ─────────────────────────────────────────
    #  LOCAL VARIABLE DECLARATION
    # ─────────────────────────────────────────

    def _lower_var_decl_local(self, node: VarDecl) -> List:
        ctype = to_ctype(node.vtype)
        instrs = []

        if node.init is not None:
            val, val_instrs = self._lower_expr(node.init)
            instrs.extend(val_instrs)
            # Add to function locals
            if self.builder:
                self.builder.func.locals.append(_vv(node.name, ctype))
            instrs.append(IRCopy(val, _vv(node.name, ctype)))
        else:
            if self.builder:
                self.builder.func.locals.append(_vv(node.name, ctype))

        return instrs

    # ─────────────────────────────────────────
    #  PRINT
    # ─────────────────────────────────────────

    def _lower_print(self, node: PrintStmt) -> List:
        val, val_instrs = self._lower_expr(node.value)
        instrs = []
        instrs.extend(val_instrs)

        func = 'Serial.println' if node.newline else 'Serial.print'

        # String interpolation
        if isinstance(node.value, Literal) and node.value.vtype == 'str':
            s = node.value.value
            import re
            parts = re.split(r'\{([^{}]+)\}', s)
            if len(parts) > 1:
                # Interpolated string: emit Serial.print for each segment
                for i, part in enumerate(parts):
                    if not part:
                        continue
                    if i % 2 == 0:
                        # Static string segment
                        f = func if i == len(parts) - 1 else 'Serial.print'
                        instrs.append(IRCall(f, [_cv(part, 'str')], dest=None))
                    else:
                        # Interpolated expression
                        f = func if i == len(parts) - 1 else 'Serial.print'
                        # Handle member access: obj.field
                        if '.' in part or '[' in part:
                            # Emit as raw expression via IRCallIndirect
                            instrs.append(IRCallIndirect(
                                func_expr=f'{f}({part})', args=[], dest=None,
                            ))
                        elif re.match(r'^[\w_]+$', part):
                            # Simple variable name
                            instrs.append(IRCall(f, [_vv(part, 'int')], dest=None))
                        else:
                            # Complex expression — emit as literal for now
                            # (parser should pre-parse these in the future)
                            instrs.append(IRCall(f, [_cv(f'({part})', 'str')], dest=None))
                return instrs

        instrs.append(IRCall(func, [val], dest=None))
        return instrs

    # ─────────────────────────────────────────
    #  PWM
    # ─────────────────────────────────────────

    def _lower_pwm_write(self, node: PwmWrite) -> List:
        if node.pin in self._pwm_pins:
            ch = self._pwm_pins[node.pin]['channel']
            val, val_instrs = self._lower_expr(node.value)
            instrs = []
            instrs.extend(val_instrs)
            instrs.append(IRCall('ledcWrite', [
                _cv(ch, 'uint8_t'),
                val,
            ], dest=None))
            return instrs
        return []

    def _lower_pwm_setup(self, node: PwmSetup) -> List:
        # Already handled at top level
        return []

    # ─────────────────────────────────────────
    #  STOP
    # ─────────────────────────────────────────

    def _lower_stop(self, node: StopStmt) -> List:
        if node.label in self._every_labels:
            active_var = self._every_labels[node.label]
            return [IRCopy(_cv(0, 'int'), _gv(active_var, 'int'))]
        return []

    def _lower_start(self, node: StartStmt) -> List:
        """start timer_label; → set active flag to 1."""
        if node.label in self._every_labels:
            active_var = self._every_labels[node.label]
            return [IRCopy(_cv(1, 'int'), _gv(active_var, 'int'))]
        return []

    # ─────────────────────────────────────────
    #  EXPRESSION LOWERING
    # ─────────────────────────────────────────

    def _get_ctype(self, node) -> str:
        """Determine the C type for an AST expression node.

        Uses semantic analysis annotations (_resolved_type) when available,
        falls back to vtype string or 'int'.
        """
        # Check for semantic type annotation (set by SemanticAnalyzer Pass 3)
        resolved = getattr(node, '_resolved_type', None)
        if resolved is not None and hasattr(resolved, 'c_type'):
            return resolved.c_type()
        # Fallback: check vtype attribute
        if hasattr(node, 'vtype') and node.vtype:
            return to_ctype(node.vtype)
        # Default for comparisons and untyped nodes
        return 'int'

    def _lower_expr(self, node: Any, dest: Optional[IRValue] = None) -> Tuple[IRValue, List]:
        """Lower an expression. Returns (value, instructions).
        If *dest* is provided, result is stored there.
        """
        # Track source line for source map generation (Milestone 5)
        if hasattr(node, 'line') and node.line > 0 and self.builder:
            self.builder._current_line = node.line

        if isinstance(node, Literal):
            ctype = self._get_ctype(node)
            val = _cv(node.value, ctype)
            if dest:
                return dest, [IRCopy(val, dest)]
            return val, []

        if isinstance(node, Identifier):
            ctype = self._get_ctype(node)
            v = _vv(node.name, ctype)
            if dest:
                return dest, [IRCopy(v, dest)]
            return v, []

        if isinstance(node, MillisExpr):
            temp = dest or self.builder.new_temp('millis', 'unsigned long')
            return temp, [IRCall('millis', [], dest=temp)]

        if isinstance(node, MathExpr):
            ctype = self._math_result_type(node.func, node.args)
            temp = dest or self.builder.new_temp('math', ctype)
            self.module.uses_math = True
            args = []
            arg_instrs = []
            for a in node.args:
                av, ai = self._lower_expr(a)
                args.append(av)
                arg_instrs.extend(ai)
            instrs = []
            instrs.extend(arg_instrs)
            instrs.append(IRCall(node.func, args, dest=temp))
            return temp, instrs

        if isinstance(node, CastExpr):
            ct = to_ctype(node.target_type)
            val, val_instrs = self._lower_expr(node.expr)
            temp = dest or self.builder.new_temp('cast', ct)
            instrs = []
            instrs.extend(val_instrs)
            instrs.append(IRCast(val, temp, ct))
            return temp, instrs

        if isinstance(node, SizeOfExpr):
            if isinstance(node.target, str):
                ct = to_ctype(node.target)
                temp = dest or self.builder.new_temp('sizeof', 'int')
                # sizeof is compile-time, emit as constant
                return _cv(f'sizeof({ct})', 'int'), []
            # expression-sized: can't evaluate at IR level, emit as call
            val, val_instrs = self._lower_expr(node.target)
            temp = dest or self.builder.new_temp('sizeof', 'int')
            instrs = []
            instrs.extend(val_instrs)
            instrs.append(IRCallIndirect(
                func_expr=f'sizeof({val.name})',
                args=[], dest=temp,
            ))
            return temp, instrs

        if isinstance(node, BinOp):
            return self._lower_binop(node, dest)

        if isinstance(node, UnaryOp):
            return self._lower_unary(node, dest)

        if isinstance(node, MemberAccess):
            ctype = self._get_ctype(node)
            # Handle raw-string obj (parser stores obj as str for simple cases)
            if isinstance(node.obj, str):
                obj_name = node.obj
                # WiFi property access: map to internal C variable name
                if obj_name in self._wifi_names:
                    wifi_prop_map = {
                        'state':     f'_iotift_wifi_{obj_name}_state',
                        'connected': f'_iotift_wifi_{obj_name}_connected',
                        'ip':        f'_iotift_wifi_{obj_name}_ip',
                        'rssi':      f'_iotift_wifi_{obj_name}_rssi',
                        'channel':   f'_iotift_wifi_{obj_name}_channel',
                        'mac':       f'_iotift_wifi_{obj_name}_mac',
                        'clients':   f'_iotift_wifi_{obj_name}_client_count',
                    }
                    if node.member in wifi_prop_map:
                        mapped_name = wifi_prop_map[node.member]
                        # Return as a variable reference to the internal C var
                        v = _vv(mapped_name, ctype)
                        if dest:
                            return dest, [IRCopy(v, dest)]
                        return v, []
                obj = _vv(obj_name, ctype)
                obj_instrs = []
            else:
                obj, obj_instrs = self._lower_expr(node.obj)
            temp = dest or self.builder.new_temp('member', ctype)
            instrs = []
            instrs.extend(obj_instrs)
            instrs.append(IRMemberAccess(obj, node.member, temp))
            return temp, instrs

        if isinstance(node, ArrayAccess):
            ctype = self._get_ctype(node)
            idx, idx_instrs = self._lower_expr(node.index)
            temp = dest or self.builder.new_temp('elem', ctype)
            instrs = []
            instrs.extend(idx_instrs)
            base = _vv(node.name, ctype)
            instrs.append(IRArrayAccess(base, idx, temp))
            return temp, instrs

        if isinstance(node, FnCall):
            ctype = self._get_ctype(node)
            args = []
            instrs = []
            for a in node.args:
                av, ai = self._lower_expr(a)
                args.append(av)
                instrs.extend(ai)
            temp = dest or self.builder.new_temp('call', ctype)
            # Map Iotift stdlib functions
            c_name = self._map_fn_name(node.name)
            # Track math function usage
            if c_name in ('sin', 'cos', 'tan', 'sqrt', 'pow', 'floor', 'ceil',
                          'round', 'log', 'exp', 'fabs', 'abs'):
                self.module.uses_math = True
            instrs.append(IRCall(c_name, args, dest=temp))
            return temp, instrs

        if isinstance(node, MethodCall):
            ctype = self._get_ctype(node)
            # Check if this is a pin method call (e.g., LED.toggle(), TEMP.read())
            obj_name = node.obj if isinstance(node.obj, str) else node.obj.name if hasattr(node.obj, 'name') else ''
            if obj_name in self._pins:
                return self._lower_pin_method(obj_name, node.method, node.args, dest)
            # Check if this is a WiFi method call (e.g., scanner.scan())
            if obj_name in self._wifi_names:
                return self._lower_wifi_method(obj_name, node.method, node.args, dest)

            obj, obj_instrs = self._lower_expr(node.obj)
            args = []
            arg_instrs = []
            for a in node.args:
                av, ai = self._lower_expr(a)
                args.append(av)
                arg_instrs.extend(ai)
            instrs = []
            instrs.extend(obj_instrs)
            instrs.extend(arg_instrs)
            temp = dest or self.builder.new_temp('call', ctype)
            arg_strs = ', '.join(a.name for a in args)
            instrs.append(IRCallIndirect(
                func_expr=f'{obj.name}.{node.method}({arg_strs})',
                args=args, dest=temp,
            ))
            return temp, instrs

        if isinstance(node, (int, float)):
            ctype = 'float' if isinstance(node, float) else 'int'
            val = _cv(node, ctype)
            if dest:
                return dest, [IRCopy(val, dest)]
            return val, []

        if isinstance(node, str):
            val = _cv(node, 'str')
            if dest:
                return dest, [IRCopy(val, dest)]
            return val, []

        # Fallback: string representation
        val = _cv(str(node), 'int')
        if dest:
            return dest, [IRCopy(val, dest)]
        return val, []

    def _lower_binop(self, node: BinOp, dest: Optional[IRValue] = None) -> Tuple[IRValue, List]:
        left, left_instrs = self._lower_expr(node.left)
        right, right_instrs = self._lower_expr(node.right)

        # Determine type from semantic analysis, fallback to operand types
        ctype = self._get_ctype(node)

        # If semantic analysis didn't provide a specific type, infer from operands.
        # Prefer the wider type to avoid truncation (e.g., int * float → float).
        if ctype == 'int' and (left.ctype == 'float' or right.ctype == 'float'):
            ctype = 'float'
        elif ctype == 'float' and (left.ctype == 'double' or right.ctype == 'double'):
            ctype = 'double'

        temp = dest or self.builder.new_temp('binop', ctype)
        instrs = []
        instrs.extend(left_instrs)
        instrs.extend(right_instrs)

        # Map Iotift operators to C operators
        c_op = node.op  # Most ops are identical in C

        instrs.append(IRBinary(c_op, left, right, temp))
        return temp, instrs

    def _lower_unary(self, node: UnaryOp, dest: Optional[IRValue] = None) -> Tuple[IRValue, List]:
        operand, op_instrs = self._lower_expr(node.operand)
        ctype = self._get_ctype(node)
        temp = dest or self.builder.new_temp('unary', ctype)
        instrs = []
        instrs.extend(op_instrs)
        instrs.append(IRUnary(node.op, operand, temp))
        return temp, instrs

    # ─────────────────────────────────────────
    #  HELPERS
    # ─────────────────────────────────────────

    def _lower_pin_method(self, pin_name: str, method: str, args: List, dest: Optional[IRValue] = None) -> Tuple[IRValue, List]:
        """Lower a pin method call (e.g., LED.toggle()) to correct Arduino HAL calls."""
        pin_node = self._pins.get(pin_name)
        pin_dir = pin_node.direction if pin_node else 'output'
        instrs = []

        if method == 'high':
            temp = dest or self.builder.new_temp('call', 'int')
            instrs.append(IRCallIndirect(
                func_expr=f'digitalWrite({pin_name}_PIN, HIGH)',
                args=[], dest=temp,
            ))
            return temp, instrs
        elif method == 'low':
            temp = dest or self.builder.new_temp('call', 'int')
            instrs.append(IRCallIndirect(
                func_expr=f'digitalWrite({pin_name}_PIN, LOW)',
                args=[], dest=temp,
            ))
            return temp, instrs
        elif method == 'toggle':
            temp = dest or self.builder.new_temp('call', 'int')
            instrs.append(IRCallIndirect(
                func_expr=f'digitalWrite({pin_name}_PIN, !digitalRead({pin_name}_PIN))',
                args=[], dest=temp,
            ))
            return temp, instrs
        elif method == 'read':
            if pin_dir == 'analog':
                temp = dest or self.builder.new_temp('call', 'int')
                instrs.append(IRCall('analogRead', [_cv(pin_name + '_PIN', 'uint8_t')], dest=temp))
                return temp, instrs
            else:
                temp = dest or self.builder.new_temp('call', 'int')
                instrs.append(IRCall('digitalRead', [_cv(pin_name + '_PIN', 'uint8_t')], dest=temp))
                return temp, instrs
        elif method == 'write':
            arg_vals = []
            for a in args:
                av, ai = self._lower_expr(a)
                arg_vals.append(av)
                instrs.extend(ai)
            if pin_dir == 'pwm' and pin_name in self._pwm_pins:
                ch = self._pwm_pins[pin_name]['channel']
                temp = dest or self.builder.new_temp('call', 'int')
                instrs.append(IRCall('ledcWrite', [_cv(ch, 'uint8_t')] + arg_vals, dest=temp))
                return temp, instrs
            elif pin_dir == 'analog':
                # analogWrite is not available on ESP32; use ledc for PWM-capable pins
                temp = dest or self.builder.new_temp('call', 'int')
                instrs.append(IRCallIndirect(
                    func_expr=f'dacWrite({pin_name}_PIN, {arg_vals[0].name if arg_vals else "0"})',
                    args=arg_vals, dest=temp,
                ))
                return temp, instrs
            else:
                temp = dest or self.builder.new_temp('call', 'int')
                instrs.append(IRCall('digitalWrite', [
                    _cv(pin_name + '_PIN', 'uint8_t'),
                    arg_vals[0] if arg_vals else _cv(0, 'int'),
                ], dest=temp))
                return temp, instrs

        # Fallback for unknown methods
        temp = dest or self.builder.new_temp('call', 'int')
        instrs.append(IRCallIndirect(
            func_expr=f'{pin_name}.{method}()',
            args=[], dest=temp,
        ))
        return temp, instrs

    def _lower_wifi_method(self, wifi_name: str, method: str, args: List, dest: Optional[IRValue] = None) -> Tuple[IRValue, List]:
        """Lower a WiFi method call (e.g., scanner.scan()) to correct C function calls."""
        instrs = []
        temp = dest or self.builder.new_temp('call', 'int')

        if method == 'scan':
            instrs.append(IRCallIndirect(
                func_expr=f'_iotift_wifi_{wifi_name}_scan_start()',
                args=[], dest=temp,
            ))
        elif method == 'disconnect':
            instrs.append(IRCallIndirect(
                func_expr=f'_iotift_wifi_{wifi_name}_disconnect()',
                args=[], dest=temp,
            ))
        else:
            # Fallback
            instrs.append(IRCallIndirect(
                func_expr=f'{wifi_name}.{method}()',
                args=[], dest=temp,
            ))

        return temp, instrs

    def _is_truthy(self, value_node: Any) -> bool:
        """Check if a value node represents a truthy constant."""
        if isinstance(value_node, Literal):
            if value_node.vtype == 'bool':
                return bool(value_node.value)
            if value_node.vtype == 'int':
                return int(value_node.value) != 0
        if isinstance(value_node, UnaryOp) and value_node.op == '!':
            return not self._is_truthy(value_node.operand)
        return False

    def _body_has_assign_after(self, nodes: List[Node]) -> bool:
        """Check if any node in the list (recursively) contains AssignAfter."""
        for node in (nodes or []):
            if isinstance(node, AssignAfter):
                return True
            if isinstance(node, IfStmt):
                if (self._body_has_assign_after(node.then_body)
                        or self._body_has_assign_after(node.else_body or [])
                        or any(self._body_has_assign_after(b) for _, b in node.elif_clauses)):
                    return True
            elif isinstance(node, (WhileStmt, ForStmt, LoopBlock, EveryBlock, VoidLoop, FnDecl, TickBlock)):
                if self._body_has_assign_after(getattr(node, 'body', [])):
                    return True
        return False

    def _map_fn_name(self, name: str) -> str:
        """Map Iotift function names to C equivalents."""
        mapping = {
            'esp_restart': 'ESP.restart',
            'millis': 'millis',
            'micros': 'micros',
            'delay': 'delay',
        }
        return mapping.get(name, name)

    def _lower_expr_const(self, node: Any) -> Any:
        """Evaluate a constant expression (for pin configs, etc.)."""
        if isinstance(node, Literal):
            return node.value
        if isinstance(node, (int, float)):
            return node
        return str(node)

    def _math_result_type(self, func: str, args: List) -> str:
        """Determine the result type of a math function."""
        float_funcs = {'sin', 'cos', 'tan', 'sqrt', 'pow', 'floor', 'ceil', 'round', 'log', 'exp', 'fabs'}
        int_funcs = {'abs'}
        if func in float_funcs:
            return 'float'
        if func in int_funcs:
            return 'int'
        return 'int'
