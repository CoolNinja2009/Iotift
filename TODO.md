# Iotift — Implementation Roadmap

**Reference:** `ARCHITECTURE_REVIEW.md` — read first for design rationale.
**Rule:** Every milestone must compile. Every milestone must have tests.

---

## ✅ MILESTONE 0 — Foundation: Working Pipeline + Tests **(DONE)**

**Goal:** Fix the broken compiler. Revert AST bloat. Wire lexer→parser→codegen.
         All existing `.iot` examples compile and generate correct C.

### 0.1 — Revert AST to working node set
- [x] Read original working `ast_nodes.py` from `nothing/Bak5(stable)/`
- [x] Keep only nodes that match the current parser's output
- [x] Add ONLY these new nodes: `EnumDecl`, `TypeAliasDecl`, `DeferStmt`,
      `CastExpr`, `SizeOfExpr`, `PeripheralDecl`, `TickBlock`, `PinConfig`
- [x] Remove: MatchStmt, all Pattern nodes, ForInStmt, ImplBlock, TraitDecl,
      ModuleDecl, RangeExpr, IfExpr, BlockExpr, SpawnExpr, CancelSchedule,
      ScheduleBlock, MicrosExpr, ExternBlock, FnParam (use VarDecl for params)
- [x] Target: ~35 node types (was 60+)  →  Achieved: 47 concrete node types

### 0.2 — Trim lexer to minimal keyword set
- [x] Remove from KEYWORDS: `match`, `spawn`, `cancel`, `module`, `trait`,
      `impl`, `in` (keep only for `schedule` if needed)
- [x] Remove `STDLIB_FUNCTIONS` — math functions are IDENT, resolved by semantic pass
- [x] Keep: `let`, `var`, `const`, `defer`, `enum`, `type`, `isr`, `volatile`,
      `sizeof`, `tick`, `schedule`, `rising`, `falling`
- [x] Keep all TYPE_KEYWORDS (`u8..u64`, `i8..i64`, `f32`, `f64`, `int`, `float`, etc.)
- [x] Keep `press`, `release`, `change` for backward compat
- [x] Fix block comment handling — replaced regex with state machine (avoid ReDoS)

### 0.3 — Update parser for trimmed feature set
- [x] Accept both old-style (`int x = 0;`) and new-style (`let x = 0;`) declarations
- [x] Parse `TYPE_KW` tokens as type names
- [x] Parse `enum Name { Variant1, Variant2 = 5 }`
- [x] Parse `defer { ... }` statement
- [x] Parse `expr as TYPE` cast expression
- [x] Parse `sizeof(TYPE)` expression
- [x] Parse `tick { ... }` (new) alongside `void loop() { ... }` (deprecated)
- [x] Parse `pin BTN = input 5 { pull: up, debounce: 50ms }` config blocks
- [x] Parse `i2c/spi/uart` peripheral declarations
- [x] Add `volatile` modifier to variable declarations
- [x] Add `isr` modifier to function declarations
- [x] Emit deprecation warning for `void loop()` suggesting `tick`
- [x] **Add basic error recovery:** synchronize on `;` `}` after parse error
- [x] Unify dot-access parsing (single `_parse_dot_tail` for both contexts)

### 0.4 — Update codegen to handle new AST
- [x] Wire codegen to work with the trimmed AST node set
- [x] Fix excessive parentheses in generated expressions (precedence-based)
- [x] Generate `static const uint8_t` for pin definitions (not `#define`)
- [x] Generate stable timer names using user labels (`_iotift_every_blinker`)
- [x] Don't emit empty timer/event handlers
- [x] Basic string interpolation: `"temp: {x}"` → `Serial.print("temp: "); Serial.print(x);`
- [x] Disable `+` on strings → compiler error with suggestion to use `{var}`
- [x] Keep backward compat: `void loop()` generates same code as before

### 0.5 — Write test suite
- [x] `tests/test_lexer.py` — 29 tests (all passing)
  - All token types, keywords, type keywords
  - Hex (`0xFF`), binary (`0b1010`), octal (`0o77`), decimal, underscore separators
  - Float (`1.5`, `1.5e-3`), time literals (`500ms`, `2s`, `5m`, `1h`)
  - String literals with escapes (`"hello\nworld"`)
  - Char literals (`'A'`, `'\n'`, `'\xFF'`)
  - C-block injection (all scopes)
  - Comments (`//`, `/* */`), whitespace handling
  - Error cases (unterminated block comment, unexpected character)
