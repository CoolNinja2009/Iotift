"""
AVR Arduino HAL — ATmega328P/ATmega2560 via standard Arduino AVR core.

Supports Arduino Uno, Nano, Mega 2560, and other classic AVR boards.
This is the most constrained target — 2 KB RAM, 32 KB flash on Uno.

Key differences from ARM targets:
- 8-bit architecture: `int` is 16-bit (use fixed-width types explicitly).
- No `INPUT_PULLUP` in older cores — uses `INPUT` + `digitalWrite(HIGH)`.
- Interrupts only on specific pins (INT0/INT1 on Uno, more on Mega).
- No hardware floating-point.
- PWM: 8-bit on most timers, 16-bit on Timer1.
"""

from __future__ import annotations
from typing import List
from .base import HALBase


class AVRArduinoHAL(HALBase):
    """HAL for AVR microcontrollers running the standard Arduino AVR core."""

    @property
    def target_name(self) -> str:
        return 'AVR (Arduino)'

    @property
    def framework(self) -> str:
        return 'arduino'

    # ── includes ─────────────────────────────────────────────────

    def get_includes(self) -> List[str]:
        return ['#include <Arduino.h>']

    # ── config ──────────────────────────────────────────────────

    def get_config_defines(self, baud_rate: int, scheduler_slots: int) -> List[str]:
        lines = super().get_config_defines(baud_rate, scheduler_slots)
        # AVR-friendly scheduler slot limit (ATmega328P has only 2 KB SRAM)
        lines += [
            '',
            '/* AVR-specific: minimal scheduler footprint */',
            f'#if IOTIFT_SCHEDULER_SLOTS > 8',
            f'#warning "Scheduler slots reduced from {scheduler_slots} to 8 for AVR"',
            f'#undef IOTIFT_SCHEDULER_SLOTS',
            f'#define IOTIFT_SCHEDULER_SLOTS 8U',
            f'#endif',
        ]
        return lines

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
        # AVR: only pins 2/3 on Uno support attachInterrupt().
        # On Mega, more pins are available (2, 3, 18-21).
        return (
            f'attachInterrupt('
            f'digitalPinToInterrupt({pin_expr}), {isr_name}, {mode});'
        )

    def interrupt_mode(self, event: str) -> str:
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

    def serial_begin(self, baud: int) -> str:
        return f'Serial.begin({baud}UL);'

    def serial_print(self, expr: str) -> str:
        return f'Serial.print({expr});'

    def serial_println(self, expr: str) -> str:
        return f'Serial.println({expr});'

    # ── PWM (hardware timer PWM) ────────────────────────────────

    def pwm_setup(self, channel: int, freq: int, resolution: int) -> List[str]:
        # AVR has hardware PWM on pins 3, 5, 6, 9, 10, 11 (Uno).
        # Default frequency is ~490 Hz (pins 5,6) or ~980 Hz (pins 3,9,10,11).
        # Resolution is 8-bit (0-255) by default.
        lines = [f'// AVR PWM: pin {channel}, {freq}Hz, {resolution}-bit']
        # On Timer1 (pins 9,10), we can set frequency via ICR1:
        if freq != 490 and freq != 980:
            lines.append(
                f'// Note: custom PWM frequency requires manual timer config on AVR'
            )
        return lines

    def pwm_attach(self, pin: int, channel: int) -> str:
        return f'pinMode({pin}U, OUTPUT);  // PWM ready on pin {pin}'

    def pwm_write(self, channel: int, duty_expr: str) -> str:
        # AVR uses analogWrite() — 0..255.
        return f'analogWrite({channel}U, (uint8_t)({duty_expr}));'

    # ── I2C (Wire) ─────────────────────────────────────────────────

    def i2c_begin(self, sda: int, scl: int, speed_hz: int = 100000) -> List[str]:
        # AVR: SDA = A4, SCL = A5 on Uno (fixed, no custom pins).
        lines = [f'Wire.begin();']
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
        # AVR: MOSI=11, MISO=12, SCK=13 on Uno (fixed).
        return [f'SPI.begin();']

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

    # ── ADC ──────────────────────────────────────────────────────

    def analog_read(self, pin_expr: str) -> str:
        return f'analogRead({pin_expr})'

    def analog_set_resolution(self, bits: int) -> str:
        # AVR ADC is 10-bit fixed.
        return f'// AVR ADC is fixed at 10-bit resolution'

    # ── ISR ──────────────────────────────────────────────────────

    def isr_attribute(self) -> str:
        # AVR uses ISR() macro vector names; function attribute not needed.
        return ''

    # ── Debug ──────────────────────────────────────────────────────

    def breakpoint_instruction(self) -> str:
        # AVR break instruction (works with debugWIRE)
        return 'asm volatile("break")'

    # ── misc ─────────────────────────────────────────────────────

    def yield_func(self) -> str:
        return 'yield()'

    def restart_func(self) -> str:
        # AVR watchdog reset.
        return (
            'wdt_enable(WDTO_15MS); while(1) {}'
        )
