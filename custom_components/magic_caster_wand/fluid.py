"""WebGL fluid visualizer for Magic Caster Wand motion."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from time import time
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
PAGE_URL = f"/api/{DOMAIN}/fluid/{{entry_id}}"
EVENTS_URL = f"/api/{DOMAIN}/fluid/{{entry_id}}/events"


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
        hass.http.register_view(MagicCasterWandFluidPageView())
        hass.http.register_view(MagicCasterWandFluidEventsView())
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
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._unsubscribers: list[Callable[[], None]] = []
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

            self._publish(
                {
                    "type": "motion",
                    "x": x / CANVAS_WIDTH,
                    "y": y / CANVAS_HEIGHT,
                    "dx": dx / CANVAS_WIDTH,
                    "dy": dy / CANVAS_HEIGHT,
                    "drawing": self._button_all,
                    "connected": self._connection_coordinator.data is True,
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
            "spell": self._spell_coordinator.data or "awaiting",
            "ts": time(),
        }

    def _publish(self, payload: dict[str, Any]) -> None:
        """Publish a payload to all subscribers, dropping stale frames."""
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


class MagicCasterWandFluidPageView(HomeAssistantView):
    """Serve the WebGL fluid visualizer page."""

    requires_auth = True
    url = PAGE_URL
    name = f"api:{DOMAIN}:fluid"

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        """Return the visualizer HTML."""
        hass: HomeAssistant = request.app["hass"]
        data = _get_entry_data(hass, entry_id)
        if data is None:
            return web.Response(status=404, text="Unknown Magic Caster Wand entry")

        html = hass.data[DOMAIN]["_fluid_index_html"]
        html = html.replace("__MCW_ENTRY_ID__", json.dumps(entry_id))
        html = html.replace("__MCW_EVENTS_URL__", json.dumps(EVENTS_URL.format(entry_id=entry_id)))
        html = html.replace("__MCW_STATIC_URL__", STATIC_URL)
        html = html.replace(
            "__MCW_FLUID_CONFIG__",
            json.dumps(data.get("fluid_config", build_fluid_config({}))),
        )
        return web.Response(text=html, content_type="text/html")


class MagicCasterWandFluidEventsView(HomeAssistantView):
    """Stream wand motion updates to the WebGL visualizer."""

    requires_auth = True
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
            }
        )
        await response.prepare(request)

        try:
            while True:
                payload = await queue.get()
                if payload.get("type") == "close":
                    break

                message = f"event: wand\ndata: {json.dumps(payload)}\n\n"
                await response.write(message.encode("utf-8"))
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            stream.unsubscribe(queue)

        return response


def _get_entry_data(hass: HomeAssistant, entry_key: str) -> dict[str, Any] | None:
    """Get entry data by config entry id, address suffix, or mcw-prefixed id."""
    domain_data = hass.data.get(DOMAIN, {})
    direct_match = domain_data.get(entry_key)
    if isinstance(direct_match, dict) and "fluid_stream" in direct_match:
        return direct_match

    normalized_key = entry_key.lower().replace("mcw_", "")
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


def _read_index_html() -> str:
    """Read the fluid visualizer HTML template."""
    return (FRONTEND_PATH / "index.html").read_text(encoding="utf-8")


def build_fluid_config(options: Mapping[str, Any]) -> dict[str, Any]:
    """Build WebGL fluid config values from Home Assistant options."""
    config: dict[str, Any] = {}
    for option_key, option in FLUID_CONFIG_OPTIONS.items():
        config[option["js_key"]] = options.get(option_key, option["default"])
    return config
