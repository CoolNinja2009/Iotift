"""
Milestone 8 — First-Class WiFi Tests

Covers parser, semantic, codegen, HAL, and integration for WiFi.
"""

import sys
import os
import pytest

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lexer import tokenize, TT
from parser import Parser
from ast_nodes import WifiDecl, OnEvent, Program
from semantic import SemanticAnalyzer
from codegen import CodeGen
from symbol_table import SymbolKind


# ─────────────────────────────────────────
#  LEXER TESTS
# ─────────────────────────────────────────


def test_lex_wifi_keyword():
    """The 'wifi' keyword is tokenized as KEYWORD."""
    tokens = tokenize('wifi home { }')
    keywords = [t for t in tokens if t.type == TT.KEYWORD and t.value == 'wifi']
    assert len(keywords) == 1


def test_lex_wifi_identifiers():
    """WiFi names and config keys are valid identifiers (contextual)."""
    tokens = tokenize('sta ap ssid connect scan none fixed')
    idents = [t for t in tokens if t.type == TT.IDENT]
    # All of these are contextual — they tokenize as IDENT
    assert len(idents) >= 6


# ─────────────────────────────────────────
#  PARSER TESTS
# ─────────────────────────────────────────


def _parse(source: str) -> Program:
    tokens = tokenize(source)
    parser = Parser(tokens)
    return parser.parse()


def _has_node(program: Program, node_type: type) -> bool:
    """Check if program contains a specific AST node type."""
    for node in program.body:
        if isinstance(node, node_type):
            return True
    return False


def _get_node(program: Program, node_type: type):
    """Get the first node of a specific type from the program."""
    for node in program.body:
        if isinstance(node, node_type):
            return node
    return None


def test_parse_wifi_sta_basic():
    """wifi home { ssid: "x", password: "y" }"""
    prog = _parse('wifi home { ssid: "MyWiFi", password: "mypassword" };')
    wd = _get_node(prog, WifiDecl)
    assert wd is not None
    assert wd.name == 'home'
    assert wd.mode == 'sta'
    assert wd.config.get('ssid') == 'MyWiFi'
    assert wd.config.get('password') == 'mypassword'


def test_parse_wifi_sta_all_options():
    """STA wifi with all config keys."""
    prog = _parse('''
    wifi office {
        mode: sta,
        ssid: "OfficeNet",
        password: "office123",
        hostname: "iotift-sensor",
        connect_timeout: 30000,
        retry: exponential,
        power_save: light,
        static_ip: "192.168.1.100",
        gateway: "192.168.1.1",
        subnet: "255.255.255.0",
        dns: "8.8.8.8",
    };
    ''')
    wd = _get_node(prog, WifiDecl)
    assert wd is not None
    assert wd.name == 'office'
    assert wd.config.get('hostname') == 'iotift-sensor'
    assert wd.config.get('static_ip') == '192.168.1.100'
    assert wd.config.get('gateway') == '192.168.1.1'
    assert wd.config.get('subnet') == '255.255.255.0'
    assert wd.config.get('dns') == '8.8.8.8'
    assert wd.config.get('power_save') == 'light'
    assert wd.config.get('retry') == {'kind': 'exponential'}


def test_parse_wifi_ap_open():
    """AP without password."""
    prog = _parse('''
    wifi guest {
        mode: ap,
        ssid: "FreeWiFi",
        channel: 6,
        max_clients: 4,
    };
    ''')
    wd = _get_node(prog, WifiDecl)
    assert wd is not None
    assert wd.mode == 'ap'
    assert wd.config.get('ssid') == 'FreeWiFi'
    assert wd.config.get('channel') == 6
    assert wd.config.get('max_clients') == 4
    assert 'password' not in wd.config


def test_parse_wifi_ap_secured():
    """AP with password."""
    prog = _parse('''
    wifi myAP {
        mode: ap,
        ssid: "MyHotspot",
        password: "ap_password",
        channel: 1,
        max_clients: 8,
    };
    ''')
    wd = _get_node(prog, WifiDecl)
    assert wd is not None
    assert wd.mode == 'ap'
    assert wd.config.get('password') == 'ap_password'


