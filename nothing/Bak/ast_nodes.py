"""
IOTIFT AST Nodes
Every construct in the language maps to one of these dataclasses.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Any


# ─────────────────────────────────────────
#  BASE
# ─────────────────────────────────────────

@dataclass
class Node:
    line: int = field(default=0, repr=False)


# ─────────────────────────────────────────
#  TOP-LEVEL
# ─────────────────────────────────────────

@dataclass
class Program(Node):
    body: List[Node] = field(default_factory=list)

@dataclass
class DeviceDecl(Node):       # @device esp32
    name: str = ''

@dataclass
class ImportDecl(Node):       # import "file.iot";
    path: str = ''


# ─────────────────────────────────────────
#  DECLARATIONS
# ─────────────────────────────────────────

@dataclass
class PinDecl(Node):          # pin LED = output 12;
    name      : str = ''
    direction : str = ''      # output | input | analog | i2c | spi | pwm
    number    : int = 0

@dataclass
class VarDecl(Node):          # int count = 0;
    vtype : str = ''          # int | float | bool | str
    name  : str = ''
    init  : Optional[Any] = None
    is_const: bool = False

@dataclass
class StructDecl(Node):       # struct Sensor { ... }
    name   : str = ''
    fields : List[VarDecl] = field(default_factory=list)

@dataclass
class FnDecl(Node):           # fn blink(int times) { ... }
    name       : str = ''
    params     : List[VarDecl] = field(default_factory=list)
    return_type: Optional[str] = None
    body       : List[Node] = field(default_factory=list)
    is_void    : bool = True

@dataclass
class ExternFnDecl(Node):     # extern fn esp_restart();
    name   : str = ''
    params : List[VarDecl] = field(default_factory=list)
    return_type: Optional[str] = None


# ─────────────────────────────────────────
#  EVENTS & TIMERS
# ─────────────────────────────────────────

@dataclass
class OnEvent(Node):          # on BTN.press { ... }
    pin    : str = ''
    event  : str = ''         # press | release | change
    body   : List[Node] = field(default_factory=list)

@dataclass
class OnThreshold(Node):      # on TEMP > 50.0 { ... }
    pin   : str = ''
    op    : str = ''
    value : Any = None
    body  : List[Node] = field(default_factory=list)

@dataclass
class EveryBlock(Node):       # every 1000 { ... }  /  every 1000 as ticker { ... }
    interval : int = 0        # ms
    label    : Optional[str] = None
    body     : List[Node] = field(default_factory=list)

@dataclass
class LoopBlock(Node):        # loop { ... }
    body: List[Node] = field(default_factory=list)

@dataclass
class VoidLoop(Node):         # void loop() { ... }
    body: List[Node] = field(default_factory=list)


# ─────────────────────────────────────────
#  STATEMENTS
# ─────────────────────────────────────────

@dataclass
class Assign(Node):           # count = 10;   LED = 1;
    target : str = ''
    value  : Any = None

@dataclass
class AssignAfter(Node):      # LED = 0 after 200;
    target : str = ''
    value  : Any = None
    delay  : int = 0

@dataclass
class CompoundAssign(Node):   # count += 1;
    target : str = ''
    op     : str = ''         # += -= *= /=
    value  : Any = None

@dataclass
class IfStmt(Node):
    condition : Any = None
    then_body : List[Node] = field(default_factory=list)
    elif_clauses: List[tuple] = field(default_factory=list)  # [(cond, body), ...]
    else_body : Optional[List[Node]] = None

@dataclass
class WhileStmt(Node):
    condition : Any = None
    body      : List[Node] = field(default_factory=list)

@dataclass
class ForStmt(Node):
    init      : Optional[Node] = None
    condition : Any = None
    step      : Optional[Node] = None
    body      : List[Node] = field(default_factory=list)

@dataclass
class ReturnStmt(Node):
    value: Any = None

@dataclass
class BreakStmt(Node):
    pass

@dataclass
class ContinueStmt(Node):
    pass

@dataclass
class StopStmt(Node):         # stop ticker;
    label: str = ''

@dataclass
class PrintStmt(Node):        # print("hello");
    value: Any = None

@dataclass
class FnCall(Node):           # esp_restart();  blink(3);
    name : str = ''
    args : List[Any] = field(default_factory=list)


# ─────────────────────────────────────────
#  EXPRESSIONS
# ─────────────────────────────────────────

@dataclass
class BinOp(Node):            # a + b,  count == 10
    left  : Any = None
    op    : str = ''
    right : Any = None

@dataclass
class UnaryOp(Node):          # !flag,  -x
    op    : str = ''
    operand: Any = None

@dataclass
class MemberAccess(Node):     # temp.value,  TEMP.read()
    obj    : str = ''
    member : str = ''

@dataclass
class ArrayAccess(Node):      # vals[0]
    name  : str = ''
    index : Any = None

@dataclass
class ArrayDecl(Node):        # int vals[10];
    vtype : str = ''
    name  : str = ''
    size  : int = 0

@dataclass
class Literal(Node):
    vtype : str = ''          # int | float | bool | str
    value : Any = None

@dataclass
class Identifier(Node):
    name: str = ''
