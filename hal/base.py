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

    # ── misc ─────────────────────────────────────────────────────

    def yield_func(self) -> str:
        return 'yield()'

    def restart_func(self) -> str:
        return 'ESP.restart()'
