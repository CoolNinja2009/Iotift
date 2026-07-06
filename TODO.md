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

---

## 🔴 MILESTONE 8.5 — IR Pipeline Bug Bash (Fix All Generated C)

**Status:** Planning | **Branch:** `milestone-9-ir-bug-bash` | **Created:** 2026-06-29

**Goal:** Every one of the 16 example `.iot` files compiles through the IR pipeline
and emits **correct, compilable, working** C code. Zero new regressions on the 569
existing tests.

**Problem:** The IR pipeline (`ir_lowering.py` → `ir_codegen.py`) is the DEFAULT
compilation path but was written as a first draft with several stubbed-out sections.
The old direct codegen (`codegen.py`) handles most constructs correctly — the IR
pipeline must be brought to parity. **All 16 generated .c files have bugs.**

---

### TIER 1 — Compile Failures (C code is syntactically invalid)

- [ ] **9.1 — Pin method calls emit invalid C** (`LED.toggle()`, `FAN.high()`)
  - `ir_lowering.py:1147-1164`: `MethodCall` → `IRCallIndirect(func_expr=f'{obj}.{method}()')`.
    Pins are `uint8_t` constants (`LED_PIN = 2U`), not objects with methods.
  - **Fix:** In `_lower_expr` for `MethodCall`, check if obj is a pin. Emit
    `digitalWrite(pin, HIGH/LOW)` or `digitalWrite(pin, !digitalRead(pin))` for toggle.
    Port logic from `codegen.py:920-928`.
  - **Affected:** `simple_blink.c`, `button_led.c`, `temp_monitor.c`, `wifi_ap.c`,
    `state_machine.c`, `math_stress.c`, `scheduler_stress.c`, `full_app.c`, `edge_cases.c`
  - **Test:** `LED.toggle()` → `digitalWrite(LED_PIN, !digitalRead(LED_PIN));`

- [ ] **9.2 — `bool` literals emit Python `True`/`False` (not C `true`/`false`)**
  - `ir_codegen.py:700-712`: Python `bool` is subclass of `int`, so
    `isinstance(False, (int, float))` is `True`, and `str(False)` → `"False"`.
  - **Fix:** Check `isinstance(val, bool)` before `isinstance(val, (int, float))`,
    or check ctype for bool before dispatching.
  - **Affected:** `temp_monitor.c:64`, `scheduler_stress.c:63`
  - **Test:** `bool cooling = false;` → `static bool cooling = false;`

- [ ] **9.3 — WiFi events lowered as pin ISRs with `attachInterrupt` on undefined pins**
  - `ir_lowering.py:341-437` `_lower_on_event` unconditionally creates ISR +
    volatile flag + debounce + `attachInterrupt`. WiFi events are not pin-based.
    No `scanner_PIN` or `primary_PIN` exists → link failure.
  - **Fix:** In `_lower_on_event`, check if target is a WiFi interface
    (look up in symbol table / wifi_decls). If so, skip ISR creation; WiFi events
    dispatch from the WiFi event loop.
  - **Affected:** `wifi_ap.c:188-189`, `wifi_scanner.c:175-177`, `full_app.c:681-683`
  - **Test:** `on scanner.scan_done` → no `attachInterrupt` for `scanner_PIN`

- [ ] **9.4 — Array declarations dropped to scalars (size lost)**
  - `ir_lowering.py:146-151`: `ArrayDecl` → `IRGlobal(ctype=to_ctype(node.vtype))`
    only stores element type (`"float"`), not array type (`"float[10]"`).
    `IRGlobal` has no `array_size` field.
  - **Fix:** Add `array_size: int = 0` to `IRGlobal`. Emit as `ctype name[size];`.
    In `ArrayAccess` lowering, verify base is an array and emit `base[index]`.
  - **Affected:** `full_app.c:118`, `struct_array.c:84`, `edge_cases.c` (missing `arr`)
  - **Test:** `float[10] readings;` → `static float readings[10];`

