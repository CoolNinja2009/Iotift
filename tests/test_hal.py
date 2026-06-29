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
        get_hal('nonexistent_mcu')


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


# ─────────────────────────────────────────
#  M7: Additional target HALs
# ─────────────────────────────────────────

def test_get_hal_stm32():
    hal = get_hal('stm32')
    from hal.stm32_arduino import STM32ArduinoHAL
    assert isinstance(hal, STM32ArduinoHAL)
    assert hal.target_name == 'STM32 (Arduino)'
    assert hal.framework == 'arduino'


def test_get_hal_rp2040():
    hal = get_hal('rp2040')
    from hal.rp2040_arduino import RP2040ArduinoHAL
    assert isinstance(hal, RP2040ArduinoHAL)
    assert hal.target_name == 'RP2040 (Arduino-Pico)'


def test_get_hal_nrf52():
    hal = get_hal('nrf52')
    from hal.nrf52_arduino import NRF52ArduinoHAL
    assert isinstance(hal, NRF52ArduinoHAL)
    assert hal.target_name == 'nRF52 (Arduino)'


def test_get_hal_avr():
    hal = get_hal('avr')
    from hal.avr_arduino import AVRArduinoHAL
    assert isinstance(hal, AVRArduinoHAL)
    assert hal.target_name == 'AVR (Arduino)'


# ─────────────────────────────────────────
#  M7: Device aliases
# ─────────────────────────────────────────

def test_alias_esp32s3():
    hal = get_hal('esp32s3')
    from hal.esp32_arduino import ESP32ArduinoHAL
    assert isinstance(hal, ESP32ArduinoHAL)


def test_alias_pico():
    hal = get_hal('pico')
    from hal.rp2040_arduino import RP2040ArduinoHAL
    assert isinstance(hal, RP2040ArduinoHAL)


def test_alias_uno():
    hal = get_hal('uno')
    from hal.avr_arduino import AVRArduinoHAL
    assert isinstance(hal, AVRArduinoHAL)


def test_alias_nano():
    hal = get_hal('nano')
    assert hal.target_name == 'AVR (Arduino)'


def test_alias_stm32f4():
    hal = get_hal('stm32f4')
    from hal.stm32_arduino import STM32ArduinoHAL
    assert isinstance(hal, STM32ArduinoHAL)


def test_alias_nrf52840():
    hal = get_hal('nrf52840')
    from hal.nrf52_arduino import NRF52ArduinoHAL
    assert isinstance(hal, NRF52ArduinoHAL)


# ─────────────────────────────────────────
#  M7: Bare-metal backends
# ─────────────────────────────────────────

def test_get_hal_espidf():
    hal = get_hal('esp32-espidf')
    from hal.esp32_espidf import ESP32IDFHAL
    assert isinstance(hal, ESP32IDFHAL)
    assert hal.target_name == 'ESP32 (ESP-IDF)'
    assert hal.framework == 'espidf'


def test_alias_espidf():
    hal = get_hal('espidf')
    assert hal.framework == 'espidf'


def test_get_hal_cmsis():
    hal = get_hal('stm32-cmsis')
    from hal.cmsis_arm import CMSISHAL
    assert isinstance(hal, CMSISHAL)


def test_cmsis_target_name():
    hal = get_hal('stm32-cmsis')
    assert 'CMSIS' in hal.target_name
    assert 'ARM Cortex-M' in hal.target_name


# ─────────────────────────────────────────
#  M7: Production features — ESP32 Arduino
# ─────────────────────────────────────────

def test_deep_sleep():
    hal = get_hal('esp32')
    result = hal.deep_sleep('5000000')
    assert 'esp_deep_sleep_start' in result or 'esp_sleep_enable_timer_wakeup' in result


def test_light_sleep():
    hal = get_hal('esp32')
    result = hal.light_sleep('1000000')
    assert 'esp_light_sleep_start' in result


def test_wakeup_pin():
    hal = get_hal('esp32')
    result = hal.set_wakeup_pin('GPIO_NUM_4', 'HIGH')
    assert 'esp_sleep_enable_ext0_wakeup' in result


def test_watchdog_enable():
    hal = get_hal('esp32')
    result = hal.watchdog_enable(5000)
    assert 'esp_task_wdt_init' in result


def test_watchdog_reset():
    hal = get_hal('esp32')
    result = hal.watchdog_reset()
    assert 'esp_task_wdt_reset' in result


def test_filesystem_mount_littlefs():
    hal = get_hal('esp32')
    result = hal.filesystem_mount('littlefs')
    assert 'LittleFS' in result


def test_filesystem_mount_fat():
    hal = get_hal('esp32')
    result = hal.filesystem_mount('fat')
    assert 'FFat' in result


