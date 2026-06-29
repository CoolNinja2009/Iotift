"""
IOTIFT Intermediate Representation — Milestone 2

Three-Address Code (TAC) IR between AST and C codegen.
Enables optimization passes before final code emission.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Any, Dict, Union


# ─────────────────────────────────────────
#  IR VALUES
# ─────────────────────────────────────────

@dataclass
class IRValue:
    """A value in the IR — temp, constant, variable, global, or label."""
    kind: str        # 'temp' | 'const' | 'var' | 'global' | 'label' | 'param' | 'void'
    name: str = ''
    ctype: str = ''  # C type (int, float, uint8_t, etc.)
    const_value: Any = None  # For 'const' kind: the compile-time value

    def __repr__(self) -> str:
        if self.kind == 'const':
            return f'{self.const_value}'
        if self.kind == 'void':
            return 'void'
        return self.name

    def __hash__(self):
        return hash((self.kind, self.name, id(self)))

    def __eq__(self, other):
        if not isinstance(other, IRValue):
            return False
        return self.kind == other.kind and self.name == other.name and self is other


# Factory helpers
def _tv(name: str, ctype: str = 'int') -> IRValue:
    """Create a temp value."""
    return IRValue('temp', name, ctype)

def _cv(value: Any, ctype: str = 'int') -> IRValue:
    """Create a constant value."""
    return IRValue('const', str(value), ctype, const_value=value)

def _vv(name: str, ctype: str = 'int') -> IRValue:
    """Create a variable reference."""
    return IRValue('var', name, ctype)

def _gv(name: str, ctype: str = 'int') -> IRValue:
    """Create a global variable reference."""
    return IRValue('global', name, ctype)

def _pv(name: str, ctype: str = 'int') -> IRValue:
    """Create a parameter reference."""
    return IRValue('param', name, ctype)

def _lv(name: str) -> IRValue:
    """Create a label reference."""
    return IRValue('label', name)

def _void() -> IRValue:
    """Void value."""
    return IRValue('void')


# ─────────────────────────────────────────
#  IR INSTRUCTIONS
# ─────────────────────────────────────────

@dataclass
class IRInstr:
    """Base class for all IR instructions."""
    line: int = field(default=0, repr=False, init=False)
    col: int = field(default=0, repr=False, init=False)


@dataclass
class IRLabel(IRInstr):
    """A label marking a position in the instruction stream."""
    label: str = field(default='')


@dataclass
class IRBinary(IRInstr):
    """dest = left op right"""
    op: str = field(default='')
    left: IRValue = field(default_factory=_void)
    right: IRValue = field(default_factory=_void)
    dest: IRValue = field(default_factory=_void)


@dataclass
class IRUnary(IRInstr):
    """dest = op operand"""
    op: str = field(default='')
    operand: IRValue = field(default_factory=_void)
    dest: IRValue = field(default_factory=_void)


@dataclass
class IRCopy(IRInstr):
    """dest = src"""
    src: IRValue = field(default_factory=_void)
    dest: IRValue = field(default_factory=_void)


@dataclass
class IRLoad(IRInstr):
    """dest = *src (load from memory)"""
    src: IRValue = field(default_factory=_void)
    dest: IRValue = field(default_factory=_void)


@dataclass
class IRStore(IRInstr):
    """*dest = src (store to memory)"""
    src: IRValue = field(default_factory=_void)
    dest: IRValue = field(default_factory=_void)


@dataclass
class IRCall(IRInstr):
    """dest = func(args...)"""
    func: str = field(default='')
    args: List[IRValue] = field(default_factory=list)
    dest: Optional[IRValue] = field(default=None)


@dataclass
class IRCallIndirect(IRInstr):
    """dest = (*func_ptr)(args...)  —  for method calls, HAL calls"""
    func_expr: str = field(default='')
    args: List[IRValue] = field(default_factory=list)
    dest: Optional[IRValue] = field(default=None)


@dataclass
class IRBranch(IRInstr):
    """if cond goto true_label else goto false_label"""
    cond: IRValue = field(default_factory=_void)
    true_label: str = field(default='')
    false_label: str = field(default='')


@dataclass
class IRJump(IRInstr):
    """goto label"""
    label: str = field(default='')


@dataclass
class IRReturn(IRInstr):
    """return value"""
    value: Optional[IRValue] = field(default=None)


@dataclass
class IRCast(IRInstr):
    """dest = (ctype) src"""
    src: IRValue = field(default_factory=_void)
    dest: IRValue = field(default_factory=_void)
    target_type: str = field(default='')


@dataclass
class IRArrayAccess(IRInstr):
    """dest = base[index]"""
    base: IRValue = field(default_factory=_void)
    index: IRValue = field(default_factory=_void)
    dest: IRValue = field(default_factory=_void)


@dataclass
class IRMemberAccess(IRInstr):
    """dest = obj.member"""
    obj: IRValue = field(default_factory=_void)
    member: str = field(default='')
    dest: IRValue = field(default_factory=_void)


# ─────────────────────────────────────────
#  BASIC BLOCK
# ─────────────────────────────────────────

@dataclass
class BasicBlock:
    """A straight-line sequence of instructions ending with a terminator."""
    label: str = ''
    instructions: List[IRInstr] = field(default_factory=list)

    @property
    def terminator(self) -> Optional[IRInstr]:
        """Return the terminator instruction (Branch, Jump, Return) or None."""
        if not self.instructions:
            return None
        last = self.instructions[-1]
        if isinstance(last, (IRBranch, IRJump, IRReturn)):
            return last
        return None

    @property
    def is_terminated(self) -> bool:
        return self.terminator is not None

    def append(self, instr: IRInstr) -> None:
        self.instructions.append(instr)

    def extend(self, instrs: List[IRInstr]) -> None:
        self.instructions.extend(instrs)


# ─────────────────────────────────────────
#  IR FUNCTION
# ─────────────────────────────────────────

@dataclass
class IRFunction:
    """A function in the IR."""
    name: str = ''
    params: List[IRValue] = field(default_factory=list)
    return_type: str = 'void'
    blocks: List[BasicBlock] = field(default_factory=list)
    locals: List[IRValue] = field(default_factory=list)
    is_static: bool = True
    is_isr: bool = False
    attrs: str = ''          # e.g. 'IRAM_ATTR'
    entry_block: str = ''    # label of the first block

    @property
    def entry(self) -> Optional[BasicBlock]:
        for b in self.blocks:
            if b.label == self.entry_block:
                return b
        return self.blocks[0] if self.blocks else None

    def add_block(self, block: BasicBlock) -> None:
        self.blocks.append(block)

    def new_block(self, label: str) -> BasicBlock:
        bb = BasicBlock(label=label)
        self.blocks.append(bb)
        return bb

    def all_instructions(self) -> List[IRInstr]:
        """Yield all instructions across all blocks."""
        result = []
        for bb in self.blocks:
            result.extend(bb.instructions)
        return result


# ─────────────────────────────────────────
#  IR GLOBALS
# ─────────────────────────────────────────

@dataclass
class IRGlobal:
    """A global variable or constant declaration."""
    name: str = ''
    ctype: str = 'int'
    init: Optional[Any] = None
    is_const: bool = False
    is_static: bool = True
    is_volatile: bool = False
    is_pin: bool = False
    pin_number: int = 0


@dataclass
class IRStruct:
    """A struct type definition."""
    name: str = ''
    fields: List[IRValue] = field(default_factory=list)


@dataclass
class IREnum:
    """An enum type definition."""
    name: str = ''
    backing_type: str = 'int'
    variants: List[Any] = field(default_factory=list)  # List[(name, optional_value)]


@dataclass
class IRTypeAlias:
    """A typedef."""
    name: str = ''
    aliased_type: str = ''


# ─────────────────────────────────────────
#  IR MODULE  (top-level container)
# ─────────────────────────────────────────

@dataclass
class IRModule:
    """Top-level IR container representing a complete Iotift program."""

    # Target
    device: str = 'esp32'
    baud_rate: int = 115200
    scheduler_slots: int = 16

    # Globals
    globals: List[IRGlobal] = field(default_factory=list)
    structs: List[IRStruct] = field(default_factory=list)
    enums: List[IREnum] = field(default_factory=list)
    type_aliases: List[IRTypeAlias] = field(default_factory=list)

    # Functions
    functions: List[IRFunction] = field(default_factory=list)

    # Pin registry
    pins: Dict[str, int] = field(default_factory=dict)       # name → number
    pwm_pins: Dict[str, Dict] = field(default_factory=dict)   # name → {channel, freq, resolution}
    pwm_channel: int = 0
    analog_pins: List[str] = field(default_factory=list)

    # Timer / event metadata
    every_handlers: List[Dict] = field(default_factory=list)
    on_event_handlers: List[Dict] = field(default_factory=list)
    on_threshold_handlers: List[Dict] = field(default_factory=list)

    # Hardware interrupt metadata (Phase 3)
    interrupts: List[Dict] = field(default_factory=list)
    # Each entry: {'pin': str, 'mode': str, 'isr_name': str}

    # C injection blocks
    header_blocks: List[str] = field(default_factory=list)
    global_blocks: List[str] = field(default_factory=list)
    setup_blocks: List[str] = field(default_factory=list)
    loop_blocks: List[str] = field(default_factory=list)

    # Include tracking
    includes: set = field(default_factory=set)
    uses_math: bool = False

    # Scheduler
    scheduler_needed: bool = False

    # Temp counter for unique names
    _temp_counter: int = field(default=0, repr=False)
    _label_counter: int = field(default=0, repr=False)

    def new_temp(self, prefix: str = 't', ctype: str = 'int') -> IRValue:
        """Create a unique temporary variable."""
        self._temp_counter += 1
        return _tv(f'_iotift_{prefix}{self._temp_counter}', ctype)

    def new_label(self, prefix: str = 'L') -> str:
        """Create a unique label name."""
        self._label_counter += 1
        return f'_iotift_{prefix}{self._label_counter}'

    def add_function(self, fn: IRFunction) -> None:
        self.functions.append(fn)

    def add_global(self, g: IRGlobal) -> None:
        self.globals.append(g)

    def add_struct(self, s: IRStruct) -> None:
        self.structs.append(s)

    def add_enum(self, e: IREnum) -> None:
        self.enums.append(e)

    def add_type_alias(self, t: IRTypeAlias) -> None:
        self.type_aliases.append(t)

    def allocate_pwm_channel(self) -> int:
        ch = self.pwm_channel
        self.pwm_channel += 1
        return ch

    def collect_all_instructions(self) -> List[IRInstr]:
        """Return all instructions in the module (for DCE analysis)."""
        result = []
        for fn in self.functions:
            result.extend(fn.all_instructions())
        return result