- [ ] **9.5 — `IRCallIndirect` dest temps not declared (undeclared C variables)**
  - `ir_codegen.py:456-469` temp collection loop enumerates `IRBinary, IRUnary,
    IRCall, IRCast, IRArrayAccess, IRMemberAccess, IRCopy` — but NOT `IRCallIndirect`.
    All method-call result temps are used without declaration.
  - **Fix:** Add `IRCallIndirect` to the `isinstance` check.
  - **Affected:** Every file with method calls (pervasive)
  - **Test:** Every temp variable used in a function appears in its declarations block

- [ ] **9.6 — Duplicate function definitions (colliding names)**
  - `ir_lowering.py:438-483` `_lower_on_threshold`: function name uses only pin name:
    `f'_iotift_threshold_{node.pin}'`. Two thresholds on same pin → identical names.
  - **Fix:** Include operator + value hash in name:
    `f'_iotift_threshold_{node.pin}_{node.op}_{hash_value}'`
  - **Affected:** `temp_monitor.c:104,117`, `full_app.c:482,495`
  - **Test:** Two `on TEMP > X` and `on TEMP < Y` → two distinct function names

- [ ] **9.7 — WiFi declarations silently dropped in IR pipeline**
  - `ir_lowering.py:129-250` `_lower_top_level` has no handler for `WifiDecl`.
    WiFi AST nodes are silently skipped. No state vars, no `WiFi.begin()`, no event dispatch.
  - **Fix:** Add `isinstance(node, WifiDecl)` handler. Port logic from
    `codegen.py:_collect_wifi_decl` and `_emit_wifi_*` methods. Generate:
    WiFi state variables, system init function, event dispatch functions,
    scan accessors, property accessor mapping.
  - **Affected:** `wifi_ap.c`, `wifi_scanner.c`, `wifi_thermostat.c`, `full_app.c`
  - **Test:** `wifi home = sta { ssid: "x"; password: "y"; }` → generates all WiFi boilerplate

---

### TIER 2 — Wrong Behavior (compiles but logic is incorrect)

- [ ] **9.8 — `if`/`elif` lowering: body code emitted BEFORE condition check**
  - `ir_lowering.py:830-869` `_lower_if` RETURNS the branch instruction as a list
    but emits then/else bodies directly via builder INSIDE the method. The caller
    emits the returned branch AFTER the bodies. Result: body code executes
    unconditionally, condition check comes after.
  - **Fix:** Rewrite `_lower_if` to collect ALL instructions (branch + bodies from
    all blocks) and return as a flat list. Do NOT emit directly in `_lower_if`.
    Alternatively: use a two-pass approach (build blocks first, linearize late).
  - **Affected:** ~80% of all handler functions with `if` statements
  - **Test:** `if (x > 5) { LED.high(); }` → condition check FIRST, body SECOND

- [ ] **9.9 — `elif` chain lowering is stubbed out (garbage code)**
  - `ir_lowering.py:850-862`: comment `# Actually need proper elif chaining —
    simplify with merge`. Uses `id(ec)` for label names → nondeterministic labels
    like `_iotift_elif_20655208267041`. Code ordering is scrambled.
  - **Fix:** Lower elif chains as nested if/else within the else block.
    Properly order: condition → then-body → jump to end → else/elif → ...
  - **Affected:** `state_machine.c:85-109`, `full_app.c:297-328`, `edge_cases.c:108-143`
  - **Test:** `if/else if/else if/else` chain → correct structured if/else-if/else

- [ ] **9.10 — Type propagation broken: ALL temp variables typed as `int`**
  - `ir_lowering.py:1057`: `_vv(node.name, 'int')` — Identifier always `'int'`
  - `ir_lowering.py:1192`: `ctype = left.ctype if left.ctype else 'int'` — only left op
  - `ir_lowering.py:1137`: `self.builder.new_temp('call', 'int')` — calls always `'int'`
  - **Fix:** Thread `_resolved_type` from semantic analysis through IR lowering.
    Use `node._resolved_type` to determine the real C type for each IRValue.
  - **Affected:** Every file using float variables or float-returning functions
  - **Test:** `float x = 3.14; float y = x * 2.0;` → `float _iotift_binopN` NOT `int`

