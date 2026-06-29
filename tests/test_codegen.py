"""
Codegen tests - snapshot tests for .iot -> .c compilation.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from lexer import tokenize
from parser import Parser
from codegen import CodeGen, CodeGenError


def compile_iot(source: str) -> str:
    """Compile Iotift source to C code."""
    tokens = tokenize(source)
    ast = Parser(tokens).parse()
    gen = CodeGen()
    return gen.generate(ast)


def test_blink_basic():
    """A basic blink program should generate working C."""
    c = compile_iot("""
@device esp32
pin LED = output 2;
every 1000 { LED = !LED; }
""")
    assert '#include <Arduino.h>' in c
    assert 'LED_PIN' in c
    assert 'ledc' not in c  # not a PWM pin
    assert 'void loop' in c
    assert 'yield()' in c


def test_rgb_pwm():
    """PWM pins should generate LEDC setup."""
    c = compile_iot("""
@device esp32
pin R = pwm 13;
R.setup(1000, 10);
every 10 { R.write(128); }
""")
    assert 'ledcSetup' in c
    assert 'ledcAttachPin' in c
    assert 'ledcWrite' in c


def test_button_with_debounce():
    """Button event should generate digitalRead handler."""
    c = compile_iot("""
@device esp32
pin LED = output 2;
pin BTN = input 5;
on BTN.press { LED = !LED; }
""")
    assert 'digitalRead' in c
    assert 'BTN_PIN' in c


def test_timer_with_label():
    """Named timers should use stable names in generated C."""
    c = compile_iot("""
@device esp32
every 1000 as blinker {
    print("tick");
}
""")
    assert '_iotift_every_blinker' in c
    assert 'blinker_active' in c


def test_empty_timer_skipped():
    """Empty every block should NOT generate a handler."""
    c = compile_iot("""
@device esp32
every 100 { }
""")
    # Should not contain a handler function for this
    assert 'static void _iotift_every_' not in c


def test_after_assign():
    """Deferred assignment should generate scheduler code."""
    c = compile_iot("""
@device esp32
pin LED = output 2;
LED = 0 after 200;
""")
    assert '_iotift_schedule_pin' in c
    assert '_iotift_scheduler_tick' in c


def test_const_pin_macros():
    """Pins should use static const, not #define macros."""
    c = compile_iot("""
@device esp32
pin LED = output 2;
pin BTN = input 5;
""")
    assert 'static const uint8_t LED_PIN' in c
    assert '#define LED_PIN' not in c


def test_fn_decl_emits_function():
    """User functions should be emitted."""
    c = compile_iot("""
@device esp32
fn add(int a, int b) -> int {
    return a + b;
}
""")
    assert 'int add(int a, int b)' in c
    assert 'return a + b;' in c


def test_cast_expression():
    """Cast should generate C cast."""
    c = compile_iot("""
@device esp32
fn convert() -> u8 {
    int x = 300;
    return x as u8;
}
""")
    assert '(uint8_t)' in c


def test_sizeof_expression():
    """sizeof should generate sizeof in C."""
    c = compile_iot("""
@device esp32
int x = sizeof(u32);
""")
    assert 'sizeof(uint32_t)' in c or 'sizeof(uint32_t)' in c


def test_enum_generates_typedef():
    """Enum should generate C typedef enum."""
    c = compile_iot("""
@device esp32
enum Mode { WarmWhite, Rainbow = 5, Breathing }
""")
    assert 'typedef enum' in c
    assert 'Mode' in c


def test_no_string_concat():
    """String + should raise CodeGenError."""
    with pytest.raises(CodeGenError):
        compile_iot("""
@device esp32
print("hello" + "world");
""")


def test_volatile_variable():
    """volatile keyword should generate volatile in C."""
    c = compile_iot("""
@device esp32
volatile int flags = 0;
""")
    assert 'volatile' in c


def test_isr_function():
    """isr fn should generate IRAM_ATTR."""
    c = compile_iot("""
@device esp32
isr fn on_timer() {
    count = count + 1;
}
""")
    assert 'IRAM_ATTR' in c
