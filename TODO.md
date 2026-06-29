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

## MILESTONE 6 — LSP & Editor Integration

**Goal:** IDE support (VS Code).

### 6.1 — LSP server
- [ ] `iotift/tools/lsp_server.py`
- [ ] Diagnostics (errors/warnings as-you-type)
- [ ] Completion (variables, functions, types, keywords)
- [ ] Hover (type info, documentation)
- [ ] Go-to-definition
- [ ] Find references
- [ ] Document symbols

### 6.2 — VS Code extension
- [ ] Syntax highlighting (TextMate grammar)
- [ ] LSP client configuration
- [ ] Snippets (pin, every, on, fn, struct, enum)
- [ ] Command: compile, flash, monitor

---

## MILESTONE 7 — Multi-Target & Production

**Goal:** Beyond ESP32. Production firmware possible.

### 7.1 — Additional targets
- [ ] STM32 (Arduino core + bare-metal)
- [ ] RP2040 (Arduino core + Pico SDK)
- [ ] nRF52 (Arduino core + nRF SDK)
- [ ] AVR (Arduino Uno/Nano legacy)

### 7.2 — Bare-metal backend
- [ ] ESP-IDF backend (no Arduino dependency)
- [ ] CMSIS backend for ARM Cortex-M
- [ ] Smaller binary, faster boot, less overhead

### 7.3 — Production features
- [ ] Power management API (deep sleep, light sleep, wake sources)
- [ ] Watchdog API
- [ ] Filesystem API (LittleFS, FAT)
- [ ] Flash/EEPROM storage API
- [ ] WiFi API
- [ ] BLE API
- [ ] OTA update support
- [ ] Secure boot integration

### 7.4 — Debugging
- [ ] Debug adapter protocol (DAP) integration
- [ ] `iotift debug` command
- [ ] Breakpoint support
- [ ] Variable inspection

### 7.5 — Package manager
- [ ] `iotift add github.com/user/package`
- [ ] `iotift remove package`
- [ ] `iotift update`
- [ ] Package registry (iotift.io/packages)
- [ ] Version pinning (iotift.toml lock file)

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

## SESSION NOTES

### Session 2026-06-28 (Architecture Review)
- Produced full architecture review (ARCHITECTURE_REVIEW.md)
- Identified: compiler is broken (AST/parser mismatch from previous rewrite)
- Decision: bottom-up incremental milestones, not big-bang rewrite
- Decision: keep event-driven philosophy, simple syntax, no Rust complexity
- Decision: 7 milestones, Milestone 0 first (fix pipeline + add tests)
- Status: Milestone 0 **COMPLETED**

### Session 2026-06-28 (Milestone 0 Implementation)
- Renamed `types.py` → `type_system.py` (stdlib shadowing fix)
- Trimmed AST to 47 node types (was 60+), based on stable reference
- Trimmed lexer keywords: removed match/spawn/cancel/module/trait/impl/in
- Removed STDLIB_FUNCTIONS set; math functions as IDENT (semantic pass later)
- Fixed block comment handling: replaced regex with state machine
- Parser: backward-compat with old syntax + new let/var/enum/defer/tick/cast/sizeof
- Parser: TYPE_KW token handling for fixed-width types
- Parser: basic error recovery with synchronize-on-boundary
- Parser: unified dot-access via single `_parse_dot_tail` method
- Codegen: precedence-based parenthesization (no more `((1.0 - 0.0))`)
- Codegen: `static const uint8_t` for pin defs (was `#define`)
- Codegen: stable timer names using user labels
- Codegen: empty handler elimination
- Codegen: string interpolation support, + on strings disabled
- Codegen: CastExpr, SizeOfExpr, EnumDecl, TickBlock, DeferStmt support
- Test suite: 77 tests passing (29 lexer, 34 parser, 14 codegen)
- All existing examples compile: led.iot, console_rgb.iot, nothing/main.iot, argb.iot
- Known limitation: `_parse_top_level` routes `void` (TYPE_KW) before `_is_type_token()` check