def test_parse_wifi_sta_and_ap():
    """Two WiFi declarations in one file."""
    prog = _parse('''
    wifi sta_if { ssid: "HomeWiFi", password: "pass" };
    wifi ap_if { mode: ap, ssid: "IotiftAP", password: "ap123" };
    ''')
    wds = [n for n in prog.body if isinstance(n, WifiDecl)]
    assert len(wds) == 2
    assert wds[0].name == 'sta_if'
    assert wds[0].mode == 'sta'
    assert wds[1].name == 'ap_if'
    assert wds[1].mode == 'ap'


def test_parse_wifi_default_mode():
    """Mode defaults to sta when omitted."""
    prog = _parse('wifi home { ssid: "x", password: "y" };')
    wd = _get_node(prog, WifiDecl)
    assert wd.mode == 'sta'


def test_parse_wifi_on_connect():
    """on home.connect { ... }"""
    prog = _parse('''
    wifi home { ssid: "x", password: "y" };
    on home.connect {
        print("Connected!");
    }
    ''')
    oe = _get_node(prog, OnEvent)
    assert oe is not None
    assert oe.target == 'home'
    assert oe.event == 'connect'


def test_parse_wifi_on_disconnect():
    """on home.disconnect { ... }"""
    prog = _parse('''
    on home.disconnect {
        print("Disconnected!");
    }
    ''')
    oe = _get_node(prog, OnEvent)
    assert oe is not None
    assert oe.target == 'home'
    assert oe.event == 'disconnect'


def test_parse_wifi_on_got_ip():
    """on home.got_ip { ... }"""
    prog = _parse('''
    on home.got_ip {
        print(home.ip);
    }
    ''')
    oe = _get_node(prog, OnEvent)
    assert oe is not None
    assert oe.event == 'got_ip'


def test_parse_wifi_on_scan_done():
    """on home.scan_done { ... }"""
    prog = _parse('''
    on home.scan_done {
        print(scan_result_count());
    }
    ''')
    oe = _get_node(prog, OnEvent)
    assert oe is not None
    assert oe.event == 'scan_done'


def test_parse_wifi_on_client_join():
    """on ap_if.client_join { ... }"""
    prog = _parse('''
    on ap_if.client_join {
        print("Client joined!");
    }
    ''')
    oe = _get_node(prog, OnEvent)
    assert oe is not None
    assert oe.event == 'client_join'


def test_parse_wifi_on_client_leave():
    """on ap_if.client_leave { ... }"""
    prog = _parse('''
    on ap_if.client_leave {
        print("Client left!");
    }
    ''')
    oe = _get_node(prog, OnEvent)
    assert oe is not None
    assert oe.event == 'client_leave'


def test_parse_wifi_property_access():
    """WiFi property access parses as MemberAccess."""
    prog = _parse('''
    wifi home { ssid: "x", password: "y" };
    bool c = home.connected;
    ''')
    assert prog is not None  # Parsed without error


def test_parse_wifi_method_call():
    """WiFi method calls parse correctly."""
    prog = _parse('''
    wifi home { ssid: "x", password: "y" };
    home.scan();
    ''')
    assert prog is not None  # Parsed without error


def test_parse_wifi_retry_none():
    """retry: none"""
    prog = _parse('wifi home { ssid: "x", password: "y", retry: none };')
    wd = _get_node(prog, WifiDecl)
    assert wd.config.get('retry') == {'kind': 'none'}


def test_parse_wifi_retry_fixed():
    """retry: fixed"""
    prog = _parse('wifi home { ssid: "x", password: "y", retry: fixed };')
    wd = _get_node(prog, WifiDecl)
    assert wd.config.get('retry') == {'kind': 'fixed'}


def test_parse_wifi_retry_forever():
    """retry: forever"""
    prog = _parse('wifi home { ssid: "x", password: "y", retry: forever };')
    wd = _get_node(prog, WifiDecl)
    assert wd.config.get('retry') == {'kind': 'forever'}


