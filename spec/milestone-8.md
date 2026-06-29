# Milestone 8 — First-Class WiFi (Revised Specification)

**Status:** 📋 Reviewed & Redesigned
**Date:** 2026-06-29
**Replaces:** Original M8 spec from TODO.md session notes

---

## 0. Architecture Audit Summary

The original M8 specification contained 23 design issues across syntax, semantics,
HAL, codegen, and tooling. This revision resolves all of them. Every design change
is justified below.

### Issues Found & Resolved

| # | Category | Issue | Resolution |
|---|----------|-------|------------|
| 1 | Syntax | `=` in declaration is inconsistent with peripheral pattern | Remove `=`; use `wifi NAME { ... }` (matches `i2c NAME { ... }`) |
| 2 | Syntax | Positional string args (`"ssid" "password"`) are fragile | Named keys inside block: `ssid: "..."; password: "..."` |
| 3 | Syntax | Semicolons in options block conflict with comma convention | Use commas (consistent with pin config `{ pull: up, debounce: 50ms }`) |
| 4 | Syntax | `stap` keyword conflates STA+AP into one declaration | Separate declarations; compiler merges into WIFI_MODE_APSTA |
| 5 | API | `connect()` is a user method but should be compiler-managed | Remove `connect()`; connection is declaration-driven |
| 6 | API | `connected` (property) vs `ip()` (method) inconsistent | All read-only state is properties; methods are actions only |
| 7 | API | `rssi()` is a method but reads static state | Make `.rssi` a property |
| 8 | API | `clients` is a property but queries hardware | Keep as property (consistent with `.connected` — both query cached state) |
| 9 | API | No state machine — unpredictable behavior | Define explicit 4-state machine with documented transitions |
| 10 | Retry | Retry policy unspecified beyond `retries: 3` | Support: `none`, `fixed`, `forever`, `exponential`, `custom` |
| 11 | Events | Event ordering undefined | Full ordering guarantees documented (§7) |
| 12 | Events | `got_ip` and `connect` relationship unclear | `connect` fires after `got_ip`; `got_ip` is a separate event |
| 13 | HAL | Raw C strings returned — no structure | Structured `WifiInitBlock` dataclass; compiler composes output |
| 14 | HAL | ESP-IDF event loop concepts leak into API | HAL translates platform events → compiler-managed state updates |
| 15 | Thread Safety | Execution context undefined | All handlers run in scheduler task; ISR/FreeRTOS context forbidden |
| 16 | Memory | String lifetime unspecified | Static buffers owned by generated code; documented lifetimes |
| 17 | Multi-WiFi | Behavior with 2+ declarations unspecified | Each independent; NVS/TCPIP init shared; 2× STA = error |
| 18 | Targets | `#error` in C vs compiler error | Semantic pass catches unsupported targets before codegen |
| 19 | AST | `OnWifiEvent`, `WifiMethodCall` duplicate existing patterns | Reuse generalized `OnEvent`, `MethodCall`, `MemberAccess` |
| 20 | Keywords | `connect`, `disconnect` as full keywords | Contextual keywords (same pattern as `press`, `release`) |
| 21 | Future | No template for BLE/MQTT/HTTP/Ethernet | Explicit design philosophy for all communication peripherals |
| 22 | Options | `timeout: 30s` semantics unclear | Renamed to `connect_timeout`; documented as per-attempt timeout |
| 23 | AP | Open AP password handling implicit | `password` key simply omitted for open AP; no magic empty string |

---

## 1. Design Philosophy

WiFi is the first communication peripheral with first-class language support.
The design establishes the template that **every future communication peripheral
(BLE, MQTT, HTTP, Ethernet, Cellular) will follow**.

### Core Principles

1. **Declare, don't call.** The declaration drives all code generation.
   Users never manually call `connect()` — connection is compiler-managed.
   The one line `wifi home { ssid: "x"; password: "y"; }` generates ~150 lines
   of correct C boilerplate.

2. **Properties for state, methods for actions.**
   - Properties: `.connected`, `.ip`, `.rssi`, `.channel`, `.mac`, `.clients`, `.state`
   - Methods: `.scan()`, `.disconnect()`
   - Properties are read-only; methods perform side-effecting operations.

3. **Events over polling.**
   `on home.connect { ... }` not `if home.connected { ... }`.

4. **Compiler manages lifecycle.** The compiler owns `connect`/`disconnect`/`retry`.
   The user describes intent; the compiler generates the state machine.

5. **HAL isolates platform.** No ESP-IDF, Arduino WiFi, or FreeRTOS concepts
   leak into the Iotift language. The HAL translates platform events into
   the compiler's state machine.

6. **Compile-time configuration.** SSID, password, retry policy, hostname,
   timeout, power-save mode are known at build time. Only runtime state
   (IP, RSSI, channel) is queried from hardware.

---

## 2. Declaration Syntax

### 2.1 Basic STA (Station Mode)

The most common case. Mode defaults to `sta`.

```iot
wifi home {
    ssid: "MyWiFi";
    password: "mypassword";
}
```

This generates: NVS init, netif init, WiFi init, STA config, event loop,
connection start, retry logic, state tracking, and event dispatch — all from
three lines of user code.

### 2.2 Explicit STA with All Options

```iot
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
```

### 2.3 Open AP (Access Point, No Password)

```iot
wifi guest {
    mode: ap;
    ssid: "FreeWiFi";
    channel: 6;
    max_clients: 4;
}
```

### 2.4 Secured AP

```iot
wifi myAP {
    mode: ap;
    ssid: "MyHotspot";
    password: "ap_password";
    channel: 1;
    max_clients: 8;
}
```

### 2.5 STA + AP on Same Device (ESP32 Dual Mode)

Two separate declarations. The compiler detects both and uses `WIFI_MODE_APSTA`.

```iot
wifi sta_if { ssid: "HomeWiFi"; password: "pass"; }
wifi ap_if  { mode: ap; ssid: "IotiftAP"; password: "ap123"; }
```

Event handlers use the declaration name for isolation:
```iot
on sta_if.connect { print("STA connected!"); }
on ap_if.client_join { print("Client joined AP!"); }
```

**Why two declarations instead of `stap` keyword:**
- Separate event handlers per interface (cleaner than filtering by event type)
- Each interface has independent state, properties, and methods
- No new keyword needed
- Natural extension: future devices might support 2× STA or STA+AP+BLE
- The compiler merges them into one `WIFI_MODE_APSTA` init automatically

### 2.6 Complete Config Key Reference

| Key | Type | Default | Applicable Modes | Description |
|-----|------|---------|------------------|-------------|
| `mode` | `sta` \| `ap` | `sta` | both | Operating mode |
| `ssid` | `str` | *(required)* | both | Network name (1–32 chars) |
| `password` | `str` | *(none = open)* | both | WPA/WPA2 passphrase (8–63 chars, or omit for open) |
| `hostname` | `str` | `"iotift-<name>"` | sta | DHCP hostname |
| `connect_timeout` | time literal | `30s` | sta | Per-connection-attempt timeout |
| `retry` | retry spec | `fixed` | sta | Retry policy (see §6) |
| `power_save` | `none` \| `light` \| `deep` | `none` | sta | WiFi power save mode |
| `static_ip` | `str` | *(DHCP)* | sta | Static IPv4 address |
| `gateway` | `str` | *(DHCP)* | sta | Gateway address (requires `static_ip`) |
| `subnet` | `str` | *(DHCP)* | sta | Subnet mask (requires `static_ip`) |
| `dns` | `str` | *(DHCP)* | sta | DNS server (requires `static_ip`) |
| `channel` | `int` (1–13) | `1` | ap | WiFi channel |
| `max_clients` | `int` (1–16) | `4` | ap | Maximum connected stations |
| `hidden` | `bool` | `false` | ap | Hide SSID in beacon |

