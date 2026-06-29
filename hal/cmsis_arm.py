"""
CMSIS ARM Cortex-M HAL — bare-metal backend for ARM Cortex-M0/M3/M4/M7.

Implements HALBase using the Cortex Microcontroller Software Interface
Standard (CMSIS) directly, without any Arduino or vendor HAL dependency.

This backend generates code for:
- STM32 (all families via CMSIS-Core device headers)
- RP2040 (Cortex-M0+)
- nRF52 (Cortex-M4)
- Any other ARM Cortex-M MCU with CMSIS headers

Key characteristics:
- No heap allocation (all static)
- SysTick timer for millis/micros
- Direct register access for GPIO
- CMSIS-RTOS2 or bare-metal super-loop
- Vendor-specific pin multiplexing via CMSIS device headers

Note: This is a template HAL — the actual pin numbers and peripheral
bases are vendor-specific. The user must provide a CMSIS device header
(SVD → header) for their specific MCU.
"""

from __future__ import annotations
from typing import List
from .base import HALBase


class CMSISHAL(HALBase):
    """HAL for ARM Cortex-M microcontrollers using CMSIS directly."""

    def __init__(self, mcu_family: str = 'stm32f103'):
        super().__init__()
        self._mcu_family = mcu_family

    @property
    def target_name(self) -> str:
        return f'ARM Cortex-M ({self._mcu_family}) via CMSIS'

    @property
    def framework(self) -> str:
        return 'cmsis'

    # ── includes ─────────────────────────────────────────────────

    def get_includes(self) -> List[str]:
        includes = [
            '#include <stdint.h>',
            '#include <stdbool.h>',
            '#include "cmsis_compiler.h"',
        ]
        # Vendor-specific device header
        if self._mcu_family.startswith('stm32'):
            includes.append(f'#include "stm32f1xx.h"')
        elif self._mcu_family.startswith('nrf52'):
            includes.append(f'#include "nrf.h"')
        elif self._mcu_family.startswith('rp2040'):
            includes.append(f'#include "rp2040.h"')
        return includes

    def get_config_defines(self, baud_rate: int, scheduler_slots: int) -> List[str]:
        return [
            f'#ifndef IOTIFT_BAUD_RATE',
            f'#define IOTIFT_BAUD_RATE          {baud_rate}UL',
            f'#endif',
            '',
            f'#ifndef IOTIFT_SCHEDULER_SLOTS',
            f'#define IOTIFT_SCHEDULER_SLOTS    {scheduler_slots}U',
            f'#endif',
            '',
            '/* CMSIS system clock (default: HSI 8 MHz → PLL 72 MHz on STM32F103) */',
            '#ifndef SYSTEM_CLOCK_HZ',
            '#define SYSTEM_CLOCK_HZ  72000000UL',
            '#endif',
            '',
            '/* SysTick reload value for 1 ms ticks */',
            '#define SYSTICK_RELOAD   ((SYSTEM_CLOCK_HZ / 1000UL) - 1UL)',
        ]

    # ── GPIO (template — vendor-specific register names) ────────

    def get_pin_macro(self, name: str, number: int) -> str:
        # CMSIS-style pin: port letter + pin number packed into a uint16_t.
        # Upper byte = port index (0=A, 1=B, ...), lower byte = pin (0-15).
        return f'static const uint16_t {name}_PIN = 0x{number:04X}U;'

    def pin_mode(self, pin_expr: str, direction: str) -> str:
        # Extract port and pin from packed value
        return (
            f'{{ uint8_t _port = ({pin_expr} >> 8) & 0xFF;\n'
            f'  uint8_t _pin  = {pin_expr} & 0xF;\n'
            f'  GPIO_TypeDef *gpio = (GPIO_TypeDef *)(GPIOA_BASE + (_port * 0x0400UL));\n'
            f'  gpio->CRL = (gpio->CRL & ~(0xFU << (_pin * 4))) | '
            f'(0x3U << (_pin * 4));  /* 50 MHz output */\n'
            f'  (void)gpio; }}'
        )

    def digital_write(self, pin_expr: str, value: str) -> str:
        level = '1' if value in ('HIGH', '1', 'true') else '0'
        return (
            f'{{ uint8_t _port = ({pin_expr} >> 8) & 0xFF;\n'
            f'  uint8_t _pin  = {pin_expr} & 0xF;\n'
            f'  GPIO_TypeDef *gpio = (GPIO_TypeDef *)(GPIOA_BASE + (_port * 0x0400UL));\n'
            f'  if ({level}) {{ gpio->BSRR = (1U << _pin); }} '
            f'else {{ gpio->BRR = (1U << _pin); }}\n'
            f'  (void)gpio; }}'
        )

    def digital_read(self, pin_expr: str) -> str:
        return (
            f'({{\n'
            f'  uint8_t _port = ({pin_expr} >> 8) & 0xFF;\n'
            f'  uint8_t _pin  = {pin_expr} & 0xF;\n'
            f'  GPIO_TypeDef *gpio = (GPIO_TypeDef *)(GPIOA_BASE + (_port * 0x0400UL));\n'
            f'  (gpio->IDR >> _pin) & 1U;\n'
            f'}})'
        )

    def pin_direction(self, direction: str) -> str:
        return {
            'output': 'OUTPUT',
            'input':  'INPUT',
            'analog': 'ANALOG',
            'i2c':    'AF_OD',
            'pwm':    'AF_PP',
        }.get(direction, 'OUTPUT')

    # ── interrupts (NVIC-based) ─────────────────────────────────

    def attach_interrupt(self, pin_expr: str, isr_name: str, mode: str) -> str:
        return (
            f'{{ /* EXTI config for pin */\n'
            f'  uint8_t _port = ({pin_expr} >> 8) & 0xFF;\n'
            f'  uint8_t _pin  = {pin_expr} & 0xF;\n'
            f'  /* Enable SYSCFG clock for EXTI */\n'
            f'  RCC->APB2ENR |= RCC_APB2ENR_SYSCFGEN;\n'
            f'  SYSCFG->EXTICR[_pin >> 2] = (SYSCFG->EXTICR[_pin >> 2] & '
            f'~(0xFU << ((_pin & 3) * 4))) | (_port << ((_pin & 3) * 4));\n'
            f'  EXTI->IMR |= (1U << _pin);\n'
            f'  EXTI->{mode} |= (1U << _pin);\n'
            f'  NVIC_EnableIRQ(EXTI0_IRQn + _pin); }}'
        )

    def interrupt_mode(self, event: str) -> str:
        return {
            'press':   'FTSR',
            'release': 'RTSR',
            'rising':  'RTSR',
            'falling': 'FTSR',
            'change':  'RTSR',
        }.get(event, 'RTSR')

    # ── timer / time (SysTick) ─────────────────────────────────

    def millis_func(self) -> str:
        return '_iotift_millis'

    def micros_func(self) -> str:
        return '_iotift_micros'

    def delay_func(self, ms_expr: str) -> str:
        return (
            f'for (uint32_t _d = 0; _d < (uint32_t)({ms_expr}); _d++) {{\n'
            f'    uint32_t _start = _iotift_millis;\n'
            f'    while ((_iotift_millis - _start) < 1) {{ __WFI(); }}\n'
            f'  }}'
        )

    def delay_us_func(self, us_expr: str) -> str:
        return (
            f'for (uint32_t _du = 0; _du < (uint32_t)({us_expr}); _du++) {{\n'
            f'    __NOP(); __NOP(); __NOP(); __NOP(); /* ~1 us at 72 MHz */\n'
            f'  }}'
        )

    # ── Serial (USART via CMSIS registers) ─────────────────────

    def serial_begin(self, baud: int) -> str:
        return (
            f'/* USART1 init at {baud} baud */\n'
            f'  RCC->APB2ENR |= RCC_APB2ENR_USART1EN | RCC_APB2ENR_IOPAEN;\n'
            f'  /* PA9 = TX (AF push-pull), PA10 = RX (input floating) */\n'
            f'  USART1->BRR = SYSTEM_CLOCK_HZ / {baud}UL;\n'
            f'  USART1->CR1 |= USART_CR1_TE | USART_CR1_RE | USART_CR1_UE;'
        )

    def serial_print(self, expr: str) -> str:
        return (
            f'{{ const char *_s = (const char*)&({expr});\n'
            f'  while (*_s) {{ while (!(USART1->SR & USART_SR_TXE)); '
            f'USART1->DR = *_s++; }} }}'
        )

    def serial_println(self, expr: str) -> str:
        return (
            f'{{ const char *_s = (const char*)&({expr});\n'
            f'  while (*_s) {{ while (!(USART1->SR & USART_SR_TXE)); '
            f'USART1->DR = *_s++; }}\n'
            f'  while (!(USART1->SR & USART_SR_TXE)); USART1->DR = \'\\r\';\n'
            f'  while (!(USART1->SR & USART_SR_TXE)); USART1->DR = \'\\n\'; }}'
        )

    # ── PWM (timer-based, vendor-specific template) ────────────

    def pwm_setup(self, channel: int, freq: int, resolution: int) -> List[str]:
        return [
            f'/* CMSIS PWM on TIM{channel + 2} — vendor-specific config */',
            f'RCC->APB1ENR |= RCC_APB1ENR_TIM{channel + 2}EN;',
            f'TIM{channel + 2}->PSC = (SYSTEM_CLOCK_HZ / '
            f'((1UL << {resolution}) * {freq}UL)) - 1UL;',
            f'TIM{channel + 2}->ARR = (1UL << {resolution}) - 1UL;',
            f'TIM{channel + 2}->CCR1 = 0;',
            f'TIM{channel + 2}->CCMR1 |= TIM_CCMR1_OC1M_1 | TIM_CCMR1_OC1M_2;',
            f'TIM{channel + 2}->CCER |= TIM_CCER_CC1E;',
            f'TIM{channel + 2}->CR1 |= TIM_CR1_CEN;',
        ]

    def pwm_attach(self, pin: int, channel: int) -> str:
        return f'/* PWM on pin {pin} — configure GPIO alternate function for TIM{channel + 2} */'

    def pwm_write(self, channel: int, duty_expr: str) -> str:
        return f'TIM{channel + 2}->CCR1 = (uint32_t)({duty_expr});'

    # ── I2C (CMSIS template) ───────────────────────────────────

    def i2c_begin(self, sda: int, scl: int, speed_hz: int = 100000) -> List[str]:
        return [f'/* I2C1 init at {speed_hz} Hz on SDA={sda}, SCL={scl} — CMSIS template */',
                f'RCC->APB1ENR |= RCC_APB1ENR_I2C1EN;']

    def i2c_begin_transmission(self, addr_expr: str) -> str:
        return (
            f'I2C1->CR1 |= I2C_CR1_START;\n'
            f'  while (!(I2C1->SR1 & I2C_SR1_SB));\n'
            f'  I2C1->DR = (uint8_t)(({addr_expr}) << 1);'
        )

    def i2c_write_data(self, data_expr: str) -> str:
        return (
            f'while (!(I2C1->SR1 & I2C_SR1_TXE));\n'
            f'  I2C1->DR = (uint8_t)({data_expr});'
        )

    def i2c_end_transmission(self) -> str:
        return (
            f'while (!(I2C1->SR1 & I2C_SR1_TXE));\n'
            f'  I2C1->CR1 |= I2C_CR1_STOP;'
        )

    def i2c_request_from(self, addr_expr: str, len_expr: str) -> str:
        return f'/* I2C read {len_expr} bytes from {addr_expr} */'

    def i2c_read(self) -> str:
        return 'I2C1->DR'

    def i2c_available(self) -> str:
        return '((I2C1->SR1 & I2C_SR1_RXNE) ? 1 : 0)'

    # ── SPI (CMSIS template) ───────────────────────────────────

    def spi_begin(self, mosi: int, miso: int, sck: int) -> List[str]:
        return [f'/* SPI1 init on MOSI={mosi}, MISO={miso}, SCK={sck} — CMSIS template */',
                f'RCC->APB2ENR |= RCC_APB2ENR_SPI1EN;']

    def spi_transfer(self, data_expr: str) -> str:
        return (
            f'while (!(SPI1->SR & SPI_SR_TXE));\n'
            f'  SPI1->DR = (uint8_t)({data_expr});\n'
            f'  while (!(SPI1->SR & SPI_SR_RXNE));\n'
            f'  (SPI1->DR)'
        )

    # ── UART ───────────────────────────────────────────────────

    def uart_begin(self, uart_num: int, baud: int) -> str:
        return f'/* UART{uart_num} init at {baud} — CMSIS template */'

    def uart_print(self, uart_num: int, expr: str) -> str:
        return f'/* USART{uart_num} print */'

    def uart_read(self, uart_num: int) -> str:
        return f'USART{uart_num}->DR'

    def uart_available(self, uart_num: int) -> str:
        return f'((USART{uart_num}->SR & USART_SR_RXNE) ? 1 : 0)'

    # ── ADC ────────────────────────────────────────────────────

    def analog_read(self, pin_expr: str) -> str:
        return f'/* ADC read on {pin_expr} — CMSIS template */ 0'

    def analog_set_resolution(self, bits: int) -> str:
        return f'/* ADC {bits}-bit resolution — CMSIS template */'

    # ── ISR ────────────────────────────────────────────────────

    def isr_attribute(self) -> str:
        # CMSIS ISRs use standard function names in the vector table.
        return ''

    # ── misc ───────────────────────────────────────────────────

    def yield_func(self) -> str:
        return '__WFI()'

    def restart_func(self) -> str:
        return 'NVIC_SystemReset()'