def test_parse_wifi_retry_exponential():
    """retry: exponential"""
    prog = _parse('wifi home { ssid: "x", password: "y", retry: exponential };')
    wd = _get_node(prog, WifiDecl)
    assert wd.config.get('retry') == {'kind': 'exponential'}


def test_parse_wifi_retry_custom():
    """retry: custom { count: 5, interval: 10000 }"""
    prog = _parse('''
    wifi home {
        ssid: "x",
        password: "y",
        retry: custom { count: 5, interval: 10000 },
    };
    ''')
    wd = _get_node(prog, WifiDecl)
    retry = wd.config.get('retry')
    assert retry is not None
    assert retry['kind'] == 'custom'
    assert retry['count'] == 5
    assert retry['interval_ms'] == 10000


def test_parse_wifi_error_no_ssid():
    """Missing ssid in STA mode is parseable (error caught by semantic)."""
    prog = _parse('wifi home { password: "y" };')
    wd = _get_node(prog, WifiDecl)
    assert wd is not None
    assert 'ssid' not in wd.config  # Parser doesn't enforce — semantic does


# ─────────────────────────────────────────
#  SEMANTIC TESTS
# ─────────────────────────────────────────


def _analyze(source: str):
    """Parse and run semantic analysis on source."""
    tokens = tokenize(source)
    parser = Parser(tokens)
    prog = parser.parse()
    analyzer = SemanticAnalyzer()
    analyzer.analyze(prog)
    return prog, analyzer


def test_semantic_wifi_sta_valid():
    """STA with password passes all semantic checks."""
    _, analyzer = _analyze('''
    wifi home { ssid: "MyWiFi", password: "mypassword" };
    ''')
    assert not analyzer.has_errors()


def test_semantic_wifi_ap_open_valid():
    """Open AP passes all semantic checks (with warning)."""
    _, analyzer = _analyze('''
    wifi guest { mode: ap, ssid: "FreeWiFi", channel: 6 };
    ''')
    assert not analyzer.has_errors()
    # Should have open-ap warning
    assert len(analyzer.warnings()) >= 1


def test_semantic_wifi_dual_sta_error():
    """Two STA declarations → error."""
    _, analyzer = _analyze('''
    wifi home { ssid: "Home", password: "pass" };
    wifi work { ssid: "Work", password: "pass" };
    ''')
    assert analyzer.has_errors()


def test_semantic_wifi_clients_on_sta_error():
    """.clients on STA wifi → error."""
    _, analyzer = _analyze('''
    wifi home { ssid: "x", password: "y" };
    int c = home.clients;
    ''')
    assert analyzer.has_errors()


def test_semantic_wifi_scan_on_ap_error():
    """.scan() on AP wifi → error."""
    _, analyzer = _analyze('''
    wifi guest { mode: ap, ssid: "FreeWiFi" };
    guest.scan();
    ''')
    assert analyzer.has_errors()


def test_semantic_wifi_rssi_on_ap_error():
    """.rssi on AP wifi → error."""
    _, analyzer = _analyze('''
    wifi guest { mode: ap, ssid: "FreeWiFi" };
    int r = guest.rssi;
    ''')
    assert analyzer.has_errors()


def test_semantic_wifi_ip_on_ap_error():
    """.ip on AP wifi → error."""
    _, analyzer = _analyze('''
    wifi guest { mode: ap, ssid: "FreeWiFi" };
    str ip = guest.ip;
    ''')
    assert analyzer.has_errors()


def test_semantic_wifi_short_password_warning():
    """Password < 8 chars → warning."""
    _, analyzer = _analyze('''
    wifi home { ssid: "x", password: "short" };
    ''')
    warnings = analyzer.warnings()
    assert any('less than 8' in w for w in warnings)


def test_semantic_wifi_no_password_warning():
    """STA mode without password → warning."""
    _, analyzer = _analyze('''
    wifi home { ssid: "x" };
    ''')
    warnings = analyzer.warnings()
    assert any('without password' in w for w in warnings)


