"""WebGL fluid visualizer for Magic Caster Wand motion."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Mapping
from math import isfinite
from numbers import Real
from pathlib import Path
from time import monotonic, time
from typing import Any

from aiohttp import web
import numpy as np

from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CASTING_LED_COLORS,
    CONF_CASTING_LED_COLOR,
    DEFAULT_CASTING_LED_COLOR,
    DOMAIN,
    FLUID_CONFIG_OPTIONS,
    FLUID_RUNTIME_SWITCHES,
)
from .mcw_ble.spell_tracker import SpellTracker

_LOGGER = logging.getLogger(__name__)

CANVAS_WIDTH = 800
CANVAS_HEIGHT = 600
FRONTEND_PATH = Path(__file__).parent / "frontend" / "fluid"
STATIC_URL = f"/{DOMAIN}_fluid"
DEFAULT_PAGE_URL = f"/{DOMAIN}/fluid"
PAGE_URL = f"/{DOMAIN}/fluid/{{entry_id}}"
EVENTS_URL = f"/{DOMAIN}/fluid/{{entry_id}}/events"
DEFAULT_STATE_URL = f"/{DOMAIN}/fluid_state"
STATE_URL = f"/{DOMAIN}/fluid_state/{{entry_id}}"
CONFIG_URL = f"/{DOMAIN}/fluid_config/{{entry_id}}"
SPELL_URL = f"/{DOMAIN}/fluid_spell/{{entry_id}}"
HEARTBEAT_INTERVAL = 10
MOTION_ACTIVE_PIXELS = 2.0
RAW_IMU_ACTIVE_THRESHOLD = 0.08
RAW_IMU_GYRO_SCALE = 0.025
RAW_IMU_ACCEL_SCALE = 0.012
MAX_POINTER_STEP = 0.08


async def async_setup_fluid(
    hass: HomeAssistant,
    entry: ConfigEntry,
    data: dict[str, Any],
) -> None:
    """Set up the WebGL fluid visualizer endpoints for a config entry."""
    if not hass.data[DOMAIN].get("_fluid_static_registered"):
        hass.data[DOMAIN]["_fluid_index_html"] = await hass.async_add_executor_job(
            _read_index_html
        )
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(FRONTEND_PATH), False)]
        )
        hass.http.register_view(MagicCasterWandFluidDefaultPageView())
        hass.http.register_view(MagicCasterWandFluidPageView())
        hass.http.register_view(MagicCasterWandFluidEventsView())
        hass.http.register_view(MagicCasterWandFluidDefaultStateView())
        hass.http.register_view(MagicCasterWandFluidStateView())
        hass.http.register_view(MagicCasterWandFluidConfigView())
        hass.http.register_view(MagicCasterWandFluidSpellView())
        hass.data[DOMAIN]["_fluid_static_registered"] = True

    data["entry"] = entry
    data["_casting_led_color_from_options"] = CONF_CASTING_LED_COLOR in entry.options
    data["casting_led_color"] = entry.options.get(
        CONF_CASTING_LED_COLOR,
        data.get("casting_led_color", DEFAULT_CASTING_LED_COLOR),
    )
    for switch_key, switch in FLUID_RUNTIME_SWITCHES.items():
        data[switch_key] = entry.options.get(
            switch_key,
            data.get(switch_key, switch["default"]),
        )
    data["fluid_config"] = build_fluid_config(entry.options)
    sync_fluid_runtime_config(data)

    stream = MagicCasterWandMotionStream(
        hass=hass,
        mcw=data["mcw"],
        imu_coordinator=data["imu_coordinator"],
        buttons_coordinator=data["buttons_coordinator"],
        spell_coordinator=data["spell_coordinator"],
        connection_coordinator=data["connection_coordinator"],
        fluid_config=data["fluid_config"],
    )
    data["fluid_stream"] = stream
    stream.start()


async def async_unload_fluid(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Unload fluid visualizer listeners for a config entry."""
    data = hass.data[DOMAIN].get(entry.entry_id)
    if not data:
        return

    stream: MagicCasterWandMotionStream | None = data.get("fluid_stream")
    if stream is not None:
        stream.stop()


