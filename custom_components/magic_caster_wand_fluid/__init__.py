"""The Magic Caster Wand BLE integration."""

import logging
from datetime import timedelta
from functools import partial

from bleak_retry_connector import close_stale_connections_by_address

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL, Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
)
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CASTING_LED_COLORS,
    CONF_CASTING_LED_COLOR,
    CONF_DRAW_ONLY,
    DEFAULT_CASTING_LED_COLOR,
    DEFAULT_SCAN_INTERVAL,
    DRAW_ONLY_UNIQUE_ID,
    DOMAIN,
    CONF_TFLITE_URL,
    DEFAULT_TFLITE_URL,
    CONF_SPELL_TIMEOUT,
    DEFAULT_SPELL_TIMEOUT,
    FLUID_CONFIG_OPTIONS,
    FLUID_RUNTIME_SWITCHES,
)
from .fluid import async_setup_fluid, async_unload_fluid, build_fluid_config, sync_fluid_runtime_config
from .mcw_ble import BLEData, McwDevice, LedGroup

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CAMERA,
]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Magic Caster Wand BLE device from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    draw_only = entry.data.get(CONF_DRAW_ONLY) is True or entry.unique_id == DRAW_ONLY_UNIQUE_ID
    address = entry.unique_id
    assert address is not None

    if not draw_only:
        await close_stale_connections_by_address(address)

    ble_device = None if draw_only else bluetooth.async_ble_device_from_address(hass, address)
    if not ble_device and not draw_only:
        _LOGGER.warning(
            "Could not find Magic Caster Wand device with address %s during setup; continuing without initial data",
            address,
        )

    # Create device instance
    tflite_url = entry.options.get(CONF_TFLITE_URL, entry.data.get(CONF_TFLITE_URL, DEFAULT_TFLITE_URL))
    spell_timeout = entry.options.get(CONF_SPELL_TIMEOUT, entry.data.get(CONF_SPELL_TIMEOUT, DEFAULT_SPELL_TIMEOUT))
    mcw = McwDevice(address, tflite_url=tflite_url, spell_timeout=spell_timeout)
    identifier = address.replace(":", "")[-8:]

    # Create coordinators with unique names for debugging
    coordinator: DataUpdateCoordinator[BLEData] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_main_{identifier}",
        update_method=partial(_async_update_method, hass, entry, mcw),
        update_interval=timedelta(
            seconds=float(entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        ),
    )

    spell_coordinator: DataUpdateCoordinator[str] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_spell_{identifier}",
    )
    spell_coordinator.async_set_updated_data("awaiting")

    draw_spell_coordinator: DataUpdateCoordinator[str] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_draw_spell_{identifier}",
    )
    draw_spell_coordinator.async_set_updated_data("awaiting")

    battery_coordinator: DataUpdateCoordinator[float] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_battery_{identifier}",
    )

    buttons_coordinator: DataUpdateCoordinator[dict[str, bool]] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_buttons_{identifier}",
    )

    calibration_coordinator: DataUpdateCoordinator[dict[str, bool]] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_calibration_{identifier}",
    )

    imu_coordinator: DataUpdateCoordinator[list[dict[str, float]]] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_imu_{identifier}",
    )

    connection_coordinator: DataUpdateCoordinator[bool] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_connection_{identifier}",
    )
    # Initialize with disconnected state
    connection_coordinator.async_set_updated_data(False)

    # Register coordinators with device for BLE callbacks
    mcw.register_coordinator(spell_coordinator, battery_coordinator, buttons_coordinator, calibration_coordinator, imu_coordinator, connection_coordinator)

    # Store data for platforms
    hass.data[DOMAIN][entry.entry_id] = {
        "address": address,
        "draw_only": draw_only,
        "mcw": mcw,
        "coordinator": coordinator,
        "spell_coordinator": spell_coordinator,
        "draw_spell_coordinator": draw_spell_coordinator,
        "battery_coordinator": battery_coordinator,
        "buttons_coordinator": buttons_coordinator,
        "calibration_coordinator": calibration_coordinator,
        "imu_coordinator": imu_coordinator,
        "connection_coordinator": connection_coordinator,
        "spell_light_effects": True,
        "spell_vibration": True,
        "wand_learn_spells": False,
        "_options_snapshot": dict(entry.options),
    }
    mcw.spell_light_effects_enabled = True
    mcw.spell_vibration_enabled = True
    mcw.spell_learn_mode_enabled = False

    await async_setup_fluid(hass, entry, hass.data[DOMAIN][entry.entry_id])

    # Perform first refresh (best-effort). If it fails, entities will remain unavailable
    # until a later successful update.
    if draw_only:
        coordinator.async_set_updated_data(BLEData(address=address, identifier=identifier))
    else:
        await coordinator.async_refresh()
    if not coordinator.last_update_success:
        _LOGGER.warning(
            "Initial update failed for %s; entities will start as unavailable: %s",
            address,
            coordinator.last_exception,
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register update listener to handle options changes
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    # Register services
    async def handle_vibrate(call: ServiceCall) -> None:
        """Handle execution of vibrate service."""
        duration = call.data.get("duration", 500)
        device_ids = call.data.get("device_id", [])
        if isinstance(device_ids, str):
            device_ids = [device_ids]
        for device_id in device_ids:
            entry_id = await get_entry_id_from_device(hass, device_id)
            if entry_id and entry_id in hass.data[DOMAIN]:
                device: McwDevice = hass.data[DOMAIN][entry_id]["mcw"]
                await device.buzz(duration)

    async def handle_set_led(call: ServiceCall) -> None:
        """Handle execution of set_led service."""
        group_str = call.data.get("group", "TIP")
        group = LedGroup[group_str]
        rgb = call.data.get("rgb_color", (255, 255, 255))
        duration = call.data.get("duration", 0)
        device_ids = call.data.get("device_id", [])
        if isinstance(device_ids, str):
            device_ids = [device_ids]
        for device_id in device_ids:
            entry_id = await get_entry_id_from_device(hass, device_id)
            if entry_id and entry_id in hass.data[DOMAIN]:
                device: McwDevice = hass.data[DOMAIN][entry_id]["mcw"]
                await device.set_led(group, rgb[0], rgb[1], rgb[2], duration)

    async def handle_clear_leds(call: ServiceCall) -> None:
        """Handle execution of clear_leds service."""
        device_ids = call.data.get("device_id", [])
        if isinstance(device_ids, str):
            device_ids = [device_ids]
        for device_id in device_ids:
            entry_id = await get_entry_id_from_device(hass, device_id)
            if entry_id and entry_id in hass.data[DOMAIN]:
                device: McwDevice = hass.data[DOMAIN][entry_id]["mcw"]
                await device.clear_leds()

    async def handle_play_spell(call: ServiceCall) -> None:
        """Handle execution of play_spell service."""
        spell_name = call.data.get("spell")
        device_ids = call.data.get("device_id", [])
        if isinstance(device_ids, str):
            device_ids = [device_ids]
        for device_id in device_ids:
            entry_id = await get_entry_id_from_device(hass, device_id)
            if entry_id and entry_id in hass.data[DOMAIN]:
                device: McwDevice = hass.data[DOMAIN][entry_id]["mcw"]
                # Use helper for more robust spell matching
                from .mcw_ble import get_spell_macro
                macro = get_spell_macro(spell_name)
                if macro:
                    await device.send_macro(macro)

    if not hass.services.has_service(DOMAIN, "vibrate"):
        hass.services.async_register(DOMAIN, "vibrate", handle_vibrate)
    if not hass.services.has_service(DOMAIN, "set_led"):
        hass.services.async_register(DOMAIN, "set_led", handle_set_led)
    if not hass.services.has_service(DOMAIN, "clear_leds"):
        hass.services.async_register(DOMAIN, "clear_leds", handle_clear_leds)
    if not hass.services.has_service(DOMAIN, "play_spell"):
        hass.services.async_register(DOMAIN, "play_spell", handle_play_spell)

    return True


async def _async_update_method(
    hass: HomeAssistant, entry: ConfigEntry, mcw: McwDevice
) -> BLEData:
    """Get data from Magic Caster Wand BLE device."""
    address = entry.unique_id
    if entry.data.get(CONF_DRAW_ONLY) is True or address == DRAW_ONLY_UNIQUE_ID:
        return BLEData(address=address or DRAW_ONLY_UNIQUE_ID, identifier=DRAW_ONLY_UNIQUE_ID)

    ble_device = bluetooth.async_ble_device_from_address(hass, address)
    if not ble_device:
        raise UpdateFailed(f"BLE device not available for address {address}")

    try:
        data = await mcw.update_device(ble_device)
    except Exception as err:
        raise UpdateFailed(f"Unable to fetch data: {err}") from err

    return data


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    await async_unload_fluid(hass, entry)
    mcw: McwDevice = hass.data[DOMAIN][entry.entry_id]["mcw"]
    await mcw.disconnect()

    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok

async def get_entry_id_from_device(hass, device_id: str) -> str:
    device_reg = dr.async_get(hass)
    device_entry = device_reg.async_get(device_id)
    if not device_entry:
        raise ValueError(f"Unknown device_id: {device_id}")
    if not device_entry.config_entries:
        raise ValueError(f"No config entries for device {device_id}")

    _LOGGER.debug("%s to %s", device_id, device_entry.config_entries)
    try:
        entry_id = next(iter(device_entry.config_entries))
    except StopIteration:
        _LOGGER.error("%s None", device_id)
        return None

    return entry_id


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update options."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if data is not None:
        old_options = data.get("_options_snapshot", {})
        new_options = dict(entry.options)
        changed_keys = {
            key
            for key in set(old_options) | set(new_options)
            if old_options.get(key) != new_options.get(key)
        }
        if not changed_keys:
            return

        live_option_keys = (
            set(FLUID_CONFIG_OPTIONS)
            | set(FLUID_RUNTIME_SWITCHES)
            | {CONF_CASTING_LED_COLOR}
        )
        if changed_keys and changed_keys <= live_option_keys:
            data["_options_snapshot"] = new_options
            color_name = new_options.get(
                CONF_CASTING_LED_COLOR,
                data.get("casting_led_color", DEFAULT_CASTING_LED_COLOR),
            )
            data["casting_led_color"] = color_name
            data["_casting_led_color_from_options"] = CONF_CASTING_LED_COLOR in new_options

            mcw: McwDevice | None = data.get("mcw")
            if mcw is not None:
                mcw.casting_led_color = CASTING_LED_COLORS.get(
                    color_name,
                    CASTING_LED_COLORS[DEFAULT_CASTING_LED_COLOR],
                )

            select_entity = data.get("casting_led_color_entity")
            select_update = getattr(select_entity, "set_current_option_from_fluid", None)
            if callable(select_update):
                select_update(color_name)

            for switch_key, switch in FLUID_RUNTIME_SWITCHES.items():
                data[switch_key] = new_options.get(switch_key, switch["default"])

            fluid_config = data.setdefault("fluid_config", {})
            fluid_config.clear()
            fluid_config.update(build_fluid_config(new_options))
            sync_fluid_runtime_config(data)
            stream = data.get("fluid_stream")
            if stream is not None:
                stream.publish_config_update()
            return

        data["_options_snapshot"] = new_options

    await hass.config_entries.async_reload(entry.entry_id)
