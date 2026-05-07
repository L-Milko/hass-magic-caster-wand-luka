"""Support for Magic Caster Wand Fluid Effects number entities."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, FLUID_CONFIG_OPTIONS, MANUFACTURER
from .fluid import update_fluid_runtime_values


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up live fluid effect number controls."""
    data = hass.data[DOMAIN][entry.entry_id]
    address = data["address"]
    mcw = data["mcw"]

    async_add_entities([
        McwFluidNumber(address, mcw, data, option_key, option)
        for option_key, option in FLUID_CONFIG_OPTIONS.items()
        if option["type"] is not bool
    ])


class McwFluidNumber(NumberEntity, RestoreEntity):
    """Number entity for a live fluid visualizer setting."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self,
        address: str,
        mcw,
        data: dict[str, Any],
        option_key: str,
        option: dict[str, Any],
    ) -> None:
        """Initialize the fluid number."""
        self._address = address
        self._mcw = mcw
        self._data = data
        self._option_key = option_key
        self._option = option
        self._js_key = option["js_key"]
        self._identifier = address.replace(":", "")[-8:]
        name = option_key.replace("fluid_", "").replace("_", " ").title()
        self._attr_name = f"Fluid {name}"
        self._attr_unique_id = f"mcwf_{self._identifier}_{option_key}"
        self._attr_native_min_value = option["min"]
        self._attr_native_max_value = option["max"]
        self._attr_native_step = 1 if option["type"] is int else 0.01
        self._attr_icon = "mdi:tune"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, self._address)},
            name=f"Magic Caster Wand Fluid Effects {self._identifier}",
            manufacturer=MANUFACTURER,
            model=self._mcw.model if self._mcw else None,
        )

    @property
    def native_value(self) -> float | int:
        """Return the current runtime value."""
        return self._data["fluid_config"].get(self._js_key, self._option["default"])

    async def async_set_native_value(self, value: float) -> None:
        """Set the live fluid value."""
        update_fluid_runtime_values(self._data, {self._js_key: value})
        stream = self._data.get("fluid_stream")
        if stream is not None:
            stream.publish_config_update()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore previous live value when added to hass."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is None:
            return
        try:
            value = float(last_state.state)
        except (TypeError, ValueError):
            return
        await self.async_set_native_value(value)