class MagicCasterWandMotionStream:
    """Convert wand IMU coordinator updates into normalized browser motion events."""

    def __init__(
        self,
        hass: HomeAssistant,
        mcw,
        imu_coordinator: DataUpdateCoordinator[list[dict[str, float]]],
        buttons_coordinator: DataUpdateCoordinator[dict[str, bool]],
        spell_coordinator: DataUpdateCoordinator[str],
        connection_coordinator: DataUpdateCoordinator[bool],
        fluid_config: dict[str, Any],
    ) -> None:
        """Initialize the motion stream."""
        self._hass = hass
        self._mcw = mcw
        self._imu_coordinator = imu_coordinator
        self._buttons_coordinator = buttons_coordinator
        self._spell_coordinator = spell_coordinator
        self._connection_coordinator = connection_coordinator
        self._fluid_config = fluid_config
        self._tracker = SpellTracker(detector=None)
        self._tracker.start()
        self._button_all = False
        self._any_button = False
        self._last_point: tuple[float, float] | None = None
        self._fluid_x = 0.5
        self._fluid_y = 0.5
        self._fluid_active = False
        self._last_motion_at: float | None = None
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._unsubscribers: list[Callable[[], None]] = []
        self._sequence = 0
        self._imu_start_task: asyncio.Task[None] | None = None
        self._last_imu_start_attempt_at = 0.0
        self._imu_start_error: str | None = None
        self._last_payload: dict[str, Any] = self._status_payload()

    def start(self) -> None:
        """Start listening for coordinator updates."""
        self._unsubscribers = [
            self._imu_coordinator.async_add_listener(self._handle_imu_update),
            self._buttons_coordinator.async_add_listener(self._handle_buttons_update),
            self._spell_coordinator.async_add_listener(self._handle_status_update),
            self._connection_coordinator.async_add_listener(self._handle_status_update),
        ]
        self._handle_buttons_update()
        self._handle_status_update()

    def stop(self) -> None:
        """Stop listening and close subscribers."""
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        for queue in list(self._subscribers):
            while queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            queue.put_nowait({"type": "close"})
        self._subscribers.clear()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Subscribe to motion events."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=32)
        self._subscribers.add(queue)
        queue.put_nowait(self._last_payload)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Unsubscribe from motion events."""
        self._subscribers.discard(queue)

    @callback
    def _handle_buttons_update(self) -> None:
        """Handle button state changes."""
        any_button = False
        casting_combo = False
        if self._buttons_coordinator.data:
            any_button = any(
                bool(value)
                for key, value in self._buttons_coordinator.data.items()
                if key.startswith("button_")
            )
            casting_combo = _is_casting_button_combo(self._buttons_coordinator.data)

        was_button_all = self._button_all
        if casting_combo and not was_button_all:
            self._tracker.start()
            self._last_point = None
            self._reset_fluid_pointer()
            self._fluid_active = True
        elif not casting_combo and was_button_all:
            self._fluid_active = False
            self._last_point = None

        self._button_all = casting_combo
        self._any_button = any_button
        self._publish(self._status_payload())

    @callback
    def _handle_status_update(self) -> None:
        """Publish non-motion state updates."""
        self._publish(self._status_payload())

    @callback
    def _handle_imu_update(self) -> None:
        """Handle updated IMU data."""
        imu_data = self._imu_coordinator.data
        if not imu_data:
            return

        for sample in imu_data:
            imu_sample = {
                "accel_x": _finite_float(sample.get("accel_x", 0.0)),
                "accel_y": _finite_float(sample.get("accel_y", 0.0)),
                "accel_z": _finite_float(sample.get("accel_z", 0.0)),
                "gyro_x": _finite_float(sample.get("gyro_x", 0.0)),
                "gyro_y": _finite_float(sample.get("gyro_y", 0.0)),
                "gyro_z": _finite_float(sample.get("gyro_z", 0.0)),
            }
            raw_motion = sum(abs(value) for value in imu_sample.values())
            point = self._tracker.update(
                ax=imu_sample["accel_y"],
                ay=-imu_sample["accel_x"],
                az=imu_sample["accel_z"],
                gx=imu_sample["gyro_y"],
                gy=-imu_sample["gyro_x"],
                gz=imu_sample["gyro_z"],
            )

            if point is None:
                if self._button_all:
                    self._publish(self._status_payload())
                continue

            x = max(
                0.0,
                min(CANVAS_WIDTH, _finite_float(point[0]) + (CANVAS_WIDTH / 2)),
            )
            y = max(
                0.0,
                min(CANVAS_HEIGHT, _finite_float(point[1]) + (CANVAS_HEIGHT / 2)),
            )
            dx = 0.0
            dy = 0.0
            if self._last_point is not None:
                dx = x - self._last_point[0]
                dy = y - self._last_point[1]
            self._last_point = (x, y)
            motion_pixels = (dx * dx + dy * dy) ** 0.5
            if not self._button_all:
                continue

            self._fluid_x = x / CANVAS_WIDTH
            self._fluid_y = y / CANVAS_HEIGHT
            self._fluid_active = True
            self._last_motion_at = monotonic()

            self._publish(
                {
                    "type": "motion",
                    "x": self._fluid_x,
                    "y": self._fluid_y,
                    "dx": dx / CANVAS_WIDTH,
                    "dy": dy / CANVAS_HEIGHT,
                    "active": True,
                    "tracker_x": x / CANVAS_WIDTH,
                    "tracker_y": y / CANVAS_HEIGHT,
                    "drawing": self._button_all,
                    "any_button": self._any_button,
                    "button_all": self._button_all,
                    "button_combo": self._button_all,
                    "connected": self._connection_coordinator.data is True,
                    "has_motion": True,
                    "motion_pixels": max(round(raw_motion, 2), round(motion_pixels, 2)),
                    "source": "spell_tracker",
                    "spell": self._spell_coordinator.data or "awaiting",
                    "ts": time(),
                }
            )

    def _status_payload(self) -> dict[str, Any]:
        """Return the current non-motion visualizer status."""
        return {
            "type": "status",
            "x": self._fluid_x,
            "y": self._fluid_y,
            "dx": 0.0,
            "dy": 0.0,
            "drawing": self._button_all,
            "active": self._fluid_active,
            "any_button": self._any_button,
            "button_all": self._button_all,
            "button_combo": self._button_all,
            "connected": self._connection_coordinator.data is True,
            "has_motion": (
                self._last_motion_at is not None
                and monotonic() - self._last_motion_at < HEARTBEAT_INTERVAL * 2
            ),
            "source": "fluid_pointer",
            "spell": self._spell_coordinator.data or "awaiting",
            "fluid_config": dict(self._fluid_config),
            "ts": time(),
        }

    def _publish(self, payload: dict[str, Any]) -> None:
        """Publish a payload to all subscribers, dropping stale frames."""
        self._sequence += 1
        payload["sequence"] = self._sequence
        self._last_payload = payload
        for queue in list(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                _LOGGER.debug("Fluid visualizer subscriber queue is still full")

    def heartbeat_payload(self) -> dict[str, Any]:
        """Return a heartbeat payload that keeps browser event streams alive."""
        payload = self._status_payload()
        payload["type"] = "heartbeat"
        return payload

    def publish_config_update(self) -> None:
        """Publish current runtime fluid config to open visualizers."""
        self._publish(self._status_payload())

    def state_payload(self) -> dict[str, Any]:
        """Return the latest browser-consumable wand state."""
        has_recent_motion = (
            self._last_motion_at is not None
            and monotonic() - self._last_motion_at < HEARTBEAT_INTERVAL * 2
        )
        payload = dict(self._last_payload)
        payload["connected"] = self._connection_coordinator.data is True
        payload["spell"] = self._spell_coordinator.data or payload.get("spell") or "awaiting"
        payload["any_button"] = self._any_button
        payload["button_all"] = self._button_all
        payload["button_combo"] = self._button_all
        payload["imu_start_error"] = self._imu_start_error
        payload["motion_age"] = (
            round(monotonic() - self._last_motion_at, 2)
            if self._last_motion_at is not None
            else None
        )
        payload["has_motion"] = has_recent_motion
        payload["status_detail"] = self._status_detail(payload)
        payload["fluid_config"] = dict(self._fluid_config)
        payload["server_ts"] = time()
        return payload

    def ensure_imu_streaming(self) -> None:
        """Request IMU streaming when the fluid page is being viewed."""
        now = monotonic()
        if self._connection_coordinator.data is not True:
            return
        if self._imu_start_task is not None and not self._imu_start_task.done():
            return
        if now - self._last_imu_start_attempt_at < 10:
            return

        self._last_imu_start_attempt_at = now
        self._imu_start_task = self._hass.async_create_task(self._async_start_imu_streaming())

    async def _async_start_imu_streaming(self) -> None:
        """Start IMU streaming without blocking the fluid state endpoint."""
        try:
            await self._mcw.imu_streaming_start()
            self._imu_start_error = None
        except Exception as err:
            self._imu_start_error = str(err)
            _LOGGER.debug("Fluid canvas failed to start IMU streaming: %s", err)

    def _status_detail(self, payload: dict[str, Any]) -> str:
        """Return a compact debug status for the fluid page."""
        if not payload.get("connected"):
            return "WAND DISCONNECTED"
        if payload.get("imu_start_error"):
            return f"IMU START ERROR: {payload['imu_start_error']}"
        if payload.get("has_motion"):
            return "IMU OK"
        return "WAITING FOR WAND IMU DATA"

    def _raw_imu_payload(self, sample: dict[str, float]) -> dict[str, Any]:
        """Map raw wand IMU data into a stable centered fluid pointer."""
        gyro_x = _finite_float(sample.get("gyro_x", 0.0))
        gyro_y = _finite_float(sample.get("gyro_y", 0.0))
        gyro_z = _finite_float(sample.get("gyro_z", 0.0))
        accel_x = _finite_float(sample.get("accel_x", 0.0))
        accel_y = _finite_float(sample.get("accel_y", 0.0))

        dx = (gyro_y * RAW_IMU_GYRO_SCALE) + (accel_y * RAW_IMU_ACCEL_SCALE)
        dy = (gyro_x * RAW_IMU_GYRO_SCALE) - (accel_x * RAW_IMU_ACCEL_SCALE)
        dx = max(-MAX_POINTER_STEP, min(MAX_POINTER_STEP, dx))
        dy = max(-MAX_POINTER_STEP, min(MAX_POINTER_STEP, dy))

        raw_motion = abs(gyro_x) + abs(gyro_y) + abs(gyro_z) + abs(accel_x) + abs(accel_y)
        active = self._button_all
        if active and not self._fluid_active:
            self._reset_fluid_pointer()

        if active:
            self._fluid_x = max(0.02, min(0.98, self._fluid_x + dx))
            self._fluid_y = max(0.02, min(0.98, self._fluid_y + dy))
            self._last_motion_at = monotonic()

        self._fluid_active = active
        return {
            "type": "motion",
            "x": self._fluid_x,
            "y": self._fluid_y,
            "dx": dx,
            "dy": dy,
            "active": active,
            "drawing": self._button_all,
            "connected": self._connection_coordinator.data is True,
            "has_motion": True,
            "motion_pixels": round(raw_motion, 2),
            "source": "raw_imu",
            "spell": self._spell_coordinator.data or "awaiting",
            "ts": time(),
        }

    def synthetic_motion_payload(self) -> dict[str, Any]:
        """Return the current fluid pointer as drawable motion state."""
        payload = {
            "type": "motion" if self._fluid_active else "status",
            "x": self._fluid_x,
            "y": self._fluid_y,
            "dx": 0.0,
            "dy": 0.0,
            "active": self._fluid_active,
            "drawing": self._button_all,
            "connected": self._connection_coordinator.data is True,
            "has_motion": (
                self._last_motion_at is not None
                and monotonic() - self._last_motion_at < HEARTBEAT_INTERVAL * 2
            ),
            "motion_pixels": 0.0,
            "source": "fluid_pointer",
            "spell": self._spell_coordinator.data or "awaiting",
            "ts": time(),
            "sequence": self._sequence,
            "any_button": self._any_button,
            "button_all": self._button_all,
            "button_combo": self._button_all,
            "imu_start_error": self._imu_start_error,
        }
        payload["status_detail"] = self._status_detail(payload)
        payload["server_ts"] = time()
        return payload

    def _reset_fluid_pointer(self) -> None:
        """Start fluid movement from the middle of the canvas."""
        self._fluid_x = 0.5
        self._fluid_y = 0.5


class MagicCasterWandFluidPageView(HomeAssistantView):
    """Serve the WebGL fluid visualizer page."""

    requires_auth = False
    url = PAGE_URL
    name = f"api:{DOMAIN}:fluid"

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        """Return the visualizer HTML."""
        hass: HomeAssistant = request.app["hass"]
        return _render_fluid_page(hass, entry_id)


class MagicCasterWandFluidDefaultPageView(HomeAssistantView):
    """Serve the first configured WebGL fluid visualizer page."""

    requires_auth = False
    url = DEFAULT_PAGE_URL
    name = f"api:{DOMAIN}:fluid:default"

    async def get(self, request: web.Request) -> web.Response:
        """Return the default visualizer HTML."""
        hass: HomeAssistant = request.app["hass"]
        entry_id = _get_first_entry_key(hass)
        if entry_id is None:
            return web.Response(status=404, text="No Magic Caster Wand Fluid Effects entry found")

        return _render_fluid_page(hass, entry_id)


def _render_fluid_page(hass: HomeAssistant, entry_id: str) -> web.Response:
    """Render the WebGL fluid visualizer HTML for an entry key."""
    data = _get_entry_data(hass, entry_id)
    if data is None:
        return web.Response(status=404, text="Unknown Magic Caster Wand entry")

    html = hass.data[DOMAIN]["_fluid_index_html"]
    html = html.replace("__MCW_ENTRY_ID__", json.dumps(entry_id))
    html = html.replace("__MCW_EVENTS_URL__", json.dumps(EVENTS_URL.format(entry_id=entry_id)))
    html = html.replace("__MCW_STATE_URL__", json.dumps(STATE_URL.format(entry_id=entry_id)))
    html = html.replace("__MCW_CONFIG_URL__", json.dumps(CONFIG_URL.format(entry_id=entry_id)))
    html = html.replace("__MCW_SPELL_URL__", json.dumps(SPELL_URL.format(entry_id=entry_id)))
    html = html.replace("__MCW_STATIC_URL__", STATIC_URL)
    html = html.replace(
        "__MCW_FLUID_CONFIG__",
        json.dumps(data.get("fluid_config", build_fluid_config({}))),
    )
    return web.Response(text=html, content_type="text/html")


class MagicCasterWandFluidEventsView(HomeAssistantView):
    """Stream wand motion updates to the WebGL visualizer."""

    requires_auth = False
    url = EVENTS_URL
    name = f"api:{DOMAIN}:fluid:events"

    async def get(self, request: web.Request, entry_id: str) -> web.StreamResponse:
        """Return an SSE stream of wand motion updates."""
        hass: HomeAssistant = request.app["hass"]
        data = _get_entry_data(hass, entry_id)
        if data is None:
            return web.Response(status=404, text="Unknown Magic Caster Wand entry")

        stream: MagicCasterWandMotionStream = data["fluid_stream"]
        queue = stream.subscribe()
        response = web.StreamResponse(
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
        await response.prepare(request)
        await response.write(b"retry: 3000\n\n")

        try:
            while True:
                try:
                    payload = await asyncio.wait_for(
                        queue.get(),
                        timeout=HEARTBEAT_INTERVAL,
                    )
                except asyncio.TimeoutError:
                    payload = stream.heartbeat_payload()

                if payload.get("type") == "close":
                    break

                message = f"event: wand\ndata: {json.dumps(_json_safe(payload))}\n\n"
                await response.write(message.encode("utf-8"))
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            stream.unsubscribe(queue)

        return response


class MagicCasterWandFluidStateView(HomeAssistantView):
    """Serve the latest wand motion state as JSON."""

    requires_auth = False
    url = STATE_URL
    name = f"api:{DOMAIN}:fluid:state"

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        """Return the latest wand motion state."""
        hass: HomeAssistant = request.app["hass"]
        return await _render_state(hass, entry_id)


class MagicCasterWandFluidDefaultStateView(HomeAssistantView):
    """Serve the latest wand motion state for the first configured wand."""

    requires_auth = False
    url = DEFAULT_STATE_URL
    name = f"api:{DOMAIN}:fluid:state:default"

    async def get(self, request: web.Request) -> web.Response:
        """Return the default wand motion state."""
        hass: HomeAssistant = request.app["hass"]
        entry_id = _get_first_entry_key(hass)
        if entry_id is None:
            return web.json_response(
                {
                    "type": "status",
                    "connected": False,
                    "has_motion": False,
                    "spell": "awaiting",
                    "error": "No Magic Caster Wand Fluid Effects entry found",
                },
                status=404,
            )

        return await _render_state(hass, entry_id)


class MagicCasterWandFluidConfigView(HomeAssistantView):
    """Update runtime fluid configuration from the iframe controls."""

    requires_auth = False
    url = CONFIG_URL
    name = f"api:{DOMAIN}:fluid:config"

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        """Return current runtime fluid configuration."""
        hass: HomeAssistant = request.app["hass"]
        data = _get_entry_data(hass, entry_id)
        if data is None:
            return web.json_response(
                {"error": "Unknown Magic Caster Wand entry"},
                status=404,
            )

        sync_fluid_runtime_config(data)
        return web.json_response({"fluid_config": _json_safe(data["fluid_config"])})

    async def post(self, request: web.Request, entry_id: str) -> web.Response:
        """Update and optionally persist fluid configuration."""
        hass: HomeAssistant = request.app["hass"]
        data = _get_entry_data(hass, entry_id)
        if data is None:
            return web.json_response(
                {"error": "Unknown Magic Caster Wand entry"},
                status=404,
            )

        body = await request.json()
        action = body.get("action", "apply")
        if action == "default":
            data["fluid_config"].update(build_fluid_config({}))
        else:
            update_fluid_runtime_values(data, body.get("config", {}))

        sync_fluid_runtime_config(data)
        if body.get("persist") or action == "save":
            persist_fluid_options(hass, data)

        stream: MagicCasterWandMotionStream | None = data.get("fluid_stream")
        if stream is not None:
            stream.publish_config_update()

        return web.json_response({"fluid_config": _json_safe(data["fluid_config"])})


class MagicCasterWandFluidSpellView(HomeAssistantView):
    """Recognize mouse or touch-drawn spells from the WebGL fluid page."""

    requires_auth = False
    url = SPELL_URL
    name = f"api:{DOMAIN}:fluid:spell"

    async def post(self, request: web.Request, entry_id: str) -> web.Response:
        """Detect a spell from a browser-drawn path."""
        hass: HomeAssistant = request.app["hass"]
        data = _get_entry_data(hass, entry_id)
        if data is None:
            return web.json_response(
                {"recognized": False, "error": "Unknown Magic Caster Wand entry"},
                status=404,
            )

        try:
            body = await request.json()
        except Exception:
            return web.json_response(
                {"recognized": False, "error": "Invalid JSON"},
                status=400,
            )

        positions, error = _normalise_drawn_spell_points(body.get("points", []))
        if positions is None:
            return web.json_response({"recognized": False, "error": error})

        mcw = data.get("mcw")
        tracker = getattr(mcw, "_spell_tracker", None)
        detector = getattr(tracker, "detector", None)
        if detector is None:
            return web.json_response(
                {"recognized": False, "error": "Spell detector is not available"}
            )

        try:
            spell_name = await detector.detect(positions, np.float32(0.95))
        except Exception as err:
            _LOGGER.warning("Drawn spell recognition failed: %s", err)
            return web.json_response(
                {"recognized": False, "error": "Spell recognition failed"},
                status=502,
            )
        if not spell_name:
            return web.json_response({"recognized": False, "spell": "awaiting"})

        learn_mode = body.get("learn") is True
        drawn_spell_name = f"draw_{spell_name}"
        if not learn_mode:
            draw_spell_coordinator = data.get("draw_spell_coordinator")
            if draw_spell_coordinator is not None:
                draw_spell_coordinator.async_set_updated_data(drawn_spell_name)

        stream: MagicCasterWandMotionStream | None = data.get("fluid_stream")
        if stream is not None:
            stream.publish_config_update()

        return web.json_response(
            {
                "recognized": True,
                "spell": spell_name,
                "automation_spell": None if learn_mode else drawn_spell_name,
                "source": "learn" if learn_mode else "draw",
            }
        )


async def _render_state(hass: HomeAssistant, entry_id: str) -> web.Response:
    """Return the latest browser-consumable wand state."""
    data = _get_entry_data(hass, entry_id)
    if data is None:
        return web.json_response(
            {
                "type": "status",
                "connected": False,
                "has_motion": False,
                "spell": "awaiting",
                "error": "Unknown Magic Caster Wand entry",
            },
            status=404,
        )

    stream: MagicCasterWandMotionStream = data["fluid_stream"]
    try:
        stream.ensure_imu_streaming()
        payload = stream.state_payload()
    except Exception as err:
        _LOGGER.exception("Fluid state endpoint failed")
        payload = stream.synthetic_motion_payload()
        payload["error"] = str(err)

    return web.json_response(_json_safe(payload))


def _get_entry_data(hass: HomeAssistant, entry_key: str) -> dict[str, Any] | None:
    """Get entry data by config entry id, address suffix, or mcw-prefixed id."""
    domain_data = hass.data.get(DOMAIN, {})
    direct_match = domain_data.get(entry_key)
    if isinstance(direct_match, dict) and "fluid_stream" in direct_match:
        return direct_match

    normalized_key = entry_key.lower().replace("mcwf_", "").replace("mcw_", "")
    for data in domain_data.values():
        if not isinstance(data, dict):
            continue

        address = data.get("address")
        if not isinstance(address, str):
            continue

        identifier = address.replace(":", "").lower()[-8:]
        if normalized_key == identifier:
            return data

    return None


def _get_first_entry_key(hass: HomeAssistant) -> str | None:
    """Return the first configured fluid entry id."""
    for entry_key, data in hass.data.get(DOMAIN, {}).items():
        if isinstance(data, dict) and "fluid_stream" in data:
            return entry_key
    return None


def _read_index_html() -> str:
    """Read the fluid visualizer HTML template."""
    return (FRONTEND_PATH / "index.html").read_text(encoding="utf-8")


def _finite_float(value: Any, default: float = 0.0) -> float:
    """Return a JSON-safe finite float."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if isfinite(numeric) else default


