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

    # ── misc ───────────────────────────────────────────────────────

    def yield_func(self) -> str:
        return 'yield()'

    def restart_func(self) -> str:
        return 'ESP.restart()'
