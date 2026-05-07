"""Constants for Magic Caster Wand Fluid Effects BLE integration."""

DOMAIN = "magic_caster_wand_fluid"
MANUFACTURER = "Warner Bros. Entertainment Inc."
DEFAULT_SCAN_INTERVAL = 300
CONF_TFLITE_URL = "tflite_url"
DEFAULT_TFLITE_URL = "http://b5e3f765-tflite-server:8000"
CONF_SPELL_TIMEOUT = "spell_timeout"
DEFAULT_SPELL_TIMEOUT = 0
CONF_CASTING_LED_COLOR = "casting_led_color"

CONF_FLUID_SIM_RESOLUTION = "fluid_sim_resolution"
CONF_FLUID_DYE_RESOLUTION = "fluid_dye_resolution"
CONF_FLUID_DENSITY_DISSIPATION = "fluid_density_dissipation"
CONF_FLUID_VELOCITY_DISSIPATION = "fluid_velocity_dissipation"
CONF_FLUID_PRESSURE = "fluid_pressure"
CONF_FLUID_PRESSURE_ITERATIONS = "fluid_pressure_iterations"
CONF_FLUID_CURL = "fluid_curl"
CONF_FLUID_SPLAT_RADIUS = "fluid_splat_radius"
CONF_FLUID_SPLAT_FORCE = "fluid_splat_force"
CONF_FLUID_SHADING = "fluid_shading"
CONF_FLUID_COLORFUL = "fluid_colorful"
CONF_FLUID_COLOR_UPDATE_SPEED = "fluid_color_update_speed"
CONF_FLUID_BLOOM = "fluid_bloom"
CONF_FLUID_BLOOM_INTENSITY = "fluid_bloom_intensity"
CONF_FLUID_BLOOM_THRESHOLD = "fluid_bloom_threshold"
CONF_FLUID_SUNRAYS = "fluid_sunrays"
CONF_FLUID_SUNRAYS_WEIGHT = "fluid_sunrays_weight"
CONF_FLUID_MATCH_LED_COLOR = "fluid_match_led_color"
CONF_FLUID_SHOW_PAGE_CONTROLS = "fluid_show_page_controls"

FLUID_CONFIG_OPTIONS = {
    CONF_FLUID_SIM_RESOLUTION: {
        "js_key": "SIM_RESOLUTION",
        "default": 256,
        "type": int,
        "min": 32,
        "max": 256,
    },
    CONF_FLUID_DYE_RESOLUTION: {
        "js_key": "DYE_RESOLUTION",
        "default": 1024,
        "type": int,
        "min": 128,
        "max": 2048,
    },
    CONF_FLUID_DENSITY_DISSIPATION: {
        "js_key": "DENSITY_DISSIPATION",
        "default": 2.5,
        "type": float,
        "min": 0,
        "max": 4,
    },
    CONF_FLUID_VELOCITY_DISSIPATION: {
        "js_key": "VELOCITY_DISSIPATION",
        "default": 2.5,
        "type": float,
        "min": 0,
        "max": 4,
    },
    CONF_FLUID_PRESSURE: {
        "js_key": "PRESSURE",
        "default": 0.2,
        "type": float,
        "min": 0,
        "max": 1,
    },
    CONF_FLUID_PRESSURE_ITERATIONS: {
        "js_key": "PRESSURE_ITERATIONS",
        "default": 20,
        "type": int,
        "min": 1,
        "max": 80,
    },
    CONF_FLUID_CURL: {
        "js_key": "CURL",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 50,
    },
    CONF_FLUID_SPLAT_RADIUS: {
        "js_key": "SPLAT_RADIUS",
        "default": 0.07,
        "type": float,
        "min": 0.01,
        "max": 1,
    },
    CONF_FLUID_SPLAT_FORCE: {
        "js_key": "SPLAT_FORCE",
        "default": 6000,
        "type": int,
        "min": 100,
        "max": 20000,
    },
    CONF_FLUID_SHADING: {
        "js_key": "SHADING",
        "default": True,
        "type": bool,
    },
    CONF_FLUID_COLORFUL: {
        "js_key": "COLORFUL",
        "default": False,
        "type": bool,
    },
    CONF_FLUID_COLOR_UPDATE_SPEED: {
        "js_key": "COLOR_UPDATE_SPEED",
        "default": 4,
        "type": float,
        "min": 1,
        "max": 20,
    },
    CONF_FLUID_BLOOM: {
        "js_key": "BLOOM",
        "default": True,
        "type": bool,
    },
    CONF_FLUID_BLOOM_INTENSITY: {
        "js_key": "BLOOM_INTENSITY",
        "default": 1,
        "type": float,
        "min": 0,
        "max": 3,
    },
    CONF_FLUID_BLOOM_THRESHOLD: {
        "js_key": "BLOOM_THRESHOLD",
        "default": 0.5,
        "type": float,
        "min": 0,
        "max": 1,
    },
    CONF_FLUID_SUNRAYS: {
        "js_key": "SUNRAYS",
        "default": True,
        "type": bool,
    },
    CONF_FLUID_SUNRAYS_WEIGHT: {
        "js_key": "SUNRAYS_WEIGHT",
        "default": 1,
        "type": float,
        "min": 0,
        "max": 2,
    },
}

# Casting LED color options (name -> RGB tuple)
CASTING_LED_COLORS = {
    "White": (255, 255, 255),
    "Red": (255, 0, 0),
    "Green": (0, 255, 0),
    "Blue": (0, 0, 255),
    "Yellow": (255, 255, 0),
    "Cyan": (0, 255, 255),
    "Magenta": (255, 0, 255),
    "Orange": (255, 96, 0),
    "Purple": (128, 0, 128),
}
DEFAULT_CASTING_LED_COLOR = "White"

FLUID_RUNTIME_SWITCHES = {
    CONF_FLUID_MATCH_LED_COLOR: {
        "js_key": "MATCH_LED_COLOR",
        "default": False,
        "name": "Match LED Color",
        "icon": "mdi:palette-swatch",
    },
    CONF_FLUID_SHOW_PAGE_CONTROLS: {
        "js_key": "SHOW_PAGE_CONTROLS",
        "default": False,
        "name": "Fluid Page Controls",
        "icon": "mdi:tune-variant",
    },
}

# Dispatcher signals
SIGNAL_SPELL_MODE_CHANGED = f"{DOMAIN}_spell_mode_changed"
