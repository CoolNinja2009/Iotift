"""
HAL unit tests — verify the HAL class hierarchy for ESP32 Arduino.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from hal import get_hal, register_hal, HALBase
from hal.esp32_arduino import ESP32ArduinoHAL


def test_get_hal_esp32():
    hal = get_hal('esp32')
    assert isinstance(hal, ESP32ArduinoHAL)
    assert hal.target_name == 'ESP32 (Arduino)'
    assert hal.framework == 'arduino'


def test_get_hal_unknown_raises():
    with pytest.raises(ValueError, match="Unknown target device"):
        get_hal('stm32')


def test_hal_includes():
    hal = get_hal('esp32')
    includes = hal.get_includes()
    assert '#include <Arduino.h>' in includes


def test_hal_pin_macro():
    hal = get_hal('esp32')
    macro = hal.get_pin_macro('LED', 2)
    assert 'LED_PIN' in macro
    assert '2U' in macro


def test_hal_pin_mode():
    hal = get_hal('esp32')
    assert 'OUTPUT' in hal.pin_mode('LED_PIN', 'OUTPUT')
    assert 'INPUT_PULLUP' in hal.pin_mode('BTN_PIN', 'INPUT_PULLUP')


def test_hal_digital_write():
    hal = get_hal('esp32')
    assert 'digitalWrite(LED_PIN, HIGH)' in hal.digital_write('LED_PIN', 'HIGH')


def test_hal_digital_read():
    hal = get_hal('esp32')
    assert 'digitalRead(BTN_PIN)' in hal.digital_read('BTN_PIN')


def test_hal_serial_begin():
    hal = get_hal('esp32')
    s = hal.serial_begin(115200)
    assert 'Serial.begin(115200UL)' in s


def test_hal_pwm():
    hal = get_hal('esp32')
    lines = hal.pwm_setup(0, 5000, 8)
    assert any('ledcSetup' in ln for ln in lines)


def test_hal_pwm_write():
    hal = get_hal('esp32')
    s = hal.pwm_write(0, '128')
    assert 'ledcWrite' in s


def test_hal_attach_interrupt():
    hal = get_hal('esp32')
    s = hal.attach_interrupt('BTN_PIN', 'my_isr', 'FALLING')
    assert 'attachInterrupt' in s
    assert 'digitalPinToInterrupt' in s
    assert 'my_isr' in s
    assert 'FALLING' in s


def test_hal_isr_attribute():
    hal = get_hal('esp32')
    assert 'IRAM_ATTR' in hal.isr_attribute()


def test_hal_interrupt_mode():
    hal = get_hal('esp32')
    assert hal.interrupt_mode('press') == 'FALLING'
    assert hal.interrupt_mode('release') == 'RISING'
    assert hal.interrupt_mode('change') == 'CHANGE'
    assert hal.interrupt_mode('rising') == 'RISING'
    assert hal.interrupt_mode('falling') == 'FALLING'


def test_hal_pin_direction():
    hal = get_hal('esp32')
    assert hal.pin_direction('output') == 'OUTPUT'
    assert hal.pin_direction('input') == 'INPUT_PULLUP'
    assert hal.pin_direction('analog') == 'INPUT'


def test_hal_i2c():
    hal = get_hal('esp32')
    lines = hal.i2c_begin(21, 22, 100000)
    assert any('Wire.begin' in ln for ln in lines)
    assert 'Wire.beginTransmission(0x3C)' in hal.i2c_begin_transmission('0x3C')


def test_hal_spi():
    hal = get_hal('esp32')
    lines = hal.spi_begin(23, 19, 18)
    assert any('SPI.begin' in ln for ln in lines)


def test_hal_uart():
    hal = get_hal('esp32')
    assert 'Serial2.begin(9600UL)' in hal.uart_begin(2, 9600)


def test_register_hal():
    class FakeHAL(HALBase):
        @property
        def target_name(self): return 'Fake'
        @property
        def framework(self): return 'none'
        def get_includes(self): return []
        def get_pin_macro(self, n, num): return ''
        def pin_mode(self, p, d): return ''
        def digital_write(self, p, v): return ''
        def digital_read(self, p): return ''
        def pin_direction(self, d): return ''
        def attach_interrupt(self, p, i, m): return ''
        def serial_begin(self, b): return ''
        def serial_print(self, e): return ''
        def serial_println(self, e): return ''
        def pwm_setup(self, c, f, r): return []
        def pwm_attach(self, p, c): return ''
        def pwm_write(self, c, d): return ''
        def isr_attribute(self): return ''
    register_hal('fake', FakeHAL)
    hal = get_hal('fake')
    assert isinstance(hal, FakeHAL)
    assert hal.target_name == 'Fake'
