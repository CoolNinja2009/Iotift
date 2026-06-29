"""
ESP32 Arduino HAL — production implementation.

This is the default target for Iotift.  It emits Arduino framework calls
for the Espressif ESP32 family (including S2, S3, C3, C6).
"""

from __future__ import annotations
from typing import List
from .base import HALBase


class ESP32ArduinoHAL(HALBase):
    """HAL for ESP32 microcontrollers running the Arduino framework."""

    @property
    def target_name(self) -> str:
        return 'ESP32 (Arduino)'

    @property
    def framework(self) -> str:
        return 'arduino'

    # ── includes ─────────────────────────────────────────────────

    def get_includes(self) -> List[str]:
        return ['#include <Arduino.h>']

    # ── GPIO ──────────────────────────────────────────────────────

    def get_pin_macro(self, name: str, number: int) -> str:
        return f'static const uint8_t {name}_PIN = {number}U;'

    def pin_mode(self, pin_expr: str, direction: str) -> str:
        return f'pinMode({pin_expr}, {direction});'

    def digital_write(self, pin_expr: str, value: str) -> str:
        return f'digitalWrite({pin_expr}, {value});'

    def digital_read(self, pin_expr: str) -> str:
        return f'digitalRead({pin_expr})'

    def pin_direction(self, direction: str) -> str:
        return {
            'output': 'OUTPUT',
            'input':  'INPUT_PULLUP',
            'analog': 'INPUT',
            'i2c':    'INPUT',
            'pwm':    'OUTPUT',
        }.get(direction, 'OUTPUT')

    # ── interrupts ─────────────────────────────────────────────────

    def attach_interrupt(self, pin_expr: str, isr_name: str, mode: str) -> str:
        return (
            f'attachInterrupt('
            f'digitalPinToInterrupt({pin_expr}), {isr_name}, {mode});'
        )

    # ── Serial ─────────────────────────────────────────────────────

    def serial_begin(self, baud: int) -> str:
        return f'Serial.begin({baud}UL);'

    def serial_print(self, expr: str) -> str:
        return f'Serial.print({expr});'

    def serial_println(self, expr: str) -> str:
        return f'Serial.println({expr});'

    # ── PWM (LEDC) ─────────────────────────────────────────────────

    def pwm_setup(self, channel: int, freq: int, resolution: int) -> List[str]:
        return [
            f'ledcSetup({channel}U, {freq}UL, {resolution});',
        ]

    def pwm_attach(self, pin: int, channel: int) -> str:
        return f'ledcAttachPin({pin}U, {channel}U);'

    def pwm_write(self, channel: int, duty_expr: str) -> str:
        return f'ledcWrite({channel}U, (uint32_t)({duty_expr}));'

    # ── I2C (Wire) ─────────────────────────────────────────────────

    def i2c_begin(self, sda: int, scl: int, speed_hz: int = 100000) -> List[str]:
        lines = [
            f'Wire.begin({sda}, {scl});',
        ]
        if speed_hz != 100000:
            lines.append(f'Wire.setClock({speed_hz}UL);')
        return lines

    def i2c_begin_transmission(self, addr_expr: str) -> str:
        return f'Wire.beginTransmission({addr_expr});'

    def i2c_write_data(self, data_expr: str) -> str:
        return f'Wire.write({data_expr});'

    def i2c_end_transmission(self) -> str:
        return 'Wire.endTransmission();'

    def i2c_request_from(self, addr_expr: str, len_expr: str) -> str:
        return f'Wire.requestFrom({addr_expr}, {len_expr});'

    def i2c_read(self) -> str:
        return 'Wire.read()'

    def i2c_available(self) -> str:
        return 'Wire.available()'

    # ── SPI ────────────────────────────────────────────────────────

    def spi_begin(self, mosi: int, miso: int, sck: int) -> List[str]:
        # CS = -1 (not using hardware CS)
        return [f'SPI.begin({mosi}, {miso}, {sck}, -1);']

    def spi_transfer(self, data_expr: str) -> str:
        return f'SPI.transfer({data_expr})'

    # ── UART ───────────────────────────────────────────────────────

    def uart_begin(self, uart_num: int, baud: int) -> str:
        if uart_num == 0:
            return f'Serial.begin({baud});'
        return f'Serial{uart_num}.begin({baud}UL);'

    def uart_print(self, uart_num: int, expr: str) -> str:
        if uart_num == 0:
            return f'Serial.print({expr});'
        return f'Serial{uart_num}.print({expr});'

    def uart_read(self, uart_num: int) -> str:
        if uart_num == 0:
            return 'Serial.read()'
        return f'Serial{uart_num}.read()'

    def uart_available(self, uart_num: int) -> str:
        if uart_num == 0:
            return 'Serial.available()'
        return f'Serial{uart_num}.available()'

    # ── ISR ────────────────────────────────────────────────────────

    def isr_attribute(self) -> str:
        return 'IRAM_ATTR '

    # ── Power Management ─────────────────────────────────────────

    def deep_sleep(self, duration_us_expr: str) -> str:
        if duration_us_expr == '0':
            return 'esp_deep_sleep_start();'
        return f'esp_sleep_enable_timer_wakeup((uint64_t)({duration_us_expr}));\n  esp_deep_sleep_start();'

    def light_sleep(self, duration_us_expr: str) -> str:
        return f'esp_sleep_enable_timer_wakeup((uint64_t)({duration_us_expr}));\n  esp_light_sleep_start();'

    def set_wakeup_pin(self, pin_expr: str, level: str) -> str:
        level_val = 'HIGH' if level in ('HIGH', '1', 'true') else 'LOW'
        return (
            f'esp_sleep_enable_ext0_wakeup((gpio_num_t){pin_expr}, '
            f'{level_val} == HIGH ? 1 : 0);'
        )

    def set_wakeup_timer(self, duration_us_expr: str) -> str:
        return f'esp_sleep_enable_timer_wakeup((uint64_t)({duration_us_expr}));'

    def get_wakeup_cause(self) -> str:
        return 'esp_sleep_get_wakeup_cause()'

    # ── Watchdog ───────────────────────────────────────────────────

    def watchdog_enable(self, timeout_ms: int) -> str:
        return (
            f'esp_task_wdt_init({timeout_ms}, true);\n'
            f'  esp_task_wdt_add(NULL);'
        )

    def watchdog_reset(self) -> str:
        return 'esp_task_wdt_reset();'

    # ── Filesystem (LittleFS) ──────────────────────────────────────

    def filesystem_mount(self, fs_type: str, mount_point: str = '/fs') -> str:
        if fs_type == 'littlefs':
            return (
                f'if (!LittleFS.begin(true)) {{\n'
                f'    Serial.println("LittleFS mount failed");\n'
                f'  }}'
            )
        elif fs_type == 'fat':
            return (
                f'if (!FFat.begin(true)) {{\n'
                f'    Serial.println("FFat mount failed");\n'
                f'  }}'
            )
        return f'/* mount {fs_type} — not supported */'

    def filesystem_open(self, path_expr: str, mode: str) -> str:
        mode_map = {'r': 'FILE_READ', 'w': 'FILE_WRITE', 'a': 'FILE_APPEND', 'r+': 'FILE_READ'}
        c_mode = mode_map.get(mode, 'FILE_READ')
        return f'LittleFS.open({path_expr}, "{mode}")'

    def filesystem_read(self, file_expr: str, buf_expr: str, size_expr: str) -> str:
        return f'(int)({file_expr}.read((uint8_t*)({buf_expr}), (size_t)({size_expr})))'

    def filesystem_write(self, file_expr: str, buf_expr: str, size_expr: str) -> str:
        return f'(int)({file_expr}.write((const uint8_t*)({buf_expr}), (size_t)({size_expr})))'

    def filesystem_close(self, file_expr: str) -> str:
        return f'{file_expr}.close()'

    def filesystem_exists(self, path_expr: str) -> str:
        return f'LittleFS.exists({path_expr})'

    def filesystem_list_dir(self, path_expr: str) -> str:
        return (
            f'File _dir = LittleFS.open({path_expr});\n'
            f'  if (_dir && _dir.isDirectory()) {{\n'
            f'    File _entry = _dir.openNextFile();\n'
            f'    while (_entry) {{\n'
            f'      Serial.println(_entry.name());\n'
            f'      _entry = _dir.openNextFile();\n'
            f'    }}\n'
            f'  }}'
        )

    # ── Flash / EEPROM (Preferences/NVS) ──────────────────────────

    def flash_read_bytes(self, addr_expr: str, buf_expr: str, size_expr: str) -> str:
        return (
            f'preferences.getBytes((const char*)({addr_expr}), '
            f'(void*)({buf_expr}), (size_t)({size_expr}))'
        )

    def flash_write_bytes(self, addr_expr: str, buf_expr: str, size_expr: str) -> str:
        return (
            f'preferences.putBytes((const char*)({addr_expr}), '
            f'(const void*)({buf_expr}), (size_t)({size_expr}))'
        )

    def flash_erase_sector(self, addr_expr: str) -> str:
        return f'preferences.remove((const char*)({addr_expr}))'

    def flash_get_size(self) -> str:
        return 'preferences.freeEntries()'

    # ── WiFi (Milestone 8 — First-Class WiFi) ────────────────────

    def wifi_supported(self) -> bool:
        return True

    def wifi_max_sta_interfaces(self) -> int:
        return 1

    def wifi_max_ap_interfaces(self) -> int:
        return 1

    def wifi_get_includes(self) -> List[str]:
        return ['#include <WiFi.h>']

    def wifi_generate_init(self, decls) -> 'HALBase.WifiInitOutput':
        """Generate all WiFi initialization code for ESP32 Arduino."""
        from .base import HALBase
        out = HALBase.WifiInitOutput()

        if not decls:
            return out

        out.includes = ['#include <WiFi.h>']

        # Shared guards
        out.nvs_init = (
            'static bool _iotift_wifi_initialized = false;\n'
            'if (!_iotift_wifi_initialized) {\n'
            '  WiFi.mode(WIFI_MODE_NULL);\n'
            '  _iotift_wifi_initialized = true;\n'
            '}'
        )

        has_sta = any(d.mode == 'sta' for d in decls)
        has_ap = any(d.mode == 'ap' for d in decls)

        if has_sta and has_ap:
            mode_line = 'WiFi.mode(WIFI_AP_STA);'
        elif has_ap:
            mode_line = 'WiFi.mode(WIFI_AP);'
        else:
            mode_line = 'WiFi.mode(WIFI_STA);'

        for d in decls:
            c_name = d.c_name or f'_iotift_wifi_{d.name}'

            # State variables
            out.state_decls.append(f'static int {c_name}_state = 0; /* WIFI_STATE_IDLE */')
            out.state_decls.append(f'static bool {c_name}_connected = false;')
            out.state_decls.append(f'static char {c_name}_ip[16] = {{0}};')
            out.state_decls.append(f'static int {c_name}_rssi = 0;')
            out.state_decls.append(f'static char {c_name}_mac[18] = {{0}};')
            out.state_decls.append(f'static int {c_name}_channel = 0;')
            if d.mode == 'ap':
                out.state_decls.append(f'static int {c_name}_client_count = 0;')
            # Event pending flags
            for ev in ['connect', 'disconnect', 'got_ip', 'scan_done',
                        'client_join', 'client_leave']:
                out.state_decls.append(
                    f'static bool {c_name}_event_{ev} = false;'
                )
            # Retry state
            rp = d.retry_policy or HALBase.RetryPolicy()
            out.state_decls.append(f'static int {c_name}_retry_count = 0;')
            out.state_decls.append(f'static unsigned long {c_name}_last_retry_ms = 0;')

            # Setup code
            if d.mode == 'sta':
                pw = d.password if d.password else ''
                out.setup_code.append(
                    f'WiFi.begin("{d.ssid}", "{pw}");'
                )
                if d.hostname:
                    out.setup_code.append(f'WiFi.setHostname("{d.hostname}");')
                if d.static_ip and d.gateway and d.subnet:
                    dns_str = d.dns if d.dns else d.gateway
                    out.setup_code.append(
                        f'WiFi.config(IPAddress({d.static_ip.replace(".", ",")}), '
                        f'IPAddress({d.gateway.replace(".", ",")}), '
                        f'IPAddress({d.subnet.replace(".", ",")}), '
                        f'IPAddress({dns_str.replace(".", ",")}));'
                    )
            elif d.mode == 'ap':
                pw = d.password if d.password else ''
                pw_arg = f'"{pw}"' if pw else 'NULL'
                out.setup_code.append(
                    f'WiFi.softAP("{d.ssid}", {pw_arg}, {d.channel}, '
                    f'{1 if d.hidden else 0}, {d.max_clients});'
                )

            # Loop dispatch
            out.loop_code.append(
                f'_iotift_wifi_{d.name}_dispatch();'
            )

        # Set mode once
        out.setup_code.insert(0, mode_line)

        # Scan buffer (shared)
        out.scan_buffer_decl = (
            'static char _iotift_wifi_scan_ssids[16][33];\n'
            'static int _iotift_wifi_scan_rssis[16];\n'
            'static int _iotift_wifi_scan_channels[16];\n'
            'static int _iotift_wifi_scan_count = 0;'
        )

        return out

    def wifi_generate_event_registration(self, wifi_name: str, c_prefix: str,
                                         event: str) -> str:
        return f'/* WiFi event {event} for {wifi_name} — dispatch via _iotift_wifi_{wifi_name}_dispatch() */'

    def wifi_generate_state_update(self, wifi_name: str, c_prefix: str,
                                    event: str) -> str:
        """Generate state update code for the ESP32 Arduino event callback."""
        name = wifi_name
        if event == 'connect':
            return (
                f'_iotift_wifi_{name}_state = 2; /* CONNECTED */\n'
                f'  _iotift_wifi_{name}_connected = true;\n'
                f'  strcpy(_iotift_wifi_{name}_ip, WiFi.localIP().toString().c_str());\n'
                f'  _iotift_wifi_{name}_rssi = WiFi.RSSI();\n'
                f'  _iotift_wifi_{name}_event_got_ip = true;\n'
                f'  _iotift_wifi_{name}_event_connect = true;'
            )
        elif event == 'disconnect':
            return (
                f'_iotift_wifi_{name}_state = 3; /* DISCONNECTED */\n'
                f'  _iotift_wifi_{name}_connected = false;\n'
                f'  _iotift_wifi_{name}_event_disconnect = true;'
            )
        elif event == 'scan_done':
            return (
                f'_iotift_wifi_{name}_event_scan_done = true;'
            )
        return f'/* state update {event} for {wifi_name} */'

    def wifi_generate_disconnect(self, name: str, c_prefix: str) -> str:
        return (
            f'WiFi.disconnect(true);\n'
            f'  _iotift_wifi_{name}_state = 3; /* DISCONNECTED */\n'
            f'  _iotift_wifi_{name}_connected = false;'
        )

    def wifi_generate_scan_start(self, name: str, c_prefix: str) -> str:
        return f'WiFi.scanNetworks(true); /* async scan */'

    def wifi_generate_property_read(self, name: str, c_prefix: str,
                                     prop: str) -> str:
        """Generate C expression to read a WiFi property."""
        _MAP = {
            'state':     f'_iotift_wifi_{name}_state',
            'connected': f'_iotift_wifi_{name}_connected',
            'ip':        f'_iotift_wifi_{name}_ip',
            'rssi':      f'_iotift_wifi_{name}_rssi',
            'channel':   f'_iotift_wifi_{name}_channel',
            'mac':       f'_iotift_wifi_{name}_mac',
            'clients':   f'_iotift_wifi_{name}_client_count',
            'ssid':      f'"{name}"',
        }
        return _MAP.get(prop, f'_iotift_wifi_{name}_{prop}')

    # ── Legacy WiFi methods (backward compat) ────────────────────

    def wifi_begin(self, ssid_expr: str, password_expr: str) -> str:
        return (
            f'WiFi.begin({ssid_expr}, {password_expr});\n'
            f'  while (WiFi.status() != WL_CONNECTED) {{\n'
            f'    delay(500);\n'
            f'    Serial.print(".");\n'
            f'  }}'
        )

    def wifi_status(self) -> str:
        return '(WiFi.status() == WL_CONNECTED ? 1 : 0)'

    def wifi_local_ip(self) -> str:
        return 'WiFi.localIP().toString().c_str()'

    def wifi_disconnect(self) -> str:
        return 'WiFi.disconnect(true);'

    # ── BLE ─────────────────────────────────────────────────────────

    def ble_begin(self, device_name_expr: str) -> str:
        return (
            f'BLEDevice::init({device_name_expr});\n'
            f'  BLEServer *_ble_server = BLEDevice::createServer();'
        )

    def ble_start_advertising(self) -> str:
        return (
            f'BLEAdvertising *_ble_adv = _ble_server->getAdvertising();\n'
            f'  _ble_adv->start();'
        )

    def ble_stop_advertising(self) -> str:
        return (
            f'BLEAdvertising *_ble_adv = _ble_server->getAdvertising();\n'
            f'  _ble_adv->stop();'
        )

    def ble_set_value(self, characteristic_expr: str, value_expr: str) -> str:
        return f'{characteristic_expr}->setValue((const char*)({value_expr}));\n  {characteristic_expr}->notify();'

    def ble_get_value(self, characteristic_expr: str) -> str:
        return f'{characteristic_expr}->getValue().c_str()'

    # ── OTA Updates ─────────────────────────────────────────────────

    def ota_begin(self, size_expr: str) -> str:
        return (
            f'if (!Update.begin((size_t)({size_expr}))) {{\n'
            f'    Serial.println("OTA begin failed");\n'
            f'  }}'
        )

    def ota_write(self, buf_expr: str, size_expr: str) -> str:
        return f'Update.write((const uint8_t*)({buf_expr}), (size_t)({size_expr}))'

    def ota_end(self) -> str:
        return (
            f'if (Update.end()) {{\n'
            f'    Serial.println("OTA complete — rebooting");\n'
            f'    ESP.restart();\n'
            f'  }}'
        )

    def ota_rollback(self) -> str:
        return 'Update.rollBack(); ESP.restart();'

    # ── Secure Boot ─────────────────────────────────────────────────

    def secure_boot_check(self) -> str:
        # ESP32 secure boot v2 status
        return '(REG_READ(EFUSE_BLK0_RDATA5_REG) & (1 << 7)) != 0'

    # ── Debug ──────────────────────────────────────────────────────

    def breakpoint_instruction(self) -> str:
        # Xtensa break instruction
        return 'asm("break 0,0")'

    # ── misc ───────────────────────────────────────────────────────

    def yield_func(self) -> str:
        return 'yield()'

    def restart_func(self) -> str:
        return 'ESP.restart()'