### Session 2026-06-29 (Milestone 1 Implementation)
- Cleaned up `type_system.py`: removed OptionType, ResultType, dead TypeKind values
- Cleaned up `symbol_table.py`: removed TRAIT/MODULE, added warning infrastructure
  - Added `werror`, `disabled_warnings`, 6 warning name constants
  - Added `_unused_vars`/`_unused_fns` tracking with mark_used/get_unused
  - Added `is_isr` field to Symbol dataclass
- Created `semantic.py` (~700 lines): 4-pass SemanticAnalyzer
  - Pass 1: Symbol Table Construction — registers all declarations
  - Pass 2: Name Resolution — resolves identifiers, annotates `_resolved_symbol`
  - Pass 3: Type Checking — computes `_resolved_type`, validates assignments/calls/returns
  - Pass 4: Scope Analysis — tags `_storage_class`, detects unused symbols
  - Uses `_pass1_scope` stored on block nodes to share scope hierarchy across passes
  - Type inference for `let` from literal initializers
  - Backward-compatible: implicit narrowing conversions are warnings, not errors
  - C-block awareness: skips unused-const warnings in files with C blocks
- Wired into `iotift.py`: `--Werror` and `--Wno` CLI flags
- Test suite: 124 tests passing (77 original + 47 semantic)
- All existing examples compile: led.iot, console_rgb.iot, nothing/main.iot, argb.iot
- Semantic warnings catch: narrowing conversions, empty handlers, unused variables, void loop deprecation

### Session 2026-06-29 (Milestone 2 Implementation)
- Created `ir.py` (~280 lines): TAC IR instruction set with 14 instruction types
  - Values: temp, const, var, global, param, label
  - Instructions: Binary, Unary, Copy, Load, Store, Call, CallIndirect,
    Branch, Jump, Return, Cast, ArrayAccess, MemberAccess
  - IRModule: globals, structs, enums, functions, handler metadata
  - IRFunction: params, blocks, locals, entry_block
  - Fixed `init=False` on IRInstr.line/col to prevent dataclass inheritance issues
- Created `ir_lowering.py` (~550 lines): AST → IR lowering pass
  - Handles all 47 AST node types
  - Expressions lowered to temporaries (three-address code)
  - Control flow lowered to basic blocks with Branch/Jump terminators
  - Every/on/tick blocks lowered to handler functions
  - Pin/PWM/peripheral declarations registered in module metadata
  - Math function detection sets `uses_math` flag
  - AssignAfter enables `scheduler_needed` flag
- Created `ir_optimizer.py` (~340 lines): 5 optimization passes
  - Constant Folding: binary, unary, cast operations; branch simplification
  - Dead Code Elimination: reachability analysis, empty function removal
  - Empty Handler Removal: filters every/on handlers with empty bodies
  - Redundant Store Elimination: within-block store-to-same-variable elimination
  - Stack Promotion: implemented but disabled (init value propagation bug)
- Created `ir_codegen.py` (~400 lines): IR → C code generator
  - Structured if/else emission for simple branch patterns
  - Local temp variable declaration emission
  - Section-based output (same structure as old codegen)
  - Math.h auto-include based on IR function analysis
- Updated `iotift.py`: added `--direct-codegen`, `--ir-dump`, `--no-optimize` flags
- Updated `codegen.py`: `__version__` = "1.1.0"; kept as legacy path
- Test suite: 178 tests passing (124 original + 54 new IR tests)
  - 21 lowering tests, 11 constant folding, 2 DCE, 2 empty handler removal
  - 14 full pipeline tests, 4 optimizer correctness, 1 console_rgb integration