def _json_safe(value: Any) -> Any:
    """Convert payload data into values Home Assistant can JSON encode."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, Real) and not isinstance(value, bool):
        return _finite_float(value)
    return value


def _is_casting_button_combo(buttons: Mapping[str, Any]) -> bool:
    """Return true for one button from 1/2 plus one from 3/4."""
    upper_pair = bool(buttons.get("button_1")) or bool(buttons.get("button_2"))
    lower_pair = bool(buttons.get("button_3")) or bool(buttons.get("button_4"))
    return upper_pair and lower_pair


def _normalise_drawn_spell_points(points: Any) -> tuple[np.ndarray | None, str | None]:
    """Convert browser stroke points into detector-ready normalized positions."""
    if not isinstance(points, list):
        return None, "Spell path must be a list"

    parsed: list[tuple[float, float]] = []
    for point in points:
        if isinstance(point, Mapping):
            raw_x = point.get("x")
            raw_y = point.get("y")
        elif isinstance(point, (list, tuple)) and len(point) >= 2:
            raw_x = point[0]
            raw_y = point[1]
        else:
            continue

        x = _finite_float(raw_x, float("nan"))
        y = _finite_float(raw_y, float("nan"))
        if not isfinite(x) or not isfinite(y):
            continue

        if parsed and (x - parsed[-1][0]) ** 2 + (y - parsed[-1][1]) ** 2 < 0.000001:
            continue
        parsed.append((x, y))

    if len(parsed) < 8:
        return None, "Not enough drawn points"

    cumulative = [0.0]
    for index in range(1, len(parsed)):
        prev_x, prev_y = parsed[index - 1]
        x, y = parsed[index]
        cumulative.append(cumulative[-1] + ((x - prev_x) ** 2 + (y - prev_y) ** 2) ** 0.5)

    total_distance = cumulative[-1]
    if total_distance < 0.04:
        return None, "No meaningful movement detected"

    xs = [point[0] for point in parsed]
    ys = [point[1] for point in parsed]
    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)
    bbox_size = max(max_x - min_x, max_y - min_y)
    if bbox_size <= 0:
        return None, "No drawable spell area"

    samples = np.zeros((50, 2), dtype=np.float32)
    segment_index = 1
    for sample_index in range(50):
        target_distance = total_distance * (sample_index / 49)
        while segment_index < len(cumulative) - 1 and cumulative[segment_index] < target_distance:
            segment_index += 1

        prev_distance = cumulative[segment_index - 1]
        next_distance = cumulative[segment_index]
        span = next_distance - prev_distance
        ratio = 0.0 if span <= 0 else (target_distance - prev_distance) / span
        prev_x, prev_y = parsed[segment_index - 1]
        next_x, next_y = parsed[segment_index]
        x = prev_x + (next_x - prev_x) * ratio
        y = prev_y + (next_y - prev_y) * ratio
        samples[sample_index, 0] = np.float32((x - min_x) / bbox_size)
        samples[sample_index, 1] = np.float32((y - min_y) / bbox_size)

    return samples, None


def sync_fluid_runtime_config(data: dict[str, Any]) -> None:
    """Apply runtime-only selections to the browser fluid config."""
    config = data.setdefault("fluid_config", build_fluid_config({}))
    for switch_key, switch in FLUID_RUNTIME_SWITCHES.items():
        config[switch["js_key"]] = bool(data.get(switch_key, switch["default"]))

    color_name = data.get("casting_led_color", DEFAULT_CASTING_LED_COLOR)
    r, g, b = CASTING_LED_COLORS.get(
        color_name,
        CASTING_LED_COLORS[DEFAULT_CASTING_LED_COLOR],
    )
    config["LED_COLOR_NAME"] = color_name
    config["LED_COLOR"] = [r, g, b]
    config["CASTING_LED_COLORS"] = list(CASTING_LED_COLORS)


def update_fluid_runtime_values(data: dict[str, Any], values: Mapping[str, Any]) -> None:
    """Apply browser or entity updates to runtime fluid config values."""
    if not isinstance(values, Mapping):
        return

    config = data.setdefault("fluid_config", build_fluid_config({}))
    valid_js_keys = {option["js_key"]: option for option in FLUID_CONFIG_OPTIONS.values()}
    runtime_js_keys = {
        switch["js_key"]: switch_key for switch_key, switch in FLUID_RUNTIME_SWITCHES.items()
    }
    for js_key, value in values.items():
        if js_key == "LED_COLOR_NAME":
            if value in CASTING_LED_COLORS:
                data["casting_led_color"] = value
                mcw = data.get("mcw")
                if mcw is not None:
                    mcw.casting_led_color = CASTING_LED_COLORS[value]
                select_entity = data.get("casting_led_color_entity")
                select_update = getattr(
                    select_entity,
                    "set_current_option_from_fluid",
                    None,
                )
                if callable(select_update):
                    select_update(value)
            continue

        switch_key = runtime_js_keys.get(js_key)
        if switch_key is not None:
            data[switch_key] = bool(value)
            continue

        option = valid_js_keys.get(js_key)
        if option is None:
            continue

        option_type = option["type"]
        if option_type is bool:
            config[js_key] = bool(value)
            continue

        numeric = _finite_float(value, option["default"])
        numeric = max(option["min"], min(option["max"], numeric))
        config[js_key] = int(numeric) if option_type is int else numeric


def persist_fluid_options(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Persist current runtime fluid config into config entry options."""
    entry: ConfigEntry | None = data.get("entry")
    if entry is None:
        return

    options = dict(entry.options)
    options[CONF_CASTING_LED_COLOR] = data.get(
        "casting_led_color",
        DEFAULT_CASTING_LED_COLOR,
    )
    for switch_key, switch in FLUID_RUNTIME_SWITCHES.items():
        options[switch_key] = bool(data.get(switch_key, switch["default"]))

    js_to_option = {
        option["js_key"]: (option_key, option)
        for option_key, option in FLUID_CONFIG_OPTIONS.items()
    }
    for js_key, value in data.get("fluid_config", {}).items():
        mapped = js_to_option.get(js_key)
        if mapped is None:
            continue
        option_key, option = mapped
        option_type = option["type"]
        if option_type is bool:
            options[option_key] = bool(value)
        else:
            numeric = _finite_float(value, option["default"])
            numeric = max(option["min"], min(option["max"], numeric))
            options[option_key] = int(numeric) if option_type is int else numeric

    hass.config_entries.async_update_entry(entry, options=options)


def build_fluid_config(options: Mapping[str, Any]) -> dict[str, Any]:
    """Build WebGL fluid config values from Home Assistant options."""
    config: dict[str, Any] = {}
    for option_key, option in FLUID_CONFIG_OPTIONS.items():
        config[option["js_key"]] = options.get(option_key, option["default"])
    return config
