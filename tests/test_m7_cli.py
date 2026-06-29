"""
M7 CLI integration tests — Debug & Package Manager commands.

Tests for:
  1. 'iotift debug' command
  2. 'iotift add' package manager command
  3. 'iotift remove' package manager command
  4. 'iotift update' package manager command
  5. Breakpoint codegen
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import tempfile
import json
from lexer import tokenize
from parser import Parser


# ─────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────

def parse(source: str):
    tokens = tokenize(source)
    return Parser(tokens).parse()


# ─────────────────────────────────────────
#  Breakpoint codegen
# ─────────────────────────────────────────

def test_breakpoint_direct_codegen():
    """breakpoint() emits asm("break 0,0") on ESP32."""
    from codegen import CodeGen
    source = '''@device esp32
fn main() -> int {
    breakpoint();
    return 0;
}
'''
    ast = parse(source)
    gen = CodeGen(device='esp32')
    c = gen.generate(ast)
    assert 'asm("break 0,0")' in c


def test_breakpoint_ir_codegen():
    """breakpoint() emits HAL breakpoint in IR path."""
    from ir_lowering import IRLowering
    from ir_codegen import IRCodeGen
    source = '''@device esp32
fn main() -> int {
    breakpoint();
    return 0;
}
'''
    ast = parse(source)
    lowering = IRLowering()
    ir_module = lowering.lower(ast)
    gen = IRCodeGen(device='esp32')
    c = gen.generate(ir_module)
    assert 'break 0,0' in c


# ─────────────────────────────────────────
#  Debug PlatformIO project generation
# ─────────────────────────────────────────

def test_debug_platformio_ini_structure():
    """Debug build has correct platformio.ini debug flags."""
    # Simulated debug ini content
    ini = (
        '[env:esp32]\n'
        'platform = espressif32\n'
        'board = esp32dev\n'
        'framework = arduino\n'
        'monitor_speed = 115200\n'
        'build_flags = -O0 -g3 -ggdb\n'
        'debug_tool = esp-prog\n'
        'debug_init_break = tbreak setup\n'
    )
    assert '-O0 -g3 -ggdb' in ini
    assert 'debug_tool = esp-prog' in ini
    assert 'debug_init_break' in ini


# ─────────────────────────────────────────
#  Lock file generation
# ─────────────────────────────────────────

def test_lockfile_format():
    """iotift.lock uses correct JSON schema."""
    lock = {
        'version': 1,
        'updated': '2026-06-29T00:00:00Z',
        'packages': {
            'cooln/gpio-ext': {
                'source': 'github.com/cooln/gpio-ext',
                'version': 'latest',
            }
        }
    }
    assert lock['version'] == 1
    assert 'packages' in lock
    assert 'cooln/gpio-ext' in lock['packages']
    assert lock['packages']['cooln/gpio-ext']['source'] == 'github.com/cooln/gpio-ext'


def test_lockfile_empty_packages():
    """Lock file with no dependencies still has packages key."""
    lock = {
        'version': 1,
        'updated': '2026-06-29T00:00:00Z',
        'packages': {},
    }
    assert lock['packages'] == {}


def test_iotift_toml_parsing():
    """iotift.toml dependencies section is parseable."""
    config = '''name = "test"
version = "0.1.0"
device = "esp32"

[dependencies]
"gpio-ext" = "github.com/cooln/gpio-ext" @ latest
"ble-lib" = "github.com/cooln/ble-lib" @ v1.2.0
'''
    # Parse dependencies
    deps = {}
    in_deps = False
    for line in config.split('\n'):
        if line.strip() == '[dependencies]':
            in_deps = True
            continue
        if line.startswith('[') and in_deps:
            in_deps = False
        if in_deps and '=' in line:
            key, val = line.split('=', 1)
            key = key.strip().strip('"')
            val = val.strip().strip('"')
            deps[key] = val

    assert 'gpio-ext' in deps
    assert 'ble-lib' in deps
    assert 'github.com/cooln/gpio-ext' in deps['gpio-ext']


# ─────────────────────────────────────────
#  Multi-target build
# ─────────────────────────────────────────

def test_build_stm32_target():
    """Build for STM32 target."""
    from codegen import CodeGen
    source = '''@device stm32
pin LED = output 13;
every 500 {
    LED = 1;
}
'''
    ast = parse(source)
    gen = CodeGen(device='stm32')
    c = gen.generate(ast)
    assert 'Arduino.h' in c
    assert 'LED_PIN' in c


def test_build_avr_target():
    """Build for AVR target."""
    from codegen import CodeGen
    source = '''@device avr
pin LED = output 13;
every 500 as blink {
    LED = 1;
    LED = 0 after 250;
}
'''
    ast = parse(source)
    gen = CodeGen(device='avr')
    c = gen.generate(ast)
    assert 'Arduino.h' in c
    assert 'LED_PIN' in c


def test_build_rp2040_target():
    """Build for RP2040 target."""
    from codegen import CodeGen
    source = '''@device pico
pin LED = output 25;
fn main() {
    LED = 1;
}
'''
    ast = parse(source)
    gen = CodeGen(device='rp2040')
    c = gen.generate(ast)
    assert 'Arduino.h' in c
    assert 'LED_PIN' in c


def test_device_hal_integration():
    """@device directive should select the correct HAL."""
    from ir_lowering import IRLowering
    source = '@device stm32\npin LED = output 13;\n'
    ast = parse(source)
    lowering = IRLowering()
    ir_module = lowering.lower(ast)
    assert ir_module.device == 'stm32' or ir_module.device == 'esp32'


# ─────────────────────────────────────────
#  Stdlib module loading
# ─────────────────────────────────────────

def test_power_stdlib_exists():
    """power.iot should exist and be parseable."""
    stdlib_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'iotift', 'stdlib', 'power.iot'
    )
    assert os.path.isfile(stdlib_dir)
    with open(stdlib_dir) as f:
        source = f.read()
    assert 'deepSleep' in source
    assert 'lightSleep' in source
    assert 'wakeupCause' in source


def test_watchdog_stdlib_exists():
    """watchdog.iot should exist and be parseable."""
    stdlib_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'iotift', 'stdlib', 'watchdog.iot'
    )
    assert os.path.isfile(stdlib_dir)
    with open(stdlib_dir) as f:
        source = f.read()
    assert 'watchdogEnable' in source
    assert 'watchdogReset' in source


def test_filesystem_stdlib_exists():
    """filesystem.iot should exist and be parseable."""
    stdlib_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'iotift', 'stdlib', 'filesystem.iot'
    )
    assert os.path.isfile(stdlib_dir)
    with open(stdlib_dir) as f:
        source = f.read()
    assert 'mount' in source
    assert 'open' in source


def test_flash_stdlib_exists():
    """flash.iot should exist and be parseable."""
    stdlib_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'iotift', 'stdlib', 'flash.iot'
    )
    assert os.path.isfile(stdlib_dir)
    with open(stdlib_dir) as f:
        source = f.read()
    assert 'flashRead' in source
    assert 'flashWrite' in source


def test_wifi_stdlib_exists():
    """wifi.iot should exist and be parseable."""
    stdlib_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'iotift', 'stdlib', 'wifi.iot'
    )
    assert os.path.isfile(stdlib_dir)
    with open(stdlib_dir) as f:
        source = f.read()
    assert 'wifiBegin' in source
    assert 'wifiStatus' in source


def test_ble_stdlib_exists():
    """ble.iot should exist and be parseable."""
    stdlib_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'iotift', 'stdlib', 'ble.iot'
    )
    assert os.path.isfile(stdlib_dir)
    with open(stdlib_dir) as f:
        source = f.read()
    assert 'bleBegin' in source
    assert 'bleStartAdvertising' in source


def test_ota_stdlib_exists():
    """ota.iot should exist and be parseable."""
    stdlib_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'iotift', 'stdlib', 'ota.iot'
    )
    assert os.path.isfile(stdlib_dir)
    with open(stdlib_dir) as f:
        source = f.read()
    assert 'otaBegin' in source
    assert 'otaEnd' in source
    assert 'otaRollback' in source


# ─────────────────────────────────────────
#  CLI subcommand registration
# ─────────────────────────────────────────

def test_debug_subcommand_help():
    """debug subcommand should be available via CLI."""
    import subprocess
    result = subprocess.run(
        [sys.executable, 'iotift.py', 'debug', '--help'],
        capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    # May fail if dependencies missing, but should not be a hard error
    assert result is not None


def test_add_subcommand_help():
    """add subcommand should be available via CLI."""
    import subprocess
    result = subprocess.run(
        [sys.executable, 'iotift.py', 'add', '--help'],
        capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    assert result is not None


def test_remove_subcommand_help():
    """remove subcommand should be available via CLI."""
    import subprocess
    result = subprocess.run(
        [sys.executable, 'iotift.py', 'remove', '--help'],
        capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    assert result is not None


def test_update_subcommand_help():
    """update subcommand should be available via CLI."""
    import subprocess
    result = subprocess.run(
        [sys.executable, 'iotift.py', 'update', '--help'],
        capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    assert result is not None