def test_semantic_wifi_scan_result_outside_handler():
    """scan_result_count() outside scan_done handler → error."""
    _, analyzer = _analyze('''
    wifi home { ssid: "x", password: "y" };
    int c = scan_result_count();
    ''')
    assert analyzer.has_errors()


def test_semantic_wifi_static_ip_incomplete():
    """static_ip without gateway → error."""
    _, analyzer = _analyze('''
    wifi home {
        ssid: "x",
        password: "y",
        static_ip: "192.168.1.100",
    };
    ''')
    assert analyzer.has_errors()


def test_semantic_wifi_connect_event_on_ap_error():
    """on ap.connect → error (AP doesn't have connect events)."""
    _, analyzer = _analyze('''
    wifi guest { mode: ap, ssid: "FreeWiFi" };
    on guest.connect { print("?"); }
    ''')
    assert analyzer.has_errors()


def test_semantic_wifi_client_event_on_sta_error():
    """on sta.client_join → error (STA doesn't have client events)."""
    _, analyzer = _analyze('''
    wifi home { ssid: "x", password: "y" };
    on home.client_join { print("?"); }
    ''')
    assert analyzer.has_errors()


def test_semantic_wifi_type_checking():
    """WiFi property types resolve correctly."""
    _, analyzer = _analyze('''
    wifi home { ssid: "x", password: "y" };
    on home.connect {
        bool c = home.connected;
        str ip = home.ip;
        int r = home.rssi;
        int ch = home.channel;
        str mac = home.mac;
    }
    ''')
    # Should not have type errors
    assert not analyzer.has_errors()


def test_semantic_wifi_state_enum():
    """WifiState enum is generated and usable."""
    _, analyzer = _analyze('''
    wifi home { ssid: "x", password: "y" };
    on home.connect {
        if home.state == WifiState_Connected { }
    }
    ''')
    assert not analyzer.has_errors()


# ─────────────────────────────────────────
#  CODEGEN TESTS
# ─────────────────────────────────────────


def _generate(source: str) -> str:
    """Compile source to C code."""
    tokens = tokenize(source)
    parser = Parser(tokens)
    prog = parser.parse()
    analyzer = SemanticAnalyzer()
    analyzer.analyze(prog)
    cg = CodeGen()
    return cg.generate(prog)


def test_codegen_wifi_sta_emits_wifi_init():
    """STA wifi emits WiFi init code."""
    c = _generate('''
    wifi home { ssid: "MyWiFi", password: "mypassword" };
    ''')
    assert 'WiFi.begin' in c or 'wifi' in c.lower()
    assert 'WIFI_STATE' in c
    assert '_iotift_wifi_home_' in c


def test_codegen_wifi_ap_emits_ap_mode():
    """AP mode emits AP config."""
    c = _generate('''
    wifi guest { mode: ap, ssid: "FreeWiFi", channel: 6 };
    ''')
    assert 'WiFi.softAP' in c or 'WIFI_MODE_AP' in c or '_wifi_ap_cfg' in c


def test_codegen_wifi_connect_handler():
    """Event handler function is emitted."""
    c = _generate('''
    wifi home { ssid: "x", password: "y" };
    on home.connect {
        print("Connected!");
    }
    ''')
    assert '_iotift_wifi_home_on_connect' in c
    assert '_iotift_wifi_home_dispatch' in c


def test_codegen_wifi_property_connected():
    """.connected → correct C variable."""
    c = _generate('''
    wifi home { ssid: "x", password: "y" };
    on home.connect {
        bool c = home.connected;
    }
    ''')
    assert '_iotift_wifi_home_connected' in c


def test_codegen_wifi_property_ip():
    """.ip → correct C variable."""
    c = _generate('''
    wifi home { ssid: "x", password: "y" };
    on home.connect {
        str ip = home.ip;
    }
    ''')
    assert '_iotift_wifi_home_ip' in c


