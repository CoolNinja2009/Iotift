<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://img.shields.io/badge/IOTIFT-ESP32-blue?style=for-the-badge">
    <img alt="Iotift" src="https://img.shields.io/badge/IOTIFT-ESP32-blue?style=for-the-badge">
  </picture>
</p>

<p align="center">
  <a href="#-quick-start"><img src="https://img.shields.io/badge/🚀-Quick%20Start-green?style=flat-square" alt="Quick Start"></a>
  <a href="#-language-reference"><img src="https://img.shields.io/badge/📖-Language%20Reference-orange?style=flat-square" alt="Language Reference"></a>
  <a href="#-examples"><img src="https://img.shields.io/badge/💡-Examples-yellow?style=flat-square" alt="Examples"></a>
  <a href="#-cli-reference"><img src="https://img.shields.io/badge/⚙️-CLI%20Reference-lightgrey?style=flat-square" alt="CLI"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.8+-blue?logo=python&logoColor=white" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/platform-ESP32-red?logo=espressif&logoColor=white" alt="Platform">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  <img src="https://img.shields.io/badge/codegen-C%2FC++-00599C?logo=c&logoColor=white" alt="C/C++">
  <img src="https://img.shields.io/badge/build-PlatformIO-orange?logo=platformio&logoColor=white" alt="PlatformIO">
</p>

---

# 🔌 Iotift — IoT, Simplified

**Iotift** is a high-level, expressive programming language that compiles to C/C++ for
microcontrollers. Write clean, readable code — let the compiler handle the boilerplate.

Stop wrestling with `pinMode()`, `digitalWrite()`, `ledcSetup()`, timer ISRs, and
register-level bit-banging. Iotift gives you **pins**, **PWM**, **timers**, and
**events** as first-class language concepts.

```iot
@device esp32

pin LED  = output 2;      // digital output on GPIO 2
pin TEMP = analog A0;     // analog input
pin R    = pwm 13;        // PWM output on GPIO 13

R.setup(5000, 8);         // 5 kHz, 8-bit resolution

every 1000 {               // run every 1000 ms
    LED = 1;               // turn LED on
    LED = 0 after 200;     // turn off after 200 ms
}

on TEMP > 50.0 {           // event: temperature threshold
    print("Overheat!");
}
```

```bash
# Compile to a C file
python iotift.py blink.iot -o blink.c

# Or generate a PlatformIO project and flash directly
python iotift.py blink.iot --flash
```

---

## 📑 Table of Contents

