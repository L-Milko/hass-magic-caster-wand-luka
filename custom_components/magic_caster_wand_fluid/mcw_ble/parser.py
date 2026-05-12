"""Parser for Magic Caster Wand BLE devices."""

import asyncio
import dataclasses
import logging
from time import time
from typing import Callable

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak_retry_connector import establish_connection
from bluetooth_sensor_state_data import BluetoothData
from home_assistant_bluetooth import BluetoothServiceInfoBleak

from .macros import BuzzCommand, ChangeLedCommand, LedGroup, Macro, get_spell_macro
from .mcw import McwClient
from .remote_tensor_spell_detector import RemoteTensorSpellDetector
from .spell_tracker import SpellTracker

_LOGGER = logging.getLogger(__name__)

@dataclasses.dataclass
class BLEData:
    """Response data with information about the Magic Caster Wand device."""

    hw_version: str = ""
    sw_version: str = ""
    name: str = ""
    identifier: str = ""
    address: str = ""
    model: str = ""
    serial_number: str = ""
    sensors: dict[str, str | float | None] = dataclasses.field(
        default_factory=lambda: {}
    )


class McwDevice:
    """Data handler for Magic Caster Wand BLE device."""

    def __init__(self, address: str, tflite_url: str = "http://b5e3f765-tflite-server:8000", model_name: str = "model.tflite", spell_timeout: int = 0) -> None:
        """Initialize the device."""
        self.address = address
        self.tflite_url = tflite_url
        self.model_name = model_name
        self.client: BleakClient | None = None
        self.model: str | None = None
        self._mcw: McwClient | None = None
        self._data = BLEData()
        self._coordinator_spell = None
        self._coordinator_battery = None
        self._coordinator_buttons = None
        self._coordinator_calibration = None
        self._coordinator_imu = None
        self._coordinator_connection = None
        self._spell_timeout = spell_timeout
        self._spell_tracker: SpellTracker | None = None
        self._button_all_pressed: bool = False
        self._spell_reset_timeout_task: asyncio.Task[None] | None = None
        self._casting_led_color: tuple[int, int, int] = (0, 0, 255)  # Default color: blue
        self._spell_light_effects_enabled: bool = True
        self._spell_vibration_enabled: bool = True
        self._spell_learn_mode_enabled: bool = False
        self._spell_light_effect_task: asyncio.Task[None] | None = None
        self._learn_spell_listeners: list[Callable[[str, int], None]] = []
        self._learn_spell_event_id = 0
        self._learn_spell_name = "awaiting"
        self._learn_spell_ts = 0.0
        self._lumos_level = 0
        self._server_reachable: bool = False

        self._init_spell_tracker()

    def _init_spell_tracker(self) -> None:
        """Initialize the spell tracker."""
        try:
            # Persistent detector and tracker
            self._spell_tracker = SpellTracker(
                RemoteTensorSpellDetector(
                    model_name=self.model_name,
                    base_url=self.tflite_url,
                ))
            _LOGGER.debug("Persistent spell tracker created")
        except Exception as err:
            _LOGGER.warning("Failed to create spell detector: %s", err)

    def register_coordinator(self, cn_spell, cn_battery, cn_buttons, cn_calibration=None, cn_imu=None, cn_connection=None) -> None:
        """Register coordinators for spell, battery, button, calibration, and connection updates."""
        self._coordinator_spell = cn_spell
        self._coordinator_battery = cn_battery
        self._coordinator_buttons = cn_buttons
        self._coordinator_calibration = cn_calibration
        self._coordinator_imu = cn_imu
        self._coordinator_connection = cn_connection

    def _schedule_spell_reset(self) -> None:
        """Schedule a reset of the spell sensor back to 'awaiting' after the configured timeout."""
        # Cancel any existing timeout task
        if self._spell_reset_timeout_task is not None:
            self._spell_reset_timeout_task.cancel()
            self._spell_reset_timeout_task = None

        # Only schedule if timeout is greater than 0
        if self._spell_timeout > 0:
            self._spell_reset_timeout_task = asyncio.create_task(self._async_reset_spell_after_timeout())

    async def _async_reset_spell_after_timeout(self) -> None:
        """Reset the spell sensor to 'awaiting' after the configured timeout."""
        try:
            await asyncio.sleep(self._spell_timeout)
            if self._coordinator_spell:
                _LOGGER.debug("Spell timeout reached, resetting to 'awaiting'")
                self._coordinator_spell.async_set_updated_data("awaiting")
        except asyncio.CancelledError:
            # Task was cancelled (likely because a new spell was detected)
            pass
        finally:
            self._spell_reset_timeout_task = None

    def _callback_spell(self, data: str) -> None:
        """Handle spell detection callback from wand-native detection."""
        if self._spell_learn_mode_enabled:
            self._publish_learn_spell(data)
            return

        if self._coordinator_spell:
            self._coordinator_spell.async_set_updated_data(data)
            self._schedule_spell_reset()
            self._schedule_spell_feedback(data)

    def _callback_battery(self, data: float) -> None:
        """Handle battery update callback."""
        if self._coordinator_battery:
            self._coordinator_battery.async_set_updated_data(data)

    def _callback_buttons(self, data: dict[str, bool]) -> None:
        """Handle button state update callback."""
        if self._coordinator_buttons:
            self._coordinator_buttons.async_set_updated_data(data)

        # Handle spell tracking start/stop when using server-side detection
        if self._spell_tracker is not None and self._spell_tracker.detector is not None and self._spell_tracker.detector.is_active:
            button_all = data.get("button_all", False)

            # Transition: not pressed -> pressed = start tracking
            if button_all and not self._button_all_pressed:
                _LOGGER.debug("All buttons pressed, starting spell tracking")
                asyncio.create_task(self._turn_on_casting_led())
                self._spell_tracker.start()

            # Transition: pressed -> not pressed = stop tracking and detect spell
            elif not button_all and self._button_all_pressed:
                _LOGGER.debug("Buttons released, stopping spell tracking")
                asyncio.create_task(self._turn_off_casting_led())
                asyncio.create_task(self._async_stop_and_detect_spell())

            self._button_all_pressed = button_all

    async def _async_stop_and_detect_spell(self) -> None:
        """Stop spell tracking and detect spell asynchronously."""
        if self._spell_tracker is None:
            return

        spell_name = await self._spell_tracker.stop()
        if not spell_name:
            return

        if self._spell_learn_mode_enabled:
            self._publish_learn_spell(str(spell_name))
            return

        if self._coordinator_spell:
            _LOGGER.debug("Server-side spell detected: %s", spell_name)
            self._coordinator_spell.async_set_updated_data(spell_name)
            self._schedule_spell_reset()
            await self._play_spell_feedback(str(spell_name))

    def _schedule_spell_feedback(self, spell_name: str) -> None:
        """Schedule the configured feedback for a detected spell."""
        self._spell_light_effect_task = asyncio.create_task(
            self._play_spell_feedback(spell_name)
        )

    async def _play_spell_feedback(self, spell_name: str) -> None:
        """Play configured vibration and light feedback for a detected spell."""
        if not self._mcw:
            return

        name = str(spell_name or "").strip()
        if not name or name == "awaiting" or name.startswith("draw_"):
            return

        lights_enabled = self._spell_light_effects_enabled
        vibration_enabled = self._spell_vibration_enabled
        if not lights_enabled and not vibration_enabled:
            return

        try:
            if lights_enabled:
                macro = self._build_spell_feedback_macro(name, vibration_enabled)
                await self._mcw.send_macro(macro)
                return

            if vibration_enabled:
                await self.buzz(self._spell_buzz_duration(name))
        except Exception as err:
            _LOGGER.warning("Failed to play spell feedback for %s: %s", name, err)

    def _build_spell_feedback_macro(self, spell_name: str, include_vibration: bool) -> Macro:
        """Build a richer four-zone wand feedback macro."""
        name = spell_name.lower().replace(" ", "_").replace("-", "_")
        color = self._spell_color(spell_name)

        if name == "lumos":
            if self._lumos_level <= 0:
                self._lumos_level = 1
                return self._lumos_macro(include_vibration, maxima=False)
            self._lumos_level = 2
            return self._lumos_macro(include_vibration, maxima=True)

        self._lumos_level = 0
        if name == "nox":
            macro = Macro()
            if include_vibration:
                macro.add_buzz(80)
            return (
                macro
                .add_led_hex(LedGroup.TIP, "DDDDFF", 120)
                .add_led_hex(LedGroup.MID_UPPER, "8888CC", 120)
                .add_led_hex(LedGroup.MID_LOWER, "444466", 120)
                .add_led_hex(LedGroup.POMMEL, "111122", 120)
                .add_delay(160)
                .add_clear()
            )

        return self._success_macro(color, include_vibration)

    def _success_macro(self, color: tuple[int, int, int], include_vibration: bool) -> Macro:
        """Build a visible travelling success animation."""
        r, g, b = color
        dim = (max(8, r // 3), max(8, g // 3), max(8, b // 3))
        mid = (max(12, (r * 2) // 3), max(12, (g * 2) // 3), max(12, (b * 2) // 3))
        macro = Macro()
        if include_vibration:
            macro.add_buzz(120)
        return (
            macro
            .add_led(LedGroup.POMMEL, *dim, 180)
            .add_delay(70)
            .add_led(LedGroup.MID_LOWER, *mid, 180)
            .add_delay(70)
            .add_led(LedGroup.MID_UPPER, *mid, 180)
            .add_delay(70)
            .add_led(LedGroup.TIP, r, g, b, 260)
            .add_delay(170)
            .add_led(LedGroup.POMMEL, r, g, b, 220)
            .add_led(LedGroup.MID_LOWER, r, g, b, 220)
            .add_led(LedGroup.MID_UPPER, r, g, b, 220)
            .add_led(LedGroup.TIP, 255, 255, 255, 120)
            .add_delay(260)
            .add_led(LedGroup.TIP, r, g, b, 220)
            .add_delay(650)
            .add_clear()
        )

    def _lumos_macro(self, include_vibration: bool, maxima: bool) -> Macro:
        """Build persistent Lumos and Lumos Maxima light states."""
        macro = Macro()
        if include_vibration:
            macro.add_buzz(180 if maxima else 100)
        if maxima:
            return (
                macro
                .add_led_hex(LedGroup.POMMEL, "6666FF", 160)
                .add_delay(80)
                .add_led_hex(LedGroup.MID_LOWER, "AAAAFF", 160)
                .add_delay(80)
                .add_led_hex(LedGroup.MID_UPPER, "DDDDFF", 160)
                .add_delay(80)
                .add_led_hex(LedGroup.TIP, "FFFFFF", 220)
                .add_delay(120)
                .add_led_hex(LedGroup.POMMEL, "FFFFFF", 400)
                .add_led_hex(LedGroup.MID_LOWER, "FFFFFF", 400)
                .add_led_hex(LedGroup.MID_UPPER, "FFFFFF", 400)
                .add_led_hex(LedGroup.TIP, "FFFFFF", 400)
            )

        return (
            macro
            .add_led_hex(LedGroup.MID_UPPER, "9999FF", 120)
            .add_delay(80)
            .add_led_hex(LedGroup.TIP, "FFFFFF", 500)
        )

    def _spell_color(self, spell_name: str) -> tuple[int, int, int]:
        """Use the first spell macro LED color, falling back to the casting color."""
        macro = get_spell_macro(spell_name)
        if macro is not None:
            for command in macro.commands:
                if isinstance(command, ChangeLedCommand):
                    return command.red, command.green, command.blue
        return self._casting_led_color

    def _spell_buzz_duration(self, spell_name: str) -> int:
        """Use the spell macro vibration length when available."""
        macro = get_spell_macro(spell_name)
        if macro is not None:
            for command in macro.commands:
                if isinstance(command, BuzzCommand):
                    return command.duration_ms
        return 120

    def _publish_learn_spell(self, spell_name: str) -> None:
        """Publish a learning-only spell event without changing automation sensors."""
        name = str(spell_name or "").strip()
        if not name or name == "awaiting":
            return
        self._learn_spell_event_id += 1
        self._learn_spell_name = name
        self._learn_spell_ts = time()
        for listener in list(self._learn_spell_listeners):
            listener(name, self._learn_spell_event_id)

    def async_add_learn_spell_listener(self, listener: Callable[[str, int], None]) -> Callable[[], None]:
        """Subscribe to learning-only wand spell events."""
        self._learn_spell_listeners.append(listener)

        def unsubscribe() -> None:
            try:
                self._learn_spell_listeners.remove(listener)
            except ValueError:
                pass

        return unsubscribe

    @property
    def learn_spell_payload(self) -> dict[str, object]:
        """Return the latest learning-only wand spell event."""
        return {
            "spell": self._learn_spell_name,
            "spell_event_id": self._learn_spell_event_id,
            "spell_ts": self._learn_spell_ts,
            "spell_mode": "learning",
        }

    async def _turn_on_casting_led(self) -> None:
        """Turn on the casting LED with configured color."""
        if self._mcw:
            try:
                r, g, b = self._casting_led_color
                await self._mcw.led_on(LedGroup.TIP, r, g, b)
                _LOGGER.debug("Casting LED turned on with color: (%d, %d, %d)", r, g, b)
            except Exception as err:
                _LOGGER.warning("Failed to turn on casting LED: %s", err)

    async def _turn_off_casting_led(self) -> None:
        """Turn off the casting LED."""
        if self._mcw:
            try:
                await self._mcw.led_off()
                _LOGGER.debug("Casting LED turned off")
            except Exception as err:
                _LOGGER.warning("Failed to turn off casting LED: %s", err)

    def _callback_calibration(self, data: dict[str, bool]) -> None:
        """Handle calibration state update callback."""
        if self._coordinator_calibration:
            self._coordinator_calibration.async_set_updated_data(data)

    def _callback_imu(self, data: list[dict[str, float]]) -> None:
        """Handle IMU data update callback."""
        if self._coordinator_imu:
            self._coordinator_imu.async_set_updated_data(data)

        if self._spell_tracker is not None and self._spell_tracker.detector is not None and self._spell_tracker.detector.is_active:
            for sample in data:
                self._spell_tracker.update(
                    ax=sample['accel_y'],
                    ay=-sample['accel_x'],
                    az=sample['accel_z'],
                    gx=sample['gyro_y'],
                    gy=-sample['gyro_x'],
                    gz=sample['gyro_z']
                )

    def _on_disconnect(self, client: BleakClient) -> None:
        """Handle BLE device disconnection."""
        _LOGGER.debug("Disconnected from Magic Caster Wand")
        self.client = None
        self._mcw = None
        if self._coordinator_connection:
            self._coordinator_connection.async_set_updated_data(False)

    def is_connected(self) -> bool:
        """Check if the device is currently connected."""
        if self.client:
            try:
                return self.client.is_connected
            except Exception:
                pass
        return False

    async def connect(self, ble_device: BLEDevice) -> bool:
        """Connect to the BLE device."""
        if self.is_connected():
            return True

        try:
            self.client = await establish_connection(
                BleakClient, ble_device, ble_device.address,
                disconnected_callback=self._on_disconnect
            )

            if not self.client.is_connected:
                return False

            # Update basic device info
            if not self._data.name:
                self._data.name = ble_device.name or "Magic Caster Wand"
            if not self._data.address:
                self._data.address = ble_device.address
            if not self._data.identifier:
                self._data.identifier = ble_device.address.replace(":", "")[-8:]
            self._mcw = McwClient(self.client)
            self._mcw.register_callback(
                self._callback_spell, 
                self._callback_battery, 
                self._callback_buttons, 
                self._callback_calibration,
                self._callback_imu
            )
            await self._mcw.start_notify()
            if not self.model:
                await self._mcw.init_wand()
                self.model = await self._mcw.get_wand_device_id()
                
            _LOGGER.debug("Connected to Magic Caster Wand: %s, %s", ble_device.address, self.model)
            if self._coordinator_connection:
                self._coordinator_connection.async_set_updated_data(True)
            return True

        except Exception as err:
            _LOGGER.warning("Failed to connect to %s: %s", ble_device.address, err)
            return False

    async def disconnect(self) -> None:
        """Disconnect from the BLE device."""
        if self.client:
            try:
                if self.client.is_connected:
                    if self._mcw:
                        # Stop IMU streaming before disconnecting
                        try:
                            await self._mcw.imu_streaming_stop()
                        except Exception as imu_err:
                            _LOGGER.debug("Failed to stop IMU streaming during disconnect: %s", imu_err)
                        await self._mcw.stop_notify()
                    await self.client.disconnect()
            except Exception as err:
                _LOGGER.warning("Error during disconnect: %s", err)
            finally:
                # Reset all states on disconnect
                if self._coordinator_buttons:
                    self._coordinator_buttons.async_set_updated_data({
                        "button_1": False,
                        "button_2": False,
                        "button_3": False,
                        "button_4": False,
                        "button_all": False,
                    })
                if self._coordinator_connection:
                    self._coordinator_connection.async_set_updated_data(False)

    async def update_device(self, ble_device: BLEDevice) -> BLEData:
        """Update device data. Sends keep-alive if connected."""
        if ble_device and not self.model:
            # Connect temporarily to fetch device info (model)
            if await self.connect(ble_device):
                await self.disconnect()
        # Send keep-alive if connected
        # if self.is_connected() and self._mcw:
        #     try:
        #         await self._mcw.keep_alive()
        #     except Exception as err:
        #         _LOGGER.debug("Keep-alive failed: %s", err)

        # _LOGGER.debug("Updated BLEData: %s", self._data)
        return self._data

    async def send_macro(self, macro: Macro) -> None:
        """Send a macro sequence to the wand."""
        if self.is_connected() and self._mcw:
            await self._mcw.send_macro(macro)

    async def set_led(self, group: LedGroup, r: int, g: int, b: int, duration: int = 0) -> None:
        """Set LED color."""
        if self.is_connected() and self._mcw:
            await self._mcw.set_led(group, r, g, b, duration)

    @property
    def casting_led_color(self) -> tuple[int, int, int]:
        """Get the current casting LED color."""
        return self._casting_led_color

    @casting_led_color.setter
    def casting_led_color(self, value: tuple[int, int, int]) -> None:
        """Set the casting LED color."""
        self._casting_led_color = value

    @property
    def spell_light_effects_enabled(self) -> bool:
        """Return whether successful spell light effects are enabled."""
        return self._spell_light_effects_enabled

    @spell_light_effects_enabled.setter
    def spell_light_effects_enabled(self, value: bool) -> None:
        """Enable or disable successful spell light effects."""
        self._spell_light_effects_enabled = bool(value)

    @property
    def spell_vibration_enabled(self) -> bool:
        """Return whether successful spell vibration is enabled."""
        return self._spell_vibration_enabled

    @spell_vibration_enabled.setter
    def spell_vibration_enabled(self, value: bool) -> None:
        """Enable or disable successful spell vibration."""
        self._spell_vibration_enabled = bool(value)

    @property
    def spell_learn_mode_enabled(self) -> bool:
        """Return whether wand spell recognition is in learning mode."""
        return self._spell_learn_mode_enabled

    @spell_learn_mode_enabled.setter
    def spell_learn_mode_enabled(self, value: bool) -> None:
        """Enable or disable wand learning mode."""
        self._spell_learn_mode_enabled = bool(value)

    @property
    def spell_detection_mode(self) -> str:
        """Get the current spell detection mode."""
        if self._spell_tracker is not None:
            if self._spell_tracker.is_active:
                return "Server"
        return "Wand"

    @property
    def server_reachable(self) -> bool:
        """Check if the TFLite server is reachable."""
        return self._server_reachable

    async def buzz(self, duration: int) -> None:
        """Vibrate the wand."""
        if self.is_connected() and self._mcw:
            await self._mcw.buzz(duration)

    async def clear_leds(self) -> None:
        """Clear all LEDs."""
        if self.is_connected() and self._mcw:
            await self._mcw.clear_leds()

    async def send_button_calibration(self) -> None:
        """Send button calibration packet."""
        if self.is_connected() and self._mcw:
            await self._mcw.calibration_button()

    async def send_imu_calibration(self) -> None:
        """Send IMU calibration packet."""
        if self.is_connected() and self._mcw:
            await self._mcw.calibration_imu()

    async def imu_streaming_start(self) -> None:
        """Start IMU streaming."""
        if self.is_connected() and self._mcw:
            await self._mcw.imu_streaming_start()

    async def imu_streaming_stop(self) -> None:
        """Stop IMU streaming."""
        if self.is_connected() and self._mcw:
            await self._mcw.imu_streaming_stop()

    async def async_spell_tracker_init(self) -> None:
        """Initialize spell tracker and detector session."""
        if self._spell_tracker is None:
            self._init_spell_tracker()

        if self._spell_tracker is None:
            _LOGGER.warning("Spell tracker not created, cannot initialize")
            return

        try:
            # Perform connectivity check before opening full session
            self._server_reachable = await self._spell_tracker.detector.check_connectivity()
            if self._server_reachable:
                # async_init will handle session creation and one-time upload
                await self._spell_tracker.detector.async_init()
                _LOGGER.debug("Spell tracker session initialized and verified")
            else:
                _LOGGER.warning("TFLite server at %s is not reachable. Spell detection will not be available.", 
                               self._spell_tracker.detector._base_url)
        except Exception as err:
            self._server_reachable = False
            _LOGGER.warning("Failed to initialize remote spell detector session: %s", err)

    async def async_spell_tracker_close(self) -> None:
        """Close spell tracker session but keep the object."""
        if self._spell_tracker is not None:
            _LOGGER.debug("Closing spell tracker session")
            await self._spell_tracker.close()
            # Do NOT set self._spell_tracker = None to keep upload state


class McwBluetoothDeviceData(BluetoothData):
    """Bluetooth device data for Magic Caster Wand."""

    # Magic Caster Wand Service UUID (from mcw.py)
    SERVICE_UUID = "57420001-587e-48a0-974c-544d6163c577"
    # Device name prefix
    DEVICE_NAME_PREFIX = "MCW-"

    def __init__(self) -> None:
        """Initialize the device data."""
        super().__init__()
        self.last_service_info: BluetoothServiceInfoBleak | None = None
        self.pending = True

    def supported(self, data: BluetoothServiceInfoBleak) -> bool:
        """Check if the device is a supported Magic Caster Wand."""
        # Check device name starts with "MCW-"
        if not data.name or not data.name.startswith(self.DEVICE_NAME_PREFIX):
            return False

        # Check for Magic Caster Wand Service UUID
        # service_uuids_lower = [uuid.lower() for uuid in data.service_uuids]
        # if self.SERVICE_UUID.lower() not in service_uuids_lower:
        #     return False

        return True