- [ ] **9.11 — Pin direction not propagated → analog/input pins set as OUTPUT**
  - `ir.py:319`: `pins: Dict[str, int]` stores only pin number. Direction is lost.
  - `ir_codegen.py:508-515`: hardcodes `_PIN_DIRECTION.get('output', 'OUTPUT')`
    — ignores the pin's actual declared direction.
  - **Fix:** Store `{'number': N, 'direction': 'analog'|'input'|'output'}` in
    module pin registry. Use direction during `_emit_setup`.
  - **Affected:** `temp_monitor.c:136`, `full_app.c:669-670`, `edge_cases.c:574-575`
  - **Test:** `pin TEMP = analog 34;` → `pinMode(TEMP_PIN, INPUT);`

- [ ] **9.12 — Debounce timestamp used uninitialized + body runs unconditionally**
  - Caused by 9.8 (code ordering) + debounce update emitted outside the flag-check
    block. When flag is not set, `_iotift_debounce_nowN` is uninitialized but still
    assigned to the `_last` variable.
  - **Fix:** Fixed automatically by 9.8 (correct block ordering)
  - **Affected:** `button_led.c:97-101`, `scheduler_stress.c:267`, `full_app.c:448,474`
  - **Test:** Debounce timestamp ONLY updated inside flag-check block

- [ ] **9.13 — `break` placeholder `__break__` leaks into C output**
  - `ir_lowering.py:720`: `return [IRJump('__break__')]` — placeholder never resolved
    to actual loop-end label.
  - **Fix:** Track loop end labels in the builder (stack of `(continue_label, break_label)`).
    `break` → `IRJump(break_label)`, `continue` → `IRJump(continue_label)`.
  - **Affected:** `edge_cases.c:192` (`goto __break__;`)
  - **Test:** `break;` inside for/while → `goto _iotift_while_endN;`

- [ ] **9.14 — String interpolation silently fails for non-`\w+` patterns**
  - `ir_lowering.py:989`: regex `r'\{(\w+)\}'` only matches `[a-zA-Z0-9_]+`.
    Fails for: `{millis()}`, `{wifi.ip}`, `{n + n}`, `{sin(f)}`, `{n * 2 + 1}`.
  - **Fix:** At minimum, match `\{([^}]+)\}` and emit the expression directly.
    For simple variable names, use `Serial.print(var)`. For complex expressions,
    evaluate to temp first, then print. Reject unsupported patterns at semantic
    check time with clear error.
  - **Affected:** `button_led.c:139`, `wifi_ap.c:151`, `full_app.c:403,427`,
    `edge_cases.c:339-345`
  - **Test:** `println("IP: {wifi.ip}");` → `Serial.print("IP: "); Serial.println(wifi_ip);`

- [ ] **9.15 — Missing return statements in functions**
  - Caused by 9.8 (block ordering). `return` in then-block is emitted, but else-block
    code is scrambled. Functions fall off the end without returning.
  - **Fix:** Fixed automatically by 9.8 + 9.9
  - **Affected:** `full_app.c:191,252,275`, `edge_cases.c:286`
  - **Test:** Every non-void function has explicit `return` on all control paths

- [ ] **9.16 — Struct field access emits member access on string literal**
  - `edge_cases.c:385-386`: `_iotift_member63 = "cs".value;` — struct variable `cs`
    accessed via string literal `"cs"`. Same root cause as 9.6 (WiFi member access
    on string literal).
  - **Fix:** Fix identifier lowering for struct variables. In `_lower_assign` for
    `MemberAccess` target, lower to `IRStore` correctly: `cs.value = ...` → 
    `cs.value = ...` in C, not `"cs".value = ...`.
  - **Affected:** `edge_cases.c:385-386`
  - **Test:** `cs.value` → `cs.value` in C (no quotes around struct name)

---

### TIER 3 — Code Quality & Robustness

- [ ] **9.17 — `<math.h>` included unconditionally, often duplicated**
  - `math.iot` prelude line 4: `c header { #include <math.h> }` injected for ALL
    files via the prelude auto-import. `ir_codegen.py:210-211` adds it AGAIN when
    math calls are detected. `led.c`, `math_stress.c`, `full_app.c`, `struct_array.c`
    have it twice. `edge_cases.c` has it THREE times.
  - **Fix:** Remove `c header { #include <math.h> }` from `math.iot` prelude.
    Let codegen add `<math.h>` only when `uses_math` is true. Deduplicate includes.
  - **Affected:** ALL 16 generated .c files
  - **Test:** `simple_blink.iot` → no `<math.h>`. `led.iot` → single `<math.h>`

