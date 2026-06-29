"""
HALBase — Abstract interface for Iotift target backends.

Every Iotift target (ESP32 Arduino, STM32, RP2040, …) implements this
interface.  The code generator calls these methods instead of hardcoding
C strings, making the compiler multi-target by construction.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Optional


class HALBase(ABC):
    """Abstract base class for Iotift HAL implementations."""

    # ── metadata ──────────────────────────────────────────────

    @property
    @abstractmethod
    def target_name(self) -> str:
        """Human-readable target name, e.g. 'ESP32 (Arduino)'."""
        ...

    @property
    @abstractmethod
    def framework(self) -> str:
        """Framework identifier, e.g. 'arduino', 'espidf', 'pico-sdk'."""
        ...

    # ── includes & configuration ────────────────────────────────

    @abstractmethod
    def get_includes(self) -> List[str]:
        """Return the #include <…> lines needed by this HAL."""
        ...

    def get_config_defines(self, baud_rate: int, scheduler_slots: int) -> List[str]:
        """Return #define / configuration lines for setup()."""
        return [
            f'#ifndef IOTIFT_BAUD_RATE',
            f'#define IOTIFT_BAUD_RATE          {baud_rate}UL',
            f'#endif',
            '',
            f'#ifndef IOTIFT_SCHEDULER_SLOTS',
            f'#define IOTIFT_SCHEDULER_SLOTS    {scheduler_slots}U',
            f'#endif',
        ]

    # ── GPIO ────────────────────────────────────────────────────

    @abstractmethod
    def get_pin_macro(self, name: str, number: int) -> str:
        """Return the C declaration for a pin constant (e.g. static const uint8_t)."""
        ...

    @abstractmethod
    def pin_mode(self, pin_expr: str, direction: str) -> str:
        """Return a C statement that configures pin mode."""
        ...

    @abstractmethod
    def digital_write(self, pin_expr: str, value: str) -> str:
        """Return a C expression/statement for digitalWrite()."""
        ...

    @abstractmethod
    def digital_read(self, pin_expr: str) -> str:
        """Return a C expression for digitalRead()."""
        ...

    @abstractmethod
    def pin_direction(self, direction: str) -> str:
        """Map Iotift pin direction ('output','input','analog',…) to a C constant."""
        ...

    # ── interrupts ───────────────────────────────────────────────

    @abstractmethod
    def attach_interrupt(self, pin_expr: str, isr_name: str, mode: str) -> str:
        """Return a C statement for attachInterrupt()."""
        ...

    def interrupt_mode(self, event: str) -> str:
        """Map Iotift event name to Arduino interrupt mode."""
        return {
            'press':   'FALLING',
            'release': 'RISING',
            'rising':  'RISING',
            'falling': 'FALLING',
            'change':  'CHANGE',
        }.get(event, 'CHANGE')

    # ── timer / time ────────────────────────────────────────────

    def millis_func(self) -> str:
        return 'millis()'

    def micros_func(self) -> str:
        return 'micros()'

    def delay_func(self, ms_expr: str) -> str:
        return f'delay({ms_expr})'

    def delay_us_func(self, us_expr: str) -> str:
        return f'delayMicroseconds({us_expr})'

    # ── Serial ──────────────────────────────────────────────────

    @abstractmethod
    def serial_begin(self, baud: int) -> str:
        """Return a C statement that initialises the default serial port."""
        ...

    @abstractmethod
    def serial_print(self, expr: str) -> str:
        ...

    @abstractmethod
    def serial_println(self, expr: str) -> str:
        ...

    # ── PWM ──────────────────────────────────────────────────────

    @abstractmethod
    def pwm_setup(self, channel: int, freq: int, resolution: int) -> List[str]:
        ...

    @abstractmethod
    def pwm_attach(self, pin: int, channel: int) -> str:
        ...

    @abstractmethod
    def pwm_write(self, channel: int, duty_expr: str) -> str:
        ...

    # ── I2C / SPI / UART  (optional — implemented by concrete HALs) ──

    def i2c_begin(self, sda: int, scl: int, speed_hz: int) -> List[str]:
        return []

    def i2c_begin_transmission(self, addr_expr: str) -> str:
        raise NotImplementedError(f"I2C not implemented for {self.target_name}")

    def i2c_write_data(self, data_expr: str) -> str:
        raise NotImplementedError(f"I2C not implemented for {self.target_name}")

    def i2c_end_transmission(self) -> str:
        raise NotImplementedError(f"I2C not implemented for {self.target_name}")

    def i2c_request_from(self, addr_expr: str, len_expr: str) -> str:
        raise NotImplementedError(f"I2C not implemented for {self.target_name}")

    def i2c_read(self) -> str:
        raise NotImplementedError(f"I2C not implemented for {self.target_name}")

    def i2c_available(self) -> str:
        raise NotImplementedError(f"I2C not implemented for {self.target_name}")

    def spi_begin(self, mosi: int, miso: int, sck: int) -> List[str]:
        return []

    def spi_transfer(self, data_expr: str) -> str:
        raise NotImplementedError(f"SPI not implemented for {self.target_name}")

    def uart_begin(self, uart_num: int, baud: int) -> str:
        raise NotImplementedError(f"UART not implemented for {self.target_name}")

    def uart_print(self, uart_num: int, expr: str) -> str:
        raise NotImplementedError(f"UART not implemented for {self.target_name}")

    def uart_read(self, uart_num: int) -> str:
        raise NotImplementedError(f"UART not implemented for {self.target_name}")

    def uart_available(self, uart_num: int) -> str:
        raise NotImplementedError(f"UART not implemented for {self.target_name}")

    # ── ADC ──────────────────────────────────────────────────────

    def analog_read(self, pin_expr: str) -> str:
        return f'analogRead({pin_expr})'

    def analog_set_resolution(self, bits: int) -> str:
        return f'analogReadResolution({bits});'

    # ── ISR ──────────────────────────────────────────────────────

    @abstractmethod
    def isr_attribute(self) -> str:
        """Return the C attribute for ISR functions (e.g. 'IRAM_ATTR ')."""
        ...

    # ── Power Management ─────────────────────────────────────────

    def deep_sleep(self, duration_us_expr: str) -> str:
        """Enter deep sleep for *duration_us_expr* microseconds (0 = forever)."""
        return f'/* deep_sleep({duration_us_expr}) — not implemented for {self.target_name} */'

    def light_sleep(self, duration_us_expr: str) -> str:
        """Enter light sleep for *duration_us_expr* microseconds."""
        return f'/* light_sleep({duration_us_expr}) — not implemented for {self.target_name} */'

    def set_wakeup_pin(self, pin_expr: str, level: str) -> str:
        """Configure a pin as a wake source (level: 'HIGH' or 'LOW')."""
        return f'/* wakeup pin {pin_expr} — not implemented for {self.target_name} */'

    def set_wakeup_timer(self, duration_us_expr: str) -> str:
        """Configure a timer wake-up after *duration_us_expr* microseconds."""
        return f'/* wakeup timer {duration_us_expr} — not implemented for {self.target_name} */'

    def get_wakeup_cause(self) -> str:
        """Return the wake-up cause as a C expression."""
        return '0  /* unknown wake cause */'

    # ── Watchdog ───────────────────────────────────────────────────

    def watchdog_enable(self, timeout_ms: int) -> str:
        """Enable the hardware watchdog with *timeout_ms* timeout."""
        return f'/* watchdog_enable({timeout_ms}) — not implemented for {self.target_name} */'

    def watchdog_reset(self) -> str:
        """Reset (feed) the watchdog timer."""
        return f'/* watchdog_reset() — not implemented for {self.target_name} */'

    # ── Filesystem ─────────────────────────────────────────────────

    def filesystem_mount(self, fs_type: str, mount_point: str = '/fs') -> str:
        """Mount a filesystem (e.g. 'littlefs', 'fat')."""
        return f'/* mount {fs_type} at {mount_point} — not implemented for {self.target_name} */'

    def filesystem_open(self, path_expr: str, mode: str) -> str:
        """Open a file. Mode: 'r', 'w', 'a', 'r+'. Returns FILE* expression."""
        return f'(NULL /* file open not implemented for {self.target_name} */)'

    def filesystem_read(self, file_expr: str, buf_expr: str, size_expr: str) -> str:
        """Read from a file into buffer."""
        return f'0 /* read not implemented */'

    def filesystem_write(self, file_expr: str, buf_expr: str, size_expr: str) -> str:
        """Write buffer to a file."""
        return f'0 /* write not implemented */'

    def filesystem_close(self, file_expr: str) -> str:
        """Close a file."""
        return f'/* close not implemented */'

    def filesystem_exists(self, path_expr: str) -> str:
        """Check if a path exists. Returns bool C expression."""
        return f'false /* exists not implemented */'

    def filesystem_list_dir(self, path_expr: str) -> str:
        """List directory contents."""
        return f'/* list_dir({path_expr}) — not implemented */'

    # ── Flash / EEPROM Storage ──────────────────────────────────────

    def flash_read_bytes(self, addr_expr: str, buf_expr: str, size_expr: str) -> str:
        """Read bytes from flash/EEPROM at *addr_expr*."""
        return f'/* flash_read({addr_expr}) — not implemented for {self.target_name} */'

    def flash_write_bytes(self, addr_expr: str, buf_expr: str, size_expr: str) -> str:
        """Write bytes to flash/EEPROM at *addr_expr*."""
        return f'/* flash_write({addr_expr}) — not implemented for {self.target_name} */'

    def flash_erase_sector(self, addr_expr: str) -> str:
        """Erase a flash sector containing *addr_expr*."""
        return f'/* flash_erase({addr_expr}) — not implemented for {self.target_name} */'

    def flash_get_size(self) -> str:
        """Return total flash/EEPROM size in bytes as a C expression."""
        return '0 /* flash size unknown */'

    # ── WiFi ────────────────────────────────────────────────────────

    def wifi_begin(self, ssid_expr: str, password_expr: str) -> str:
        """Connect to a WiFi network."""
        return f'/* wifi_begin({ssid_expr}, ***) — not implemented for {self.target_name} */'

    def wifi_status(self) -> str:
        """Return WiFi connection status as a C expression (0 = disconnected, 1 = connected)."""
        return '0 /* wifi status not implemented */'

    def wifi_local_ip(self) -> str:
        """Return local IP address as a C string expression."""
        return '"0.0.0.0" /* wifi ip not implemented */'

    def wifi_disconnect(self) -> str:
        """Disconnect from WiFi."""
        return f'/* wifi_disconnect() — not implemented for {self.target_name} */'

    # ── BLE ─────────────────────────────────────────────────────────

    def ble_begin(self, device_name_expr: str) -> str:
        """Initialize BLE with *device_name_expr*."""
        return f'/* ble_begin({device_name_expr}) — not implemented for {self.target_name} */'

    def ble_start_advertising(self) -> str:
        """Start BLE advertising."""
        return f'/* ble_advertise() — not implemented for {self.target_name} */'

    def ble_stop_advertising(self) -> str:
        """Stop BLE advertising."""
        return f'/* ble_stop_advertise() — not implemented for {self.target_name} */'

    def ble_set_value(self, characteristic_expr: str, value_expr: str) -> str:
        """Set a BLE characteristic value."""
        return f'/* ble_set_value({characteristic_expr}) — not implemented */'

    def ble_get_value(self, characteristic_expr: str) -> str:
        """Get a BLE characteristic value as a C expression."""
        return '0 /* ble_get_value not implemented */'

    # ── OTA Updates ─────────────────────────────────────────────────

    def ota_begin(self, size_expr: str) -> str:
        """Begin an OTA update of *size_expr* bytes."""
        return f'/* ota_begin({size_expr}) — not implemented for {self.target_name} */'

    def ota_write(self, buf_expr: str, size_expr: str) -> str:
        """Write a chunk to the OTA partition."""
        return f'/* ota_write({size_expr}) — not implemented for {self.target_name} */'

    def ota_end(self) -> str:
        """Finalize the OTA update."""
        return f'/* ota_end() — not implemented for {self.target_name} */'

    def ota_rollback(self) -> str:
        """Roll back to the previous firmware."""
        return f'/* ota_rollback() — not implemented for {self.target_name} */'

    # ── Secure Boot ─────────────────────────────────────────────────

    def secure_boot_check(self) -> str:
        """Return a C expression that is true if secure boot is enabled."""
        return 'false /* secure boot check not implemented */'

    # ── Debug ──────────────────────────────────────────────────────

    def breakpoint_instruction(self) -> str:
        """Return a C breakpoint/trap instruction for the target.

        ARM Cortex-M: __asm__("bkpt #0")
        ESP32 (Xtensa): __asm__("break 0,0")
        AVR: __asm__("break")
        x86: __asm__("int3")
        """
        return '/* breakpoint — not implemented for this target */'

    # ── misc ─────────────────────────────────────────────────────

    def yield_func(self) -> str:
        return 'yield()'

    def restart_func(self) -> str:
        return 'ESP.restart()'
