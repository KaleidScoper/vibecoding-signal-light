"""MCP2221A GPIO adapter for the traffic signal model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class LightMapping:
    """GPIO pin mapping for the traffic signal model."""

    green: str = "gp0"
    yellow: str = "gp1"
    red: str = "gp2"
    active_low: bool = True

    @property
    def pins(self) -> tuple[str, str, str]:
        return (self.green, self.yellow, self.red)

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> "LightMapping":
        active_low = environ.get("SIGNAL_LIGHT_ACTIVE_LOW", "1").strip().lower()
        return cls(
            green=environ.get("SIGNAL_LIGHT_GREEN_PIN", "gp0").strip() or "gp0",
            yellow=environ.get("SIGNAL_LIGHT_YELLOW_PIN", "gp1").strip() or "gp1",
            red=environ.get("SIGNAL_LIGHT_RED_PIN", "gp2").strip() or "gp2",
            active_low=active_low not in {"0", "false", "no", "off"},
        )


class SignalLightError(RuntimeError):
    """Raised when the signal light hardware cannot be controlled."""


class SignalLight:
    """Small wrapper around EasyMCP2221 GPIO writes."""

    def __init__(self, mapping: LightMapping | None = None) -> None:
        self.mapping = mapping or LightMapping()
        self._device = None

    def __enter__(self) -> "SignalLight":
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def connect(self) -> None:
        if self._device is not None:
            return

        try:
            import EasyMCP2221
        except ImportError as exc:
            raise SignalLightError(
                "EasyMCP2221 is not installed. Install the project dependencies or run in --dry-run mode."
            ) from exc

        try:
            device = EasyMCP2221.Device()
            kwargs: dict[str, object] = {}
            for pin in self.mapping.pins:
                kwargs[pin] = "GPIO_OUT"
                kwargs[f"out{pin[-1]}"] = self._physical_value(False)
            device.set_pin_function(**kwargs)
        except Exception as exc:  # pragma: no cover - depends on local USB hardware.
            raise SignalLightError(f"Failed to initialize MCP2221A GPIO: {exc}") from exc

        self._device = device

    def close(self) -> None:
        self._device = None

    def off(self) -> None:
        self.write(green=False, yellow=False, red=False)

    def write(self, *, green: bool = False, yellow: bool = False, red: bool = False) -> None:
        if self._device is None:
            self.connect()

        values = {
            self.mapping.green: green,
            self.mapping.yellow: yellow,
            self.mapping.red: red,
        }
        gpio_values = {pin: self._physical_value(on) for pin, on in values.items()}

        try:
            self._device.GPIO_write(**gpio_values)
        except Exception as exc:  # pragma: no cover - depends on local USB hardware.
            raise SignalLightError(f"Failed to write MCP2221A GPIO: {exc}") from exc

    def _physical_value(self, logical_on: bool) -> bool:
        if self.mapping.active_low:
            return not logical_on
        return logical_on