- [x] `tests/test_parser.py` — 34 tests (all passing)
  - Every declaration type (pin, var, fn, struct, enum, extern, device, import)
  - Every statement type (if/else/elif, while, for, loop, tick, return, break, continue, defer, print)
  - Every expression type (binary ops, unary, member access, array access, fn call, method call, cast, sizeof)
  - Event/timer syntax (on press/release/rising/falling/change, on threshold, every, every as, after)
  - Error recovery (parse continues after first error)
- [x] `tests/test_codegen.py` — 14 tests (all passing)
  - blink, PWM, button debounce, named timer, empty timer skip, after assign, const pins,
    function emission, cast, sizeof, enums, no string concat, volatile, ISR functions

### 0.6 — Verify existing examples
- [x] `led.iot` compiles and generates correct C (12 nodes → 88 lines)
- [x] `console_rgb.iot` compiles and generates correct C (39 nodes → 401 lines)
- [x] `nothing/main.iot` compiles and generates correct C (17 nodes → 128 lines)

---

## ✅ MILESTONE 1 — Semantic Analysis **(DONE)**

**Goal:** Type checking, name resolution, scope analysis. Catch errors before C compiler.

### 1.1 — Integrate symbol table
- [x] Wire `symbol_table.py` into compilation pipeline
- [x] Run symbol table construction pass before codegen
- [x] Define symbols for: variables, functions, pins, timers, structs, enums, types

### 1.2 — Implement 4 semantic passes
- [x] **Pass 1: Symbol Table Construction** — register all declarations
- [x] **Pass 2: Name Resolution** — resolve every identifier to a symbol
- [x] **Pass 3: Type Checking** — check assignments, fn args, return types
- [x] **Pass 4: Scope Analysis** — determine global vs. stack-local vs. static

### 1.3 — Type inference
- [x] `let x = 0` infers `int`
- [x] `let x = 0xFF` infers `int`
- [x] `let x = 25.5` infers `float`
- [x] `let x = true` infers `bool`
- [x] `let x = "hello"` infers `str`
- [x] `let x = 'A'` infers `char`
- [x] `let x: u32 = 0` uses explicit type

### 1.4 — Warning infrastructure
- [x] Warning collector in symbol table
- [x] `-Werror` flag (warnings as errors)
- [x] `-Wno-<name>` flag (disable specific warning)
- [x] Warning: unused variable
- [x] Warning: unused function
- [x] Warning: variable used before init
- [x] Warning: implicit narrowing conversion
- [x] Warning: empty event/timer body
- [x] Warning: `void loop()` deprecation (suggest `tick`)

### 1.5 — Semantic tests
- [x] `tests/test_semantic.py` — 47 tests (all passing)
  - Type mismatch errors
  - Undefined variable errors
  - Duplicate declaration errors
  - Scope shadowing
  - Type inference cases
  - Warning emission cases

---

## ✅ MILESTONE 2 — IR & Optimization **(DONE)**

**Goal:** Three-address code IR. Constant folding, DCE, stack promotion.

### 2.1 — Implement IR
- [x] `ir.py` — TAC instruction set
- [x] Instr types: Binary, Unary, Copy, Load, Store, Call, Branch, Jump,
      Label, Return, Cast, ArrayAccess, MemberAccess
- [x] IR module: list of functions, each with list of basic blocks
- [x] IR values: temp, const, var, global, param, label

### 2.2 — AST → IR lowering
- [x] `ir_lowering.py` — AST → IR pass
- [x] Lower every AST node to IR instructions
- [x] Lower expressions to temporaries
- [x] Lower control flow to basic blocks with branches
- [x] Lower `every`/`on`/`tick` blocks to functions called from loop()
- [x] Lower pin/VarDecl/struct/enum to IR globals
- [x] Handle AssignAfter with scheduler detection

### 2.3 — Optimization passes
- [x] **Constant Folding** — evaluate `1 + 2` at compile time
- [x] **Dead Code Elimination** — remove unreachable blocks, empty functions
- [x] **Empty Handler Removal** — delete `every`/`on` blocks with empty bodies
- [x] **Redundant Store Elimination** — remove back-to-back stores to same var
- [x] Stack Promotion — implemented but disabled (needs debug for local init values)

### 2.4 — IR → C codegen
- [x] `ir_codegen.py` — emit C from IR (not AST directly)
- [x] Old AST→C codegen preserved as fallback behind `--direct-codegen` flag
- [x] Structured if/else emission for branch patterns
- [x] Local temp variable declarations
- [x] Math.h auto-include detection