def test_codegen_wifi_method_scan():
    """.scan() → correct C function."""
    c = _generate('''
    wifi home { ssid: "x", password: "y" };
    on home.connect {
        home.scan();
    }
    ''')
    assert '_iotift_wifi_home_scan_start' in c


def test_codegen_wifi_method_disconnect():
    """.disconnect() → correct C function."""
    c = _generate('''
    wifi home { ssid: "x", password: "y" };
    on home.connect {
        home.disconnect();
    }
    ''')
    assert '_iotift_wifi_home_disconnect' in c


def test_codegen_wifi_no_leakage():
    """Non-WiFi program emits zero WiFi code."""
    c = _generate('''
    pin LED = output 2;
    every 1s { LED = !LED; }
    ''')
    assert 'wifi' not in c.lower()
    assert 'WiFi' not in c
    assert 'WIFI_STATE' not in c


def test_codegen_wifi_nvs_guard_shared():
    """Multiple WiFi declarations share init guard."""
    c = _generate('''
    wifi sta_if { ssid: "a", password: "pass" };
    wifi ap_if { mode: ap, ssid: "b", password: "pass2" };
    ''')
    assert '_iotift_wifi_system_initialized' in c


def test_codegen_wifi_static_ip():
    """Static IP config is emitted."""
    c = _generate('''
    wifi home {
        ssid: "x",
        password: "y",
        static_ip: "192.168.1.100",
        gateway: "192.168.1.1",
        subnet: "255.255.255.0",
        dns: "8.8.8.8",
    };
    ''')
    # Static IP gets transformed to IPAddress() call with commas
    assert '192' in c  # Part of the IP address appears somewhere


def test_codegen_wifi_scan_result_accessors():
    """Scan result functions are emitted when scan_done handler exists."""
    c = _generate('''
    wifi home { ssid: "x", password: "y" };
    on home.scan_done {
        int count = scan_result_count();
    }
    ''')
    assert '_iotift_wifi_scan_result_count' in c


# ─────────────────────────────────────────
#  INTEGRATION TESTS
# ─────────────────────────────────────────


def test_full_pipeline_wifi_sta():
    """Full parse→semantic→codegen for STA WiFi."""
    source = '''
    wifi home { ssid: "MyWiFi", password: "pass1234" };
    on home.connect {
        print("Connected!");
    }
    '''
    tokens = tokenize(source)
    prog = Parser(tokens).parse()
    analyzer = SemanticAnalyzer()
    analyzer.analyze(prog)
    assert not analyzer.has_errors()
    c = CodeGen().generate(prog)
    assert 'WiFi.begin' in c or '_iotift_wifi_system_init' in c
    assert '_iotift_wifi_home_connected' in c


def test_full_pipeline_wifi_ap():
    """Full parse→semantic→codegen for AP WiFi."""
    source = '''
    wifi guest { mode: ap, ssid: "FreeWiFi", channel: 6 };
    on guest.client_join {
        print("Client joined!");
    }
    '''
    tokens = tokenize(source)
    prog = Parser(tokens).parse()
    analyzer = SemanticAnalyzer()
    analyzer.analyze(prog)
    assert not analyzer.has_errors()
    c = CodeGen().generate(prog)
    assert 'WiFi.softAP' in c or '_iotift_wifi_guest_' in c


def test_no_wifi_leakage_led():
    """Non-WiFi program still compiles cleanly (no WiFi leakage)."""
    source = '''
    pin LED = output 2;
    every 500ms { LED = !LED; }
    '''
    tokens = tokenize(source)
    prog = Parser(tokens).parse()
    c = CodeGen().generate(prog)
    assert 'wifi' not in c.lower()


def test_wifi_pin_on_event_still_works():
    """Existing pin OnEvent still works with target field."""
    source = '''
    pin BTN = input 5;
    on BTN.press { print("pressed"); }
    '''
    tokens = tokenize(source)
    prog = Parser(tokens).parse()
    analyzer = SemanticAnalyzer()
    analyzer.analyze(prog)
    assert not analyzer.has_errors()
    c = CodeGen().generate(prog)
    assert 'BTN_PIN' in c
    assert '_iotift_on_BTN_press' in c