- [ ] **9.18 — Bogus `extern` declarations with wrong signatures from prelude**
  - Stdlib prelude auto-imports `time.iot`, `math.iot`, `gpio.iot` for every file:
    - `time.iot:4`: `extern fn millis() -> int;` — returns `unsigned long`, not `int`
    - `gpio.iot:7`: `extern fn toggle(int pin);` — `toggle()` does NOT exist in Arduino
  - **Fix:** 
    - `time.iot`: `extern fn millis() -> u32;`
    - `gpio.iot`: Remove `toggle`. Pin toggle is lowered to `digitalWrite(pin, !digitalRead(pin))`
    - Don't emit `extern` for functions already declared by `<Arduino.h>`
  - **Affected:** ALL 16 files
  - **Test:** Generated C has no `extern int millis(void);` or `extern void toggle(int pin);`

- [ ] **9.19 — `after` block: fire-body code unreachable (goto ordering)**
  - `ir_lowering.py:572-639` `_lower_after_block` + `_is_simple_if_else` detection
    causes fire-block code to appear after the goto in the body block, making it
    look unreachable in source (though it's in the binary via label).
  - **Fix:** Expand `_is_simple_if_else` in `ir_codegen.py` to handle the 4-block
    pattern: entry → body → fire → end. Emit properly structured `if/else`.
  - **Affected:** `wifi_ap.c:170-174`, `scheduler_stress.c:217-221`, `full_app.c:618-654`
  - **Test:** `after 5s { LED.high(); }` → fire block code reachable, in correct order

- [ ] **9.20 — `goto` spaghetti instead of structured control flow**
  - `ir_codegen.py:762-770` `_is_simple_if_else`: only matches exact 3-block patterns
    with entry branch. Everything else emits raw goto+labels.
  - **Fix:** Expand structured flow detection for: if/else-if/else, while, for,
    after blocks. Use dominator-tree analysis for general case. Fall back to
    goto only when control flow is irreducible.
  - **Affected:** ALL complex files
  - **Test:** All control flow → structured `if`/`else`/`while`/`for` (no `goto`)

- [ ] **9.21 — `start timer_a;` — Iotift syntax leaks into C**
  - `ir_lowering.py:_lower_stmt` has no handler for `StartStmt` AST node.
    Falls through to string-representation fallback → raw `start timer_a;` in C.
  - **Fix:** Add `StartStmt` handler: set the timer's active flag to 1.
    `IRCopy(_cv(1, 'int'), _gv(active_var, 'int'))`.
  - **Affected:** `scheduler_stress.c:258`
  - **Test:** `start timer_a;` → `_iotift_every_timer_a_active = 1;`

- [ ] **9.22 — While-loop end block creates infinite loop**
  - `ir_lowering.py:871-896` `_lower_while`: end-block emits `IRJump(cond_label)`
    as fallthrough. The end block has no body; the body block already jumps back
    to condition. Result: `goto _iotift_while_condN;` at end-block position
    creates a spin loop.
  - **Fix:** End block should emit `IRReturn()` or nothing (if already terminated).
    The body block already handles the back-edge.
  - **Affected:** `full_app.c:212`, `struct_array.c:111,154`, `edge_cases.c:201,232`
  - **Test:** While loop ends cleanly; no duplicate `goto cond` after the loop

- [ ] **9.23 — `Serial.begin()` called twice in setup**
  - `edge_cases.c:572,582`: `Serial.begin(115200UL);` and `Serial.begin(115200);`
    — one from the Iotift default, one from user code.
  - **Fix:** Deduplicate `Serial.begin` calls. If user code has `Serial.begin`,
    suppress the auto-generated one.
  - **Affected:** `edge_cases.c`
  - **Test:** Only one `Serial.begin()` call in setup

---

### Stdlib / Prelude Fixes

- [ ] **9.24 — Fix `time.iot` prelude: `millis()` return type**
  - `extern fn millis() -> int;` → `extern fn millis() -> u32;`
  - Arduino `millis()` returns `unsigned long` (32-bit on ESP32)

- [ ] **9.25 — Fix `gpio.iot` prelude: remove nonexistent `toggle()`**
  - `extern fn toggle(int pin);` — does not exist in Arduino
  - Pin toggle is an Iotift built-in, lowered to `digitalWrite(pin, !digitalRead(pin))`

- [ ] **9.26 — Fix `math.iot` prelude: remove unconditional `<math.h>` injection**
  - Remove `c header { #include <math.h> }` line
  - Let codegen add `<math.h>` only when `uses_math` is true

---

### Verification

- [ ] **9.27 — Compile check: all 16 examples produce valid C syntax**
  - Build each `.iot` file through the IR pipeline
  - Verify zero C syntax errors (at minimum: `gcc -fsyntax-only` equivalent check)
  - Verify: no Python `True`/`False`, no `"name".method()`, no `__break__`,
    no duplicate function names, no undeclared variables

- [ ] **9.28 — Correctness check: generated C matches intent**
  - `simple_blink.c`: LED toggle via `digitalWrite` + `digitalRead`
  - `temp_monitor.c`: condition before body, analog → INPUT, `False` → `false`
  - `state_machine.c`: `enter_state` has correct if/elif chain, no goto spaghetti
  - `math_stress.c`: float temps have `float` type, `clamp()` returns correctly
  - `wifi_scanner.c`: WiFi events dispatch correctly, no pin ISRs for WiFi
  - `full_app.c`: WiFi init present, arrays have sizes, analog pins INPUT
  - `scheduler_stress.c`: `true` (not `True`), `start` → active flag
  - `edge_cases.c`: `break` resolves, struct access on real vars

- [ ] **9.29 — Regression: all 569 existing tests pass**
  - `python -m pytest tests/ -v`
  - Direct codegen (`--direct-codegen`) still works for all examples
  - No new warnings from semantic analysis

- [ ] **9.30 — Rebuild all 16 example .c files**
  - Run `python iotift.py build examples/<name>.iot` for each
  - Verify output in `examples/<name>.c`
  - Git diff shows improvements, not regressions

---

### Implementation Order

```
Phase A (control flow):  9.8 → 9.9 → 9.13 → 9.22 → 9.19 → 9.20
Phase B (expressions):   9.1 → 9.10 → 9.2 → 9.5
Phase C (declarations):  9.4 → 9.7 → 9.3 → 9.11 → 9.6
Phase D (quality):       9.14 → 9.16 → 9.21 → 9.23
Phase E (prelude):       9.17 → 9.18 → 9.24 → 9.25 → 9.26
Phase F (verify):        9.27 → 9.28 → 9.29 → 9.30
```

Phase A first because control-flow bugs cascade into ~50% of all other issues.

### Files to Modify

| File | Changes |
|------|---------|
| `ir_lowering.py` | Rewrite `_lower_if`, `_lower_elif`; add `StartStmt`; fix `MethodCall` for pins; thread types from semantic analysis; add `WifiDecl` lowering; fix `_lower_on_event` for WiFi targets; fix array sizes; fix break/continue; fix `_lower_on_threshold` naming; fix `_lower_while` end block |
| `ir_codegen.py` | Fix `_value_c` bool handling; expand `_is_simple_if_else` + `_emit_structured_if`; add `IRCallIndirect` to temp collection; fix `_emit_setup` pin directions; add array type emission; deduplicate includes/`Serial.begin` |
| `ir.py` | Add `array_size` to `IRGlobal`; add direction to pin registry; add WiFi fields to `IRModule` |
| `iotift/stdlib/time.iot` | Fix `millis()` return type: `int` → `u32` |
| `iotift/stdlib/gpio.iot` | Remove `extern fn toggle(int pin);` |
| `iotift/stdlib/math.iot` | Remove `c header { #include <math.h> }` |
| `codegen.py` | Reference only — the working "gold standard" to port from |
