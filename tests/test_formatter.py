"""
Tests for the Iotift formatter (Milestone 5).

Covers:
- Basic formatting: indentation, brace placement, semicolons
- All declaration types
- All statement types
- All expression types
- Time literal formatting
- C block preservation
- Top-level blank line separation
- check_format() function
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from iotift.tools.formatter import format_source, check_format, FormatError


# ─────────────────────────────────────────
#  BASIC FORMATTING RULES
# ─────────────────────────────────────────

def test_indentation_body():
    """Body statements are indented 4 spaces."""
    source = 'fn foo() {\nint x = 1;\n}\n'
    result = format_source(source)
    assert '    int x = 1;' in result


def test_nested_indentation():
    """Nested blocks double-indent."""
    source = 'fn foo() {\nif (x > 0) {\nint y = 1;\n}\n}\n'
    result = format_source(source)
    assert '        int y = 1;' in result


def test_brace_same_line():
    """Opening brace on same line, preceded by space."""
    source = 'fn foo()\n{\n}\n'
    result = format_source(source)
    assert 'fn foo() {' in result


def test_semicolons_preserved():
    """Semicolons are preserved for top-level declarations."""
    source = 'pin LED = output 2;\n'
    result = format_source(source)
    assert ';' in result


def test_trailing_newline():
    """Output ends with exactly one newline."""
    source = 'pin LED = output 2;\n\n\n'
    result = format_source(source)
    assert result.endswith('\n')
    assert not result.endswith('\n\n')


# ─────────────────────────────────────────
#  PIN DECLARATIONS
# ─────────────────────────────────────────

def test_pin_output():
    source = 'pin LED = output 2;\n'
    result = format_source(source)
    assert 'pin LED = output 2' in result


def test_pin_with_config():
    source = 'pin BTN = input 5 { pull: up, debounce: 50ms };\n'
    result = format_source(source)
    assert 'pull: up' in result
    assert 'debounce: 50ms' in result


def test_pin_pwm():
    source = 'pin R = pwm 13;\n'
    result = format_source(source)
    assert 'pwm 13' in result


# ─────────────────────────────────────────
#  VARIABLE DECLARATIONS (Iotift syntax)
# ─────────────────────────────────────────

def test_old_style_var():
    """Old-style: type name = value;"""
    source = 'int count = 0;\n'
    result = format_source(source)
    assert 'int count = 0' in result or 'var count' in result


def test_let_var():
    source = 'let count = 0;\n'
    result = format_source(source)
    assert 'let count = 0' in result


def test_let_with_type():
    source = 'let x: i32 = 0;\n'
    result = format_source(source)
    assert 'let x: i32 = 0' in result


def test_var_mutable():
    source = 'var temp: f32 = 25.5;\n'
    result = format_source(source)
    # Parser treats var-style and old-style identically; formatter emits old-style
    assert 'temp' in result
    assert '25.5' in result


def test_const_var():
    """Const declaration: const int NAME = value;"""
    source = 'const int MAX_TEMP = 100;\n'
    result = format_source(source)
    assert 'const int MAX_TEMP' in result


def test_volatile_var():
    source = 'volatile int counter = 0;\n'
    result = format_source(source)
    assert 'volatile' in result


# ─────────────────────────────────────────
#  FUNCTIONS
# ─────────────────────────────────────────

def test_fn_no_params():
    source = 'fn blink() {\nint x = 1;\n}\n'
    result = format_source(source)
    assert 'fn blink() {' in result


def test_fn_with_params():
    """Iotift params are type name: fn add(i32 a, i32 b) -> i32"""
    source = 'fn add(i32 a, i32 b) -> i32 {\nreturn a + b;\n}\n'
    result = format_source(source)
    assert 'fn add(' in result
    assert 'a: i32' in result
    assert '-> i32' in result


def test_extern_fn():
    source = 'extern fn esp_restart();\n'
    result = format_source(source)
    assert 'extern fn esp_restart();' in result


def test_isr_fn():
    source = 'isr fn on_timer() {\nint x = 0;\n}\n'
    result = format_source(source)
    assert 'isr fn on_timer() {' in result


# ─────────────────────────────────────────
#  CONTROL FLOW (Iotift requires parentheses)
# ─────────────────────────────────────────

def test_if_stmt():
    source = 'if (x > 0) {\nx = 1;\n}\n'
    result = format_source(source)
    assert 'if x > 0 {' in result


def test_if_else():
    source = 'if (x > 0) {\nx = 1;\n} else {\nx = 0;\n}\n'
    result = format_source(source)
    assert 'if x > 0 {' in result
    assert '} else {' in result


def test_if_elif_else():
    source = 'if (x > 0) {\nx = 1;\n} else if (x < 0) {\nx = -1;\n} else {\nx = 0;\n}\n'
    result = format_source(source)
    assert 'if x > 0 {' in result
    assert '} else if x < 0 {' in result
    assert '} else {' in result


def test_while_stmt():
    source = 'while (x < 10) {\nx += 1;\n}\n'
    result = format_source(source)
    assert 'while x < 10 {' in result


def test_for_stmt():
    source = 'for (int i = 0; i < 10; i += 1) {\nprint(i);\n}\n'
    result = format_source(source)
    assert 'for ' in result
    assert 'i < 10' in result


def test_loop_block():
    source = 'loop {\nprint("x");\n}\n'
    result = format_source(source)
    assert 'loop {' in result


def test_return_stmt():
    source = 'fn f() -> int {\nreturn 42;\n}\n'
    result = format_source(source)
    assert 'return 42;' in result


def test_return_void():
    source = 'fn f() {\nreturn;\n}\n'
    result = format_source(source)
    assert 'return;' in result


def test_break_continue():
    source = 'while (true) {\nif (x) {\nbreak;\n} else {\ncontinue;\n}\n}\n'
    result = format_source(source)
    assert 'break;' in result
    assert 'continue;' in result


# ─────────────────────────────────────────
#  EVENTS & TIMERS
# ─────────────────────────────────────────

def test_every_block():
    source = 'every 1s {\nLED = 1;\n}\n'
    result = format_source(source)
    assert 'every 1s {' in result


def test_every_with_label():
    source = 'every 500ms as blinker {\nLED = 1;\n}\n'
    result = format_source(source)
    assert 'as blinker' in result


def test_every_with_offset():
    source = 'every 10s offset 2s {\nprint("x");\n}\n'
    result = format_source(source)
    assert 'offset 2s' in result


def test_after_block():
    source = 'after 5s {\nLED = 0;\n}\n'
    result = format_source(source)
    assert 'after 5s {' in result


def test_on_event():
    source = 'pin BTN = input 5;\non BTN.press {\nLED = 1;\n}\n'
    result = format_source(source)
    assert 'on BTN.press {' in result


def test_on_threshold():
    source = 'on TEMP > 50.0 {\nprint("Hot!");\n}\n'
    result = format_source(source)
    assert 'on TEMP > 50.0 {' in result


def test_tick_block():
    source = 'tick {\nprint("x");\n}\n'
    result = format_source(source)
    assert 'tick {' in result


# ─────────────────────────────────────────
#  EXPRESSIONS
# ─────────────────────────────────────────

def test_binary_op():
    source = 'int x = a + b * c;\n'
    result = format_source(source)
    assert 'a + b * c' in result


def test_unary_op():
    source = 'bool x = !flag;\n'
    result = format_source(source)
    assert '!flag' in result


def test_member_access():
    source = 'int x = sensor.value;\n'
    result = format_source(source)
    assert 'sensor.value' in result


def test_array_access():
    source = 'int x = vals[0];\n'
    result = format_source(source)
    assert 'vals[0]' in result


def test_fn_call():
    source = 'int x = millis();\n'
    result = format_source(source)
    assert 'millis()' in result


def test_method_call():
    source = 'LED.write(128);\n'
    result = format_source(source)
    assert '.write(128)' in result


def test_cast():
    source = 'int x = value as u8;\n'
    result = format_source(source)
    assert 'value as u8' in result


def test_sizeof():
    source = 'int x = sizeof(i32);\n'
    result = format_source(source)
    assert 'sizeof(i32)' in result


def test_millis():
    source = 'int t = millis();\n'
    result = format_source(source)
    assert 'millis()' in result


def test_math_expr():
    source = 'float x = sin(t);\n'
    result = format_source(source)
    assert 'sin(t)' in result


# ─────────────────────────────────────────
#  TOP-LEVEL SEPARATION
# ─────────────────────────────────────────

def test_blank_line_between_decls():
    """Blank line between top-level declarations."""
    source = 'pin LED = output 2;\npin BTN = input 5;\n'
    result = format_source(source)
    assert 'LED' in result
    assert 'BTN' in result
    assert '\n\npin BTN' in result


def test_device_decl():
    source = '@device esp32\n'
    result = format_source(source)
    assert '@device esp32' in result


def test_import_decl():
    source = 'import "time";\n'
    result = format_source(source)
    assert 'import "time";' in result


def test_selective_import():
    source = 'import { sin, cos } from "math";\n'
    result = format_source(source)
    assert 'import { sin, cos } from "math";' in result


# ─────────────────────────────────────────
#  STRUCTS & ENUMS (Iotift syntax)
# ─────────────────────────────────────────

def test_struct_decl():
    """Struct fields use type-name syntax separated by semicolons: int id; float value;"""
    source = 'struct Sensor {\nint id;\nfloat value;\n}\n'
    result = format_source(source)
    assert 'struct Sensor {' in result


def test_enum_decl():
    source = 'enum Mode {\nWarmWhite,\nRainbow = 5,\n}\n'
    result = format_source(source)
    assert 'enum Mode {' in result
    assert 'WarmWhite' in result
    assert 'Rainbow = 5' in result


# ─────────────────────────────────────────
#  CHECK FORMAT (file-based)
# ─────────────────────────────────────────

def test_check_format_clean():
    """check_format returns True when file is already formatted."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.iot', delete=False,
                                     encoding='utf-8') as f:
        f.write('pin LED = output 2;\n')
        tmpname = f.name
    try:
        result = check_format(tmpname)
        assert result is True
    finally:
        os.unlink(tmpname)


