"""
STM32 Arduino HAL — STM32F1/F4 families via Arduino_Core_STM32.

Supports STM32F103 (Blue Pill), STM32F407 (Discovery), and other
STM32 boards running the STM32duino Arduino core.
"""

from __future__ import annotations
from typing import List
from .base import HALBase


class STM32ArduinoHAL(HALBase):
    """HAL for STM32 microcontrollers running the Arduino_STM32 core."""

    @property
    def target_name(self) -> str:
        return 'STM32 (Arduino)'

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
            'analog': 'INPUT_ANALOG',
            'i2c':    'INPUT',
            'pwm':    'OUTPUT',
        }.get(direction, 'OUTPUT')

    # ── interrupts ─────────────────────────────────────────────────

    def attach_interrupt(self, pin_expr: str, isr_name: str, mode: str) -> str:
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

    # ── PWM (hardware timer based) ──────────────────────────────

    def pwm_setup(self, channel: int, freq: int, resolution: int) -> List[str]:
        # STM32 Arduino core uses analogWrite with PWM-capable pins.
        # Frequency is set via analogWriteFrequency() where available,
        # or defaults to the core's PWM frequency (~1 kHz on most boards).
        return [f'// PWM channel {channel}: freq={freq}Hz, res={resolution}-bit']

    def pwm_attach(self, pin: int, channel: int) -> str:
        return f'pinMode({pin}U, OUTPUT);  // PWM ready on pin {pin}'

    def pwm_write(self, channel: int, duty_expr: str) -> str:
        # STM32 uses analogWrite() for PWM — duty is 0..255 (8-bit default)
        return f'analogWrite({channel}U, (int)({duty_expr}));'

    # ── I2C (Wire) ─────────────────────────────────────────────────

    def i2c_begin(self, sda: int, scl: int, speed_hz: int = 100000) -> List[str]:
        lines = [f'Wire.setSDA({sda});',
                 f'Wire.setSCL({scl});',
                 f'Wire.begin();']
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
        return [f'SPI.setMOSI({mosi});',
                f'SPI.setMISO({miso});',
                f'SPI.setSCK({sck});',
                f'SPI.begin();']

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
        return f'analogReadResolution({bits});'

    # ── ISR ──────────────────────────────────────────────────────

    def isr_attribute(self) -> str:
        # STM32 does not require IRAM_ATTR; ISR runs from flash by default.
        return ''

    # ── Debug ──────────────────────────────────────────────────────

    def breakpoint_instruction(self) -> str:
        # ARM Cortex-M breakpoint
        return '__asm__("bkpt #0")'

    # ── misc ─────────────────────────────────────────────────────

    def yield_func(self) -> str:
        return 'yield()'

    def restart_func(self) -> str:
        return 'NVIC_SystemReset()'