# ─────────────────────────────────────────
#  BACKWARD COMPAT
# ─────────────────────────────────────────


def test_on_event_backward_compat_pin_property():
    """OnEvent.pin property still works for backward compat."""
    from ast_nodes import OnEvent
    oe = OnEvent(target='BTN', event='press', body=[])
    assert oe.pin == 'BTN'  # backward compat
    oe.pin = 'BTN2'
    assert oe.target == 'BTN2'


def test_ast_wifi_decl_node():
    """WifiDecl dataclass works correctly."""
    wd = WifiDecl(name='home', mode='sta',
                  config={'ssid': 'x', 'password': 'y'})
    assert wd.name == 'home'
    assert wd.mode == 'sta'
    assert wd.config['ssid'] == 'x'
    assert wd.config['password'] == 'y'
    assert wd.config.get('hostname') is None


# ─────────────────────────────────────────
#  HAL TESTS
# ─────────────────────────────────────────


def test_hal_wifi_supported_esp32_arduino():
    """ESP32 Arduino HAL reports WiFi as supported."""
    from hal.esp32_arduino import ESP32ArduinoHAL
    hal = ESP32ArduinoHAL()
    assert hal.wifi_supported() is True
    assert hal.wifi_max_sta_interfaces() == 1
    assert hal.wifi_max_ap_interfaces() == 1


def test_hal_wifi_supported_esp32_espidf():
    """ESP32 ESP-IDF HAL reports WiFi as supported."""
    from hal.esp32_espidf import ESP32IDFHAL
    hal = ESP32IDFHAL()
    assert hal.wifi_supported() is True


def test_hal_wifi_unsupported_targets():
    """AVR, STM32, RP2040, nRF52, CMSIS targets report WiFi as unsupported."""
    from hal.avr_arduino import AVRArduinoHAL
    from hal.stm32_arduino import STM32ArduinoHAL
    from hal.rp2040_arduino import RP2040ArduinoHAL
    from hal.nrf52_arduino import NRF52ArduinoHAL
    from hal.cmsis_arm import CMSISHAL

    for hal_cls in [AVRArduinoHAL, STM32ArduinoHAL, RP2040ArduinoHAL,
                     NRF52ArduinoHAL, CMSISHAL]:
        hal = hal_cls()
        assert hal.wifi_supported() is False, f'{hal_cls.__name__} should not support WiFi'
        assert hal.wifi_max_sta_interfaces() == 0
        assert hal.wifi_max_ap_interfaces() == 0


def test_hal_wifi_init_output_structure():
    """Structured WifiInitOutput dataclass works."""
    from hal.base import HALBase
    ctx = HALBase.WifiInitContext(
        name='home', c_name='_iotift_wifi_home', mode='sta',
        ssid='Test', password='pass1234',
    )
    assert ctx.name == 'home'
    assert ctx.mode == 'sta'
    assert ctx.password == 'pass1234'

    out = HALBase.WifiInitOutput(
        includes=['#include <WiFi.h>'],
        state_decls=['static int test;'],
    )
    assert len(out.includes) == 1
    assert len(out.state_decls) == 1


def test_hal_esp32_arduino_wifi_init():
    """Arduino HAL generates expected C output."""
    from hal.esp32_arduino import ESP32ArduinoHAL
    from hal.base import HALBase
    hal = ESP32ArduinoHAL()
    ctx = HALBase.WifiInitContext(
        name='home', c_name='_iotift_wifi_home', mode='sta',
        ssid='TestWiFi', password='test1234',
    )
    out = hal.wifi_generate_init([ctx])
    assert len(out.includes) > 0
    assert len(out.state_decls) > 0
    assert any('connected' in d for d in out.state_decls)