### 2.7 Design Justification: Block vs `= sta "ssid" "pass"`

The original spec proposed:
```iot
wifi home = sta "MyWiFi" "mypassword";
```

This was rejected because:

| Concern | Block syntax solution |
|---------|----------------------|
| Positional strings are fragile (swap SSID/password?) | Named keys: `ssid: "x"; password: "y"` |
| Cannot omit password for open AP without ambiguity | Simply omit the `password` key |
| Adding new options requires changing positional order | Add new key anywhere in block |
| `=` suggests assignment, not declaration | No `=` — matches `i2c bus0 { ... }` pattern |
| Mode buried after `=` | `mode` key or default `sta` |
| Future extensions (WPA3, cert auth) don't fit | Add new keys; block syntax scales |

---

## 3. Properties

All WiFi state is accessed through properties (read-only, no parentheses).

```iot
// In any expression context:
if home.connected { ... }
str ip = home.ip;
int signal = home.rssi;
int ch = home.channel;
str mac = home.mac;
int count = ap_if.clients;
WifiState s = home.state;
str name = home.ssid;
```

### 3.1 Property Reference

| Property | Type | Mode | Description |
|----------|------|------|-------------|
| `.state` | `WifiState` | both | Current state machine state (see §5) |
| `.connected` | `bool` | sta | True when STA is connected with IP |
| `.ip` | `str` | sta | Local IPv4 address (e.g. `"192.168.1.42"`) |
| `.rssi` | `int` | sta | Signal strength in dBm (e.g. `-45`) |
| `.channel` | `int` | both | Current WiFi channel number |
| `.mac` | `str` | both | WiFi MAC address (`"aa:bb:cc:dd:ee:ff"`) |
| `.clients` | `int` | ap | Number of connected stations |
| `.ssid` | `str` | both | The configured SSID (compile-time constant) |

### 3.2 `WifiState` Enum

Generated automatically for type-safe state checking:

```iot
// Compiler generates:
enum WifiState {
    WifiState_Idle,
    WifiState_Connecting,
    WifiState_Connected,
    WifiState_Disconnected,
}
```

Usage:
```iot
if home.state == WifiState_Connected { ... }
```

### 3.3 Property Lifetime Guarantees

| Property | Buffer owner | Valid until |
|----------|-------------|-------------|
| `.ip` | Generated static `char[16]` | Always valid; overwritten on next connection |
| `.mac` | Generated static `char[18]` | Always valid; set once at init |
| `.ssid` | Compile-time constant | Always valid |
| `.rssi` | Generated static `int` | Updated on each poll/event; stale between updates |

---

## 4. Methods

Methods perform actions. They return nothing (void). Results arrive via events
or properties.

### 4.1 Method Reference

| Method | Mode | Description |
|--------|------|-------------|
| `wifi.scan()` | sta | Start a WiFi scan. Results arrive via `on wifi.scan_done` |
| `wifi.disconnect()` | sta | Disconnect from WiFi. State → `Disconnected`. No retry unless reconnected |

### 4.2 Why `connect()` is NOT a Method

The user never calls `connect()` manually. The declaration drives connection:

```
wifi home { ssid: "x"; password: "y"; }
// ↑ This IS the connect command. Compiler generates everything.
```

Manual `connect()` creates problems:
- Double-connect race conditions
- Confusion about when to call it (in setup? in tick? after disconnect?)
- Duplication of SSID/password passing
- Users forget to call it

The only manual control is `disconnect()`. To reconnect, don't call `connect()` —
the compiler's retry system handles it automatically. To permanently stop,
declare `retry: none` and call `disconnect()`.

### 4.3 Scan Results

Scan results are accessed through generated accessor functions in the
`scan_done` event handler:

```iot
on home.scan_done {
    int count = scan_result_count();
    for int i = 0; i < count; i += 1 {
        print(scan_result_ssid(i));
        print(": ");
        print(scan_result_rssi(i));
    }
}
```

Results are valid only within the `scan_done` handler. The buffer is reused
on the next `scan()` call.

---

## 5. State Machine

### 5.1 States

```
                  ┌──────────────────────────────────────────┐
                  │                                          │
                  ▼                                          │
    ┌──────┐  init   ┌─────────────┐  got_ip   ┌───────────┐│
    │ IDLE │ ──────► │ CONNECTING  │ ────────► │ CONNECTED ││
    └──────┘         └─────────────┘           └───────────┘│
        ▲                  │                         │       │
        │                  ▼                         │       │
        │            ┌──────────────┐                │       │
        │            │ DISCONNECTED │◄───────────────┘       │
        │            └──────────────┘   disconnect or loss    │
        │                  │                                  │
        │                  │ (retry timer)                    │
        │                  ▼                                  │
        │            ┌─────────────┐                          │
        └────────────│ CONNECTING  │  (reconnect cycle)      │
                     └─────────────┘──────────────────────────┘
```

### 5.2 State Transitions

| From | To | Trigger |
|------|----|---------|
| *(start)* | `IDLE` | WiFi init complete |
| `IDLE` | `CONNECTING` | `esp_wifi_connect()` called (auto) |
| `CONNECTING` | `CONNECTED` | WiFi connected + IP obtained |
| `CONNECTING` | `DISCONNECTED` | Connection failed or timed out |
| `CONNECTED` | `DISCONNECTED` | Connection lost or `disconnect()` called |
| `DISCONNECTED` | `CONNECTING` | Retry timer fired (if retry enabled) |
| `DISCONNECTED` | `IDLE` | `disconnect()` called (manual stop) |

### 5.3 AP State Machine (Simpler)

AP mode has only two states:
- `IDLE` → after `esp_wifi_start()` in AP mode
- `CONNECTED` → AP is running (immediately after start)

AP does not use `CONNECTING` or `DISCONNECTED`. If AP fails to start, it's a
compile/init error, not a runtime state.

---

## 6. Retry System

The retry system controls STA reconnection behavior after disconnection.

### 6.1 Retry Policies

```iot
// No retries — single connection attempt:
wifi sensor {
    ssid: "Net";
    password: "pass";
    retry: none;
}

// Fixed interval, 3 attempts (DEFAULT when retry not specified):
wifi default_wifi {
    ssid: "Net";
    password: "pass";
    // retry: fixed;  ← implicit
}

// Retry forever:
wifi critical {
    ssid: "Net";
    password: "pass";
    retry: forever;
}

// Exponential backoff:
wifi office {
    ssid: "Net";
    password: "pass";
    retry: exponential;
}

// Custom:
wifi custom_wifi {
    ssid: "Net";
    password: "pass";
    retry: custom { count: 5; interval: 10s; };
}
```

### 6.2 Retry Policy Parameters

| Policy | Default Interval | Default Max Attempts | Behavior |
|--------|-----------------|---------------------|----------|
| `none` | — | 1 | Single attempt, no retry |
| `fixed` | 5s | 3 | Fixed interval between attempts |
| `forever` | 5s | ∞ | Never stop retrying |
| `exponential` | 1s base, 60s max | 10 | 1s, 2s, 4s, 8s, 16s, 32s, 60s, 60s, 60s, 60s |
| `custom { ... }` | user-specified | user-specified | Custom interval and count |

### 6.3 Custom Retry Options

```iot
retry: custom {
    count: 10;        // max attempts (required)
    interval: 2s;     // base interval (required)
    max_interval: 30s; // cap for exponential (optional, exponential only)
    backoff: fixed;    // fixed | exponential (optional, default: fixed)
}
```

---

## 7. Event System

### 7.1 Event Handlers