### 2.5 — IR tests
- [x] `tests/test_ir.py` — 54 tests (all passing)
  - Lowering correctness (21 tests)
  - Constant folding verification (11 tests)
  - DCE verification (2 tests)
  - Empty handler removal (2 tests)
  - Full pipeline integration (14 tests)
  - Optimizer correctness (4 tests)
  - Console RGB integration (1 test)
  - Direct codegen backward compat (1 test)

---

## ✅ MILESTONE 3 — Embedded Improvements **(DONE)**

**Goal:** Real interrupts, better scheduler, HAL architecture, peripheral APIs.

### 3.1 — Real interrupts for `on PIN.event`
- [x] Generate `attachInterrupt()` for `on PIN.press/release/change`
- [x] ISR function: minimal — sets `volatile bool` flag, nothing else
- [x] Handler function: runs in `loop()`, checks flag, executes user body
- [x] Add `debounce` support in handler (not ISR)
- [x] ISR safety checks: no print, no delay, no allocation in ISR body

### 3.2 — Scheduler improvements
- [x] Replace linear scan with min-heap (O(log n) insert, O(1) peek)
- [x] Configurable slot count via `@config scheduler_slots = N` or CLI flag
- [x] Overflow detection: set error flag when full (debug: panic with diagnostics)
- [x] Timer offset: `every 1s offset 100ms { ... }`
- [x] One-shot timer: `after 5s { ... }` block (extends current assignment-only)
- [x] Timer status: `blinker.running`, `blinker.stop()`, `blinker.start()`

### 3.3 — HAL architecture
- [x] `hal/base.py` — HAL interface (abstract base class)
- [x] `hal/esp32_arduino.py` — ESP32 Arduino implementation
- [x] HAL methods for: GPIO, PWM, ADC, I2C, SPI, UART, interrupts, serial, time
- [x] Device selection: `@device esp32` → loads ESP32 Arduino HAL
- [x] Codegen calls HAL methods instead of hardcoded Arduino strings

### 3.4 — Peripheral APIs
- [x] `i2c NAME { sda: N, scl: N, speed: X }` declaration + begin/read/write
- [x] `spi NAME { mosi, miso, sck, speed, mode }` declaration + transfer
- [x] `uart NAME { tx, rx, baud }` declaration + print/read
- [x] `adc` configuration (resolution, attenuation)
- [x] `pwm` improvements (multi-channel, servo mode)

### 3.5 — `isr fn` support
- [x] Parser: `isr fn name(params) { ... }`
- [x] Codegen: `IRAM_ATTR` on ESP32, equivalent on other targets
- [x] Safety: compile error if body contains `print`, `delay`, I2C/SPI calls
- [x] Safety: compile error if accessed variables not `volatile`

### 3.6 — Integration tests
- [x] Compiler-level tests for all features (221 tests passing)
- [x] blink test (GPIO output) — via codegen verification
- [x] button test (interrupt + debounce) — via codegen verification
- [x] PWM test (LED fade) — existing console_rgb.iot
- [x] HAL unit tests — 18 tests passing
- [ ] Test on real ESP32 hardware (deferred for hardware availability)

---

## MILESTONE 4 — Standard Library & Module System ✅ **(DONE)**

**Goal:** Working imports. Stdlib available.

### 4.1 — Import system
- [x] `import "file.iot"` — import all top-level symbols
- [x] `import { Name1, Name2 } from "file.iot"` — selective import
- [x] Resolve path relative to importing file
- [x] Prevent circular imports (detect and error)
- [x] Merge imported symbols into importer's scope

### 4.2 — Standard library
- [x] `iotift/stdlib/time.iot` — millis, micros, delay, delay_us
- [x] `iotift/stdlib/math.iot` — sin, cos, tan, sqrt, abs, pow, floor, ceil, round, log, exp
- [x] `iotift/stdlib/gpio.iot` — digital_read, digital_write, toggle, pin_mode
- [x] `iotift/stdlib/serial.iot` — print, println, read, available, begin
- [x] `iotift/stdlib/i2c.iot` — begin, read, write, scan
- [x] `iotift/stdlib/spi.iot` — begin, transfer
- [x] `iotift/stdlib/pwm.iot` — setup, write, stop

### 4.3 — Auto-import prelude
- [x] `time`, `math`, `gpio` auto-imported (available without explicit import)
- [x] Others require explicit `import "module"`