- [✨ Features](#-features)
- [🚀 Quick Start](#-quick-start)
- [📖 Language Reference](#-language-reference)
  - [Device Declaration](#device-declaration)
  - [Pin Declarations](#pin-declarations)
  - [Variables & Types](#variables--types)
  - [Structs & Arrays](#structs--arrays)
  - [Functions](#functions)
  - [Control Flow](#control-flow)
  - [Events & Timers](#events--timers)
  - [PWM Methods](#pwm-methods)
  - [Math Functions](#math-functions)
  - [Printing](#printing)
  - [Time Literals](#time-literals)
  - [Raw C Injection](#raw-c-injection)
  - [Imports & Modules](#imports--modules)
- [💡 Examples](#-examples)
- [⚙️ CLI Reference](#-cli-reference)
- [🏗️ Architecture](#-architecture)
- [🎯 Supported Targets](#-supported-targets)
- [🧩 Project Structure](#-project-structure)
- [📄 License](#-license)

---

## 🗺️ Milestones

| Milestone | Status | Key Deliverables |
|-----------|--------|-----------------|
| **0 — Foundation** | ✅ Done | Working lexer→parser→codegen pipeline, 29 AST node types, 77 tests |
| **1 — Semantic Analysis** | ✅ Done | Type checking, name resolution, scope analysis, 47 tests |
| **2 — IR & Optimization** | ✅ Done | Three-address code IR, constant folding, DCE, RSE, 54 tests |
| **3 — Embedded Improvements** | ✅ Done | Real interrupts, min-heap scheduler, HAL architecture, ISR safety |
| **4 — Standard Library** | ✅ Done | Import system, stdlib modules, prelude auto-import, 49 tests |
| **5 — Tooling** | ✅ Done | Formatter, linter, polished CLI, source maps (84 tests) |
| **6 — LSP & Editor** | ✅ Done | LSP server, VS Code extension, diagnostics, completion, hover (77 tests) |
| **7 — Multi-Target** | ✅ Done | 8 targets, ESP-IDF/CMSIS, production APIs, debugger, package manager (500 tests) |
| **8 — First-Class WiFi** | 📐 Spec Ready | Block-syntax declarations, event-driven WiFi, 4-state FSM, retry policies, 25 criteria |

---

## ✨ Features

<table>
  <tr>
    <td width="50%">
      <h3>🔌 Pin-First Design</h3>
      <p>Declare pins with direction and number in one line. PWM setup is a method call, not a ritual of register configuration.</p>
    </td>
    <td width="50%">
      <h3>⏱️ Built-in Timers</h3>
      <p><code>every 1000 { ... }</code> gives you a repeating timer in one line. Label it with <code>as</code> and stop it with <code>stop</code>.</p>
    </td>
  </tr>
  <tr>
    <td>
      <h3>🎯 Event-Driven</h3>
      <p><code>on PIN.press { ... }</code> and <code>on PIN > threshold { ... }</code> wire up interrupts and analog comparators declaratively.</p>
    </td>
    <td>
      <h3>🧵 Raw C Injection</h3>
      <p>Drop to C/C++ anywhere — <code>c header { ... }</code>, <code>c global { ... }</code>, <code>c setup { ... }</code>, <code>c loop { ... }</code>. No escape-hatch compromises.</p>
    </td>
  </tr>
  <tr>
    <td>
      <h3>📐 Math Built-In</h3>
      <p><code>sin()</code>, <code>cos()</code>, <code>tan()</code>, <code>sqrt()</code>, <code>abs()</code>, <code>pow()</code>, <code>floor()</code>, <code>ceil()</code>, <code>round()</code>, <code>log()</code>, <code>exp()</code> — all available without includes.</p>
    </td>
    <td>
      <h3>🚀 One-Command Flash</h3>
      <p><code>python iotift.py myfile.iot --flash</code> — auto-detects your ESP32 port, generates a PlatformIO project, builds, and uploads.</p>
    </td>
  </tr>
  <tr>
    <td>
      <h3>🖨️ Time Literals</h3>
      <p>Write <code>2s</code> for 2000 ms or <code>30m</code> for 1,800,000 ms. The compiler converts at compile-time — no runtime cost.</p>
    </td>
    <td>
      <h3>🎚️ LEDC PWM</h3>
      <p>First-class PWM on ESP32 via the LEDC peripheral. <code>pin R = pwm 13; R.setup(5000, 8); R.write(128);</code> — the compiler generates all the <code>ledcSetup</code>/<code>ledcAttachPin</code>/<code>ledcWrite</code> boilerplate.</p>
    </td>
  </tr>
  <tr>
    <td>
      <h3>\U0001f4e6 Module System</h3>
      <p><code>import "file.iot"</code> shares code across files. <code>import { sin, cos } from "math"</code> for selective imports. Stdlib modules (time, math, gpio, serial, i2c, spi, pwm) included. Circular import detection built in.</p>
    </td>
    <td>
      <h3>⚡ Auto-Import Prelude</h3>
      <p><code>time</code>, <code>math</code>, and <code>gpio</code> are auto-imported into every program. <code>millis()</code>, <code>sin()</code>, <code>digitalWrite()</code> — always available without imports.</p>
    </td>
  </tr>
  <tr>
    <td>
      <h3>🌐 Multi-Target</h3>
      <p>8 targets, 2 frameworks. ESP32, STM32, RP2040, nRF52, AVR. Arduino & bare-metal (ESP-IDF, CMSIS). One codebase, any MCU.</p>
    </td>
    <td>
      <h3>📦 Package Manager</h3>
      <p><code>iotift add github.com/user/pkg</code> adds deps to iotift.toml. <code>iotift update</code> syncs the lock file. Version pinning built in.</p>
    </td>
  </tr>
</table>

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.8+**
- (Optional) **PlatformIO** — for `--project` / `--flash` features (auto-installed if missing)
- (Optional) **pyserial** — for ESP32 port auto-detection (auto-installed if missing)

### Installation

```bash
git clone https://github.com/your-org/iotift.git
cd iotift

# Create a virtual environment (recommended)
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # macOS / Linux

# Install dependencies
pip install platformio pyserial
```

### Your First Program

Create `blink.iot`:

```iot
@device esp32

pin LED = output 2;

every 500 {
    LED = 1;
    LED = 0 after 250;
}
```

Compile and flash:

```bash
python iotift.py blink.iot --flash
```

Or just generate the C code:

```bash
python iotift.py blink.iot -o blink.c
```

---

## 📖 Language Reference

### Device Declaration

Every `.iot` file starts with a device declaration. This selects the correct HAL for
code generation.

```iot
@device esp32          // ESP32
```

> `@device esp32` is the default and currently the only supported target.

### Pin Declarations

```
pin <name> = <direction> <number>;
```

| Direction | C Equivalent | Description |
|-----------|-------------|-------------|
| `output` | `pinMode(n, OUTPUT)` | Digital output |
| `input` | `pinMode(n, INPUT_PULLUP)` | Digital input with pull-up |
| `analog` | `pinMode(n, INPUT)` | Analog input (ADC) |
| `i2c` | `pinMode(n, INPUT)` | I²C bus |
| `spi` | — | SPI bus |
| `pwm` | `ledcSetup(...)` | PWM output (ESP32 LEDC peripheral) |

```iot
pin LED    = output 2;    // GPIO 2 as digital output
pin BTN    = input  5;    // GPIO 5 as input w/ pull-up
pin SENSOR = analog A0;   // Analog pin A0
pin SDA    = i2c    21;   // I²C data line
pin R      = pwm    13;   // PWM-capable pin
```

#### PWM-Specific Options

You can specify PWM frequency and resolution directly in the declaration:

```iot
pin R = pwm 13 freq 5000 resolution 8;
//       ^      ^^^^            ^^
//       pin    5 kHz        8-bit (0–255)
```

### Variables & Types

```
<type> <name> = <value>;
```

| Type | C Equivalent | Example |
|------|-------------|---------|
| `int` | `int` | `int count = 0;` |
| `float` | `float` | `float temp = 25.5;` |
| `bool` | `bool` | `bool on = true;` |
| `str` | `const char*` | `str msg = "hello";` |

```iot
int   count   = 0;
float temp    = 23.5;
bool  running = true;
str   label   = "sensor_1";

const float MAX_TEMP = 100.0;   // compile-time constant
```

### Structs & Arrays

```iot
struct Sensor {
    int   id;
    float value;
    str   name;
}

int readings[10];          // array of 10 ints
```

Access struct members and array elements with the expected syntax:

```iot
Sensor s;
s.id    = 1;
s.value = 42.0;

readings[0] = 100;
```

### Functions

```
fn <name>(<params>) -> <return_type> {
    <body>
}
```

```iot
fn add(int a, int b) -> int {
    return a + b;
}

fn blink(int times) {
    int i = 0;
    while i < times {
        LED = 1;
        LED = 0 after 200;
        i += 1;
    }
}
```

#### External (C) Functions

Declare C functions from libraries or your own injected code:

```iot
extern fn esp_restart();
extern fn digitalRead(int pin) -> int;
```

### Control Flow

#### if / else if / else

```iot
if temp > 30.0 {
    print("Hot!");
} else if temp < 10.0 {
    print("Cold!");
} else {
    print("Comfortable");
}
```

#### while

```iot
while count < 10 {
    count += 1;
}
```

#### for

```iot
for int i = 0; i < 10; i += 1 {
    print(i);
}
```

#### loop

An infinite loop (generates `while(1)`):

```iot
loop {
    // runs forever
}
```

#### void loop()

A named user loop that runs on each main loop iteration:

```iot
void loop() {
    // runs every main loop tick
}
```

#### break / continue

```iot
while true {
    if condition {
        break;      // exits the loop
    }
    if other {
        continue;   // skips to next iteration
    }
}
```

### Events & Timers

#### on — Pin Event

Triggers when a digital pin changes state. Compiles to an interrupt handler.

```iot
on BTN.press {              // rising edge
    LED = 1;
}

on BTN.release {            // falling edge
    LED = 0;
}

on BTN.change {             // any edge
    print("Changed!");
}
```

| Event | Interrupt Mode | Trigger |
|-------|---------------|---------|
| `.press` | `FALLING` | Button pressed (HIGH → LOW, assumes pull-up) |
| `.release` | `RISING` | Button released (LOW → HIGH) |
| `.rising` | `RISING` | Rising edge |
| `.falling` | `FALLING` | Falling edge |
| `.change` | `CHANGE` | Any edge |

> 🔌 **Since Milestone 3:** `on PIN.event` compiles to a **real hardware interrupt**
> via `attachInterrupt()`. The ISR is minimal (sets a `volatile bool` flag) and the
> user body runs in `loop()` — safe, predictable, and non-blocking.
> 
> Debounce is configured in the pin declaration and applied in the handler
> (never in the ISR):
> ```iot
> pin BTN = input 5 { pull: up, debounce: 50ms };
> on BTN.press { LED = 1; }   // debounced button press
> ```

#### on — Threshold Event

Monitors an analog pin and triggers when a threshold is crossed.

```iot
on TEMP > 50.0 {
    print("Overheat warning!");
}

on LIGHT < 200 {
    LED = 1;
}
```

#### every — Repeating Timer

Runs a block at a fixed interval. The interval is in **milliseconds**.

```iot
every 1000 {                // every 1 second
    LED = !LED;              // toggle LED
}
```

Use time literals for readability:

```iot
every 1s {                  // 1s = 1000 ms
    print("Tick");
}

every 5m {                  // 5m = 300,000 ms
    print("5 minutes passed");
}
```

##### Named Timers

Label a timer with `as` to stop it later:

```iot
every 500 as blinker {
    LED = !LED;
}

// later...
stop blinker;               // stops the timer
```

#### after — Delayed Assignment

Schedule a pin/value change after a delay. Runs once (uses the scheduler).

```iot
LED = 1;                    // turn on now
LED = 0 after 200;          // turn off in 200 ms
```

#### after — One-Shot Timer Block  *(new in Milestone 3)*

Standalone `after` block that fires once after the given delay, then never again.

```iot
after 5s {
    print("5 seconds elapsed!");
}

after 100ms {
    LED = 0;                  // turn off after 100 ms
}
```

#### every — Timer Offset  *(new in Milestone 3)*

Delay the first fire of a repeating timer with `offset`:

```iot
every 10s offset 2s {        // first fire at 2s, then every 10s
    print("Tick");
}
```

#### Timer Status Methods  *(new in Milestone 3)*

Named timers expose `.running`, `.stop()`, and `.start()`:

```iot
every 500 as blinker {
    LED = !LED;
}

tick {
    if blinker.running {     // check if timer is active
        blinker.stop();      // stop the timer
    }
}

// later...
blinker.start();              // restart from now
```

#### ISR Functions  *(new in Milestone 3)*

Declare interrupt service routines with `isr fn`. The compiler emits
`IRAM_ATTR` on ESP32 and enforces safety rules at compile time:

```iot
volatile int counter = 0;

isr fn on_timer() {
    counter += 1;             // OK: counter is volatile
}

// Compile-time errors:
// isr fn bad() {
//     print("hello");        // ERROR: cannot print in ISR
//     delay(100);            // ERROR: cannot block in ISR
//     int x = 0;             // ERROR: non-volatile variable
// }
```

**ISR Safety Rules:**
- ❌ `print` / `println` — error
- ❌ `delay` / `delayMicroseconds` — error
- ❌ I2C / SPI / UART calls — error
- ❌ Non-`volatile` variables — error
- ✅ `volatile` variable access — OK
- ✅ Simple arithmetic, flag-setting — OK

### Scheduler  *(upgraded in Milestone 3)*

The deferred-execution scheduler (used for `after` assignments) now uses a
**min-heap** for O(log n) insert and O(1) peek:

- **Overflow detection**: `_iotift_scheduler_overflow` flag set when full
- **Configurable slots**: `@config scheduler_slots = 32;` or `--scheduler-slots 32`
- **Deterministic**: no dynamic allocation, fixed-size array at compile time

### HAL Architecture  *(new in Milestone 3)*

Iotift now has a **Hardware Abstraction Layer** (`hal/` package) that isolates
platform-specific code from the compiler:

```
hal/
├── __init__.py          # HAL registry + get_hal() factory
├── base.py              # HALBase abstract class (~25 methods)
└── esp32_arduino.py     # ESP32 Arduino implementation
```

`@device esp32` now actually dispatches to `ESP32ArduinoHAL`. Adding a new
target (STM32, RP2040, …) means implementing `HALBase` and registering it.

### PWM Methods

PWM pins expose two methods:

```iot
pin R = pwm 13;

R.setup(5000, 8);           // .setup(frequency_hz, resolution_bits)
R.write(128);               // .write(duty_value)  —  0 to (2^resolution - 1)
```

- **`.setup(freq, resolution)`** — configures the PWM channel.
  - `freq`: frequency in Hz (e.g. `5000` for 5 kHz)
  - `resolution`: bit depth (e.g. `8` → 0–255, `10` → 0–1023)
  - Calls `ledcSetup()` + `ledcAttachPin()` on ESP32
- **`.write(value)`** — sets the duty cycle.
  - Calls `ledcWrite()` on ESP32

### Math Functions

All standard math functions are available without headers or imports:

```iot
float x = sin(t * 0.001);
float y = cos(angle);
float z = sqrt(a*a + b*b);
int   v = abs(diff);
float p = pow(base, 2.0);
float l = log(sensor_val);
```

| Function | Equivalent C |
|----------|-------------|
| `sin(x)` | `sin(x)` |
| `cos(x)` | `cos(x)` |
| `tan(x)` | `tan(x)` |
| `sqrt(x)` | `sqrt(x)` |
| `abs(x)` | `abs(x)` / `fabs(x)` |
| `pow(x, y)` | `pow(x, y)` |
| `floor(x)` | `floor(x)` |
| `ceil(x)` | `ceil(x)` |
| `round(x)` | `round(x)` |
| `log(x)` | `log(x)` |
| `exp(x)` | `exp(x)` |

The compiler automatically emits `#include <math.h>` when any math function is used.

### WiFi  *(new in v2.1.0 / Milestone 8)*

WiFi is a **first-class language feature**. The compiler generates all boilerplate:
NVS init, TCP/IP stack, event loop, and WiFi state machine. You write only the
logic that matters.

#### Declaration

```iot
wifi home {
    ssid: "MyWiFi";
    password: "mypassword";
}
```

This single block generates ~150 lines of correct C: WiFi init, STA config,
event loop, connection, retry logic, state tracking, and event dispatch.

#### All Configuration Keys

| Key | Type | Default | Mode | Description |
|-----|------|---------|------|-------------|
| `mode` | `sta` \| `ap` | `sta` | both | Operating mode |
| `ssid` | `str` | *(required)* | both | Network name (1–32 chars) |
| `password` | `str` | *(none)* | both | WPA/WPA2 passphrase (omit for open) |
| `hostname` | `str` | auto | sta | DHCP hostname |
| `connect_timeout` | time | `30s` | sta | Per-attempt timeout |
| `retry` | retry spec | `fixed` | sta | Retry policy |
| `power_save` | `none` \| `light` \| `deep` | `none` | sta | Power save mode |
| `static_ip` | `str` | DHCP | sta | Static IPv4 address |
| `gateway` | `str` | DHCP | sta | Gateway (requires static_ip) |
| `subnet` | `str` | DHCP | sta | Subnet mask |
| `dns` | `str` | DHCP | sta | DNS server |
| `channel` | `int` (1–13) | `1` | ap | WiFi channel |
| `max_clients` | `int` (1–16) | `4` | ap | Max stations |
| `hidden` | `bool` | `false` | ap | Hide SSID |

#### Access Point Mode

```iot
wifi guest {
    mode: ap;
    ssid: "FreeWiFi";
    channel: 6;
    max_clients: 4;
}
```

#### Dual Mode (STA + AP)

Declare two separate wifi blocks — the compiler auto-merges into `WIFI_MODE_APSTA`:

```iot
wifi sta_if { ssid: "HomeWiFi"; password: "pass"; }
wifi ap_if  { mode: ap; ssid: "IotiftAP"; password: "ap123"; }
```

#### Properties (Read-Only State)

| Property | Type | Mode | Description |
|----------|------|------|-------------|
| `.state` | `WifiState` | both | State machine state |
| `.connected` | `bool` | sta | True when connected with IP |
| `.ip` | `str` | sta | Local IPv4 address |
| `.rssi` | `int` | sta | Signal strength in dBm |
| `.channel` | `int` | both | Current channel |
| `.mac` | `str` | both | MAC address |
| `.clients` | `int` | ap | Connected station count |
| `.ssid` | `str` | both | Configured SSID |

#### Methods

| Method | Mode | Description |
|--------|------|-------------|
| `wifi.scan()` | sta | Start async WiFi scan |
| `wifi.disconnect()` | sta | Disconnect from WiFi |

There is no `.connect()` method — connection is **declaration-driven** and
compiler-managed.

#### Events

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
    int count = scan_result_count();
    for int i = 0; i < count; i += 1 {
        print(scan_result_ssid(i));
        print(": ");
        println(scan_result_rssi(i));
    }
}

on ap_if.client_join {
    print("Client joined. Total: " + ap_if.clients);
}
```

| Event | Mode | Fires when |
|-------|------|------------|
| `connect` | sta | WiFi connected AND IP obtained |
| `disconnect` | sta | WiFi disconnected (any reason) |
| `got_ip` | sta | IP address assigned (before `connect`) |
| `scan_done` | sta | WiFi scan completed |
| `client_join` | ap | Station connected to AP |
| `client_leave` | ap | Station disconnected from AP |

#### Retry Policies

```iot
wifi sensor { retry: none; }         // single attempt
wifi stable { retry: fixed; }        // 3 retries, 5s apart (default)
wifi critical { retry: forever; }    // never stop retrying
wifi office  { retry: exponential; } // 1s, 2s, 4s, 8s... up to 60s
wifi custom  { retry: custom { count: 5, interval: 10s }; }
```

#### State Machine

The compiler generates a 4-state FSM: **IDLE → CONNECTING → CONNECTED ⇄ DISCONNECTED**.
All event handlers run in the scheduler task (no ISR, no FreeRTOS event loop).

#### No Leakage Guarantee

Programs without WiFi declarations emit **zero** WiFi-related code. No
`#include <WiFi.h>`, no NVS init, no event loop.

### Printing

```iot
print("Hello, World!");
print(temp);
print("Temperature: " + temp);
```

Generates `Serial.println(...)` on ESP32.

### Time Literals

Suffixes that compile to integer milliseconds:

| Suffix | Meaning | Example | Compiles to |
|--------|---------|---------|-------------|
| `s` | seconds × 1000 | `2s` | `2000` |
| `m` | minutes × 60000 | `5m` | `300000` |

```iot
every 1s { ... }            // 1000 ms
every 30m { ... }           // 1,800,000 ms (30 minutes)
```

> These are **compile-time constants** — they cost nothing at runtime.

### Raw C Injection

When you need to write C/C++ directly (libraries, registers, ISRs, RTOS primitives,
etc.), use `c` blocks. There are four scopes, each mapping to a specific section
of the generated output:

```
c header { ... }    // above all includes and declarations
c global { ... }    // in the global scope (variables, functions, structs)
c setup  { ... }    // inside setup()
c loop   { ... }    // inside loop()
```

```iot
c header {
    #include <driver/rmt.h>
    #include <driver/gpio.h>

    #define MY_PIN GPIO_NUM_4
}

c global {
    // This goes in the global scope
    void my_custom_init() {
        gpio_set_direction(MY_PIN, GPIO_MODE_OUTPUT);
    }

    int shared_counter = 0;
}

c setup {
    // This runs inside setup()
    my_custom_init();
    Serial.println("Initialized!");
}

c loop {
    // This runs inside loop() on every iteration
    shared_counter++;
}
```

The lexer handles C blocks with full brace-depth tracking — strings, comments
(both `//` and `/* */`), and nested braces inside `c` blocks are all handled
correctly.

### Imports & Modules  *(new in Milestone 4)*

Iotift supports importing symbols from other `.iot` files and from the standard library.

#### Import All

Import all top-level symbols from a file:

```iot
import "utils.iot";       // all symbols from utils.iot are now available
```

#### Selective Import

Import only specific names:

```iot
import { sin, cos, PI } from "math";     // only sin, cos, and PI
import { digitalWrite } from "gpio";     // only digitalWrite
```

#### Path Resolution

| Path Style | Example | Resolves To |
|-----------|---------|-------------|
| Bare name | `"time"` | Relative to importing file, then stdlib directory |
| Relative | `"./lib.iot"` | Relative to importing file |
| Parent-relative | `"../shared.iot"` | One directory up from importing file |

#### Prelude (Auto-Import)

Three modules are automatically imported into every Iotift program — no explicit
`import` needed:

| Module | Provides |
|--------|----------|
| `time` | `millis()`, `micros()`, `delay()`, `delay_us()` |
| `math` | `sin()`, `cos()`, `tan()`, `sqrt()`, `abs()`, `pow()`, `floor()`, `ceil()`, `round()`, `log()`, `exp()` |
| `gpio` | `digitalRead()`, `digitalWrite()`, `pinMode()`, `toggle()` |

#### Standard Library

Additional modules available via explicit import:

| Module | Import | Key Functions |
|--------|--------|---------------|
| serial | `import "serial";` | `serialBegin()`, `serialPrint()`, `serialPrintln()`, `serialRead()` |
| i2c | `import "i2c";` | `i2cBegin()`, `i2cRead()`, `i2cWrite()`, `i2cScan()` |
| spi | `import "spi";` | `spiBegin()`, `spiTransfer()` |
| pwm | `import "pwm";` | `pwmSetup()`, `pwmWrite()`, `pwmStop()` |

> **How it works:** Imports are resolved at the AST level before semantic analysis.
> The compiler lexes and parses the imported file, then inlines its declarations
> into your program. Circular imports are detected and reported as errors.

---


## 💡 Examples

### RGB LED Fader (PWM)

Uses three PWM pins and math functions to create a smooth color cycle.

```iot
@device esp32

pin R = pwm 13;
pin G = pwm 12;
pin B = pwm 14;

R.setup(1000, 10);
G.setup(1000, 10);
B.setup(1000, 10);

float r = 0.0;
float g = 0.0;
float b = 0.0;
float t = 0.0;

every 10 {
    t = millis();

    r = 255 - (127.5 + 127.5 * sin(t * 0.001));
    g = 255 - (127.5 + 127.5 * sin(t * 0.001 + 2.094));
    b = 255 - (127.5 + 127.5 * sin(t * 0.001 + 4.189));

    R.write(r);
    G.write(g);
    B.write(b);
}
```

### WS2812B / Neopixel Sniffer

Full example — uses raw C injection for the RMT peripheral on ESP32 to decode
WS2812B timing, then prints decoded RGB frames over serial.

```iot
@device esp32

c header {
    #include <driver/rmt.h>

    #define GPIO_ARGB_DATA   4
    #define RMT_RX_CHANNEL   RMT_CHANNEL_0
    #define MAX_LEDS         300

    struct RGB {
        uint8_t r, g, b;
    };

    RGB           ledFrame[MAX_LEDS];
    int           ledCount = 0;
    RingbufHandle_t rb     = NULL;
}

c global {
    void setupRMT() {
        rmt_config_t cfg = RMT_DEFAULT_CONFIG_RX(
            (gpio_num_t)GPIO_ARGB_DATA, RMT_RX_CHANNEL
        );
        cfg.clk_div = 8;
        rmt_config(&cfg);
        rmt_driver_install(RMT_RX_CHANNEL, 2048, 0);
        rmt_get_ringbuf_handle(RMT_RX_CHANNEL, &rb);
        rmt_rx_start(RMT_RX_CHANNEL, true);
    }

    void decodeFrame(rmt_item32_t* items, size_t count) {
        // ... (bit-banging decode logic)
    }
}

c setup {
    setupRMT();
}

c loop {
    // poll RMT ringbuffer, decode, print
}
```

### Button-Controlled LED

Event-driven input handling.

```iot
@device esp32

pin LED = output 2;
pin BTN = input  5;

on BTN.press {
    LED = 1;
}

on BTN.release {
    LED = 0;
}
```

### Temperature Monitor

Analog threshold monitoring.

```iot
@device esp32

pin TEMP = analog A0;
pin FAN  = output 4;
pin RED  = output 13;

on TEMP > 80.0 {
    FAN = 1;
    RED = 1;
    print("CRITICAL: " + TEMP);
}

on TEMP < 30.0 {
    FAN = 0;
    RED = 0;
}
```

### Named Timer with Stop

```iot
@device esp32

pin LED = output 2;

every 500 as blinker {
    LED = !LED;
}

// After 10 seconds, stop blinking and leave LED on
LED = 1 after 10000;
stop blinker after 10000;
```

---

## ⚙️ CLI Reference

```
iotift <command> [options]

Commands:
  check   <file.iot>              Type-check only, no code generation
  build   <file.iot> [-o out.c]   Compile to C (default command)
  flash   <file.iot>              Compile + flash to device
  debug   <file.iot>              Build with debug flags + GDB launch
  fmt     <file.iot> [--check]    Format source file
  lint    <file.iot>              Run linter
  new     <project-name>          Scaffold new project
  add     <package>               Add a package dependency
  remove  <package>               Remove a package dependency
  update  [package]               Update package dependencies
  version                         Print version

Legacy: iotift <file.iot> [options]  (equivalent to 'build')
```

### Common Flags

| Flag | Description |
|------|-------------|
| `-o`, `--output <file>` | Output C file (default: `<source>.c`) |
| `--ast` | Dump the AST to stdout (for debugging) |
| `--ir-dump` | Dump the IR to stdout (implies `--no-optimize`) |
| `--direct-codegen` | Use direct AST→C codegen (skip IR pipeline) |
| `--no-optimize` | Skip IR optimization passes |
| `--target`, `--device <target>` | Target device (default: `esp32`) |
| `--debug` | Emit source maps (`// @iot:line N` comments + `.map.json`) |
| `--project` | Generate a full PlatformIO project folder |
| `--flash` | Generate PlatformIO project, build, and upload |
| `--port <port>` | Serial port for flashing (auto-detected if omitted) |
| `--Werror` | Promote all warnings to errors |
| `--Wno <name>` | Disable a specific warning |
| `--scheduler-slots <N>` | Number of scheduler task slots (default: 16) |

### Examples

```bash
# Type-check only (no C output)
iotift check blink.iot

# Basic compilation (uses IR pipeline by default)
iotift build blink.iot -o blink.c

# Target a specific MCU
iotift build blink.iot --target stm32
iotift build blink.iot --target rp2040

# Bare-metal build (no Arduino)
iotift build blink.iot --target espidf

# Compile with debug symbols + launch GDB
iotift debug blink.iot
iotift debug blink.iot --gdb arm-none-eabi-gdb

# Format code
iotift fmt blink.iot
iotift fmt blink.iot --check     # check only, no modification

# Run linter
iotift lint blink.iot

# Scaffold new project
iotift new my-project

# Package management
iotift add github.com/user/package
iotift add github.com/user/package --version v1.2.0
iotift remove package
iotift update                    # update all
iotift update package            # update specific

# Print version
iotift version

# Compile and flash in one command
iotift flash blink.iot

# Flash to a specific port
iotift flash blink.iot --port COM5

# Dump IR for debugging
iotift build blink.iot --ir-dump

# Treat warnings as errors
iotift build blink.iot --Werror
```

### Auto-Detection

When `--flash` is used without `--port`, Iotift scans available serial ports for
ESP32 chips by looking for common USB-serial bridge manufacturers:

- **CP210x** (Silicon Labs)
- **CH340 / CH341** (WCH)
- **FTDI**

If exactly one match is found, it's used automatically. If multiple are found,
the first one is used with a warning. If none are found, you'll be prompted
to specify `--port`.

---

## 🔌 LSP & Editor Integration

Iotift includes a full Language Server Protocol (LSP) server and VS Code extension
for a modern IDE experience.

### LSP Server

```bash
# Start the language server (for editor integration)
iotift lsp
```

The LSP server provides:

| Feature | Description |
|---------|-------------|
| **Diagnostics** | Real-time error and warning reporting from lexer, parser, semantic analyzer, and linter |
| **Completion** | Keywords, types, snippets, in-scope symbols, and stdlib functions |
| **Hover** | Type information and documentation for variables, functions, pins, structs, enums, and peripherals |
| **Go-to-Definition** | Jump to the declaration of any symbol |
| **Find References** | Find all uses of a symbol across the document |
| **Document Symbols** | Outline view showing all declarations with hierarchical structure |

### VS Code Extension

The extension is in `vscode-extension/` and provides:

- **Syntax highlighting** — Full TextMate grammar for `.iot` files
- **Snippets** — 30+ ready-made templates (pin, fn, every, on, struct, enum, if, for, etc.)
- **Commands** — Compile, flash, format, and lint from the command palette
- **LSP client** — Automatic language server integration
- **Language configuration** — Bracket matching, auto-closing pairs, comment toggling

To build from source:

```bash
cd vscode-extension
npm install
npm run compile
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      IOTIFT COMPILER                             │
├──────────┬──────────┬──────────┬──────────┬──────────┬─────────┤
│ lexer.py │parser.py │semantic  │ir_      │ir_       │ir_      │
│ ───────  │───────── │.py       │lowering │optimizer │codegen  │
│ Tokenize │Build AST │Type      │.py      │.py       │.py      │
│ source   │from      │checking, │AST→IR   │Constant  │IR→C/C++ │
│          │tokens    │scope     │TAC      │folding,  │(HAL-    │
│          │          │analysis  │lowering │DCE       │aware)   │
├──────────┴──────────┴──────────┴──────────┴──────────┴─────────┤
│                   ast_nodes.py                                   │
│  Pure dataclass definitions for every language node              │
├─────────────────────────────────────────────────────────────────┤
│                   ir.py                                          │
│  Three-Address Code IR: instructions, basic blocks, IR module    │
└─────────────────────────────────────────────────────────────────┘
```

### Pipeline

```
.iot source
    │
    ▼
┌─────────┐  tokens   ┌──────────┐  AST   ┌────────────────┐  inlined AST
│  lexer  │ ────────► │  parser  │ ─────► │ import resolver │ ────────────►
│  .py    │           │  .py     │        │ .py            │
└─────────┘           └──────────┘        └────────────────┘
                                                 │
    ┌────────────────────────────────────────────┘
    │
    ▼
┌───────────┐  typed AST  ┌──────────────┐   IR   ┌───────────────┐  opt IR
│ semantic  │ ──────────► │ ir_lowering  │ ─────► │ ir_optimizer  │ ───────►
│ .py       │             │ .py          │        │ .py           │
└───────────┘             └──────────────┘        └───────────────┘
                                                          │
                                                          ▼
                                                  ┌──────────────┐  C code
                                                  │ ir_codegen   │ ──────►
                                                  │ .py          │
                                                  └──────────────┘

### Key Design Decisions

1. **Separation of concerns.** `ast_nodes.py` holds only dataclasses — zero logic.
   `lexer.py` knows only about characters and tokens. `parser.py` knows only about
   tokens and AST nodes. `codegen.py` is the **single source of all C/C++ knowledge**.

2. **Three-Address Code IR.** The IR (`ir.py`) sits between semantic analysis and
   code generation, enabling optimization passes like constant folding, dead code
   elimination, and redundant store elimination before final C emission.

3. **IR pipeline is default.** Compilation goes through the full IR pipeline
   (AST → IR → optimize → C). The original AST→C codegen is preserved behind
   `--direct-codegen` for backward compatibility.

4. **HAL abstraction.** Device-specific differences (`millis()`, pin constants,
   PWM APIs) live in the `hal/` package. Adding a new target
   means implementing `HALBase`. The `@device` directive now actually
   dispatches to the correct HAL.

5. **First-pass collection.** The code generator does two logical passes:
   1. **Collect** — walk the AST, register pins, functions, timers, and events
   2. **Emit** — assemble the final C output in the correct order (headers →
      globals → scheduler → functions → handlers → setup → loop)

6. **Min-heap scheduler.** `every` blocks compile to a lightweight cooperative
   scheduler using a binary min-heap (O(log n) insert, O(1) peek). Overflow
   detection sets a flag when all slots are full. Configurable via
   `@config scheduler_slots = N` or `--scheduler-slots N`.

7. **Real interrupts.** `on PIN.event` generates `attachInterrupt()` with a
   minimal IRAM ISR that sets a `volatile bool` flag. The user body runs
   safely in `loop()` with optional debounce applied in the handler.

8. **AST-level imports.** `import "file.iot"` and `import { Name } from "..."`
   are resolved before semantic analysis by inlining the imported file's AST
   declarations. Circular imports are detected. The prelude (time, math, gpio)
   is auto-imported into every file.

---

## 🎯 Supported Targets

| Target | Framework | `millis()` | Digital I/O | PWM | ISR |
|--------|-----------|-----------|-------------|-----|-----|
| **ESP32** | Arduino | `millis()` | `digitalWrite` | `ledcWrite` (LEDC) | `IRAM_ATTR` |
| **ESP32** | ESP-IDF | `esp_timer_get_time()` | `gpio_set_level` | `ledc_set_duty` | `IRAM_ATTR` |
| **STM32** | Arduino | `millis()` | `digitalWrite` | `analogWrite` | — |
| **STM32** | CMSIS | SysTick | `GPIO->BSRR` | `TIM->CCR` | — |
| **RP2040** | Arduino-Pico | `millis()` | `digitalWrite` | `analogWrite` (PIO) | — |
| **nRF52** | Arduino | `millis()` | `digitalWrite` | `analogWrite` | — |
| **nRF52** | CMSIS | SysTick | `GPIO->BSRR` | `TIM->CCR` | — |
| **AVR** | Arduino | `millis()` | `digitalWrite` | `analogWrite` (8-bit) | `ISR()` |

> Adding a new target means implementing `HALBase` (~40 methods) and
> registering it in `hal/__init__.py`. Alias support (e.g. `pico` → `rp2040`,
> `uno` → `avr`) makes device selection natural. See `hal/` for examples.

---

## 🧩 Project Structure

```
Iotift/
├── iotift.py           # CLI entry point, PlatformIO integration
├── lexer.py            # Lexer: source text → token stream
├── parser.py           # Parser: token stream → AST
├── ast_nodes.py        # AST node definitions (pure dataclasses)
├── semantic.py         # Semantic analyzer: type checking, scope resolution
├── symbol_table.py     # Hierarchical symbol table with scoping
├── type_system.py      # Type definitions and checking rules
├── import_resolver.py  # Import resolution: path lookup, inlining, circular detection
│
├── ir.py               # IR: three-address code instruction set
├── ir_lowering.py      # IR lowering: AST → IR translation
├── ir_optimizer.py     # IR optimizer: constant folding, DCE, RSE
├── ir_codegen.py       # IR codegen: IR → C/C++ with HAL
├── codegen.py          # Direct codegen: AST → C/C++ (legacy path)
│
├── hal/                # Hardware Abstraction Layer
│   ├── __init__.py     # HAL registry + factory (8 targets)
│   ├── base.py         # HALBase abstract class (~80 methods)
│   ├── esp32_arduino.py# ESP32 Arduino HAL (default target)
│   ├── esp32_espidf.py # ESP32 ESP-IDF HAL (bare-metal, no Arduino)
│   ├── stm32_arduino.py# STM32F1/F4 Arduino HAL
│   ├── rp2040_arduino.py# Raspberry Pi Pico Arduino HAL
│   ├── nrf52_arduino.py # nRF52840/nRF52832 Arduino HAL
│   ├── avr_arduino.py # ATmega328P/2560 Arduino HAL
│   └── cmsis_arm.py   # ARM Cortex-M CMSIS HAL (bare-metal template)
│
├── iotift/             # Iotift package
│   ├── __init__.py     #   Package init
│   ├── stdlib/         #   Standard library (.iot files)
│   │   ├── time.iot    #     millis, micros, delay, delay_us
│   │   ├── math.iot    #     sin, cos, tan, sqrt, abs, pow, ...
│   │   ├── gpio.iot    #     digitalRead, digitalWrite, pinMode, toggle
│   │   ├── serial.iot  #     serialBegin, serialPrint, serialRead
│   │   ├── i2c.iot     #     i2cBegin, i2cRead, i2cWrite, i2cScan
│   │   ├── spi.iot     #     spiBegin, spiTransfer
│   │   ├── pwm.iot     #     pwmSetup, pwmWrite, pwmStop
│   │   ├── power.iot   #     deepSleep, lightSleep, wakeupCause
│   │   ├── watchdog.iot#     watchdogEnable, watchdogReset
│   │   ├── filesystem.iot#   mount, open, read, write, close
│   │   ├── flash.iot   #     flashRead, flashWrite, flashErase
│   │   ├── wifi.iot    #     wifiBegin, wifiStatus, wifiLocalIP
│   │   ├── ble.iot     #     bleBegin, bleStartAdvertising
│   │   └── ota.iot     #     otaBegin, otaWrite, otaEnd, otaRollback
│   └── tools/          #   Tooling (Milestone 5)
│       ├── __init__.py #     Package init
│       ├── formatter.py#     Opinionated code formatter
│       └── linter.py   #     Static analysis linter
│
├── tests/              # Test suite (500 tests)
│   ├── test_lexer.py   # 29 tests
│   ├── test_parser.py  # 41 tests
│   ├── test_codegen.py # 14 tests
│   ├── test_semantic.py# 65 tests
│   ├── test_ir.py      # 54 tests
│   ├── test_hal.py     # 62 tests (new HALs, production features)
│   ├── test_imports.py # 30 tests
│   ├── test_stdlib.py  # 19 tests
│   ├── test_formatter.py # 57 tests
│   ├── test_linter.py  # 27 tests
│   ├── test_lsp.py     # 77 tests
│   └── test_m7_cli.py  # 25 tests (debug, package manager, multi-target)
│
├── examples/           # Example .iot programs
│   ├── led.iot         #   RGB LED PWM fader
│   ├── console_rgb.iot #   Console RGB (WS2812B)
│   └── argb.iot        #   WS2812B sniffer (RMT)
│
├── nothing/            # Backup/scratch directory (gitignored)
├── .venv/              # Python virtual environment (gitignored)
├── .gitignore
└── README.md
```

---

## 📄 License

MIT © 2025

---

<p align="center">
  <sub>Built with ❤️ for the embedded community. PRs welcome!</sub>
</p>

<p align="center">
  <a href="https://www.espressif.com/en/products/socs/esp32">
    <img src="https://img.shields.io/badge/Powered%20by-ESP32-E7352C?logo=espressif&logoColor=white&style=flat-square" alt="ESP32">
  </a>
</p>