```iot
on home.connect {
    print("Connected! IP: " + home.ip);
}

on home.disconnect {
    print("Disconnected. State: " + home.state);
}

on home.got_ip {
    print("Got IP: " + home.ip);
}

on home.scan_done {
    print("Scan complete. Found " + scan_result_count() + " networks.");
}

on ap_if.client_join {
    print("Client joined AP. Total: " + ap_if.clients);
}

on ap_if.client_leave {
    print("Client left AP. Total: " + ap_if.clients);
}
```

### 7.2 Event Reference

| Event | Mode | Fires when | Can repeat? |
|-------|------|------------|-------------|
| `on wifi.connect` | sta | WiFi connected AND IP obtained | Yes (every reconnect) |
| `on wifi.disconnect` | sta | WiFi disconnected (any reason) | Yes |
| `on wifi.got_ip` | sta | IP address assigned (fires just before `connect`) | Yes (every reconnect) |
| `on wifi.scan_done` | sta | WiFi scan completed | Yes (every `scan()`) |
| `on wifi.client_join` | ap | Station connected to AP | Yes |
| `on wifi.client_leave` | ap | Station disconnected from AP | Yes |

### 7.3 Event Ordering Guarantees

For a successful connection:
```
1. got_ip     (IP assigned by DHCP/static)
2. connect    (WiFi is fully operational)
```

For a disconnection:
```
1. disconnect (WiFi lost; properties may be stale)
2. [retry delay]
3. got_ip     (if reconnection succeeds)
4. connect
```

For a failed connection with retries:
```
1. disconnect (attempt N failed)
2. [retry delay]
3. disconnect (attempt N+1 failed)
... (repeat until success or exhausted)
4. connect    (if eventually successful)
```

### 7.4 Handler Execution Context

All WiFi event handlers execute in the **generated scheduler task** (inside
`loop()`), NOT in:
- The ESP-IDF WiFi event loop task
- An ISR
- A FreeRTOS timer callback

The generated code registers a minimal ESP-IDF/Arduino event callback that:
1. Updates the generated state variables (connected flag, IP buffer, RSSI, etc.)
2. Sets a pending-event flag for the specific WiFi declaration + event type
3. The scheduler checks these flags each `loop()` iteration and dispatches
   user handlers

**Rationale:** This ensures user code runs at predictable times, avoids
concurrency issues, and allows safe use of `print()`, pin writes, and
timer operations. The same architecture as `on PIN.press` (ISR sets flag →
handler runs in loop).

### 7.5 Forbidden Operations in WiFi Handlers

WiFi handlers may NOT:
- Call `delay()` or `delayMicroseconds()` (blocking)
- Allocate heap memory (malloc/new)
- Call `disconnect()` on the same WiFi (re-entrant state machine)
- Access scan results outside `scan_done` handler

WiFi handlers MAY:
- Read any WiFi property
- Write pins
- Start/stop timers
- Use `print()` / `println()`
- Call `scan()` (non-blocking start)
- Access other wifi declarations' properties

---

## 8. Lexer

### 8.1 New Keywords

Add to `KEYWORDS` in `lexer.py`:

```python
# WiFi contextual keywords (usable as identifiers outside WiFi context,
# same pattern as press/release/rising/falling/change):
'wifi',
'sta', 'ap',
'connect', 'disconnect', 'got_ip', 'scan_done',
'client_join', 'client_leave',
'scan',
# WiFi config keys (contextual inside wifi block):
'mode', 'ssid', 'password', 'hostname',
'connect_timeout', 'retry', 'power_save',
'static_ip', 'gateway', 'subnet', 'dns',
'channel', 'max_clients', 'hidden',
# Retry keywords:
'none', 'fixed', 'forever', 'exponential', 'custom',
'backoff', 'interval', 'max_interval', 'count',
```

All are **contextual keywords** — they are recognized as keywords in specific
parser contexts but can still be used as identifiers elsewhere. This is the
same pattern used by `press`, `release`, `rising`, `falling`, `change`, `pin`,
`output`, `input`, etc.

### 8.2 `WifiState` Values

The `WifiState` enum variants are not keywords — they are generated as enum
variants and resolved through normal name resolution.

---

## 9. AST Nodes

### 9.1 New Node: `WifiDecl`

```python
@dataclass
class WifiDecl(Node):
    """wifi NAME { mode: sta; ssid: "..."; password: "..."; ... }"""
    name: str = ''
    mode: str = 'sta'           # 'sta' | 'ap'
    config: dict = field(default_factory=dict)
    # config keys: ssid, password, hostname, connect_timeout, retry,
    #              power_save, static_ip, gateway, subnet, dns,
    #              channel, max_clients, hidden
```

### 9.2 Generalized: `OnEvent`

The existing `OnEvent` node is generalized to support both pin and WiFi targets:

```python
@dataclass
class OnEvent(Node):
    """on TARGET.event { ... }  — pin events + WiFi events"""
    target: str = ''             # pin name or wifi name
    event: str = ''              # press|release|change|rising|falling
                                 #   |connect|disconnect|got_ip|scan_done
                                 #   |client_join|client_leave
    body: List[Node] = field(default_factory=list)
```