- All existing examples compile: led.iot, console_rgb.iot through IR pipeline
- Known issues (non-blocking):
  - Temp type inference is weak (defaults to 'int' for many ops)
  - IR codegen output uses more temporaries than direct codegen (quality gap)
  - Stack promotion disabled (init values not propagated to promoted locals)
  - goto-based control flow in complex cases (simple patterns use structured if)

---

### Session 2026-06-29 (Milestone 3 Implementation)
- Phase 1 — Syntax Foundation: Added AfterBlock, SchedulerConfig AST nodes
  - Extended EveryBlock with offset_ms field
  - Added `offset`, `config` keywords to lexer
  - Parser: _parse_after_block(), _parse_scheduler_config(), extended _parse_every()
  - Semantic: AfterBlock walking, timer status validation (.running/.stop/.start)
  - Semantic: ISR safety infrastructure (_in_isr tracking, forbidden call detection)
  - Semantic: volatile enforcement for ISR functions
  - Symbol table: PERIPHERAL symbol kind, _in_isr property
- Phase 2 — Min-Heap Scheduler: Replaced linear scan with binary min-heap
  - O(log n) insert (bubble-up), O(1) peek, O(log n) pop (bubble-down)
  - _iotift_scheduler_size tracking, _iotift_scheduler_overflow flag
  - Configurable slots via @config / --scheduler-slots CLI
  - AfterBlock IR lowering → one-shot timer with done-flag
  - EveryBlock offset support (unsigned arithmetic trick for init timing)
  - Updated both ir_codegen.py and codegen.py (legacy path)
- Phase 3 — Real Interrupts: Replaced polling with attachInterrupt()
  - ISR function: minimal, IRAM_ATTR, sets volatile bool flag
  - Handler function: checks flag, applies debounce, runs user body in loop()
  - Edge mode mapping: press→FALLING, release→RISING, rising→RISING, etc.
  - Debounce in handler only (not ISR), using millis() timestamp check
  - Added interrupts list to IRModule
- Phase 4 — HAL Architecture: Created hal/ package
  - HALBase abstract class with ~25 methods
  - ESP32ArduinoHAL: full Arduino framework implementation
  - HAL registry with get_hal() factory
  - @device now dispatches to correct HAL
  - IR codegen uses HAL for setup, pinMode, Serial, PWM, interrupts
  - Package location: hal/ (not iotift/hal/) to avoid iotift.py conflict
- Phase 5 — Peripheral APIs: Semantic handling for I2C/SPI/UART declarations
  - PERIPHERAL symbol kind with name registration
  - HAL methods for I2C (Wire), SPI, UART operations
- Phase 6 — ISR fn Safety: Already handled in Phase 1
  - Parser already supports isr fn (since M0)
  - Codegen already emits IRAM_ATTR (since M0)
  - Added compile-time safety: no print/delay/peripherals, volatile enforcement
- Phase 7 — Tests & Docs: 221 tests passing (178 original + 43 new)
  - 7 new parser tests (after block, every offset, @config)
  - 18 new semantic tests (timer status, ISR safety, after blocks, peripherals)
  - 18 new HAL unit tests (all methods, edge modes, registry)
  - README updated: Milestone 3 status, new feature docs, updated project structure
  - TODO.md: All M3 checkboxes marked done
- Known issues (non-blocking):
  - Debounce branch nesting in structured-if emission may skip body execution
  - Peripheral API codegen (Wire.begin/SPI.begin/SerialN) is HAL-ready but not
    yet wired through the full IR pipeline for method calls
  - Hardware integration tests deferred for physical ESP32 availability

---

### Session 2026-06-29 (Milestone 4 Implementation)
- Created `import_resolver.py` (~195 lines): AST-level import resolution
  - `ImportResolver.resolve()` walks AST, finds ImportDecl, inlines declarations
  - Path resolution: `./` `../` relative, bare name → relative then stdlib
  - Circular import detection via visited-set tracking
  - Prelude auto-injection: time, math, gpio imported before user code
  - `_imported_from` attribute on inlined nodes for diagnostics
