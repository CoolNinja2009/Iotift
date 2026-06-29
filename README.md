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
| **4 — Standard Library** | 📋 Planned | Import system, stdlib modules (time, math, gpio, serial, etc.) |
| **5 — Tooling** | 📋 Planned | Formatter, linter, polished CLI |
| **6 — LSP & Editor** | 📋 Planned | VS Code extension, diagnostics, completion, hover |
| **7 — Multi-Target** | 📋 Planned | STM32, RP2040, nRF52, bare-metal backends, production features |

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
python iotift.py <source.iot> [options]
```

| Flag | Description |
|------|-------------|
| `<source.iot>` | **Required.** The input Iotift source file |
| `-o`, `--output <file>` | Output C file (default: `generated.c`) |
| `--ast` | Dump the Abstract Syntax Tree to stdout (for debugging) |
| `--ir-dump` | Dump the IR to stdout (for debugging, implies `--no-optimize`) |
| `--direct-codegen` | Use direct AST→C codegen (skip IR pipeline) |
| `--no-optimize` | Skip IR optimization passes |
| `--device <target>` | Target device (default: `esp32`) |
| `--project` | Generate a full PlatformIO project folder instead of a single `.c` file |
| `--flash` | Generate PlatformIO project, build, and upload to device |
| `--port <port>` | Serial port for flashing (e.g. `COM3`, `/dev/ttyUSB0`). If omitted, auto-detects ESP32 |
| `--Werror` | Promote all warnings to errors |
| `--Wno <name>` | Disable a specific warning (e.g., `unused-variable`, `implicit-narrowing`) |
| `--scheduler-slots <N>` | Number of scheduler task slots (default: 16) |

### Examples

```bash
# Basic compilation (uses IR pipeline by default)
python iotift.py blink.iot -o blink.c

# Use direct AST→C codegen (legacy path)
python iotift.py blink.iot -o blink.c --direct-codegen

# Dump AST for debugging
python iotift.py blink.iot --ast

# Dump IR for debugging
python iotift.py blink.iot --ir-dump

# Generate PlatformIO project (folder with platformio.ini + src/main.cpp)
python iotift.py blink.iot --project

# Compile and flash in one command (auto-detect port)
python iotift.py blink.iot --flash

# Flash to a specific port
python iotift.py blink.iot --flash --port COM5

# Treat warnings as errors
python iotift.py blink.iot --Werror

# Suppress specific warnings
python iotift.py blink.iot --Wno unused-variable --Wno implicit-narrowing
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
┌─────────┐  tokens   ┌──────────┐  AST   ┌───────────┐  typed AST
│  lexer  │ ────────► │  parser  │ ─────► │ semantic  │ ──────────►
│  .py    │           │  .py     │        │ .py       │
└─────────┘           └──────────┘        └───────────┘
                                                 │
    ┌────────────────────────────────────────────┘
    │
    ▼
┌──────────────┐   IR   ┌───────────────┐  opt IR  ┌──────────────┐  C code
│ ir_lowering  │ ─────► │ ir_optimizer  │ ───────► │ ir_codegen   │ ──────►
│ .py          │        │ .py           │          │ .py          │
│ AST → TAC IR │        │ folds, DCE,   │          │ IR → C/C++   │
│              │        │ RSE           │          │ (HAL-aware)   │
└──────────────┘        └───────────────┘          └──────────────┘
                                                          │
                                                          ▼
                                                  ┌──────────────┐
                                                  │ PlatformIO    │
                                                  │ build & flash │
                                                  │ (optional)    │
                                                  └──────────────┘
```

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

---

## 🎯 Supported Target

| Target | `millis()` | `HIGH`/`LOW` | Digital I/O | Analog | PWM |
|--------|-----------|-------------|-------------|--------|-----|
| **ESP32** | `millis()` | `HIGH`/`LOW` | `digitalWrite` | `analogRead` | `ledcWrite` (LEDC) |

> The HAL dictionary in `codegen.py` (line ~18) makes adding new targets
> straightforward — each target is a single entry mapping Iotift primitives
> to platform-specific C calls.

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
│
├── ir.py               # IR: three-address code instruction set
├── ir_lowering.py      # IR lowering: AST → IR translation
├── ir_optimizer.py     # IR optimizer: constant folding, DCE, RSE
├── ir_codegen.py       # IR codegen: IR → C/C++ with HAL
├── codegen.py          # Direct codegen: AST → C/C++ (legacy path)
│
├── hal/                # Hardware Abstraction Layer
│   ├── __init__.py     # HAL registry + factory
│   ├── base.py         # HALBase abstract class
│   └── esp32_arduino.py# ESP32 Arduino HAL implementation
│
├── tests/              # Test suite (221 tests)
│   ├── test_lexer.py   # 29 tests
│   ├── test_parser.py  # 41 tests
│   ├── test_codegen.py # 14 tests
│   ├── test_semantic.py# 65 tests
│   ├── test_ir.py      # 54 tests
│   └── test_hal.py     # 18 tests
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
