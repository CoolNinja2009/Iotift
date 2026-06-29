"""
Hardware Abstraction Layer for Iotift targets.

Provides a factory to load the correct HAL implementation based on
the target device string (e.g. 'esp32', 'stm32', 'rp2040', 'nrf52', 'avr').
"""

from .base import HALBase
from .esp32_arduino import ESP32ArduinoHAL
from .stm32_arduino import STM32ArduinoHAL
from .rp2040_arduino import RP2040ArduinoHAL
from .nrf52_arduino import NRF52ArduinoHAL
from .avr_arduino import AVRArduinoHAL
from .esp32_espidf import ESP32IDFHAL
from .cmsis_arm import CMSISHAL

_HAL_REGISTRY = {
    'esp32':       ESP32ArduinoHAL,
    'esp32-espidf': ESP32IDFHAL,
    'stm32':       STM32ArduinoHAL,
    'stm32-cmsis':  CMSISHAL,
    'rp2040':      RP2040ArduinoHAL,
    'nrf52':       NRF52ArduinoHAL,
    'nrf52-cmsis':  CMSISHAL,
    'avr':         AVRArduinoHAL,
}

# Alias mappings for convenience
_ALIASES = {
    'esp32s2':     'esp32',
    'esp32s3':     'esp32',
    'esp32c3':     'esp32',
    'esp32c6':     'esp32',
    'esp32-bare':  'esp32-espidf',
    'espidf':      'esp32-espidf',
    'stm32f1':     'stm32',
    'stm32f4':     'stm32',
    'stm32-bare':  'stm32-cmsis',
    'cortex-m':    'stm32-cmsis',
    'cmsis':       'stm32-cmsis',
    'pico':        'rp2040',
    'nrf52840':    'nrf52',
    'nrf52832':    'nrf52',
    'nrf-bare':    'nrf52-cmsis',
    'uno':         'avr',
    'nano':        'avr',
    'mega':        'avr',
}


def get_hal(device: str) -> HALBase:
    """Load the HAL implementation for *device*.

    Raises ValueError if *device* is not a known target.
    """
    # Resolve aliases
    device = _ALIASES.get(device.lower(), device.lower())

    cls = _HAL_REGISTRY.get(device)
    if cls is None:
        raise ValueError(
            f"Unknown target device: '{device}'. "
            f"Supported targets: {', '.join(sorted(_HAL_REGISTRY.keys()))}"
        )
    return cls()


def register_hal(device: str, hal_class: type) -> None:
    """Register a new HAL implementation (for extensibility)."""
    _HAL_REGISTRY[device] = hal_class


def supported_targets() -> list:
    """Return a list of (device_id, target_name) tuples for all registered targets."""
    result = []
    for device, cls in _HAL_REGISTRY.items():
        try:
            hal = cls()
            result.append((device, hal.target_name))
        except Exception:
            result.append((device, device))
    return result
