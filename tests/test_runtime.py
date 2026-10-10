"""
Runtime tests: compile the generated C++ with the host compiler against a
simulated Arduino core (tests/sim/) and check what the program *does*.

The older test files mostly check that certain strings appear in the
generated code.  That is how the compiler could pass ~650 tests while most
example programs failed to compile or silently did nothing on a device.
These tests run the program instead: they drive pins / ADC / WiFi events
over simulated time and assert on pin changes and Serial output.

Requires g++ or clang++ on PATH; skipped otherwise.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from lexer import tokenize
from parser import Parser
from semantic import SemanticAnalyzer
from codegen import CodeGen, CodeGenError

ROOT = Path(__file__).resolve().parent.parent
SIM = Path(__file__).resolve().parent / 'sim'
CXX = shutil.which('g++') or shutil.which('clang++')
_WORK = Path(tempfile.mkdtemp(prefix='iotift_rt_'))
_SIM_OBJ = None
_COUNTER = [0]


def _need_compiler():
    if CXX is None:
        pytest.skip('no C++ compiler on PATH')


def _sim_obj() -> Path:
    global _SIM_OBJ
    if _SIM_OBJ is None:
        obj = _WORK / 'sim.o'
        subprocess.run([CXX, '-std=c++17', '-c', '-I', str(SIM), str(SIM / 'sim.cpp'), '-o', str(obj)],
                       check=True, capture_output=True, text=True)
        _SIM_OBJ = obj
    return _SIM_OBJ


def parse(source: str):
    p = Parser(tokenize(source))
    prog = p.parse()
    assert not p._had_error, f'parse errors: {p._errors}'
    return prog


def generate(source: str, check_semantics: bool = True) -> str:
    prog = parse(source)
    if check_semantics:
        sa = SemanticAnalyzer()
        sa.analyze(prog)
        assert not sa.has_errors(), sa.errors()
    return CodeGen().generate(prog)


def build(source: str, check_semantics: bool = True) -> Path:
    """Generate C++ for *source*, compile it, return the executable path."""
    _need_compiler()
    code = generate(source, check_semantics)
    _COUNTER[0] += 1
    cpp = _WORK / f'prog{_COUNTER[0]}.cpp'
    exe = _WORK / f'prog{_COUNTER[0]}'
    cpp.write_text(code)
    r = subprocess.run([CXX, '-std=c++17', '-Wall', '-Werror=return-type', '-Werror=parentheses',
                        '-I', str(SIM), str(cpp), str(_sim_obj()), '-o', str(exe)],
                       capture_output=True, text=True)
    assert r.returncode == 0, f'generated C++ does not compile:\n{r.stderr}\n--- code ---\n{code}'
    return exe


def run(source: str, ms: int, events: str = '', check_semantics: bool = True):
    exe = build(source, check_semantics)
    r = subprocess.run([str(exe), str(ms), events], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout.splitlines()


def serial(lines):
    """[(ms, text)] for every completed Serial line."""
    out = []
    for ln in lines:
        if '] SERIAL: ' in ln:
            t, text = ln.split('] SERIAL: ', 1)
            out.append((int(t[1:]), text))
    return out


def texts(lines):
    return [t for _, t in serial(lines)]


def pin_changes(lines, gpio: int):
    """[(ms, level)] for every change of an output pin."""
    out = []
    tag = f'] PIN {gpio} -> '
    for ln in lines:
        if tag in ln:
            t, v = ln.split(tag)
            out.append((int(t[1:]), int(v)))
    return out


# ═════════════════════════════════════════
#  Timers
# ═════════════════════════════════════════

def test_every_toggles_on_schedule():
    lines = run('pin LED = output 2;\nevery 500 { LED.toggle(); }', 2100)
    assert pin_changes(lines, 2) == [(500, 1), (1000, 0), (1500, 1), (2000, 0)]


def test_every_assign_not_pin_toggle():
    lines = run('pin LED = output 2;\nevery 250 { LED = !LED; }', 1100)
    assert pin_changes(lines, 2) == [(250, 1), (500, 0), (750, 1), (1000, 0)]


def test_every_offset_first_fire():
    lines = run('int n = 0;\nevery 1000 offset 200 { n += 1; println("tick {n}"); }', 2300)
    assert serial(lines) == [(200, 'tick 1'), (1200, 'tick 2'), (2200, 'tick 3')]


def test_stop_and_start_named_timer_declared_later():
    # `stop fast` appears before `every ... as fast` in the source.
    src = '''
int ticks = 0;
after 350 { stop fast; }
after 1000 { start fast; }
every 100 as fast { ticks += 1; println("t{ticks}"); }
'''
    out = serial(run(src, 1250))
    assert [t for t, _ in out] == [100, 200, 300, 1100, 1200]


def test_timer_running_property_and_methods():
    src = '''
every 100 as blink { }
after 450 { blink.stop(); }
every 300 { println("running={blink.running}"); }
'''
    assert texts(run(src, 700)) == ['running=true', 'running=false']


# ═════════════════════════════════════════
#  after / deferred assignment
# ═════════════════════════════════════════

def test_after_block_fires_once():
    src = 'after 1500 { println("once"); }'
    assert serial(run(src, 5000)) == [(1500, 'once')]


def test_after_inside_every_fires_relative_to_trigger():
    src = '''
pin LED = output 4;
every 1000 { LED.high(); after 200 { LED.low(); } }
'''
    assert pin_changes(run(src, 2500), 4) == [(1000, 1), (1200, 0), (2000, 1), (2200, 0)]


def test_assign_after_pin_and_int():
    src = '''
pin LED = output 4;
int flag = 0;
LED = 1;
LED = 0 after 300;
flag = 7 after 100;
every 150 { println("flag={flag}"); }
'''
    lines = run(src, 320)
    assert pin_changes(lines, 4) == [(0, 1), (300, 0)]
    assert texts(lines) == ['flag=7', 'flag=7']


def test_after_block_cannot_capture_locals():
    with pytest.raises(CodeGenError, match='local variable'):
        generate('fn f() { int x = 3; after 10 { println("{x}"); } }', check_semantics=False)


# ═════════════════════════════════════════
#  Pin events
# ═════════════════════════════════════════

BUTTON = '''
pin BTN = input 5 { pull: up, debounce: 50ms };
pin LED = output 13;
int presses = 0;
on BTN.press { presses += 1; LED.toggle(); println("press {presses}"); }
on BTN.release { println("release"); }
'''


def test_press_and_release_both_fire_on_same_pin():
    lines = run(BUTTON, 2000, '100:5:0,400:5:1,1000:5:0,1300:5:1')
    assert serial(lines) == [(150, 'press 1'), (450, 'release'), (1050, 'press 2'), (1350, 'release')]
    assert pin_changes(lines, 13) == [(150, 1), (1050, 0)]


def test_bouncing_contact_counts_once():
    bounce = '100:5:0,103:5:1,106:5:0,109:5:1,112:5:0,500:5:1,503:5:0,506:5:1'
    assert texts(run(BUTTON, 1000, bounce)) == ['press 1', 'release']


def test_pull_down_button_press_is_rising_edge():
    src = '''
pin BTN = input 5 { pull: down, debounce: 10ms };
on BTN.press { println("press"); }
on BTN.release { println("release"); }
'''
    assert serial(run(src, 500, '100:5:1,300:5:0')) == [(110, 'press'), (310, 'release')]


def test_threshold_fires_once_per_crossing():
    src = '''
pin TEMP = analog 34;
on TEMP > 2000 { println("hot {TEMP.read()}"); }
on TEMP < 500 { println("cold"); }
'''
    ev = '0:A34:1000,100:A34:2500,150:A34:2600,200:A34:1000,300:A34:3000,400:A34:100'
    assert serial(run(src, 600, ev)) == [(100, 'hot 2500'), (300, 'hot 3000'), (400, 'cold')]


# ═════════════════════════════════════════
#  Expressions & statements
# ═════════════════════════════════════════

def test_float_math_is_not_truncated():
    src = '''
float x = sin(1.0) * 2.0;
float y = 7 / 2.0;
int z = 7 / 2;
println("{x} {y} {z}");
'''
    assert texts(run(src, 5)) == ['1.68 3.50 3']


def test_operator_precedence_matches_c():
    src = '''
bool a = true;
bool b = false;
bool c = false;
int m = 6;
println("{a || b && c} {(a || b) && c} {2 + 3 * 4} {m & 3 | 8} {1 << 3 + 1} {10 - 4 - 3}");
'''
    assert texts(run(src, 5)) == ['true false 14 10 16 3']


def test_bitwise_and_unary():
    src = 'int v = 12;\nprintln("{v & 4} {v | 1} {v ^ 15} {~v & 255} {-v} {!(v == 12)}");'
    assert texts(run(src, 5)) == ['4 13 3 243 -12 false']


def test_print_vs_println_and_interpolation():
    src = '''
int n = 5;
bool lit = true;
print("a");
print(" b");
println(" c");
println("n={n}, twice={n * 2}, lit={lit}, braces={{x}}");
println("sum: " + n + " units");
'''
    assert texts(run(src, 5)) == ['a b c', 'n=5, twice=10, lit=true, braces={x}', 'sum: 5 units']


def test_string_escapes_survive():
    src = r'println("tab\there \"quoted\" back\\slash");'
    assert texts(run(src, 5)) == ['tab\there "quoted" back\\slash']


def test_control_flow():
    src = '''
fn sum_to(int n) -> int {
    int total = 0;
    for (int i = 1; i <= n; i += 1) {
        if (i % 3 == 0) { continue; }
        if (i > 10) { break; }
        total += i;
    }
    return total;
}
fn classify(int x) -> int {
    if (x < 0) { return -1; } else if (x == 0) { return 0; } else { return 1; }
}
fn loop_until() -> int {
    int i = 0;
    loop { i += 1; if (i == 7) { break; } }
    return i;
}
println("{sum_to(20)} {classify(-4)} {classify(0)} {classify(9)} {loop_until()}");
'''
    # 1+2+4+5+7+8+10 = 37
    assert texts(run(src, 5)) == ['37 -1 0 1 7']


def test_functions_can_be_called_before_definition():
    src = '''
println("{first(2)}");
fn first(int x) -> int { return second(x) + 1; }
fn second(int x) -> int { return x * 10; }
'''
    assert texts(run(src, 5)) == ['21']


def test_defer_runs_after_return_value_is_computed():
    src = '''
int counter = 0;
fn work() -> int {
    defer { counter = 100; println("cleanup 1"); }
    defer { println("cleanup 2"); }
    counter = 5;
    return counter + 1;
}
int r = 0;
r = work();
println("r={r} counter={counter}");
'''
    assert texts(run(src, 5)) == ['cleanup 2', 'cleanup 1', 'r=6 counter=100']


def test_struct_enum_array():
    src = '''
struct Reading { int id; float value; }
enum Level { LOW_LEVEL, MID_LEVEL = 5, HIGH_LEVEL }
Reading last;
float hist[4];
fn fill() {
    int i = 0;
    while (i < 4) { hist[i] = i * 1.5; i += 1; }
    last.id = HIGH_LEVEL;
    last.value = hist[3];
}
fill();
println("{last.id} {last.value} {Level.MID_LEVEL} {hist[1] + hist[2]}");
'''
    assert texts(run(src, 5)) == ['6 4.50 5 4.50']


def test_min_max_clamp_map_mixed_types():
    src = '''
float f = 2.5;
println("{min(f, 3)} {max(1, 2)} {clamp(300, 0, 255)} {clamp(-0.5, 0.0, 1.0)} {map(5.0, 0.0, 10.0, 0.0, 100.0)} {abs(-2.5)} {abs(-3)}");
'''
    assert texts(run(src, 5)) == ['2.50 2 255 0.00 50.00 2.50 3']


def test_user_function_named_like_builtin_wins():
    src = '''
fn clamp(float v, float lo, float hi) -> float { return 42.0; }
println("{clamp(1.0, 2.0, 3.0)}");
'''
    assert texts(run(src, 5)) == ['42.00']


# ═════════════════════════════════════════
#  Pins
# ═════════════════════════════════════════

def test_pin_reads_writes():
    src = '''
pin IN = input 5;
pin OUT = output 6;
pin ADC = analog 34;
every 10 { OUT = IN; println("{ADC.read()} {IN}"); }
'''
    lines = run(src, 25, '0:A34:1234,15:5:0')
    assert texts(lines) == ['1234 1', '1234 0']
    assert pin_changes(lines, 6) == [(10, 1), (20, 0)]


def test_pwm_setup_write_clamp_and_readback():
    src = '''
pin R = pwm 13;
R.setup(1000, 10);
R.write(512);
println("{R}");
R.write(5000);
println("{R}");
R = -3;
println("{R}");
'''
    lines = run(src, 5)
    assert any('ledcSetup(ch0,1000,10)' in ln for ln in lines)
    assert [ln.split('] ')[1] for ln in lines if 'ledcWrite' in ln] == \
        ['ledcWrite(ch0,512)', 'ledcWrite(ch0,1023)', 'ledcWrite(ch0,0)']
    assert texts(lines) == ['512.00', '1023.00', '0.00']


def test_output_pin_initial_level():
    lines = run('pin RELAY = output 7 { initial: high };', 5)
    assert pin_changes(lines, 7) == [(0, 1)]


# ═════════════════════════════════════════
#  WiFi
# ═════════════════════════════════════════

STA = '''
wifi home {{ ssid: "Net", password: "secret123", retry: {retry} }};
on home.connect {{ println("up {{home.ip}} rssi={{home.rssi}}"); home.scan(); }}
on home.disconnect {{ println("down"); }}
on home.scan_done {{
    int n = scan_result_count();
    for (int i = 0; i < n; i += 1) {{ println("{{scan_result_ssid(i)}} {{scan_result_rssi(i)}}"); }}
}}
every 1000 {{ println("connected={{home.connected}}"); }}
'''


def test_wifi_station_events_and_scan():
    lines = run(STA.format(retry='fixed'), 2100, '500:W:got_ip,700:W:scan_done,1500:W:lost')
    assert texts(lines) == ['up 192.168.1.50 rssi=-50', 'NetA -50', 'NetB -60',
                            'connected=true', 'down', 'connected=false']


def test_wifi_retry_policy_fixed_gives_up_after_three():
    lines = run(STA.format(retry='fixed'), 160000)
    begins = [int(ln[1:ln.index(']')]) for ln in lines if 'WiFi.begin' in ln]
    # initial attempt + 3 retries; each attempt times out after 30 s, retry 5 s later
    assert begins == [0, 35000, 70000, 105000]


def test_wifi_retry_policy_none():
    lines = run(STA.format(retry='none'), 100000)
    assert sum('WiFi.begin' in ln for ln in lines) == 1


def test_wifi_reconnects_after_drop():
    lines = run(STA.format(retry='forever'), 9000, '100:W:got_ip,2000:W:lost,7500:W:got_ip')
    begins = [int(ln[1:ln.index(']')]) for ln in lines if 'WiFi.begin' in ln]
    assert begins == [0, 7000]
    assert [t for t in texts(lines) if t.startswith(('up', 'down'))] == \
        ['up 192.168.1.50 rssi=-50', 'down', 'up 192.168.1.50 rssi=-50']


def test_wifi_access_point_clients():
    src = '''
wifi hub { mode: ap, ssid: "Hub", password: "longenough", channel: 6 };
on hub.client_join { println("join {hub.clients} {hub.ip}"); }
on hub.client_leave { println("leave {hub.clients}"); }
'''
    lines = run(src, 1000, '100:W:join,200:W:join,300:W:leave')
    assert any('WiFi.softAP(Hub,longenough,ch6,max4)' in ln for ln in lines)
    assert texts(lines) == ['join 1 192.168.4.1', 'join 2 192.168.4.1', 'leave 1']


# ═════════════════════════════════════════
#  Compile-time errors instead of silent garbage
# ═════════════════════════════════════════

def _gen_error(src: str, match: str):
    with pytest.raises(CodeGenError, match=match):
        generate(src, check_semantics=False)


def test_unknown_timer_label_is_an_error():
    _gen_error('every 100 { stop nope; }', 'unknown timer')


def test_two_pins_on_one_gpio_is_an_error():
    _gen_error('pin A = output 5;\npin B = input 5;', 'both GPIO 5')


def test_arduino_macro_names_are_rejected():
    _gen_error('const float PI = 3.14;', 'clashes with a macro')


def test_short_ap_password_is_rejected():
    _gen_error('wifi ap { mode: ap, ssid: "x", password: "short" };', 'at least 8')


def test_unknown_pin_method_is_an_error():
    _gen_error('pin LED = output 2;\nevery 10 { LED.blink(); }', 'unknown pin method')


def test_wifi_event_on_unknown_interface():
    _gen_error('on nothere.connect { }', 'not a declared wifi')


def test_parse_errors_stop_the_build():
    # The parser used to print the error and continue, generating code from
    # whatever it managed to parse.
    _need_compiler()
    src = _WORK / 'bad.iot'
    src.write_text('pin LED = output 2;\nevery 100 { LED = ; }\nevery 200 { LED.toggle(); }\n')
    out = _WORK / 'bad.cpp'
    r = subprocess.run([sys.executable, str(ROOT / 'iotift.py'), 'build', str(src), '-o', str(out)],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode != 0
    assert not out.exists()


# ═════════════════════════════════════════
#  Every example compiles
# ═════════════════════════════════════════

def test_all_examples_compile():
    _need_compiler()
    failures = []
    for ex in sorted((ROOT / 'examples').glob('*.iot')):
        out = _WORK / (ex.stem + '.cpp')
        r = subprocess.run([sys.executable, str(ROOT / 'iotift.py'), 'build', str(ex), '-o', str(out)],
                           capture_output=True, text=True, cwd=str(ROOT))
        if r.returncode != 0:
            failures.append(f'{ex.name}: iotift: {r.stderr.strip().splitlines()[-1:]}')
            continue
        c = subprocess.run([CXX, '-std=c++17', '-fsyntax-only', '-Werror=return-type', '-I', str(SIM), str(out)],
                           capture_output=True, text=True)
        if c.returncode != 0:
            failures.append(f'{ex.name}: g++: {c.stderr.strip()[:400]}')
    assert not failures, '\n'.join(failures)
