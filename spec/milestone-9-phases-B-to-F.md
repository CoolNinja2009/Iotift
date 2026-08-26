# Milestone 8.5 — Remaining Phases: B, C, D, E, F

**Context:** Phase A (control flow: bugs 9.8, 9.9, 9.13, 9.19, 9.20, 9.22) is already fixed.
`ir_codegen.py` now has `_emit_cfg_region` with `no_inline_targets`/`jump_targets` params,
`_emit_cfg_else_chain` for elif chains, proper C label emission, and back-edge handling.

---

## Phase B — Expressions (9.1 → 9.10 → 9.2 → 9.5)

### Bug 9.1 — Pin method calls emit invalid C

**Problem:** `ir_lowering.py` lowers `MethodCall` for pins to
`IRCallIndirect(func_expr=f'{obj}.{method}()')`. Pins are `uint8_t` constants
(`LED_PIN = 2U`), not objects with methods. This emits `LED_PIN.toggle()` in C,
which is invalid.

**Fix:**
In `ir_lowering.py`, `_lower_expr` for `MethodCall` (around line 1147):
- Check if `node.obj` is a pin name (look up in `self._pins` or `symbol_table`)
- If so, emit the appropriate HAL call:
  - `.high()` → `digitalWrite(LED_PIN, HIGH)`
  - `.low()` → `digitalWrite(LED_PIN, LOW)`
  - `.toggle()` → `digitalWrite(LED_PIN, !digitalRead(LED_PIN))`
  - `.read()` → `digitalRead(LED_PIN)` or `analogRead(LED_PIN)` for analog pins
  - `.write(val)` → `analogWrite(LED_PIN, val)` or `ledcWrite(ch, val)` for PWM
- Pin method calls are side-effecting statements (not expressions that return temps)
- Port the logic from `codegen.py:_pin_method_c` (lines 920-970)

**Test:** `LED.toggle()` → `digitalWrite(LED_PIN, !digitalRead(LED_PIN));`

---

### Bug 9.10 — Type propagation broken: ALL temp variables typed as `int`

**Problem:** Three places in `ir_lowering.py` default all temps to `int`:
1. Line ~1057: `_vv(node.name, 'int')` — Identifier always `'int'`
2. Line ~1192: `ctype = left.ctype if left.ctype else 'int'` — only checks left op
3. Line ~1137: `self.builder.new_temp('call', 'int')` — calls always `'int'`

**Fix:**
Thread `_resolved_type` from semantic analysis through IR lowering:
- Use `getattr(node, '_resolved_type', None)` on the AST node
- Map Iotift types to C types: `float`→`float`, `int`→`int`, `u32`→`uint32_t`, `bool`→`bool`, etc.
- In `_vv()` for identifiers: look up resolved type from symbol table or AST annotation
- In binary ops: determine result type from operand types (float op → float result)
- In `new_temp('call', ...)`: use the function's return type from symbol table

**Test:** `float x = 3.14; float y = x * 2.0;` → `float _iotift_binopN` NOT `int`

---

### Bug 9.2 — `bool` literals emit Python `True`/`False`

**Problem:** `ir_codegen.py:_value_c` (line ~700) checks `isinstance(val, (int, float))` 
before `isinstance(val, bool)`. Python's `bool` is a subclass of `int`, so `True`/`False`
get formatted as `"True"`/`"False"` in C output.

**Fix:**
In `_value_c()`, check `isinstance(val, bool)` FIRST, before checking `isinstance(val, (int, float))`:
```python
if isinstance(val, bool):
    return 'true' if val else 'false'
elif isinstance(val, (int, float)):
    ...
```

**Test:** `bool cooling = false;` → `static bool cooling = false;`

---

### Bug 9.5 — `IRCallIndirect` dest temps not declared

**Problem:** `ir_codegen.py` temp collection loop (line ~456) enumerates `IRBinary, IRUnary,
IRCall, IRCast, IRArrayAccess, IRMemberAccess, IRCopy` — but NOT `IRCallIndirect`.
All method-call result temps are used without declaration → C compilation error.

**Fix:**
Add `IRCallIndirect` to the `isinstance` check in the temp collection loop:
```python
if isinstance(instr, (IRBinary, IRUnary, IRCall, IRCast, IRArrayAccess,
                       IRMemberAccess, IRCopy, IRCallIndirect)):
```