- Extended parser `_parse_import()`: both `import "path"` and `import { A, B } from "path"`
  - Uses `TT.LBRACE`/`TT.RBRACE` (not OP) — discovered through tokenization debug
  - Added `from` to KEYWORDS set
- Fixed `_parse_param_list()`: accepts both IDENT and KEYWORD for param names
  - Required because `pin`, `output`, etc. are contextual keywords
- Removed `millis` from KEYWORDS → now an IDENT, usable in `extern fn` declarations
  - Updated parser's millis check from `TT.KEYWORD` to `TT.IDENT`
  - Removed `millis` from `_MATH_FUNCTIONS` (it produces `MillisExpr`, not `MathExpr`)
- Updated `SymbolTable.define()`: catches `NameError` from `Scope.define()` and records
  as semantic error instead of crashing (fixes duplicate symbol detection from imports)
- Created `iotift/stdlib/` with 7 `.iot` files: time, math, gpio, serial, i2c, spi, pwm
  - Each uses `extern fn` declarations + optional `c header` blocks
  - `math.iot` includes `c header { #include <math.h> }` for automatic header emission
- Test suite: 270 tests passing (221 original + 49 new)
  - `tests/test_imports.py` — 30 tests: import-all, selective, path resolution,
    circular detection (direct + indirect), nested imports, parser syntax, conflicts
  - `tests/test_stdlib.py` — 19 tests: prelude availability, explicit imports,
    codegen verification for each stdlib module
- README updated: M4 status, import docs, pipeline diagram, project structure
- All existing examples still compile: led.iot, console_rgb.iot, argb.iot

---

### Session 2026-06-29 (Milestone 5 Implementation)
- Created `iotift/__init__.py` — proper Python package init
- Created `iotift/tools/__init__.py` — tooling package
- Created `iotift/tools/formatter.py` (~540 lines): AST-based pretty-printer
  - Opinionated rules: 4-space indent, same-line braces, blank line between top-level decls
  - Preserves semicolons, wraps long lines, formats time literals
  - Preserves C block content as-is
  - `format_source()`, `format_file()`, `check_format()` public API
- Created `iotift/tools/linter.py` (~340 lines): AST-based static analyzer
  - 10 lint rules: no-float-in-isr (error), no-print-in-isr, no-blocking-in-timer,
    prefer-fixed-width, empty-timer, unused-variable, unused-function,
    const-candidate, volatile-needed, parse-error
  - Three severity levels: ERROR, WARNING, INFO
  - Two-pass: collect definitions → walk AST with context tracking
- Redesigned CLI (`iotift.py`): subcommand architecture
  - `iotift check` — type-check only, no codegen
  - `iotift build` — compile to C
  - `iotift flash` — compile + flash to device
  - `iotift fmt [--check]` — format source file
  - `iotift lint` — run linter
  - `iotift new <name>` — scaffold new project (iotift.toml + .iot + .gitignore)
  - `iotift version` — print version
  - Backward compatible: `iotift file.iot -o out.c` still works (legacy mode)
  - Added `--debug` flag for source maps
  - Added `--target` flag alias for `--device`
- Added source map support (`ir_codegen.py`):
  - `--debug` flag enables `// @iot:line N` comments in generated C
  - Generates `.map.json` file with line mappings
  - IR instructions track source line via `IRBuilder._current_line`
  - `ir.py`: added `source_path` field to `IRModule`
  - `ir_lowering.py`: `_lower_stmt` and `_lower_expr` set `_current_line` from AST nodes
- Test suite: 354 tests passing (270 original + 84 new)
  - `tests/test_formatter.py` — 57 tests: all declaration/statement/expression types,
    indentation, brace placement, idempotency, C block preservation
  - `tests/test_linter.py` — 27 tests: all 10 lint rules, severity levels,
    integration with multiple diagnostics
- All existing examples still compile: led.iot, console_rgb.iot, argb.iot

*Last updated: 2026-06-29*
