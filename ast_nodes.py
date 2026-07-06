"""
IOTIFT AST Nodes — Milestone 0 working set (~35 node types).

Every language construct maps to exactly one dataclass here.
Zero logic, zero imports beyond stdlib.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Any, Tuple


# ─────────────────────────────────────────
#  BASE
# ─────────────────────────────────────────

@dataclass
class Node:
    """Base node carrying source span for error reporting."""
    line: int = field(default=0, repr=False)
    col: int = field(default=0, repr=False)
    end_line: int = field(default=0, repr=False)
    end_col: int = field(default=0, repr=False)


# ─────────────────────────────────────────
#  TOP-LEVEL
# ─────────────────────────────────────────

@dataclass
class Program(Node):
    """Root node — holds every top-level declaration."""
    body: List[Node] = field(default_factory=list)


@dataclass
class DeviceDecl(Node):
    """@device esp32"""
    name: str = ''


@dataclass
class SchedulerConfig(Node):
    """@config scheduler_slots = 16;"""
    key: str = ''          # 'scheduler_slots'
    value: Any = None      # e.g. 16


@dataclass
class ImportDecl(Node):
    """import "file.iot";  or  import { Name1, Name2 } from "file.iot";"""
    path: str = ''
    selected_names: Optional[List[str]] = None  # None = import all


# ─────────────────────────────────────────
#  RAW C INJECTION
# ─────────────────────────────────────────

@dataclass
class CBlockNode(Node):
    """
    c <scope> { ... }
    scope is one of: header | global | setup | loop | isr
    """
    scope: str = ''
    code: str = ''


# ─────────────────────────────────────────
#  DECLARATIONS
# ─────────────────────────────────────────

@dataclass
class PinConfig(Node):
    """Configuration for a pin declaration."""
    pull: Optional[str] = None        # 'up' | 'down' | 'none'
    debounce_ms: Optional[int] = None
    initial: Optional[Any] = None     # initial output value


@dataclass
class PinDecl(Node):
    """
    pin LED = output 2;
    pin BTN = input 5 { pull: up, debounce: 50ms };
    pin R   = pwm 13 freq 5000 resolution 8;
    """
    name: str = ''
    direction: str = ''          # output | input | analog | i2c | spi | pwm
    number: int = 0
    config: PinConfig = field(default_factory=PinConfig)
    pwm_freq: Optional[int] = None
    pwm_resolution: Optional[int] = None


@dataclass
class VarDecl(Node):
    """
    int count = 0;               // old-style (vtype required)
    let count = 0;               // new-style immutable, type inferred
    var temp: f32 = 25.5;        // new-style mutable, explicit type
    const MAX_TEMP = 100;        // compile-time constant
    """
    name: str = ''
    vtype: Optional[str] = None        # type annotation (may be None for let inference)
    init: Any = None                   # initializer expression
    is_const: bool = False             # compile-time constant
    is_mutable: bool = True            # let (false) vs var/old-style (true)
    is_volatile: bool = False          # volatile qualifier


@dataclass
class ArrayDecl(Node):
    """int vals[10];   or   let readings: [10]i16;"""
    name: str = ''
    vtype: Optional[str] = None
    elem_type: Optional[str] = None
    size: int = 0
    init: Optional[Any] = None
    is_mutable: bool = True


@dataclass
class StructDecl(Node):
    """
    struct Sensor {
        id: u32,
        value: f32,
    }
    """
    name: str = ''
    fields: List[VarDecl] = field(default_factory=list)


@dataclass
class FnDecl(Node):
    """
    fn blink(times: u32) -> bool { ... }
    isr fn on_timer() { ... }
    """
    name: str = ''
    params: List[VarDecl] = field(default_factory=list)
    return_type: Optional[str] = None
    body: List[Node] = field(default_factory=list)
    is_void: bool = True
    is_extern: bool = False
    is_isr: bool = False


@dataclass
class ExternFnDecl(Node):
    """extern fn esp_restart();"""
    name: str = ''
    params: List[VarDecl] = field(default_factory=list)
    return_type: Optional[str] = None


@dataclass
class EnumDecl(Node):
    """
    enum Mode {
        WarmWhite,
        Rainbow = 5,
        Breathing,
    }
    """
    name: str = ''
    variants: List[Tuple[str, Optional[int]]] = field(default_factory=list)
    backing_type: Optional[str] = None   # e.g. 'u8'


@dataclass
class TypeAliasDecl(Node):
    """type Celsius = f32;"""
    name: str = ''
    aliased_type: str = ''


# ─────────────────────────────────────────
#  EVENTS & TIMERS
# ─────────────────────────────────────────

@dataclass
class OnEvent(Node):
    """
    on BTN.press { ... }
    on BTN.rising { ... }
    on BTN.falling { ... }
    on BTN.change { ... }
    on home.connect { ... }       // WiFi events
    on home.disconnect { ... }
    """
    target: str = ''             # pin name or wifi name (was 'pin')
    event: str = ''              # press|release|change|rising|falling
                                 #   |connect|disconnect|got_ip|scan_done
                                 #   |client_join|client_leave
    body: List[Node] = field(default_factory=list)

    # Backward-compat alias: code reading .pin gets .target
    @property
    def pin(self) -> str:
        return self.target

    @pin.setter
    def pin(self, value: str) -> None:
        self.target = value


@dataclass
class OnThreshold(Node):
    """
    on TEMP > 50.0 { ... }
    Polled analog threshold check.
    """
    pin: str = ''
    op: str = ''               # > | < | >= | <= | ==
    value: Any = None
    body: List[Node] = field(default_factory=list)


@dataclass
class EveryBlock(Node):
    """
    every 500ms { ... }
    every 1s as blinker { ... }
    every 1s offset 100ms { ... }
    """
    interval: int = 0          # milliseconds
    label: Optional[str] = None
    body: List[Node] = field(default_factory=list)
    offset_ms: Optional[int] = None   # optional first-fire delay offset


@dataclass
class LoopBlock(Node):
    """loop { ... }  —  infinite loop (generates while(1))."""
    body: List[Node] = field(default_factory=list)


@dataclass
class VoidLoop(Node):
    """void loop() { ... }  —  DEPRECATED, use tick { ... }."""
    body: List[Node] = field(default_factory=list)


@dataclass
class TickBlock(Node):
    """
    tick { ... }  —  run on each main loop iteration.
    Replaces the deprecated `void loop()`.
    """
    body: List[Node] = field(default_factory=list)


@dataclass
class AfterBlock(Node):
    """
    after 5s { ... }  —  one-shot timer block.
    Fires once after the given delay, then never again.
    """
    interval: int = 0          # milliseconds
    body: List[Node] = field(default_factory=list)


# ─────────────────────────────────────────
#  PERIPHERAL DECLARATIONS
# ─────────────────────────────────────────

@dataclass
class PeripheralDecl(Node):
    """
    i2c bus0 { sda: 21, scl: 22, speed: 100kHz };
    spi bus0 { mosi: 23, miso: 19, sck: 18, speed: 10MHz };
    uart serial1 { tx: 17, rx: 16, baud: 9600 };
    """
    periph_type: str = ''        # 'i2c' | 'spi' | 'uart'
    name: str = ''               # 'bus0', 'serial1'
    config: dict = field(default_factory=dict)


@dataclass
class WifiDecl(Node):
    """
    wifi home {
        ssid: "MyWiFi";
        password: "mypassword";
    }
    wifi office {
        mode: sta;
        ssid: "OfficeNet";
        password: "office123";
        hostname: "iotift-sensor";
        connect_timeout: 30s;
        retry: exponential;
        power_save: light;
        static_ip: "192.168.1.100";
        gateway: "192.168.1.1";
        subnet: "255.255.255.0";
        dns: "8.8.8.8";
    }
    """
    name: str = ''
    mode: str = 'sta'            # 'sta' | 'ap'
    config: dict = field(default_factory=dict)
    # config keys: ssid, password, hostname, connect_timeout, retry,
    #              power_save, static_ip, gateway, subnet, dns,
    #              channel, max_clients, hidden


# ─────────────────────────────────────────
#  STATEMENTS
# ─────────────────────────────────────────

@dataclass
class Assign(Node):
    """
    count = 10;
    LED = 1;
    target is str, ArrayAccess, or MemberAccess.
    """
    target: Any = ''             # str | ArrayAccess | MemberAccess
    value: Any = None


@dataclass
class AssignAfter(Node):
    """LED = 0 after 200;"""
    target: str = ''
    value: Any = None
    delay: int = 0


@dataclass
class CompoundAssign(Node):
    """count += 1;   /   total -= 5;"""
    target: str = ''
    op: str = ''                # += | -= | *= | /= | %= | &= | |= | ^=
    value: Any = None


@dataclass
class IfStmt(Node):
    """if (cond) { ... } else if (cond) { ... } else { ... }"""
    condition: Any = None
    then_body: List[Node] = field(default_factory=list)
    elif_clauses: List[Tuple[Any, List[Node]]] = field(default_factory=list)
    else_body: Optional[List[Node]] = None


@dataclass
class WhileStmt(Node):
    """while (cond) { ... }"""
    condition: Any = None
    body: List[Node] = field(default_factory=list)


@dataclass
class ForStmt(Node):
    """for (let i = 0; i < 10; i += 1) { ... }"""
    init: Optional[Node] = None
    condition: Any = None
    step: Optional[Node] = None
    body: List[Node] = field(default_factory=list)


@dataclass
class ReturnStmt(Node):
    """return;  /  return expr;"""
    value: Any = None


@dataclass
class BreakStmt(Node):
    """break;"""
    pass


@dataclass
class ContinueStmt(Node):
    """continue;"""
    pass


@dataclass
class StopStmt(Node):
    """stop blinker;  —  halts a named every-block."""
    label: str = ''


@dataclass
class StartStmt(Node):
    """start blinker;  —  resumes a named every-block."""
    label: str = ''


@dataclass
class PrintStmt(Node):
    """
    print("hello");
    println("done");
    """
    value: Any = None
    newline: bool = True


@dataclass
class DeferStmt(Node):
    """defer { cleanup(); }  —  run when exiting current block."""
    body: List[Node] = field(default_factory=list)


@dataclass
class ExprStmt(Node):
    """Bare expression as statement: fn_call();"""
    expr: Any = None


# ─────────────────────────────────────────
#  EXPRESSIONS
# ─────────────────────────────────────────

@dataclass
class BinOp(Node):
    """a + b,  count == 10,  flag && ready"""
    left: Any = None
    op: str = ''
    right: Any = None


@dataclass
class UnaryOp(Node):
    """!flag,  -x,  ~mask"""
    op: str = ''
    operand: Any = None


@dataclass
class MemberAccess(Node):
    """temp.value   /   sensor.id"""
    obj: Any = ''               # str or nested expression
    member: str = ''


@dataclass
class ArrayAccess(Node):
    """vals[0]   /   readings[i + 1]"""
    name: str = ''              # array variable name
    index: Any = None


@dataclass
class Literal(Node):
    """42, 3.14, "hello", true, 'A'"""
    vtype: str = ''             # int | float | bool | str | char | u8 | i32 | ...
    value: Any = None


@dataclass
class Identifier(Node):
    """Bare variable/function reference."""
    name: str = ''


@dataclass
class FnCall(Node):
    """blink(3);   /   sensor.read();"""
    name: str = ''               # or dotted path like "sensor.read"
    args: List[Any] = field(default_factory=list)


@dataclass
class MethodCall(Node):
    """obj.method(args)  —  generic method dispatch."""
    obj: Any = None              # expression
    method: str = ''
    args: List[Any] = field(default_factory=list)


@dataclass
class PwmSetup(Node):
    """R.setup(freq, resolution);"""
    pin: str = ''
    freq: Any = None
    resolution: Any = None


@dataclass
class PwmWrite(Node):
    """R.write(duty);"""
    pin: str = ''
    value: Any = None


@dataclass
class MillisExpr(Node):
    """millis()  —  returns ms since boot."""
    pass


@dataclass
class MathExpr(Node):
    """sin(x),  pow(base, exp),  sqrt(val)  —  via stdlib."""
    func: str = ''
    args: List[Any] = field(default_factory=list)


@dataclass
class CastExpr(Node):
    """value as u8   /   temp as i32"""
    expr: Any = None
    target_type: str = ''


@dataclass
class SizeOfExpr(Node):
    """sizeof(i32)  /  sizeof(my_var)"""
    target: Any = None           # type name str or expression