**Test:** Every temp variable used in a function appears in its declarations block

---

## Phase C — Declarations (9.4 → 9.7 → 9.3 → 9.11 → 9.6)

### Bug 9.4 — Array declarations lose their size

**Problem:** `ir_lowering.py:146-151`: `ArrayDecl` → `IRGlobal(ctype=to_ctype(node.vtype))`
only stores element type (`"float"`), not array type (`"float[10]"`). `IRGlobal` has no
`array_size` field.

**Fix:**
1. In `ir.py`: Add `array_size: int = 0` to `IRGlobal`
2. In `ir_lowering.py`: When lowering `ArrayDecl`, pass the array size
   (extract from `node.size` or `node.vtype` which may be `ArrayType`)
3. In `ir_codegen.py`: When emitting `IRGlobal`, if `array_size > 0`, emit as
   `ctype name[size];` instead of `ctype name;`
4. In `ArrayAccess` lowering: verify base is an array, emit `base[index]`

**Test:** `float[10] readings;` → `static float readings[10];`

---

### Bug 9.7 — WiFi declarations silently dropped in IR pipeline

**Problem:** `ir_lowering.py:_lower_top_level` (lines 129-250) has no handler for
`WifiDecl` AST nodes. They're silently skipped — no state variables, no `WiFi.begin()`,
no event dispatch, no accessor functions. WiFi programs produce completely broken C.

**Fix:**
Add `isinstance(node, WifiDecl)` handler in `_lower_top_level`. Port the full logic from
`codegen.py:_collect_wifi_decl` and `_emit_wifi_*` methods. This needs to generate:
1. WiFi state variables (SSID, password, connection state, retry counters)
2. System init function (`nvs_flash_init`, `WiFi.begin()`, event handler registration)
3. Event dispatch functions (connect, disconnect, got_ip, scan_done, etc.)
4. Scan accessor functions (list access, count, RSSI, encryption type)
5. Property accessor mapping (`.connected`, `.ip`, `.rssi`, etc.)

This is the most complex fix — see `codegen.py` for the reference implementation.

**Test:** `wifi home = sta { ssid: "x"; password: "y"; }` → generates all WiFi boilerplate

---

### Bug 9.3 — WiFi events lowered as pin ISRs with `attachInterrupt`

**Problem:** `ir_lowering.py:_lower_on_event` (lines 341-437) unconditionally creates
ISR + volatile flag + debounce + `attachInterrupt` for ALL `on` events. WiFi events
(e.g., `on scanner.scan_done`) are not pin-based — no `scanner_PIN` exists → link failure.

**Fix:**
In `_lower_on_event`, check if `node.target` is a WiFi interface name:
- Look up in `self._wifi_decls` or symbol table to determine if target is WiFi
- If WiFi: skip ISR creation. Instead, the event dispatches from the WiFi event loop
  (lower to a flag + handler function called from the WiFi event callback)
- If pin: keep existing ISR logic

**Test:** `on scanner.scan_done` → no `attachInterrupt` for `scanner_PIN`

---

### Bug 9.11 — Pin direction not propagated → wrong pinMode

**Problem:** `ir.py:319`: `pins: Dict[str, int]` stores only pin number. Direction info
is lost. `ir_codegen.py:508-515`: hardcodes `_PIN_DIRECTION.get('output', 'OUTPUT')`
— ignores the pin's actual declared direction.

**Fix:**
1. In `ir.py`: Change pin storage to `Dict[str, dict]` or similar:
   `{'number': int, 'direction': 'analag'|'input'|'output'|'pwm'}`
