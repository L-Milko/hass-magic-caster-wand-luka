"""WebGL fluid visualizer for Magic Caster Wand motion."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from time import monotonic, time
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, FLUID_CONFIG_OPTIONS
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
HEARTBEAT_INTERVAL = 10
MOTION_ACTIVE_PIXELS = 2.0


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
        hass.data[DOMAIN]["_fluid_static_registered"] = True

    stream = MagicCasterWandMotionStream(
        hass=hass,
        imu_coordinator=data["imu_coordinator"],
        buttons_coordinator=data["buttons_coordinator"],
        spell_coordinator=data["spell_coordinator"],
        connection_coordinator=data["connection_coordinator"],
    )
    data["fluid_stream"] = stream
    data["fluid_config"] = build_fluid_config(entry.options)
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
        imu_coordinator: DataUpdateCoordinator[list[dict[str, float]]],
        buttons_coordinator: DataUpdateCoordinator[dict[str, bool]],
        spell_coordinator: DataUpdateCoordinator[str],
        connection_coordinator: DataUpdateCoordinator[bool],
    ) -> None:
        """Initialize the motion stream."""
        self._hass = hass
        self._imu_coordinator = imu_coordinator
        self._buttons_coordinator = buttons_coordinator
        self._spell_coordinator = spell_coordinator
        self._connection_coordinator = connection_coordinator
        self._tracker = SpellTracker(detector=None)
        self._tracker.start()
        self._button_all = False
        self._last_point: tuple[float, float] | None = None
        self._last_motion_at: float | None = None
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._unsubscribers: list[Callable[[], None]] = []
        self._sequence = 0
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
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=8)
        self._subscribers.add(queue)
        queue.put_nowait(self._last_payload)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Unsubscribe from motion events."""
        self._subscribers.discard(queue)

    @callback
    def _handle_buttons_update(self) -> None:
        """Handle button state changes."""
        button_all = False
        if self._buttons_coordinator.data:
            button_all = self._buttons_coordinator.data.get("button_all", False)

        if button_all and not self._button_all:
            self._tracker.start()
            self._last_point = None

        self._button_all = button_all
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
            point = self._tracker.update(
                ax=sample["accel_y"],
                ay=-sample["accel_x"],
                az=sample["accel_z"],
                gx=sample["gyro_y"],
                gy=-sample["gyro_x"],
                gz=sample["gyro_z"],
            )

            if point is None:
                continue

            x = max(0.0, min(CANVAS_WIDTH, point[0] + (CANVAS_WIDTH / 2)))
            y = max(0.0, min(CANVAS_HEIGHT, point[1] + (CANVAS_HEIGHT / 2)))
            dx = 0.0
            dy = 0.0
            if self._last_point is not None:
                dx = x - self._last_point[0]
                dy = y - self._last_point[1]
            self._last_point = (x, y)
            motion_pixels = (dx * dx + dy * dy) ** 0.5
            active = self._button_all or motion_pixels >= MOTION_ACTIVE_PIXELS
            self._last_motion_at = monotonic()

            self._publish(
                {
                    "type": "motion",
                    "x": x / CANVAS_WIDTH,
                    "y": y / CANVAS_HEIGHT,
                    "dx": dx / CANVAS_WIDTH,
                    "dy": dy / CANVAS_HEIGHT,
                    "active": active,
                    "drawing": self._button_all,
                    "connected": self._connection_coordinator.data is True,
                    "has_motion": True,
                    "motion_pixels": round(motion_pixels, 2),
                    "spell": self._spell_coordinator.data or "awaiting",
                    "ts": time(),
                }
            )

    def _status_payload(self) -> dict[str, Any]:
        """Return the current non-motion visualizer status."""
        return {
            "type": "status",
            "drawing": self._button_all,
            "connected": self._connection_coordinator.data is True,
            "has_motion": (
                self._last_motion_at is not None
                and monotonic() - self._last_motion_at < HEARTBEAT_INTERVAL * 2
            ),
            "spell": self._spell_coordinator.data or "awaiting",
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

    def state_payload(self) -> dict[str, Any]:
        """Return the latest browser-consumable wand state."""
        payload = dict(self._last_payload)
        payload["connected"] = self._connection_coordinator.data is True
        payload["spell"] = self._spell_coordinator.data or payload.get("spell") or "awaiting"
        payload["has_motion"] = (
            self._last_motion_at is not None
            and monotonic() - self._last_motion_at < HEARTBEAT_INTERVAL * 2
        )
        payload["server_ts"] = time()
        return payload


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

                message = f"event: wand\ndata: {json.dumps(payload)}\n\n"
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
        return _render_state(hass, entry_id)


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

        return _render_state(hass, entry_id)


def _render_state(hass: HomeAssistant, entry_id: str) -> web.Response:
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
    return web.json_response(stream.state_payload())


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


def build_fluid_config(options: Mapping[str, Any]) -> dict[str, Any]:
    """Build WebGL fluid config values from Home Assistant options."""
    config: dict[str, Any] = {}
    for option_key, option in FLUID_CONFIG_OPTIONS.items():
        config[option["js_key"]] = options.get(option_key, option["default"])
    return config