def test_hal_esp32_espidf_wifi_init():
    """ESP-IDF HAL generates expected C output."""
    from hal.esp32_espidf import ESP32IDFHAL
    from hal.base import HALBase
    hal = ESP32IDFHAL()
    ctx = HALBase.WifiInitContext(
        name='home', c_name='_iotift_wifi_home', mode='sta',
        ssid='TestWiFi', password='test1234',
    )
    out = hal.wifi_generate_init([ctx])
    assert len(out.includes) > 0
    assert len(out.state_decls) > 0


def test_hal_wifi_property_read():
    """Property read generation returns correct C expressions."""
    from hal.esp32_arduino import ESP32ArduinoHAL
    hal = ESP32ArduinoHAL()
    assert 'connected' in hal.wifi_generate_property_read('home', '_iotift_wifi_home', 'connected')
    assert 'ip' in hal.wifi_generate_property_read('home', '_iotift_wifi_home', 'ip')
    assert 'rssi' in hal.wifi_generate_property_read('home', '_iotift_wifi_home', 'rssi')


def test_hal_wifi_event_registration():
    """Event registration generates expected code."""
    from hal.esp32_arduino import ESP32ArduinoHAL
    hal = ESP32ArduinoHAL()
    result = hal.wifi_generate_event_registration('home', '_iotift_wifi_home', 'connect')
    assert 'home' in result or 'connect' in result.lower()


def test_hal_wifi_retry_policy():
    """RetryPolicy dataclass works."""
    from hal.base import HALBase
    rp = HALBase.RetryPolicy(kind='exponential', count=10, interval_ms=1000,
                              max_interval_ms=60000, backoff='exponential')
    assert rp.kind == 'exponential'
    assert rp.count == 10
    assert rp.interval_ms == 1000
    assert rp.max_interval_ms == 60000


def test_hal_wifi_event_context():
    """EventContext dataclass works."""
    from hal.base import HALBase
    ec = HALBase.EventContext(
        wifi_name='home', c_prefix='_iotift_wifi_home',
        event='connect', handler_body='print("hi");',
        handler_func_name='_iotift_wifi_home_on_connect',
    )
    assert ec.wifi_name == 'home'
    assert ec.event == 'connect'


# ─────────────────────────────────────────
#  LINTER TESTS
# ─────────────────────────────────────────


def test_lint_wifi_no_password():
    """STA without password produces lint warning."""
    from iotift.tools.linter import Linter, LintSeverity
    tokens = tokenize('wifi home { ssid: "x" };')
    prog = Parser(tokens).parse()
    linter = Linter()
    diags = linter.lint(prog)
    assert any(d.rule == 'wifi-no-password' for d in diags)


def test_lint_wifi_short_password():
    """Short password produces lint warning."""
    from iotift.tools.linter import Linter
    tokens = tokenize('wifi home { ssid: "x", password: "shrt" };')
    prog = Parser(tokens).parse()
    linter = Linter()
    diags = linter.lint(prog)
    assert any(d.rule == 'wifi-short-password' for d in diags)


def test_lint_wifi_open_ap():
    """Open AP produces lint info."""
    from iotift.tools.linter import Linter
    tokens = tokenize('wifi guest { mode: ap, ssid: "FreeWiFi" };')
    prog = Parser(tokens).parse()
    linter = Linter()
    diags = linter.lint(prog)
    assert any(d.rule == 'wifi-open-ap' for d in diags)


def test_lint_wifi_blocking():
    """delay() in WiFi handler produces lint warning."""
    from iotift.tools.linter import Linter
    source = '''
    wifi home { ssid: "x", password: "y" };
    on home.connect {
        delay(100);
    }
    '''
    tokens = tokenize(source)
    prog = Parser(tokens).parse()
    linter = Linter()
    diags = linter.lint(prog)
    assert any(d.rule == 'wifi-blocking-in-handler' for d in diags)


def test_lint_wifi_unused():
    """WiFi without event handlers produces lint warning."""
    from iotift.tools.linter import Linter
    tokens = tokenize('wifi home { ssid: "x", password: "y" };')
    prog = Parser(tokens).parse()
    linter = Linter()
    diags = linter.lint(prog)
    assert any(d.rule == 'wifi-unused' for d in diags)