2. In `ir_lowering.py`: Preserve pin direction when lowering `PinDecl`
3. In `ir_codegen.py:_emit_setup`: Use the stored direction:
   - `analog` → `pinMode(PIN, INPUT)` (analog pins don't need analog-specific pinMode)
   - `input` → `pinMode(PIN, INPUT_PULLUP)` if pull-up, else `INPUT`
   - `output` → `pinMode(PIN, OUTPUT)`
   - `pwm` → `ledcSetup(ch, freq, res); ledcAttachPin(PIN, ch)`

**Test:** `pin TEMP = analog 34;` → `pinMode(TEMP_PIN, INPUT);`

---

### Bug 9.6 — Duplicate function definitions (colliding names)

**Problem:** `ir_lowering.py:_lower_on_threshold` (lines 438-483): function name uses
only pin name: `f'_iotift_threshold_{node.pin}'`. Two thresholds on same pin
(e.g., `on TEMP > 30` and `on TEMP < 15`) → identical function names → C compilation error.

**Fix:**
Include operator + value hash in the function name:
```python
val_str = str(hash(str(node.value))) if node.value else '0'
fn_name = f"_iotift_threshold_{node.pin}_{node.op}_{val_str}"
```

**Test:** Two `on TEMP > X` and `on TEMP < Y` → two distinct function names

---

## Phase D — Quality (9.14 → 9.16 → 9.21 → 9.23)

### Bug 9.14 — String interpolation silently fails for non-`\w+` patterns

**Problem:** `ir_lowering.py:989`: regex `r'\{(\w+)\}'` only matches `[a-zA-Z0-9_]+`.
Fails for: `{millis()}`, `{wifi.ip}`, `{n + n}`, `{sin(f)}`, `{n * 2 + 1}`.

**Fix:**
1. Change regex to `r'\{([^{}]+)\}'` to match any expression between braces
2. For simple identifiers (`^\w+$`): emit `Serial.print(var)`
3. For member access (`^\w+\.\w+$`): emit `Serial.print(var_member)` (resolve)
4. For complex expressions: evaluate to temp first, then `Serial.print(temp)`
5. Reject truly unsupported patterns at semantic check time with clear error

**Test:** `println("IP: {wifi.ip}");` → `Serial.print("IP: "); Serial.println(wifi_ip);`

---

### Bug 9.16 — Struct field access emits member access on string literal

**Problem:** `edge_cases.c:385-386`: `_iotift_member63 = "cs".value;` — struct variable
`cs` is accessed via string literal `"cs"`. The identifier lowering for struct variables
is broken.

**Fix:**
1. In `_lower_assign` for `MemberAccess` target: lower correctly as
   `IRStore(target=IRVar('cs.value', '...'), ...)` without quotes around struct name
2. In `_lower_expr` for `MemberAccess`: use the variable name directly, not
   as a string literal. The issue is likely in how identifiers are resolved —
   if the variable name is stored as a raw string, it gets treated as a string literal
3. Ensure `_vv()` returns the correct name for struct variables

**Test:** `cs.value` → `cs.value` in C (no quotes around struct name)

---

### Bug 9.21 — `start timer_a;` — Iotift syntax leaks into C

**Problem:** `ir_lowering.py:_lower_stmt` has no handler for `StartStmt` AST node.
Falls through to string-representation fallback → raw `start timer_a;` in C output.

**Fix:**
Add `StartStmt` handler in `_lower_stmt`:
```python
if isinstance(node, StartStmt):
    active_var = self._every_labels.get(node.label)
    if active_var:
        return [IRCopy(dest=_gv(active_var, 'int'), src=_cv(1, 'int'))]
    return []
```
(Note: `StopStmt` may already be handled — check and fix similarly if not.)

**Test:** `start timer_a;` → `_iotift_every_timer_a_active = 1;`

---

### Bug 9.23 — `Serial.begin()` called twice in setup

**Problem:** `edge_cases.c:572,582`: `Serial.begin(115200UL);` and `Serial.begin(115200);`
— one from the Iotift default, one from user code.

**Fix:**
1. In `ir_codegen.py:_emit_setup`: track whether `Serial.begin` has been emitted
2. Check if any user code already contains `Serial.begin(...)` call
3. If user code has it, suppress the auto-generated one
4. Use a set of emitted function calls to deduplicate

**Test:** Only one `Serial.begin()` call in setup

---

## Phase E — Prelude (9.17 → 9.18 → 9.24 → 9.25 → 9.26)

### Bug 9.17 — `<math.h>` included unconditionally, often duplicated

**Problem:** `math.iot` prelude line 4: `c header { #include <math.h> }` injected for ALL
files via the prelude auto-import. `ir_codegen.py:210-211` adds it AGAIN when
math calls are detected. Result: 2-3 copies of `<math.h>` in generated C.

**Fix:**
1. Remove `c header { #include <math.h> }` from `iotift/stdlib/math.iot` prelude
2. Let codegen add `<math.h>` only when `uses_math` is true (single deduplicated include)
3. Use a `set` for includes in `ir_codegen.py` to prevent duplicates

**Test:** `simple_blink.iot` → no `<math.h>`. `led.iot` → single `<math.h>`

---

### Bug 9.18 — Bogus `extern` declarations with wrong signatures

**Problem:** Stdlib prelude auto-imports `time.iot`, `math.iot`, `gpio.iot` for every file:
- `time.iot:4`: `extern fn millis() -> int;` — returns `unsigned long`, not `int`
- `gpio.iot:7`: `extern fn toggle(int pin);` — `toggle()` does NOT exist in Arduino

These bogus `extern` declarations pollute the generated C and may conflict with
`<Arduino.h>` which already declares these functions.

**Fix:**
1. `time.iot`: Change `extern fn millis() -> int;` → `extern fn millis() -> u32;`
2. `gpio.iot`: Remove `extern fn toggle(int pin);` entirely
   (Pin toggle is lowered to `digitalWrite(pin, !digitalRead(pin))` by codegen)
3. Don't emit `extern` for functions already declared by `<Arduino.h>`

**Test:** Generated C has no `extern int millis(void);` or `extern void toggle(int pin);`

---

### Bug 9.24 — Fix `time.iot` prelude: `millis()` return type

**Fix:**
In `iotift/stdlib/time.iot`:
```diff
- extern fn millis() -> int;
+ extern fn millis() -> u32;
```
Arduino `millis()` returns `unsigned long` (32-bit on ESP32).

---

### Bug 9.25 — Fix `gpio.iot` prelude: remove nonexistent `toggle()`

**Fix:**
In `iotift/stdlib/gpio.iot`, remove the line:
```
extern fn toggle(int pin);
```
Pin toggle is an Iotift built-in, lowered by the codegen to
`digitalWrite(pin, !digitalRead(pin))` — there's no Arduino `toggle()` function.

---

### Bug 9.26 — Fix `math.iot` prelude: remove unconditional `<math.h>` injection

**Fix:**
In `iotift/stdlib/math.iot`, remove the line:
```
c header { #include <math.h> }
```
Let `ir_codegen.py` add `<math.h>` only when `uses_math` is detected (math function calls).

---

## Phase F — Verification (9.27 → 9.28 → 9.29 → 9.30)

### Bug 9.27 — Compile check: all 16 examples produce valid C syntax

**Prompt:**
Build each of the 16 example `.iot` files through the IR pipeline and verify:
- Zero C syntax errors (run `gcc -fsyntax-only` equivalent or just eyeball the C)
- No Python `True`/`False` in output
- No `"name".method()` pattern (string-quoted method calls)
- No `__break__` or `__continue__` placeholders
- No duplicate function names
- No undeclared variables
- All arrays have proper sizes
- All control flow is structured if/else/while/for, no raw `goto`+label spaghetti

---

### Bug 9.28 — Correctness check: generated C matches intent

**Prompt:**
Manually inspect the generated C for each example to verify functional correctness:
- `simple_blink.c`: LED toggle via `digitalWrite` + `digitalRead`
- `temp_monitor.c`: condition before body, analog → INPUT, `False` → `false`
- `state_machine.c`: `enter_state` has correct if/elif chain, no goto spaghetti
- `math_stress.c`: float temps have `float` type, `clamp()` returns correctly
- `wifi_scanner.c`: WiFi events dispatch correctly, no pin ISRs for WiFi
- `full_app.c`: WiFi init present, arrays have sizes, analog pins INPUT
- `scheduler_stress.c`: `true` (not `True`), `start` → active flag
- `edge_cases.c`: `break` resolves, struct access on real vars, no duplicate includes

---

### Bug 9.29 — Regression: all 569 existing tests pass

**Prompt:**
Run the full test suite and verify:
```
python -m pytest tests/ -v
```
- All 569+ tests pass
- Direct codegen (`--direct-codegen`) still works for all examples
- No new warnings from semantic analysis
- Zero regressions

---

### Bug 9.30 — Rebuild all 16 example .c files

**Prompt:**
Regenerate all example C files through the IR pipeline:
```
python iotift.py build examples/<name>.iot -o examples/<name>.c
```
For each of the 16 `.iot` files in `examples/`. Verify:
- Output exists and is non-empty
- Git diff shows improvements, not regressions
- Output compiles (no syntax errors)
- Output is functionally correct (behavior matches the `.iot` source intent)
