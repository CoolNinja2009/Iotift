"""
Hardware Abstraction Layer for Iotift targets.

Provides a factory to load the correct HAL implementation based on
the target device string (e.g. 'esp32').
"""

from .base import HALBase
from .esp32_arduino import ESP32ArduinoHAL

_HAL_REGISTRY = {
    'esp32': ESP32ArduinoHAL,
}

def get_hal(device: str) -> HALBase:
    """Load the HAL implementation for *device*.

    Raises ValueError if *device* is not a known target.
    """
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