### 4.4 — Stdlib tests
- [x] `tests/test_imports.py` — import resolution, circular import detection (30 tests)
- [x] `tests/test_stdlib.py` — each stdlib function generates correct C (19 tests)

---

## MILESTONE 5 — Tooling ✅ **(DONE)**

**Goal:** Formatter, linter, polished CLI.

### 5.1 — CLI redesign
- [x] `iotift check file.iot` — type-check only, no codegen
- [x] `iotift build file.iot -o output.c` — compile to C
- [x] `iotift flash file.iot` — compile + flash (auto-detect port)
- [x] `iotift fmt file.iot` — format file in-place
- [x] `iotift fmt --check file.iot` — check formatting without modifying
- [x] `iotift lint file.iot` — run linter
- [x] `iotift new project-name` — scaffold new project
- [x] `iotift version` — print version
- [x] `--debug` flag — emit source maps, verbose IR dumps
- [x] `--target` flag — select target device

### 5.2 — Formatter (`iotift/tools/formatter.py`)
- [x] Opinionated, zero configuration
- [x] 4-space indentation
- [x] Opening brace on same line
- [x] One blank line between top-level declarations
- [x] Semicolons preserved
- [x] Long lines (>100 chars) wrapped

### 5.3 — Linter (`iotift/tools/linter.py`)
- [x] `no-float-in-isr` — error
- [x] `no-heap-in-isr` — error
- [x] `no-print-in-isr` — warning
- [x] `no-blocking-in-timer` — warning
- [x] `prefer-fixed-width` — warning (`int` → `i32`)
- [x] `unused-variable` — warning
- [x] `unused-function` — warning
- [x] `empty-timer` — warning
- [x] `const-candidate` — info (variable never mutated)
- [x] `volatile-needed` — warning (variable shared with ISR)

### 5.4 — Source maps
- [x] `.iot` line → generated `.c` line mapping
- [x] Emit as comment in generated C (`// @iot:line 42`)
- [x] Separate `.map` JSON file for tooling

---

## MILESTONE 6 — LSP & Editor Integration ✅ **(DONE)**

**Goal:** IDE support (VS Code).

### 6.1 — LSP server
- [x] `iotift/tools/lsp_server.py`
- [x] Diagnostics (errors/warnings as-you-type)
- [x] Completion (variables, functions, types, keywords)
- [x] Hover (type info, documentation)
- [x] Go-to-definition
- [x] Find references
- [x] Document symbols

### 6.2 — VS Code extension
- [x] Syntax highlighting (TextMate grammar)
- [x] LSP client configuration
- [x] Snippets (pin, every, on, fn, struct, enum)
- [x] Command: compile, flash, monitor

---

## MILESTONE 7 — Multi-Target & Production ✅ **(DONE)**

**Goal:** Beyond ESP32. Production firmware possible.

### 7.1 — Additional targets
- [x] STM32 (Arduino core + bare-metal)
- [x] RP2040 (Arduino core + Pico SDK)
- [x] nRF52 (Arduino core + nRF SDK)
- [x] AVR (Arduino Uno/Nano legacy)

### 7.2 — Bare-metal backend
- [x] ESP-IDF backend (no Arduino dependency)
- [x] CMSIS backend for ARM Cortex-M
- [x] Smaller binary, faster boot, less overhead

### 7.3 — Production features
- [x] Power management API (deep sleep, light sleep, wake sources)
- [x] Watchdog API
- [x] Filesystem API (LittleFS, FAT)
- [x] Flash/EEPROM storage API
- [x] WiFi API
- [x] BLE API
- [x] OTA update support
- [x] Secure boot integration

### 7.4 — Debugging
- [x] Debug adapter protocol (DAP) integration
- [x] `iotift debug` command
- [x] Breakpoint support
- [x] Variable inspection

### 7.5 — Package manager
- [x] `iotift add github.com/user/package`
- [x] `iotift remove package`
- [x] `iotift update`
- [x] Package registry (iotift.io/packages)
- [x] Version pinning (iotift.toml lock file)

---

## FEATURES NEVER TO ADD

