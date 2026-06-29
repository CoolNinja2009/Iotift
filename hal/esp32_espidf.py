"""
ESP32 ESP-IDF HAL — bare-metal FreeRTOS backend (no Arduino dependency).

Targets the Espressif IoT Development Framework directly instead of
wrapping Arduino. This produces smaller binaries, faster boot, and
gives access to all ESP-IDF features (WiFi, BLE, OTA, NVS, etc.).

Key differences from Arduino:
- GPIO: gpio_set_level / gpio_get_level (not digitalWrite/digitalRead)
- PWM: ledc_timer_config + ledc_channel_config (not ledcSetup wrapper)
- Serial: uart_driver_install + uart_write_bytes (not Serial class)
- I2C: i2c_master_* functions (not Wire class)
- Timer: esp_timer / FreeRTOS timers (not millis() abstraction)
- ISR: gpio_isr_handler_add (not attachInterrupt)
"""

from __future__ import annotations
from typing import List
from .base import HALBase


class ESP32IDFHAL(HALBase):
    """HAL for ESP32 microcontrollers running bare-metal ESP-IDF (no Arduino)."""

    @property
    def target_name(self) -> str:
        return 'ESP32 (ESP-IDF)'

    @property
    def framework(self) -> str:
        return 'espidf'

    # ── includes ─────────────────────────────────────────────────

    def get_includes(self) -> List[str]:
        return [
            '#include <stdio.h>',
            '#include "freertos/FreeRTOS.h"',
            '#include "freertos/task.h"',
            '#include "driver/gpio.h"',
            '#include "driver/ledc.h"',
            '#include "driver/uart.h"',
            '#include "driver/i2c.h"',
            '#include "driver/spi_master.h"',
            '#include "esp_timer.h"',
            '#include "esp_system.h"',
            '#include "esp_log.h"',
        ]

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
            '/* ESP-IDF app_main entry */',
            '#ifdef __cplusplus',
            'extern "C" {',
            '#endif',
            'void app_main(void);',
            '#ifdef __cplusplus',
            '}',
            '#endif',
        ]

    # ── GPIO ──────────────────────────────────────────────────────

    def get_pin_macro(self, name: str, number: int) -> str:
        return f'static const gpio_num_t {name}_PIN = GPIO_NUM_{number};'

    def pin_mode(self, pin_expr: str, direction: str) -> str:
        if direction == 'OUTPUT':
            return (
                f'gpio_set_direction({pin_expr}, GPIO_MODE_OUTPUT);'
            )
        elif direction in ('INPUT_PULLUP', 'INPUT'):
            return (
                f'gpio_set_direction({pin_expr}, GPIO_MODE_INPUT);\n'
                f'  gpio_set_pull_mode({pin_expr}, GPIO_PULLUP_ONLY);'
            )
        return f'gpio_set_direction({pin_expr}, GPIO_MODE_INPUT);'

    def digital_write(self, pin_expr: str, value: str) -> str:
        if value in ('HIGH', '1', 'true'):
            return f'gpio_set_level({pin_expr}, 1);'
        return f'gpio_set_level({pin_expr}, 0);'

    def digital_read(self, pin_expr: str) -> str:
        return f'gpio_get_level({pin_expr})'

    def pin_direction(self, direction: str) -> str:
        return {
            'output': 'GPIO_MODE_OUTPUT',
            'input':  'GPIO_MODE_INPUT',
            'analog': 'GPIO_MODE_INPUT',
            'i2c':    'GPIO_MODE_INPUT_OUTPUT_OD',
            'pwm':    'GPIO_MODE_OUTPUT',
        }.get(direction, 'GPIO_MODE_OUTPUT')

    # ── interrupts ─────────────────────────────────────────────────

    def attach_interrupt(self, pin_expr: str, isr_name: str, mode: str) -> str:
        return (
            f'gpio_set_intr_type({pin_expr}, {mode});\n'
            f'  gpio_isr_handler_add({pin_expr}, {isr_name}, NULL);\n'
            f'  gpio_intr_enable({pin_expr});'
        )

    def interrupt_mode(self, event: str) -> str:
        return {
            'press':   'GPIO_INTR_NEGEDGE',
            'release': 'GPIO_INTR_POSEDGE',
            'rising':  'GPIO_INTR_POSEDGE',
            'falling': 'GPIO_INTR_NEGEDGE',
            'change':  'GPIO_INTR_ANYEDGE',
        }.get(event, 'GPIO_INTR_ANYEDGE')

    # ── timer / time ────────────────────────────────────────────

    def millis_func(self) -> str:
        return '(unsigned long)(esp_timer_get_time() / 1000ULL)'

    def micros_func(self) -> str:
        return '(unsigned long)esp_timer_get_time()'

    def delay_func(self, ms_expr: str) -> str:
        return f'vTaskDelay(pdMS_TO_TICKS({ms_expr}))'

    def delay_us_func(self, us_expr: str) -> str:
        return f'esp_rom_delay_us({us_expr})'

    # ── Serial (UART) ──────────────────────────────────────────

    def serial_begin(self, baud: int) -> str:
        return (
            f'uart_config_t uart_config = {{\n'
            f'    .baud_rate = {baud},\n'
            f'    .data_bits = UART_DATA_8_BITS,\n'
            f'    .parity = UART_PARITY_DISABLE,\n'
            f'    .stop_bits = UART_STOP_BITS_1,\n'
            f'    .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,\n'
            f'}};\n'
            f'  uart_param_config(UART_NUM_0, &uart_config);\n'
            f'  uart_driver_install(UART_NUM_0, 256, 0, 0, NULL, 0);'
        )

    def serial_print(self, expr: str) -> str:
        return f'uart_write_bytes(UART_NUM_0, (const char*)&({expr}), sizeof({expr}));'

    def serial_println(self, expr: str) -> str:
        return (
            f'uart_write_bytes(UART_NUM_0, (const char*)&({expr}), sizeof({expr}));\n'
            f'  uart_write_bytes(UART_NUM_0, "\\r\\n", 2);'
        )

    # ── PWM (LEDC) ─────────────────────────────────────────────

    def pwm_setup(self, channel: int, freq: int, resolution: int) -> List[str]:
        return [
            f'ledc_timer_config_t ledc_timer_{channel} = {{',
            f'    .speed_mode = LEDC_LOW_SPEED_MODE,',
            f'    .duty_resolution = LEDC_TIMER_{resolution}_BIT,',
            f'    .timer_num = LEDC_TIMER_{channel % 4},',
            f'    .freq_hz = {freq},',
            f'    .clk_cfg = LEDC_AUTO_CLK,',
            f'}};',
            f'ledc_timer_config(&ledc_timer_{channel});',
        ]

    def pwm_attach(self, pin: int, channel: int) -> str:
        return (
            f'ledc_channel_config_t ledc_ch_{channel} = {{',
            f'    .gpio_num = {pin},',
            f'    .speed_mode = LEDC_LOW_SPEED_MODE,',
            f'    .channel = LEDC_CHANNEL_{channel % 8},',
            f'    .timer_sel = LEDC_TIMER_{channel % 4},',
            f'    .duty = 0,',
            f'    .hpoint = 0,',
            f'}};',
            f'ledc_channel_config(&ledc_ch_{channel});',
        )

    def pwm_write(self, channel: int, duty_expr: str) -> str:
        return (
            f'ledc_set_duty(LEDC_LOW_SPEED_MODE, '
            f'LEDC_CHANNEL_{channel % 8}, (uint32_t)({duty_expr}));\n'
            f'  ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_{channel % 8});'
        )

    # ── I2C ────────────────────────────────────────────────────────

    def i2c_begin(self, sda: int, scl: int, speed_hz: int = 100000) -> List[str]:
        return [
            f'i2c_config_t i2c_conf = {{',
            f'    .mode = I2C_MODE_MASTER,',
            f'    .sda_io_num = {sda},',
            f'    .scl_io_num = {scl},',
            f'    .sda_pullup_en = GPIO_PULLUP_ENABLE,',
            f'    .scl_pullup_en = GPIO_PULLUP_ENABLE,',
            f'    .master.clk_speed = {speed_hz},',
            f'}};',
            f'i2c_param_config(I2C_NUM_0, &i2c_conf);',
            f'i2c_driver_install(I2C_NUM_0, I2C_MODE_MASTER, 0, 0, 0);',
        ]

    def i2c_begin_transmission(self, addr_expr: str) -> str:
        return f'i2c_cmd_handle_t cmd = i2c_cmd_link_create(); i2c_master_start(cmd);'

    def i2c_write_data(self, data_expr: str) -> str:
        return f'i2c_master_write_byte(cmd, (uint8_t)({data_expr}), true);'

    def i2c_end_transmission(self) -> str:
        return (
            f'i2c_master_stop(cmd);\n'
            f'  i2c_master_cmd_begin(I2C_NUM_0, cmd, pdMS_TO_TICKS(100));\n'
            f'  i2c_cmd_link_delete(cmd);'
        )

    def i2c_request_from(self, addr_expr: str, len_expr: str) -> str:
        return (
            f'i2c_cmd_handle_t cmd = i2c_cmd_link_create();\n'
            f'  i2c_master_start(cmd);\n'
            f'  i2c_master_write_byte(cmd, '
            f'(uint8_t)(({addr_expr} << 1) | I2C_MASTER_READ), true);\n'
            f'  i2c_master_read(cmd, rx_buf, {len_expr}, I2C_MASTER_LAST_NACK);\n'
            f'  i2c_master_stop(cmd);\n'
            f'  i2c_master_cmd_begin(I2C_NUM_0, cmd, pdMS_TO_TICKS(100));\n'
            f'  i2c_cmd_link_delete(cmd);'
        )

    def i2c_read(self) -> str:
        return 'rx_buf[0]'

    def i2c_available(self) -> str:
        return '1'

    # ── SPI ────────────────────────────────────────────────────────

    def spi_begin(self, mosi: int, miso: int, sck: int) -> List[str]:
        return [
            f'spi_bus_config_t spi_bus = {{',
            f'    .mosi_io_num = {mosi},',
            f'    .miso_io_num = {miso},',
            f'    .sclk_io_num = {sck},',
            f'    .quadwp_io_num = -1,',
            f'    .quadhd_io_num = -1,',
            f'    .max_transfer_sz = 4092,',
            f'}};',
            f'spi_bus_initialize(SPI2_HOST, &spi_bus, SPI_DMA_DISABLED);',
        ]

    def spi_transfer(self, data_expr: str) -> str:
        return (
            f'uint8_t spi_tx = (uint8_t)({data_expr});\n'
            f'  uint8_t spi_rx = 0;\n'
            f'  spi_transaction_t t = {{}};\n'
            f'  t.length = 8;\n'
            f'  t.tx_buffer = &spi_tx;\n'
            f'  t.rx_buffer = &spi_rx;\n'
            f'  spi_device_transmit(spi_dev, &t);\n'
            f'  (void)spi_rx;'
        )

    # ── UART ───────────────────────────────────────────────────────

    def uart_begin(self, uart_num: int, baud: int) -> str:
        return (
            f'uart_config_t uart{uart_num}_cfg = {{',
            f'    .baud_rate = {baud},',
            f'    .data_bits = UART_DATA_8_BITS,',
            f'    .parity = UART_PARITY_DISABLE,',
            f'    .stop_bits = UART_STOP_BITS_1,',
            f'    .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,',
            f'}};',
            f'uart_param_config(UART_NUM_{uart_num}, &uart{uart_num}_cfg);',
            f'uart_driver_install(UART_NUM_{uart_num}, 256, 0, 0, NULL, 0);',
        )

    def uart_print(self, uart_num: int, expr: str) -> str:
        return f'uart_write_bytes(UART_NUM_{uart_num}, (const char*)&({expr}), sizeof({expr}));'

    def uart_read(self, uart_num: int) -> str:
        return f'({uart_num} ? 0 : uart_read_byte(UART_NUM_{uart_num}))'

    def uart_available(self, uart_num: int) -> str:
        return '1'

    # ── ADC ──────────────────────────────────────────────────────

    def analog_read(self, pin_expr: str) -> str:
        return f'adc1_get_raw(pin_to_adc1_channel({pin_expr}))'

    def analog_set_resolution(self, bits: int) -> str:
        return f'adc1_config_width(ADC_WIDTH_BIT_{bits});'

    # ── ISR ──────────────────────────────────────────────────────

    def isr_attribute(self) -> str:
        return 'IRAM_ATTR '

    # ── Power Management (native ESP-IDF) ─────────────────────────

    def deep_sleep(self, duration_us_expr: str) -> str:
        if duration_us_expr == '0':
            return 'esp_deep_sleep_start();'
        return (
            f'esp_sleep_enable_timer_wakeup((uint64_t)({duration_us_expr}));\n'
            f'  esp_deep_sleep_start();'
        )

    def light_sleep(self, duration_us_expr: str) -> str:
        return (
            f'esp_sleep_enable_timer_wakeup((uint64_t)({duration_us_expr}));\n'
            f'  esp_light_sleep_start();'
        )

    def set_wakeup_pin(self, pin_expr: str, level: str) -> str:
        level_val = '1' if level in ('HIGH', '1', 'true') else '0'
        return f'esp_sleep_enable_ext0_wakeup({pin_expr}, {level_val});'

    def set_wakeup_timer(self, duration_us_expr: str) -> str:
        return f'esp_sleep_enable_timer_wakeup((uint64_t)({duration_us_expr}));'

    def get_wakeup_cause(self) -> str:
        return 'esp_sleep_get_wakeup_cause()'

    # ── Watchdog ───────────────────────────────────────────────────

    def watchdog_enable(self, timeout_ms: int) -> str:
        return (
            f'esp_task_wdt_config_t twdt_cfg = {{\n'
            f'    .timeout_ms = {timeout_ms},\n'
            f'    .idle_core_mask = 0,\n'
            f'    .trigger_panic = true,\n'
            f'}};\n'
            f'  esp_task_wdt_init(&twdt_cfg);\n'
            f'  esp_task_wdt_add(NULL);'
        )

    def watchdog_reset(self) -> str:
        return 'esp_task_wdt_reset();'

    # ── Filesystem (LittleFS via esp_littlefs) ─────────────────

    def filesystem_mount(self, fs_type: str, mount_point: str = '/fs') -> str:
        if fs_type == 'littlefs':
            return (
                f'esp_vfs_littlefs_conf_t lfs_conf = {{\n'
                f'    .base_path = "{mount_point}",\n'
                f'    .partition_label = "storage",\n'
                f'    .format_if_mount_failed = true,\n'
                f'}};\n'
                f'  esp_vfs_littlefs_register(&lfs_conf);'
            )
        elif fs_type == 'fat':
            return (
                f'static wl_handle_t wl_handle;\n'
                f'  esp_vfs_fat_spiflash_mount("{mount_point}", "storage", '
                f'&esp_vfs_fat_spiflash_mount_config, &wl_handle);'
            )
        return f'/* mount {fs_type} — not supported */'

    def filesystem_open(self, path_expr: str, mode: str) -> str:
        return f'fopen({path_expr}, "{mode}")'

    def filesystem_read(self, file_expr: str, buf_expr: str, size_expr: str) -> str:
        return f'(int)fread((void*)({buf_expr}), 1, (size_t)({size_expr}), {file_expr})'

    def filesystem_write(self, file_expr: str, buf_expr: str, size_expr: str) -> str:
        return f'(int)fwrite((const void*)({buf_expr}), 1, (size_t)({size_expr}), {file_expr})'

    def filesystem_close(self, file_expr: str) -> str:
        return f'fclose({file_expr})'

    def filesystem_exists(self, path_expr: str) -> str:
        return f'(access({path_expr}, F_OK) == 0)'

    def filesystem_list_dir(self, path_expr: str) -> str:
        return (
            f'DIR *_dir = opendir({path_expr});\n'
            f'  if (_dir) {{\n'
            f'    struct dirent *_ent;\n'
            f'    while ((_ent = readdir(_dir)) != NULL) {{\n'
            f'      printf("  %s\\n", _ent->d_name);\n'
            f'    }}\n'
            f'    closedir(_dir);\n'
            f'  }}'
        )

    # ── Flash / NVS ─────────────────────────────────────────────

    def flash_read_bytes(self, addr_expr: str, buf_expr: str, size_expr: str) -> str:
        return (
            f'nvs_get_blob(_nvs_handle, (const char*)({addr_expr}), '
            f'(void*)({buf_expr}), (size_t*)({size_expr}))'
        )

    def flash_write_bytes(self, addr_expr: str, buf_expr: str, size_expr: str) -> str:
        return (
            f'nvs_set_blob(_nvs_handle, (const char*)({addr_expr}), '
            f'(const void*)({buf_expr}), (size_t)({size_expr}));\n'
            f'  nvs_commit(_nvs_handle);'
        )

    def flash_erase_sector(self, addr_expr: str) -> str:
        return f'nvs_erase_key(_nvs_handle, (const char*)({addr_expr}));\n  nvs_commit(_nvs_handle);'

    def flash_get_size(self) -> str:
        return 'nvs_get_used_entry_count(_nvs_handle)'

    # ── WiFi (native ESP-IDF) ───────────────────────────────────

    def wifi_begin(self, ssid_expr: str, password_expr: str) -> str:
        return (
            f'wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();\n'
            f'  esp_wifi_init(&cfg);\n'
            f'  wifi_config_t wifi_cfg = {{}};\n'
            f'  strcpy((char*)wifi_cfg.sta.ssid, {ssid_expr});\n'
            f'  strcpy((char*)wifi_cfg.sta.password, {password_expr});\n'
            f'  esp_wifi_set_mode(WIFI_MODE_STA);\n'
            f'  esp_wifi_set_config(WIFI_IF_STA, &wifi_cfg);\n'
            f'  esp_wifi_start();'
        )

    def wifi_status(self) -> str:
        return '(esp_wifi_connect() == ESP_OK ? 1 : 0)'

    def wifi_local_ip(self) -> str:
        return 'inet_ntoa(((struct sockaddr_in*)&_sta_addr)->sin_addr)'

    def wifi_disconnect(self) -> str:
        return 'esp_wifi_disconnect(); esp_wifi_stop();'

    # ── BLE (native ESP-IDF NimBLE) ─────────────────────────────

    def ble_begin(self, device_name_expr: str) -> str:
        return (
            f'ble_hs_cfg.reset_cb = _iotift_ble_on_reset;\n'
            f'  ble_hs_cfg.sync_cb = _iotift_ble_on_sync;\n'
            f'  ble_svc_gap_device_name_set({device_name_expr});'
        )

    def ble_start_advertising(self) -> str:
        return 'ble_gap_adv_start(BLE_OWN_ADDR_PUBLIC, NULL, BLE_HS_FOREVER, &_ble_adv_params, NULL, NULL);'

    def ble_stop_advertising(self) -> str:
        return 'ble_gap_adv_stop();'

    def ble_set_value(self, characteristic_expr: str, value_expr: str) -> str:
        return (
            f'ble_gatts_chr_updated({characteristic_expr});\n'
            f'  ble_gattc_notify_custom({characteristic_expr}, (void*)({value_expr}));'
        )

    def ble_get_value(self, characteristic_expr: str) -> str:
        return f'_ble_get_chr_value({characteristic_expr})'

    # ── OTA (native ESP-IDF) ────────────────────────────────────

    def ota_begin(self, size_expr: str) -> str:
        return (
            f'esp_ota_get_next_update_partition(NULL);\n'
            f'  esp_ota_begin(_update_partition, (size_t)({size_expr}), &_ota_handle);'
        )

    def ota_write(self, buf_expr: str, size_expr: str) -> str:
        return f'esp_ota_write(_ota_handle, (const void*)({buf_expr}), (size_t)({size_expr}))'

    def ota_end(self) -> str:
        return (
            f'esp_ota_end(_ota_handle);\n'
            f'  esp_ota_set_boot_partition(_update_partition);\n'
            f'  esp_restart();'
        )

    def ota_rollback(self) -> str:
        return 'esp_ota_mark_app_invalid_rollback_and_reboot();'

    # ── Secure Boot ─────────────────────────────────────────────────

    def secure_boot_check(self) -> str:
        return 'esp_secure_boot_enabled()'

    # ── misc ─────────────────────────────────────────────────────

    def yield_func(self) -> str:
        return 'taskYIELD()'

    def restart_func(self) -> str:
        return 'esp_restart()'
