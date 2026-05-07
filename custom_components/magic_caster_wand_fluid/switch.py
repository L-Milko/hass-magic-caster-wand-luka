"""Support for Magic Caster Wand BLE switch."""

import logging

from homeassistant.components import bluetooth
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import DOMAIN, FLUID_CONFIG_OPTIONS, FLUID_RUNTIME_SWITCHES, MANUFACTURER, SIGNAL_SPELL_MODE_CHANGED
from .fluid import sync_fluid_runtime_config, update_fluid_runtime_values
from .mcw_ble import BLEData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Magic Caster Wand BLE switch."""
    data = hass.data[DOMAIN][entry.entry_id]
    address = data["address"]
    mcw = data["mcw"]
    connection_coordinator = data["connection_coordinator"]

    entities = [
        McwConnectionSwitch(hass, address, mcw, connection_coordinator),
        McwSpellTrackingSwitch(hass, address, mcw, connection_coordinator),
    ]
    entities.extend(
        McwFluidRuntimeSwitch(address, mcw, data, switch_key)
        for switch_key in FLUID_RUNTIME_SWITCHES
    )
    entities.extend(
        McwFluidConfigSwitch(address, mcw, data, option_key, option)
        for option_key, option in FLUID_CONFIG_OPTIONS.items()
        if option["type"] is bool
    )
    async_add_entities(entities)


class McwConnectionSwitch(CoordinatorEntity, SwitchEntity):
    """Switch entity for controlling BLE connection."""

    _attr_has_entity_name = True

    def __init__(
        self, 
        hass: HomeAssistant, 
        address: str, 
        mcw, 
        connection_coordinator: DataUpdateCoordinator[bool],
    ) -> None:
        """Initialize the connection switch."""
        super().__init__(connection_coordinator)
        self._hass = hass
        self._address = address
        self._mcw = mcw
        self._identifier = address.replace(":", "")[-8:]
        self._attr_name = "Connect"
        self._attr_unique_id = f"mcwf_{self._identifier}_connect"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Only available if we have received initial data and device model is known
        return super().available and self._mcw is not None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, self._address)},
            name=f"Magic Caster Wand Fluid Effects {self._identifier}",
            manufacturer=MANUFACTURER,
        )

    @property
    def is_on(self) -> bool:
        """Return true if the device is connected."""
        return self.coordinator.data is True

    @property
    def icon(self) -> str:
        """Return the icon based on connection state."""
        return "mdi:bluetooth" if self.is_on else "mdi:bluetooth-off"

    async def async_turn_on(self, **kwargs) -> None:
        """Connect to the device."""
        ble_device = bluetooth.async_ble_device_from_address(self._hass, self._address)
        if ble_device and self._mcw:
            await self._mcw.connect(ble_device)

    async def async_turn_off(self, **kwargs) -> None:
        """Disconnect from the device."""
        if self._mcw:
            await self._mcw.disconnect()


class McwSpellTrackingSwitch(CoordinatorEntity, SwitchEntity):
    """Switch entity for controlling IMU streaming for spell tracking."""

    _attr_has_entity_name = True

    def __init__(
        self, 
        hass: HomeAssistant, 
        address: str, 
        mcw, 
        connection_coordinator: DataUpdateCoordinator[bool],
    ) -> None:
        """Initialize the spell tracking switch."""
        super().__init__(connection_coordinator)
        self._hass = hass
        self._address = address
        self._mcw = mcw
        self._identifier = address.replace(":", "")[-8:]
        self._attr_name = "Spell Tracking"
        self._attr_unique_id = f"mcwf_{self._identifier}_spell_tracking"
        self._is_on = False

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.data is True

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, self._address)},
            name=f"Magic Caster Wand Fluid Effects {self._identifier}",
            manufacturer=MANUFACTURER,
        )

    @property
    def is_on(self) -> bool:
        """Return true if IMU streaming is active."""
        if self.coordinator.data is not True:
            return False
        return self._is_on

    @property
    def icon(self) -> str:
        """Return the icon based on tracking state."""
        return "mdi:broadcast" if self.is_on else "mdi:broadcast-off"

    async def async_turn_on(self, **kwargs) -> None:
        """Start IMU streaming."""
        if self._mcw and self.coordinator.data is True:
            await self._mcw.async_spell_tracker_init()
            await self._mcw.imu_streaming_start()
            self._is_on = True
            async_dispatcher_send(self._hass, SIGNAL_SPELL_MODE_CHANGED)
            self.async_write_ha_state()
        elif self.coordinator.data is not True:
            _LOGGER.warning("Cannot start tracking: Magic Caster Wand is not connected")

    async def async_turn_off(self, **kwargs) -> None:
        """Stop IMU streaming."""
        if self._mcw:
            if self.coordinator.data is True:
                await self._mcw.imu_streaming_stop()
                await self._mcw.async_spell_tracker_close()
            self._is_on = False
            async_dispatcher_send(self._hass, SIGNAL_SPELL_MODE_CHANGED)
            self.async_write_ha_state()


class McwFluidRuntimeSwitch(SwitchEntity, RestoreEntity):
    """Switch entity for live fluid visualizer runtime options."""

    _attr_has_entity_name = True

    def __init__(self, address: str, mcw, data: dict, switch_key: str) -> None:
        """Initialize the fluid runtime switch."""
        self._address = address
        self._mcw = mcw
        self._data = data
        self._switch_key = switch_key
        self._switch = FLUID_RUNTIME_SWITCHES[switch_key]
        self._identifier = address.replace(":", "")[-8:]
        self._attr_name = self._switch["name"]
        self._attr_unique_id = f"mcwf_{self._identifier}_{switch_key}"
        self._attr_icon = self._switch["icon"]

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, self._address)},
            name=f"Magic Caster Wand Fluid Effects {self._identifier}",
            manufacturer=MANUFACTURER,
        )

    @property
    def is_on(self) -> bool:
        """Return true if the runtime option is enabled."""
        return bool(self._data.get(self._switch_key, self._switch["default"]))

    async def async_turn_on(self, **kwargs) -> None:
        """Enable the runtime option."""
        self._set_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Disable the runtime option."""
        self._set_enabled(False)

    def _set_enabled(self, enabled: bool) -> None:
        """Set the runtime option."""
        self._data[self._switch_key] = enabled
        sync_fluid_runtime_config(self._data)
        stream = self._data.get("fluid_stream")
        if stream is not None:
            stream.publish_config_update()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore previous runtime switch state."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in {"on", "off"}:
            self._set_enabled(last_state.state == "on")


class McwFluidConfigSwitch(SwitchEntity, RestoreEntity):
    """Switch entity for a live boolean fluid visualizer setting."""

    _attr_has_entity_name = True

    def __init__(self, address: str, mcw, data: dict, option_key: str, option: dict) -> None:
        """Initialize the fluid config switch."""
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
        self._attr_icon = "mdi:tune-variant"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, self._address)},
            name=f"Magic Caster Wand Fluid Effects {self._identifier}",
            manufacturer=MANUFACTURER,
        )

    @property
    def is_on(self) -> bool:
        """Return true if the fluid setting is enabled."""
        return bool(self._data["fluid_config"].get(self._js_key, self._option["default"]))

    async def async_turn_on(self, **kwargs) -> None:
        """Enable the fluid setting."""
        self._set_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Disable the fluid setting."""
        self._set_enabled(False)

    def _set_enabled(self, enabled: bool) -> None:
        """Set the fluid option."""
        update_fluid_runtime_values(self._data, {self._js_key: enabled})
        stream = self._data.get("fluid_stream")
        if stream is not None:
            stream.publish_config_update()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore previous live switch state."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in {"on", "off"}:
            self._set_enabled(last_state.state == "on")