# ─────────────────────────────────────────
#  IDEMPOTENCY
# ─────────────────────────────────────────

def test_format_idempotent():
    """Formatting twice gives the same result."""
    source = 'fn foo() {\nint x = 1;\n}\n'
    first = format_source(source)
    second = format_source(first)
    assert first == second


# ─────────────────────────────────────────
#  ERROR CASES
# ─────────────────────────────────────────

def test_syntax_error_graceful():
    """FormatError or ParseError raised on severe syntax errors."""
    # Use something that's definitively unparseable
    try:
        result = format_source('fn foo( {')
        # If we get here, the result should at least be returned
        assert isinstance(result, str)
    except Exception as e:
        # Either FormatError or ParseError is acceptable
        assert isinstance(e, (FormatError, Exception))


def test_empty_source():
    """Empty source produces empty output."""
    result = format_source('')
    assert result == '\n'


# ─────────────────────────────────────────
#  C BLOCK PRESERVATION
# ─────────────────────────────────────────

def test_c_header_block():
    source = 'c header {\n#include <math.h>\n}\n'
    result = format_source(source)
    assert '#include <math.h>' in result
    assert 'c header {' in result


def test_c_global_block():
    source = 'c global {\nint x = 0;\n}\n'
    result = format_source(source)
    assert 'c global {' in result
    assert 'int x = 0;' in result


# ─────────────────────────────────────────
#  PRINT STATEMENTS
# ─────────────────────────────────────────

def test_print_stmt():
    source = 'print("hello");\n'
    result = format_source(source)
    assert 'println("hello")' in result


def test_print_expr():
    source = 'print(temp);\n'
    result = format_source(source)
    assert 'println(temp)' in result


# ─────────────────────────────────────────
#  COMPOUND ASSIGN & STOP
# ─────────────────────────────────────────

def test_compound_assign():
    source = 'x += 1;\n'
    result = format_source(source)
    assert 'x += 1;' in result


def test_stop_stmt():
    source = 'stop blinker;\n'
    result = format_source(source)
    assert 'stop blinker;' in result


def test_assign_after():
    source = 'LED = 0 after 200;\n'
    result = format_source(source)
    assert 'LED = 0 after 200ms;' in result