def test_filesystem_open():
    hal = get_hal('esp32')
    result = hal.filesystem_open('"/data.txt"', 'r')
    assert 'LittleFS.open' in result


def test_filesystem_read():
    hal = get_hal('esp32')
    result = hal.filesystem_read('_f', '_buf', '128')
    assert '.read' in result


def test_filesystem_write():
    hal = get_hal('esp32')
    result = hal.filesystem_write('_f', '_buf', '128')
    assert '.write' in result


def test_filesystem_close():
    hal = get_hal('esp32')
    result = hal.filesystem_close('_f')
    assert '.close()' in result


def test_filesystem_exists():
    hal = get_hal('esp32')
    result = hal.filesystem_exists('"/data.txt"')
    assert 'LittleFS.exists' in result


def test_flash_read_bytes():
    hal = get_hal('esp32')
    result = hal.flash_read_bytes('"mykey"', '_buf', '64')
    assert 'preferences.getBytes' in result


def test_flash_write_bytes():
    hal = get_hal('esp32')
    result = hal.flash_write_bytes('"mykey"', '_buf', '64')
    assert 'preferences.putBytes' in result


def test_flash_erase():
    hal = get_hal('esp32')
    result = hal.flash_erase_sector('"mykey"')
    assert 'preferences.remove' in result


def test_wifi_begin():
    hal = get_hal('esp32')
    result = hal.wifi_begin('"myssid"', '"password"')
    assert 'WiFi.begin' in result


def test_wifi_status():
    hal = get_hal('esp32')
    result = hal.wifi_status()
    assert 'WL_CONNECTED' in result


def test_wifi_local_ip():
    hal = get_hal('esp32')
    result = hal.wifi_local_ip()
    assert 'WiFi.localIP' in result


def test_ble_begin():
    hal = get_hal('esp32')
    result = hal.ble_begin('"MyDevice"')
    assert 'BLEDevice::init' in result


def test_ble_advertising():
    hal = get_hal('esp32')
    result = hal.ble_start_advertising()
    assert 'getAdvertising' in result


def test_ota_begin():
    hal = get_hal('esp32')
    result = hal.ota_begin('4096')
    assert 'Update.begin' in result


def test_ota_write():
    hal = get_hal('esp32')
    result = hal.ota_write('_buf', '512')
    assert 'Update.write' in result


def test_ota_end():
    hal = get_hal('esp32')
    result = hal.ota_end()
    assert 'Update.end' in result


def test_ota_rollback():
    hal = get_hal('esp32')
    result = hal.ota_rollback()
    assert 'Update.rollBack' in result


def test_secure_boot_check():
    hal = get_hal('esp32')
    result = hal.secure_boot_check()
    assert 'EFUSE' in result or 'REG_READ' in result


# ─────────────────────────────────────────
#  M7: Breakpoint instruction
# ─────────────────────────────────────────

def test_breakpoint_esp32():
    hal = get_hal('esp32')
    result = hal.breakpoint_instruction()
    assert 'break' in result


def test_breakpoint_stm32():
    hal = get_hal('stm32')
    result = hal.breakpoint_instruction()
    assert 'bkpt' in result


def test_breakpoint_rp2040():
    hal = get_hal('rp2040')
    result = hal.breakpoint_instruction()
    assert 'bkpt' in result


def test_breakpoint_avr():
    hal = get_hal('avr')
    result = hal.breakpoint_instruction()
    assert 'break' in result


# ─────────────────────────────────────────
#  M7: Supported targets list
# ─────────────────────────────────────────

def test_supported_targets():
    from hal import supported_targets
    targets = supported_targets()
    target_ids = [t[0] for t in targets]
    assert 'esp32' in target_ids
    assert 'esp32-espidf' in target_ids
    assert 'stm32' in target_ids
    assert 'stm32-cmsis' in target_ids
    assert 'rp2040' in target_ids
    assert 'nrf52' in target_ids
    assert 'avr' in target_ids


def test_stm32_gpio():
    hal = get_hal('stm32')
    assert 'OUTPUT' in hal.pin_mode('LED_PIN', 'OUTPUT')
    assert 'digitalWrite' in hal.digital_write('LED_PIN', 'HIGH')
    assert 'analogWrite' in hal.pwm_write(0, '128')


def test_avr_config_defines():
    hal = get_hal('avr')
    config = hal.get_config_defines(9600, 32)
    config_str = '\n'.join(config)
    assert 'AVR-specific' in config_str
    assert '8U' in config_str  # AVR scheduler slot limit


def test_stm32_restart():
    hal = get_hal('stm32')
    assert 'NVIC_SystemReset' in hal.restart_func()


def test_rp2040_pwm():
    hal = get_hal('rp2040')
    result = '\n'.join(hal.pwm_setup(0, 1000, 8))
    assert 'analogWriteFreq' in result
    assert 'analogWriteRange' in result