| Feature | Reason |
|---------|--------|
| Borrow checker / ownership | Rust complexity |
| Lifetime annotations | Rust complexity |
| Async/await | Heap futures = unpredictable RAM |
| Exceptions (try/catch) | Code bloat, unpredictable control flow |
| Class inheritance (virtual dispatch) | vtable overhead |
| Operator overloading | Hides cost model |
| Template metaprogramming | Unreadable errors |
| Garbage collection | Unpredictable pauses |
| REPL | Not useful for firmware |
| Macros (token-tree / hygenic) | `comptime` evaluation is enough |
| Pattern matching (`match`) | `if`/`else if` works |
| Traits / typeclasses | HAL uses simple function tables |
| Significant whitespace | Breaks C interop, hard to auto-format |
---
## ✅ MILESTONE 8 — First-Class WiFi  **(DONE)**

**Goal:** WiFi as a first-class language feature with native syntax support.
The compiler generates ALL boilerplate: NVS init, TCP/IP stack, event loop,
WiFi state machine.  Users write only the logic that matters.

**Full specification:** `spec/milestone-8.md` — complete architecture review
and language design. Read that first before implementing.

**Key design decisions (from the 2026-06-29 architecture review):**

1. **Block syntax, no `=`:** `wifi home { ssid: "x"; password: "y"; }`
   — matches `i2c bus0 { ... }` pattern. Rejected `wifi home = sta "ssid" "pass"`.

2. **Properties for state, methods for actions:**
   `.connected`, `.ip`, `.rssi`, `.channel`, `.mac`, `.clients`, `.state` are properties.
   `.scan()`, `.disconnect()` are methods. No `.connect()` — compiler-managed.

3. **No `stap` keyword:** Dual mode = two declarations. Compiler auto-merge.

4. **Generalized `OnEvent`:** `target` field replaces `pin`; WiFi events reuse
   the same AST node. No `OnWifiEvent`/`WifiMethodCall` nodes needed.

5. **Structured HAL output:** `WifiInitOutput` dataclass instead of raw C strings.
   Compiler composes output; HAL isolates platform details.

6. **4-state machine:** IDLE → CONNECTING → CONNECTED ⇄ DISCONNECTED.

7. **5 retry policies:** none, fixed (default), forever, exponential, custom.

8. **Semantic pass catches unsupported targets** (not C `#error`).

9. **All handlers run in scheduler task** (not ISR, not FreeRTOS event loop).

**Design philosophy applies to all future comm peripherals:**
BLE (§9), MQTT (§10), HTTP (§11), Ethernet (§12), Cellular (§13).

### Acceptance criteria (25 items)

- [x] 8.1  — WiFi declaration syntax: STA, AP, STA+AP, all config keys
- [x] 8.2  — Lexer: wifi contextual keywords
- [x] 8.3  — AST: WifiDecl node; OnEvent generalized (pin→target)
- [x] 8.4  — Parser: parses all wifi syntax forms with error recovery
- [x] 8.5  — Semantic: validates wifi config, resolves names, enforces mode rules
- [x] 8.6  — Semantic: catches dual-STA, unsupported-target, property-on-wrong-mode
- [x] 8.7  — HAL: structured WiFi interface; ESP32 Arduino + ESP-IDF implementations
- [x] 8.8  — HAL: unsupported targets return clear diagnostics
- [x] 8.9  — Codegen (direct): emits all WiFi boilerplate from declarations
- [x] 8.10 — Codegen (IR): WiFi-ready (HAL methods available for IR lowering)
- [x] 8.11 — State machine: 4-state FSM with correct transitions
- [x] 8.12 — Retry system: none, fixed, forever, exponential, custom
- [x] 8.13 — Event ordering: connect after got_ip, disconnect before retry
- [x] 8.14 — Properties: .connected, .ip, .rssi, .channel, .mac, .clients, .state, .ssid
- [x] 8.15 — Methods: .scan(), .disconnect() (no .connect())
- [x] 8.16 — Events: connect, disconnect, got_ip, scan_done, client_join, client_leave
- [x] 8.17 — Multi-wifi: independent naming, shared guards, dual-mode detection
- [x] 8.18 — No leakage: non-WiFi programs emit zero WiFi code
- [x] 8.19 — NVS guard: single nvs_flash_init across multiple declarations
- [x] 8.20 — LSP: completions + hover for all wifi constructs
- [x] 8.21 — Formatter: wifi declarations and event handlers
- [x] 8.22 — Linter: 7 wifi-specific lint rules
- [x] 8.23 — Tests: 69 new WiFi tests; all 500 existing tests still pass (569 total)
- [x] 8.24 — Examples: wifi_thermostat.iot, wifi_scanner.iot
- [x] 8.25 — Docs: README WiFi section, version → 2.1.0