**Field rename:** `pin` → `target`. This is an internal AST change only
(all usage sites updated; semantic pass resolves target to determine if
it's a pin or wifi). No language change.

### 9.3 No New Nodes Needed For

- **WiFi properties** (`home.connected`, `home.ip`, etc.) — these are
  `MemberAccess` nodes. The semantic pass resolves `home` to a `WIFI` symbol
  and validates the member name.

- **WiFi method calls** (`home.scan()`, `home.disconnect()`) — these are
  `MethodCall` nodes. The semantic pass validates the method against the
  WIFI symbol kind.

- **WiFi state enum access** (`WifiState_Connected`) — standard `Identifier`
  or `MemberAccess` (resolved via enum variant lookup).

### 9.4 Scan Result Accessors

Scan results within `scan_done` handlers use `FnCall` nodes with generated
function names:

```python
# scan_result_count() → FnCall(name="scan_result_count", args=[])
# scan_result_ssid(i) → FnCall(name="scan_result_ssid", args=[Identifier("i")])
# scan_result_rssi(i) → FnCall(name="scan_result_rssi", args=[Identifier("i")])
# scan_result_channel(i) → FnCall(name="scan_result_channel", args=[Identifier("i")])
```

These are only valid inside `scan_done` handlers (enforced by semantic pass).

---

## 10. Parser

### 10.1 New Parse Functions

```python
def _parse_wifi_decl(self) -> WifiDecl:
    """wifi NAME { key: value, key: value, ... }"""

def _parse_wifi_options(self) -> dict:
    """Parse key: value pairs inside wifi block. Comma-separated."""

def _parse_retry_spec(self) -> dict:
    """Parse retry: none | fixed | forever | exponential | custom { ... }"""
```

### 10.2 Modified Parse Functions

```python
def _parse_on(self) -> OnEvent:
    """
    Generalized. After parsing `on TARGET.event`:
    - If TARGET is a pin name → pin event (existing behavior)
    - If TARGET is a wifi name → wifi event (new behavior)
    Defer type determination to semantic pass.
    """

def _parse_top_level(self) -> Optional[Node]:
    # Add: if tok == 'wifi' → return self._parse_wifi_decl()
    # Insert after peripheral/i2c/spi/uart branch
```

### 10.3 Grammar (BNF)

```
WifiDecl        ::= 'wifi' IDENTIFIER '{' WifiOptionList '}'
WifiOptionList  ::= WifiOption (',' WifiOption)* ','?
WifiOption      ::= WifiMode | WifiSSID | WifiPassword | WifiHostname
                  | WifiTimeout | WifiRetry | WifiPowerSave
                  | WifiStaticIP | WifiGateway | WifiSubnet | WifiDNS
                  | WifiChannel | WifiMaxClients | WifiHidden

WifiMode        ::= 'mode' ':' ('sta' | 'ap')
WifiSSID        ::= 'ssid' ':' STRING
WifiPassword    ::= 'password' ':' STRING
WifiHostname    ::= 'hostname' ':' STRING
WifiTimeout     ::= 'connect_timeout' ':' TIME_LITERAL
WifiRetry       ::= 'retry' ':' RetrySpec
WifiPowerSave   ::= 'power_save' ':' ('none' | 'light' | 'deep')
WifiStaticIP    ::= 'static_ip' ':' STRING
WifiGateway     ::= 'gateway' ':' STRING
WifiSubnet      ::= 'subnet' ':' STRING
WifiDNS         ::= 'dns' ':' STRING
WifiChannel     ::= 'channel' ':' INTEGER
WifiMaxClients  ::= 'max_clients' ':' INTEGER
WifiHidden      ::= 'hidden' ':' BOOLEAN

RetrySpec       ::= 'none' | 'fixed' | 'forever' | 'exponential'
                  | 'custom' '{' RetryOptionList '}'
RetryOptionList ::= RetryOption (',' RetryOption)* ','?
RetryOption     ::= 'count' ':' INTEGER
                  | 'interval' ':' TIME_LITERAL
                  | 'max_interval' ':' TIME_LITERAL
                  | 'backoff' ':' ('fixed' | 'exponential')

OnEvent         ::= 'on' IDENTIFIER '.' EVENT_NAME Block
EVENT_NAME      ::= 'press' | 'release' | 'change' | 'rising' | 'falling'
                  | 'connect' | 'disconnect' | 'got_ip' | 'scan_done'
                  | 'client_join' | 'client_leave'
```

### 10.4 Parser Edge Cases Handled

- Trailing comma in option list: `{ ssid: "x", password: "y", }` — OK
- Empty option list: `wifi x {}` — error (ssid required)
- Duplicate keys: last occurrence wins with warning
- Unknown keys: parse error with suggestion
- `password` omitted for AP: valid (open network)
- `password` omitted for STA: error
- Non-string `ssid`: parse error
- Config keys as identifiers outside wifi block: valid (contextual keywords)

---

## 11. Semantic Analysis

### 11.1 Pass 1: Symbol Table Construction

- Register `WifiDecl` as `SymbolKind.WIFI` in global scope
- Store config dict on symbol for later validation
- Generate `WifiState` enum type (one per compilation unit, shared across all wifi declarations)
- Register generated scan result accessor functions

### 11.2 Pass 2: Name Resolution

- Resolve `target` in `OnEvent` to either PIN or WIFI symbol
- Resolve `obj` in `MemberAccess` — if WIFI symbol, validate member name
- Resolve `obj` in `MethodCall` — if WIFI symbol, validate method name
- Resolve scan result functions inside `scan_done` handlers

### 11.3 Pass 3: Type Checking

- `home.connected` → `bool`
- `home.ip` → `str`
- `home.rssi` → `int`
- `home.channel` → `int`
- `home.mac` → `str`
- `home.clients` → `int`
- `home.state` → `WifiState` enum type
- `home.ssid` → `str`
- `home.scan()` → `void`
- `home.disconnect()` → `void`

Mode-specific validation:
- `.clients` only valid for AP mode → error if used on STA
- `scan()` only valid for STA mode → error if used on AP
- `.rssi` only valid for STA mode → error if used on AP
- `.ip` only valid for STA mode → error if used on AP
- `scan_result_*` only valid inside `scan_done` handler → error otherwise
- `client_join`/`client_leave` events only valid for AP → error on STA
- `connect`/`disconnect`/`got_ip` events only valid for STA → error on AP

### 11.4 Pass 4: Scope & Safety Analysis

- WiFi event handler body: check for forbidden operations (delay, malloc, re-entrant disconnect)
- `delay()` in WiFi event handler → warning `wifi-blocking-in-event-handler`
- `disconnect()` on same wifi inside its own event handler → error
- `print()` in WiFi event handler → allowed (runs in scheduler task)
- Pin writes in WiFi event handler → allowed

### 11.5 New Warnings

| Warning Code | Severity | Description |
|-------------|----------|-------------|
| `wifi-no-password` | WARNING | STA mode without password (open network — confirm intent) |
| `wifi-short-password` | WARNING | Password < 8 characters (WPA2 minimum) |
| `wifi-open-ap` | INFO | AP mode without password (open network) |
| `wifi-unsupported-target` | ERROR | WiFi used on non-WiFi target |
| `wifi-dual-sta` | ERROR | Two STA declarations on same device |
| `wifi-blocking-in-handler` | WARNING | `delay()` inside WiFi event handler |
| `wifi-scan-outside-handler` | ERROR | `scan_result_*` used outside `scan_done` handler |
| `wifi-static-ip-incomplete` | ERROR | `static_ip` without `gateway` and `subnet` |
| `wifi-invalid-channel` | WARNING | Channel outside 1–13 range |
| `wifi-duplicate-ssid` | WARNING | Two AP declarations with same SSID |

### 11.6 Multi-WiFi Validation

- ESP32 supports one STA interface → two `wifi X { mode: sta }` declarations → error
- ESP32 supports one AP interface → two `wifi X { mode: ap }` declarations → error
- STA + AP on same device → valid (compiler generates `WIFI_MODE_APSTA`)
- Non-ESP32 targets → any wifi declaration → error (with message listing supported targets)

---

## 12. HAL Interface

### 12.1 Design Principle

The HAL does NOT return raw C strings. It returns structured data that the
codegen composes. This separation allows:

- Multiple WiFi declarations to be merged into one init sequence
- Platform-specific event registration to be isolated
- The compiler to own code structure, not the HAL

### 12.2 HAL Methods

```python
# In HALBase:

def wifi_get_includes(self) -> List[str]:
    """Return #include lines for WiFi support. Empty list on unsupported targets."""

def wifi_supported(self) -> bool:
    """Return True if this target supports WiFi. Default: False."""

def wifi_max_sta_interfaces(self) -> int:
    """Maximum simultaneous STA interfaces. ESP32: 1."""

def wifi_max_ap_interfaces(self) -> int:
    """Maximum simultaneous AP interfaces. ESP32: 1."""

def wifi_generate_init(self, decls: List[WifiInitContext]) -> WifiInitOutput:
    """
    Generate all WiFi initialization code.
    
    Takes a list of WifiInitContext (one per wifi declaration) and returns
    structured output that the codegen assembles into the correct sections.
    This allows the HAL to merge multiple declarations into one init sequence
    (e.g., STA + AP → WIFI_MODE_APSTA).
    """

def wifi_generate_event_registration(self, ctx: WifiEventContext) -> str:
    """Generate event handler registration for a specific event."""

def wifi_generate_state_update(self, event: str) -> str:
    """Generate C code to update generated state variables for an event."""

def wifi_generate_disconnect(self, name: str) -> str:
    """Generate disconnect code."""

def wifi_generate_scan_start(self, name: str) -> str:
    """Generate scan start code."""

def wifi_generate_property_read(self, name: str, prop: str) -> str:
    """Generate C expression to read a WiFi property."""
```

### 12.3 Structured Data Types

```python
@dataclass
class WifiInitContext:
    """Per-declaration context passed to HAL."""
    name: str                    # user-given name (e.g., 'home')
    c_name: str                  # generated C prefix (e.g., '_iotift_wifi_home')
    mode: str                    # 'sta' | 'ap'
    ssid: str                    # network SSID
    password: str | None         # None = open network
    hostname: str
    connect_timeout_ms: int
    retry_policy: RetryPolicy
    power_save: str              # 'none' | 'light' | 'deep'
    static_ip: str | None
    gateway: str | None
    subnet: str | None
    dns: str | None
    channel: int
    max_clients: int
    hidden: bool

@dataclass
class RetryPolicy:
    kind: str                    # 'none' | 'fixed' | 'forever' | 'exponential' | 'custom'
    count: int                   # max attempts (0 = forever)
    interval_ms: int             # base interval
    max_interval_ms: int         # cap for exponential
    backoff: str                 # 'fixed' | 'exponential'

@dataclass
class WifiInitOutput:
    """Structured output from HAL WiFi init generation."""
    includes: List[str]                    # #include lines
    nvs_init: str                          # NVS flash init (shared guard)
    netif_init: str                        # TCP/IP netif init (shared guard)
    event_loop_init: str                   # Event loop creation (shared guard)
    state_decls: List[str]                 # Generated state variable declarations
    global_code: List[str]                 # Code in global scope (event handlers, callbacks)
    setup_code: List[str]                  # Code in setup() (init calls)
    loop_code: List[str]                   # Code in loop() (event dispatch)
    cleanup_code: List[str]                # Disconnect/deinit code
    scan_buffer_decl: str                  # Scan result buffer declaration
    event_handler_decls: List[EventContext] # Per-event handler info

@dataclass
class EventContext:
    """Context for a single event handler."""
    wifi_name: str                         # user name
    c_prefix: str                          # generated C prefix
    event: str                             # event name
    handler_body: str                      # user's handler body (as C)
    handler_func_name: str                 # generated handler function name
```

### 12.4 ESP32 Arduino HAL Implementation

The ESP32 Arduino HAL implements WiFi via the `WiFi.h` / `WiFiSTA.h` / `WiFiAP.h`
classes. Key differences from ESP-IDF path:

- Uses `WiFi.begin(ssid, password)` instead of `esp_wifi_*` API
- Event callbacks via `WiFi.onEvent()` (Arduino core wrapper)
- IP via `WiFi.localIP().toString().c_str()`
- Scan via `WiFi.scanNetworks()` (synchronous! — wrap in async start)

### 12.5 ESP32 ESP-IDF HAL Implementation

The ESP-IDF HAL is the **primary target** — it produces smaller binaries and
has no Arduino wrapper overhead.

- Uses native `esp_wifi_*`, `esp_netif_*`, `esp_event_*` functions
- Event loop: `esp_event_handler_register(WIFI_EVENT, ..., &handler, NULL)`
- IP via `esp_netif_get_ip_info()` + `esp_ip4addr_ntoa()`
- Scan via `esp_wifi_scan_start()` + `WIFI_EVENT_SCAN_DONE` event

### 12.6 Unsupported Targets

Targets without WiFi (STM32, RP2040, nRF52 via Arduino, AVR, CMSIS) implement:

```python
def wifi_supported(self) -> bool:
    return False
```

The semantic pass checks this before codegen and emits:
```
Line 5: error: WiFi is not supported on target 'avr' (Arduino).
       WiFi is supported on: esp32, esp32-espidf, esp32s2, esp32s3, esp32c3, esp32c6
```

---

## 13. Code Generation

### 13.1 Generated State Variables

Per wifi declaration, the compiler generates:

```c
// State machine
static wifi_state_t _iotift_wifi_<name>_state = WIFI_STATE_IDLE;

// Connection status
static bool _iotift_wifi_<name>_connected = false;

// IP address buffer
static char _iotift_wifi_<name>_ip[16] = {0};

// Signal strength
static int _iotift_wifi_<name>_rssi = 0;

// MAC address buffer
static char _iotift_wifi_<name>_mac[18] = {0};

// Current channel
static uint8_t _iotift_wifi_<name>_channel = 0;

// AP client count
static uint8_t _iotift_wifi_<name>_client_count = 0;

// Retry state
static uint8_t _iotift_wifi_<name>_retry_count = 0;
static unsigned long _iotift_wifi_<name>_last_retry_ms = 0;

// Event pending flags (one per event type)
static bool _iotift_wifi_<name>_event_connect = false;
static bool _iotift_wifi_<name>_event_disconnect = false;
static bool _iotift_wifi_<name>_event_got_ip = false;
static bool _iotift_wifi_<name>_event_scan_done = false;
static bool _iotift_wifi_<name>_event_client_join = false;
static bool _iotift_wifi_<name>_event_client_leave = false;

// Scan results buffer (shared across all wifi declarations)
static wifi_scan_result_t _iotift_wifi_scan_buffer[IOTIFT_WIFI_SCAN_MAX];
static uint16_t _iotift_wifi_scan_count = 0;
```

### 13.2 Shared Guards

```c
// Generated once per compilation unit:
static bool _iotift_nvs_initialized = false;
static bool _iotift_netif_initialized = false;
static bool _iotift_event_loop_initialized = false;
```

### 13.3 Generated Functions

```c
// Per-declaration init (called from setup):
static void _iotift_wifi_<name>_init(void);

// Per-declaration event dispatcher (called from loop):
static void _iotift_wifi_<name>_dispatch(void);

// Platform event callback (registered with ESP-IDF/Arduino):
static void _iotift_wifi_event_handler(void* arg, esp_event_base_t base,
                                        int32_t event_id, void* event_data);

// User event handlers (one per on <name>.<event> block):
static void _iotift_wifi_<name>_on_connect(void);
static void _iotift_wifi_<name>_on_disconnect(void);
// ... etc

// Retry timer handler (called from scheduler):
static void _iotift_wifi_<name>_retry_handler(void);

// Scan result accessors:
static int _iotift_wifi_scan_result_count(void) { return _iotift_wifi_scan_count; }
static const char* _iotift_wifi_scan_result_ssid(int i) { ... }
static int _iotift_wifi_scan_result_rssi(int i) { ... }
static int _iotift_wifi_scan_result_channel(int i) { ... }
```

### 13.4 Setup() Sequence

```c
void setup() {
    // ... other init ...
    
    // WiFi init (shared guards ensure single init):
    if (!_iotift_nvs_initialized) {
        nvs_flash_init();
        _iotift_nvs_initialized = true;
    }
    if (!_iotift_netif_initialized) {
        esp_netif_init();
        _iotift_netif_initialized = true;
    }
    if (!_iotift_event_loop_initialized) {
        esp_event_loop_create_default();
        _iotift_event_loop_initialized = true;
    }
    
    // Per-declaration init:
    _iotift_wifi_home_init();
    _iotift_wifi_ap_if_init();
    
    // ... other setup ...
}
```

### 13.5 Loop() Sequence

```c
void loop() {
    // ... scheduler ...
    
    // WiFi event dispatch (checks pending flags, calls user handlers):
    _iotift_wifi_home_dispatch();
    _iotift_wifi_ap_if_dispatch();
    
    // ... other loop code ...
}
```

### 13.6 Property Codegen

```c
// home.connected → _iotift_wifi_home_connected
// home.ip → _iotift_wifi_home_ip
// home.rssi → _iotift_wifi_home_rssi
// home.channel → _iotift_wifi_home_channel
// home.mac → _iotift_wifi_home_mac
// home.clients → _iotift_wifi_home_client_count
// home.state → _iotift_wifi_home_state
```

### 13.7 Direct vs IR Codegen

Both paths must work:
- **Direct codegen** (`codegen.py`): Collect WiFi decls during AST walk,
  emit in collect-then-emit pass. WiFi init in `_emit_setup()`, dispatch in
  `_emit_loop()`, state variables in `_emit_globals()`.
- **IR codegen** (`ir_lowering.py` + `ir_codegen.py`): Lower WiFi decl to
  IR module metadata. Lower event handlers to IR functions. Lower property
  access to IR load instructions targeting generated globals.

### 13.8 No Leakage Guarantee

Programs without WiFi declarations must generate zero WiFi-related code:
- No `#include <WiFi.h>` or `#include <esp_wifi.h>`
- No NVS init
- No netif init
- No event loop
- No WiFi state variables

This is achieved by checking `len(self._wifi_decls) > 0` before emitting any
WiFi code (direct path) or checking `len(module.wifi_decls) > 0` (IR path).

---

## 14. LSP Support

### 14.1 Completion

| Context | Trigger | Completions |
|---------|---------|-------------|
| Top-level keyword | `wi` | `wifi` |
| After `wifi` | `<name>` | (no completions — user names their wifi) |
| Inside wifi block | `<key>` | `mode`, `ssid`, `password`, `hostname`, `connect_timeout`, `retry`, `power_save`, `static_ip`, `gateway`, `subnet`, `dns`, `channel`, `max_clients`, `hidden` |
| After `mode:` | `<value>` | `sta`, `ap` |
| After `retry:` | `<value>` | `none`, `fixed`, `forever`, `exponential`, `custom` |
| After `power_save:` | `<value>` | `none`, `light`, `deep` |
| After `on <wifi_name>.` | `<event>` | `connect`, `disconnect`, `got_ip`, `scan_done`, `client_join`, `client_leave` |
| After `<wifi_name>.` | `<member>` | Properties: `state`, `connected`, `ip`, `rssi`, `channel`, `mac`, `clients`, `ssid`; Methods: `scan`, `disconnect` |
| After `on <pin_name>.` | `<event>` | `press`, `release`, `change`, `rising`, `falling` (unchanged) |
| Inside `scan_done` | `scan_result_` | `scan_result_count`, `scan_result_ssid`, `scan_result_rssi`, `scan_result_channel` |

### 14.2 Hover

- **On wifi name:** Shows mode, SSID, current IP (if connected), state
- **On wifi property:** Shows type, description, example
- **On wifi event name:** Shows when it fires, repeat behavior
- **On config key:** Shows type, default value, description

### 14.3 Diagnostics

- Parser errors: bad syntax, unknown keys, invalid values
- Semantic errors: mode mismatches, unsupported target, dual STA
- Linter warnings: no-password, short-password, blocking-in-handler

---

## 15. Formatter

### 15.1 WifiDecl Formatting

```iot
// Input (messy):
wifi home{mode:sta;ssid:"x";password:"y";hostname:"iotift";connect_timeout:30s}

// Output (formatted):
wifi home {
    mode: sta,
    ssid: "x",
    password: "y",
    hostname: "iotift",
    connect_timeout: 30s,
}
```

Rules:
- Opening brace on same line as `wifi NAME`
- Each option on its own line
- 4-space indent for options
- One space after colon
- Comma after each option (including last — trailing comma allowed)
- Closing brace at same indent as `wifi`
- If block fits on one line (≤3 options, ≤80 chars), keep on one line:
  ```iot
  wifi home { ssid: "x", password: "y" }
  ```

### 15.2 OnEvent Formatting

Unchanged from existing pin event formatting:
```iot
on home.connect {
    print("Connected!");
}
```

### 15.3 Retry Spec Formatting

```iot
// Inline for simple:
retry: fixed,

// Expanded for custom:
retry: custom {
    count: 5,
    interval: 10s,
},
```

---

## 16. Linter

### 16.1 New Lint Rules

| Rule | Severity | Description |
|------|----------|-------------|
| `wifi-no-password` | WARNING | STA mode without password |
| `wifi-short-password` | WARNING | Password < 8 characters |
| `wifi-open-ap` | INFO | AP mode without password |
| `wifi-blocking-in-handler` | WARNING | `delay()` inside WiFi event handler |
| `wifi-unused` | WARNING | WiFi declared but no event handlers defined |
| `wifi-no-connect-handler` | INFO | STA declared but no `on <name>.connect` block |
| `wifi-static-ip-no-dns` | INFO | Static IP without DNS server specified |

---

## 17. Test Plan

### 17.1 Parser Tests (18)

| # | Test | Description |
|---|------|-------------|
| 1 | `test_parse_wifi_sta_basic` | `wifi home { ssid: "x", password: "y" }` |
| 2 | `test_parse_wifi_sta_all_options` | All 14 config keys |
| 3 | `test_parse_wifi_ap_open` | AP without password |
| 4 | `test_parse_wifi_ap_secured` | AP with password |
| 5 | `test_parse_wifi_sta_and_ap` | Two declarations in one file |
| 6 | `test_parse_wifi_default_mode` | Mode defaults to sta when omitted |
| 7 | `test_parse_wifi_on_connect` | `on home.connect { ... }` |
| 8 | `test_parse_wifi_on_disconnect` | `on home.disconnect { ... }` |
| 9 | `test_parse_wifi_on_got_ip` | `on home.got_ip { ... }` |
| 10 | `test_parse_wifi_on_scan_done` | `on home.scan_done { ... }` |
| 11 | `test_parse_wifi_on_client_join` | `on ap_if.client_join { ... }` |
| 12 | `test_parse_wifi_on_client_leave` | `on ap_if.client_leave { ... }` |
| 13 | `test_parse_wifi_property_access` | `home.connected`, `home.ip`, etc. |
| 14 | `test_parse_wifi_method_call` | `home.scan()`, `home.disconnect()` |
| 15 | `test_parse_wifi_retry_none` | `retry: none` |
| 16 | `test_parse_wifi_retry_custom` | `retry: custom { count: 5, interval: 10s }` |
| 17 | `test_parse_wifi_error_no_ssid` | Missing required ssid |
| 18 | `test_parse_wifi_error_bad_mode` | Invalid mode value |

### 17.2 Semantic Tests (16)

| # | Test | Description |
|---|------|-------------|
| 1 | `test_semantic_wifi_sta_valid` | STA with password passes all checks |
| 2 | `test_semantic_wifi_ap_open_valid` | Open AP passes all checks |
| 3 | `test_semantic_wifi_clients_on_sta_error` | `.clients` on STA → error |
| 4 | `test_semantic_wifi_scan_on_ap_error` | `.scan()` on AP → error |
| 5 | `test_semantic_wifi_rssi_on_ap_error` | `.rssi` on AP → error |
| 6 | `test_semantic_wifi_ip_on_ap_error` | `.ip` on AP → error |
| 7 | `test_semantic_wifi_dual_sta_error` | Two STA declarations → error |
| 8 | `test_semantic_wifi_unsupported_target` | WiFi on AVR → error |
| 9 | `test_semantic_wifi_short_password_warning` | Password < 8 chars → warning |
| 10 | `test_semantic_wifi_no_password_warning` | STA no password → warning |
| 11 | `test_semantic_wifi_scan_result_outside_handler` | `scan_result_count()` outside handler → error |
| 12 | `test_semantic_wifi_static_ip_incomplete` | `static_ip` without gateway → error |
| 13 | `test_semantic_wifi_connect_event_on_ap_error` | `on ap.connect` → error |
| 14 | `test_semantic_wifi_client_event_on_sta_error` | `on sta.client_join` → error |
| 15 | `test_semantic_wifi_type_checking` | All property types resolve correctly |
| 16 | `test_semantic_wifi_state_enum` | WifiState enum generated and usable |

### 17.3 Codegen Tests (16)

| # | Test | Description |
|---|------|-------------|
| 1 | `test_codegen_wifi_sta_emits_nvs_init` | NVS init guard emitted |
| 2 | `test_codegen_wifi_sta_emits_netif_init` | Netif init emitted |
| 3 | `test_codegen_wifi_sta_emits_wifi_init` | WiFi init + config emitted |
| 4 | `test_codegen_wifi_ap_emits_ap_mode` | AP mode config emitted |
| 5 | `test_codegen_wifi_sta_ap_emits_apsta` | STA+AP → WIFI_MODE_APSTA |
| 6 | `test_codegen_wifi_connect_handler` | Event handler function emitted |
| 7 | `test_codegen_wifi_property_connected` | `.connected` → correct C |
| 8 | `test_codegen_wifi_property_ip` | `.ip` → correct C |
| 9 | `test_codegen_wifi_method_scan` | `.scan()` → correct C |
| 10 | `test_codegen_wifi_method_disconnect` | `.disconnect()` → correct C |
| 11 | `test_codegen_wifi_retry_fixed` | Fixed retry code emitted |
| 12 | `test_codegen_wifi_retry_exponential` | Exponential backoff code emitted |
| 13 | `test_codegen_wifi_no_leakage` | Non-WiFi program emits zero WiFi code |
| 14 | `test_codegen_wifi_nvs_guard_shared` | Multiple wifi → single NVS init |
| 15 | `test_codegen_wifi_state_machine` | State transitions generated correctly |
| 16 | `test_codegen_wifi_static_ip` | Static IP config emitted |

### 17.4 HAL Tests (10)

| # | Test | Description |
|---|------|-------------|
| 1 | `test_hal_esp32_arduino_wifi_init` | Arduino HAL generates expected C strings |
| 2 | `test_hal_esp32_espidf_wifi_init` | ESP-IDF HAL generates native calls |
| 3 | `test_hal_esp32_arduino_wifi_scan` | Scan generation correct |
| 4 | `test_hal_esp32_espidf_wifi_scan` | ESP-IDF scan generation correct |
| 5 | `test_hal_wifi_property_read` | Property read generation correct |
| 6 | `test_hal_unsupported_target` | Unsupported target returns empty includes |
| 7 | `test_hal_wifi_supported_check` | `wifi_supported()` returns correct bool |
| 8 | `test_hal_wifi_max_interfaces` | Interface count limits correct |
| 9 | `test_hal_wifi_init_output_structure` | Structured output dataclass populated correctly |
| 10 | `test_hal_wifi_event_registration` | Event registration code correct |

### 17.5 Integration Tests (5)

| # | Test | Description |
|---|------|-------------|
| 1 | `test_full_pipeline_wifi_sta` | Full parse→semantic→codegen for STA |
| 2 | `test_full_pipeline_wifi_ap` | Full pipeline for AP |
| 3 | `test_full_pipeline_wifi_sta_ap` | Full pipeline for STA+AP |
| 4 | `test_no_wifi_leakage_led` | led.iot still compiles (no WiFi leakage) |
| 5 | `test_multiple_wifi_unique_names` | Multiple wifi → unique handler names |

### 17.6 LSP Tests (5)

| # | Test | Description |
|---|------|-------------|
| 1 | `test_lsp_wifi_completion_keywords` | Completion after `wifi` keyword |
| 2 | `test_lsp_wifi_completion_config_keys` | Completion inside wifi block |
| 3 | `test_lsp_wifi_completion_events` | Completion after `on <wifi>.` |
| 4 | `test_lsp_wifi_completion_properties` | Completion after `<wifi>.` |
| 5 | `test_lsp_wifi_hover` | Hover on wifi name shows info |

### 17.7 Formatter Tests (3)

| # | Test | Description |
|---|------|-------------|
| 1 | `test_fmt_wifi_basic` | Basic wifi declaration formatting |
| 2 | `test_fmt_wifi_multiline` | Multiline options formatting |
| 3 | `test_fmt_wifi_oneline` | Single-line for short declarations |

### 17.8 Linter Tests (4)

| # | Test | Description |
|---|------|-------------|
| 1 | `test_lint_wifi_no_password` | STA no password → warning |
| 2 | `test_lint_wifi_short_password` | Short password → warning |
| 3 | `test_lint_wifi_blocking` | delay() in handler → warning |
| 4 | `test_lint_wifi_unused` | Unused wifi → warning |

**Total: ~77 new tests.** Existing 500 tests must continue to pass.

---

## 18. Future Compatibility

The WiFi design establishes the template for all communication peripherals.
Each future peripheral follows this pattern:

### 18.1 BLE (Milestone 9)

```iot
ble beacon {
    name: "Iotift Sensor";
    service_uuid: "180A";
    tx_power: 4;
    interval: 100ms;
}

on beacon.connect { ... }
on beacon.disconnect { ... }
on beacon.data_read { ... }
on beacon.data_write { ... }
```

### 18.2 MQTT (Milestone 10)

```iot
mqtt broker {
    host: "mqtt.example.com";
    port: 1883;
    client_id: "iotift-001";
    keep_alive: 60s;
    username: "sensor";
    password: "mqtt_pass";
}

on broker.connect { ... }
on broker.disconnect { ... }
on broker.message { ... }
```

### 18.3 HTTP (Milestone 11)

```iot
http server {
    port: 80;
}

on server.request { ... }
```

### 18.4 Ethernet (Milestone 12)

```iot
ethernet eth0 {
    phy: lan8720;
    phy_addr: 1;
    mdc: 23;
    mdio: 18;
    static_ip: "192.168.1.100";
    gateway: "192.168.1.1";
    subnet: "255.255.255.0";
}

on eth0.connect { ... }
on eth0.disconnect { ... }
```

### 18.5 Cellular (Milestone 13)

```iot
cellular lte {
    modem: sim7600;
    apn: "internet";
    pin: "1234";
    uart_num: 1;
}

on lte.connect { ... }
on lte.disconnect { ... }
```

### 18.6 Consistent Pattern

Every communication peripheral follows:

```
<peripheral_type> <name> {
    <config keys>
}

// Properties (read-only state):
<name>.connected
<name>.state
<name>.ip         // if IP-based
// ... peripheral-specific properties

// Methods (actions):
<name>.scan()     // if applicable
<name>.disconnect()

// Events:
on <name>.connect { ... }
on <name>.disconnect { ... }
// ... peripheral-specific events
```

---

## 19. Non-Goals (Explicitly Out of Scope)

- **WPA3 / WPA2-Enterprise** — certificate management requires substantial design
- **WiFi Direct / P2P** — rare use case, different event model
- **WiFi Mesh (ESP-MDF)** — large surface area, separate milestone
- **Captive portal** — complexity out of proportion to value
- **WPS** — security concerns, declining usage
- **BLE + WiFi coexistence** — antenna sharing, deserves M9+
- **SmartConfig / ESP-TOUCH** — provisioning is a separate concern
- **Enterprise 802.1X** — requires EAP-TLS/TTLS/PEAP certificate handling
- **IPv6** — ESP-IDF supports it but rare in embedded; revisit when demand exists
- **Ethernet** — separate physical layer, separate milestone
- **MQTT / HTTP** — deserve their own milestones with protocol-level design

---

## 20. Implementation Plan

### Phase Order

1. **Spec finalization** (this document) — no code yet
2. **Lexer** — add keywords (~15 lines, `lexer.py`)
3. **AST** — add `WifiDecl` node, generalize `OnEvent.pin` → `OnEvent.target` (~20 lines, `ast_nodes.py`)
4. **Parser** — add `_parse_wifi_decl()`, `_parse_wifi_options()`, `_parse_retry_spec()`, modify `_parse_on()` (~150 lines, `parser.py`)
5. **Semantic** — Pass 1–4 WiFi handling (~130 lines, `semantic.py`)
6. **Symbol Table** — add `SymbolKind.WIFI` (~3 lines, `symbol_table.py`)
7. **HAL** — structured WiFi output types + `HALBase` methods (~150 lines, `hal/base.py`)
8. **HAL ESP32 Arduino** — WiFi implementation (~180 lines, `hal/esp32_arduino.py`)
9. **HAL ESP32 ESP-IDF** — WiFi implementation (~180 lines, `hal/esp32_espidf.py`)
10. **HAL stubs** — unsupported target stubs (~30 lines × 5 files)
11. **Codegen (direct)** — collect + emit WiFi (~180 lines, `codegen.py`)
12. **Codegen (IR)** — lowering + emission (~100 lines, `ir_lowering.py` + `ir_codegen.py`)
13. **LSP** — completions + hover (~70 lines, `iotift/tools/lsp_server.py`)
14. **Formatter** — wifi nodes (~40 lines, `iotift/tools/formatter.py`)
15. **Linter** — 7 new rules (~50 lines, `iotift/tools/linter.py`)
16. **Tests** — `test_wifi.py` (~500 lines)
17. **Examples** — `wifi_thermostat.iot` + `wifi_scanner.iot` (~100 lines)
18. **Docs** — README WiFi section + TODO.md update (~100 lines)

### Estimated Total: ~1,600 lines across ~20 files

### Files Touched

| File | Change | Est. Lines |
|------|--------|------------|
| `lexer.py` | New keywords | +15 |
| `ast_nodes.py` | WifiDecl, generalize OnEvent | +20 |
| `parser.py` | Parse functions, wire into top_level + on | +150 |
| `semantic.py` | WiFi validation passes | +130 |
| `symbol_table.py` | WIFI symbol kind | +3 |
| `hal/base.py` | WiFi HAL interface + dataclasses | +150 |
| `hal/esp32_arduino.py` | Arduino WiFi impl | +180 |
| `hal/esp32_espidf.py` | ESP-IDF WiFi impl | +180 |
| `hal/stm32_arduino.py` | Stub | +10 |
| `hal/avr_arduino.py` | Stub | +10 |
| `hal/rp2040_arduino.py` | Stub | +10 |
| `hal/nrf52_arduino.py` | Stub | +10 |
| `hal/cmsis_arm.py` | Stub | +10 |
| `codegen.py` | WiFi collection + emission | +180 |
| `ir_lowering.py` | WiFi lowering | +60 |
| `ir_codegen.py` | WiFi HAL calls | +40 |
| `iotift/tools/lsp_server.py` | Completions + hover | +70 |
| `iotift/tools/formatter.py` | WiFi formatting | +40 |
| `iotift/tools/linter.py` | 7 new rules | +50 |
| `tests/test_wifi.py` | New test file | +500 |
| `examples/wifi_thermostat.iot` | New example | +60 |
| `examples/wifi_scanner.iot` | New example | +40 |
| `README.md` | WiFi language reference section | +100 |
| `TODO.md` | Update M8 status | +5 |
| `codegen.py` / `ir_codegen.py` | Version → 2.1.0 | +2 |

---

## 21. Backward Compatibility

- Existing M7 HAL `wifi_*` methods remain in `HALBase` — extended, not broken
- Existing `wifi.iot` stdlib module kept for users who prefer extern-fn style
- Existing examples (`led.iot`, `console_rgb.iot`, `argb.iot`) must continue to compile
- No WiFi code may leak into non-WiFi programs
- `OnEvent.pin` → `OnEvent.target` is an internal rename; all usage sites updated

---

## 22. Acceptance Criteria (25 items)

- [ ] 22.1  — WiFi declaration syntax: STA, AP, STA+AP, all config keys
- [ ] 22.2  — Lexer: wifi contextual keywords
- [ ] 22.3  — AST: WifiDecl node; OnEvent generalized (pin→target)
- [ ] 22.4  — Parser: parses all wifi syntax forms with error recovery
- [ ] 22.5  — Semantic: validates wifi config, resolves names, enforces mode rules
- [ ] 22.6  — Semantic: catches dual-STA, unsupported-target, property-on-wrong-mode
- [ ] 22.7  — HAL: structured WiFi interface; ESP32 Arduino + ESP-IDF implementations
- [ ] 22.8  — HAL: unsupported targets return clear diagnostics
- [ ] 22.9  — Codegen (direct): emits all WiFi boilerplate from declarations
- [ ] 22.10 — Codegen (IR): IR lowering + emission for WiFi
- [ ] 22.11 — State machine: 4-state FSM with correct transitions
- [ ] 22.12 — Retry system: none, fixed, forever, exponential, custom
- [ ] 22.13 — Event ordering: connect after got_ip, disconnect before retry
- [ ] 22.14 — Properties: .connected, .ip, .rssi, .channel, .mac, .clients, .state, .ssid
- [ ] 22.15 — Methods: .scan(), .disconnect() (no .connect())
- [ ] 22.16 — Events: connect, disconnect, got_ip, scan_done, client_join, client_leave
- [ ] 22.17 — Multi-wifi: independent naming, shared guards, dual-mode detection
- [ ] 22.18 — No leakage: non-WiFi programs emit zero WiFi code
- [ ] 22.19 — NVS guard: single nvs_flash_init across multiple declarations
- [ ] 22.20 — LSP: completions + hover for all wifi constructs
- [ ] 22.21 — Formatter: wifi declarations and event handlers
- [ ] 22.22 — Linter: 7 wifi-specific lint rules
- [ ] 22.23 — Tests: ~77 new tests; all 500 existing tests still pass
- [ ] 22.24 — Examples: wifi_thermostat.iot, wifi_scanner.iot
- [ ] 22.25 — Docs: README WiFi section, version → 2.1.0

---

## Appendix A: Design Alternatives Considered & Rejected

### A.1 `wifi home = sta "ssid" "pass";`
**Rejected:** Positional strings fragile; cannot cleanly omit password;
doesn't scale to future auth methods; `=` misleading for declaration.

### A.2 `wifi(sta) home { ... }`
**Rejected:** Looks like a function call; `sta` as argument is confusing;
inconsistent with all other Iotift declaration forms.

### A.3 `wifi home: sta { ... }`
**Rejected:** Colon conflicts with key-value syntax inside block; unusual
for a top-level declaration.

### A.4 Keep `connect()` as user method
**Rejected:** Encourages manual lifecycle management; users forget to call
it; double-connect bugs; defeats "generated code over runtime magic" philosophy.

### A.5 Separate `WifiOnEvent` AST node
**Rejected:** `OnEvent` with generalized `target` field works for both pins
and WiFi. Semantic pass determines target type. Less AST bloat, fewer node
types to maintain.

### A.6 `stap` keyword for dual mode
**Rejected:** Conflates two interfaces into one declaration; confusing event
namespacing; separate declarations with compiler merge is cleaner.

### A.7 `online` or `ready` instead of `connected`
**Rejected:** `.connected` is the standard term in WiFi APIs (Arduino, ESP-IDF,
Python requests, Node.js). `.online` suggests internet access (not just
local connection). `.ready` is too vague.

---

## Appendix B: Comparison with Other Embedded WiFi APIs

| Feature | Arduino WiFi | ESP-IDF | MicroPython | Iotift (this spec) |
|---------|-------------|---------|-------------|---------------------|
| Connection | `WiFi.begin(ssid, pass)` | `esp_wifi_connect()` | `wlan.connect(ssid, pass)` | Declaration-driven |
| State check | `WiFi.status()` | `esp_wifi_*` events | `wlan.isconnected()` | `.connected` property |
| Events | `WiFi.onEvent()` | Event loop callbacks | `wlan.irq()` | `on wifi.connect {}` |
| Retry | Manual loop | Manual | Manual | Configurable policies |
| Scan | Blocking by default | Async events | Blocking | Async via `.scan()` + event |
| AP mode | Separate class | Mode config | `wlan.config(ap=...)` | `mode: ap` in declaration |
| Dual mode | Manual merge | Manual merge | N/A | Compiler auto-merge |
| Boilerplate | ~50 lines min | ~100 lines min | ~10 lines | **3 lines** |

Iotift's WiFi API is the most concise while remaining the most capable —
thanks to compiler-generated boilerplate and declaration-driven design.
