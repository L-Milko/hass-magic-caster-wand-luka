const promoPopup = document.getElementsByClassName('promo')[0];

if (promoPopup && isMobile()) {
    setTimeout(() => {
        promoPopup.style.display = 'table';
    }, 20000);
}

// Simulation section default

const canvas = document.getElementsByTagName('canvas')[0];
resizeCanvas();

const castingLedColors = {
    White: [255, 255, 255],
    Red: [255, 0, 0],
    Green: [0, 255, 0],
    Blue: [0, 0, 255],
    Yellow: [255, 255, 0],
    Cyan: [0, 255, 255],
    Magenta: [255, 0, 255],
    Orange: [255, 96, 0],
    Purple: [128, 0, 128]
};

const fluidColorHues = {
    Red: 0,
    Orange: 0.055,
    Yellow: 0.16,
    Green: 0.33,
    Cyan: 0.5,
    Blue: 0.66,
    Purple: 0.78,
    Magenta: 0.83
};

let config = {
    SIM_RESOLUTION: 256,
    DYE_RESOLUTION: 1024,
    CAPTURE_RESOLUTION: 512,
    DENSITY_DISSIPATION: 2.5,
    VELOCITY_DISSIPATION: 2.5,
    PRESSURE: 0.2,
    PRESSURE_ITERATIONS: 20,
    CURL: 0,
    SPLAT_RADIUS: 0.07,
    SPLAT_FORCE: 6000,
    SHADING: true,
    COLORFUL: false,
    COLOR_UPDATE_SPEED: 4,
    MATCH_LED_COLOR: false,
    SHOW_PAGE_CONTROLS: false,
    LED_COLOR_NAME: 'White',
    LED_COLOR: castingLedColors.White.slice(),
    PAUSED: false,
    BACK_COLOR: { r: 0, g: 0, b: 0 },
    TRANSPARENT: false,
    BLOOM: true,
    BLOOM_ITERATIONS: 6,
    BLOOM_RESOLUTION: 256,
    BLOOM_INTENSITY: 1,
    BLOOM_THRESHOLD: 0.5,
    BLOOM_SOFT_KNEE: 0.7,
    SUNRAYS: true,
    SUNRAYS_RESOLUTION: 196,
    SUNRAYS_WEIGHT: 1,
}

const defaultFluidConfig = {
    SIM_RESOLUTION: 256,
    DYE_RESOLUTION: 1024,
    DENSITY_DISSIPATION: 2.5,
    VELOCITY_DISSIPATION: 2.5,
    PRESSURE: 0.2,
    PRESSURE_ITERATIONS: 20,
    CURL: 0,
    SPLAT_RADIUS: 0.07,
    SPLAT_FORCE: 6000,
    SHADING: true,
    LED_COLOR_NAME: 'White',
    MATCH_LED_COLOR: false,
    COLORFUL: false,
    COLOR_UPDATE_SPEED: 4,
    BLOOM: true,
    BLOOM_INTENSITY: 1,
    BLOOM_THRESHOLD: 0.5,
    SUNRAYS: true,
    SUNRAYS_WEIGHT: 1
};

function pointerPrototype () {
    this.id = -1;
    this.texcoordX = 0;
    this.texcoordY = 0;
    this.prevTexcoordX = 0;
    this.prevTexcoordY = 0;
    this.deltaX = 0;
    this.deltaY = 0;
    this.down = false;
    this.moved = false;
    this.color = [30, 0, 300];
}

function applyHomeAssistantConfig () {
    if (!window.MCW_FLUID_CONFIG) return;

    applyFluidConfig(window.MCW_FLUID_CONFIG, false);
}

function applyFluidConfig (nextConfig, refresh = true) {
    if (!nextConfig) return;

    if (nextConfig.CASTING_LED_COLORS && Array.isArray(nextConfig.CASTING_LED_COLORS)) {
        Object.keys(castingLedColors).forEach(key => delete castingLedColors[key]);
        nextConfig.CASTING_LED_COLORS.forEach(name => {
            if (Object.prototype.hasOwnProperty.call(defaultCastingLedColors, name)) {
                castingLedColors[name] = defaultCastingLedColors[name].slice();
            }
        });
    }

    let shouldResize = false;
    let shouldUpdateKeywords = false;
    Object.keys(nextConfig).forEach(key => {
        if (Object.prototype.hasOwnProperty.call(config, key)) {
            if ((key === 'SIM_RESOLUTION' || key === 'DYE_RESOLUTION') && config[key] !== nextConfig[key]) {
                shouldResize = true;
            }
            if ((key === 'SHADING' || key === 'BLOOM' || key === 'SUNRAYS') && config[key] !== nextConfig[key]) {
                shouldUpdateKeywords = true;
            }
            config[key] = nextConfig[key];
        }
    });
    if (Object.prototype.hasOwnProperty.call(nextConfig, 'LED_COLOR_NAME')) {
        const colorName = String(nextConfig.LED_COLOR_NAME);
        if (Object.prototype.hasOwnProperty.call(castingLedColors, colorName)) {
            config.LED_COLOR_NAME = colorName;
            config.LED_COLOR = castingLedColors[colorName].slice();
        }
    }
    if (Array.isArray(nextConfig.LED_COLOR)) config.LED_COLOR = nextConfig.LED_COLOR;
    if (Object.prototype.hasOwnProperty.call(nextConfig, 'MATCH_LED_COLOR')) {
        config.MATCH_LED_COLOR = nextConfig.MATCH_LED_COLOR === true;
    }
    if (Object.prototype.hasOwnProperty.call(nextConfig, 'SHOW_PAGE_CONTROLS')) {
        config.SHOW_PAGE_CONTROLS = nextConfig.SHOW_PAGE_CONTROLS === true;
    }

    if (refresh && shouldResize) initFramebuffers();
    if (refresh && shouldUpdateKeywords) updateKeywords();
    updateFluidControlPanel();
}

const defaultCastingLedColors = Object.fromEntries(
    Object.entries(castingLedColors).map(([name, rgb]) => [name, rgb.slice()])
);

const fluidControlSections = [
    ['grey', 'Resolution'],
    ['blue', 'Simulation'],
    ['white', 'Color'],
    ['green', 'Bloom'],
    ['yellow', 'Sunrays']
];

const fluidControlDefinitions = [
    { key: 'SIM_RESOLUTION', label: 'Simulation Resolution', type: 'number', min: 32, max: 256, step: 1, section: 'grey' },
    { key: 'DYE_RESOLUTION', label: 'Dye Resolution', type: 'number', min: 128, max: 2048, step: 1, section: 'grey' },
    { key: 'DENSITY_DISSIPATION', label: 'Density Dissipation', type: 'number', min: 0, max: 4, step: 0.01, section: 'blue' },
    { key: 'VELOCITY_DISSIPATION', label: 'Velocity Dissipation', type: 'number', min: 0, max: 4, step: 0.01, section: 'blue' },
    { key: 'PRESSURE', label: 'Pressure', type: 'number', min: 0, max: 1, step: 0.01, section: 'blue' },
    { key: 'PRESSURE_ITERATIONS', label: 'Pressure Iterations', type: 'number', min: 1, max: 80, step: 1, section: 'blue' },
    { key: 'CURL', label: 'Curl', type: 'number', min: 0, max: 50, step: 1, section: 'blue' },
    { key: 'SPLAT_RADIUS', label: 'Splat Radius', type: 'number', min: 0.01, max: 1, step: 0.01, section: 'blue' },
    { key: 'SPLAT_FORCE', label: 'Splat Force', type: 'number', min: 100, max: 20000, step: 100, section: 'blue' },
    { key: 'SHADING', label: 'Shading', type: 'boolean', section: 'blue' },
    { key: 'LED_COLOR_NAME', label: 'Wand Tip', type: 'select', options: () => Object.keys(castingLedColors), section: 'white' },
    { key: 'MATCH_LED_COLOR', label: 'Match LED Color', type: 'boolean', section: 'white' },
    { key: 'COLORFUL', label: 'Colorful Trails', type: 'boolean', section: 'white' },
    { key: 'COLOR_UPDATE_SPEED', label: 'Color Update Speed', type: 'number', min: 1, max: 20, step: 0.1, section: 'white' },
    { key: 'BLOOM', label: 'Bloom', type: 'boolean', section: 'green' },
    { key: 'BLOOM_INTENSITY', label: 'Bloom Intensity', type: 'number', min: 0, max: 3, step: 0.01, section: 'green' },
    { key: 'BLOOM_THRESHOLD', label: 'Bloom Threshold', type: 'number', min: 0, max: 1, step: 0.01, section: 'green' },
    { key: 'SUNRAYS', label: 'Sunrays', type: 'boolean', section: 'yellow' },
    { key: 'SUNRAYS_WEIGHT', label: 'Sunrays Weight', type: 'number', min: 0, max: 2, step: 0.01, section: 'yellow' }
];

let fluidControlPanel;
let fluidControlsDirty = false;
let fluidControlsCollapsed = false;
let fluidLiveUpdatePending = false;

function updateFluidControlPanel () {
    if (!fluidControlPanel) createFluidControlPanel();
    if (!fluidControlPanel) return;

    const showControls = config.SHOW_PAGE_CONTROLS === true;
    fluidControlPanel.hidden = !showControls;
    fluidControlPanel.style.display = showControls ? 'block' : 'none';
    fluidControlPanel.classList.toggle('is-collapsed', fluidControlsCollapsed);
    const collapseButton = fluidControlPanel.querySelector('[data-fluid-action="collapse"]');
    if (collapseButton) collapseButton.textContent = fluidControlsCollapsed ? '+' : '-';
    fluidControlDefinitions.forEach(definition => {
        const { key, type } = definition;
        const input = fluidControlPanel.querySelector(`[data-fluid-key="${key}"]`);
        const value = fluidControlPanel.querySelector(`[data-fluid-value="${key}"]`);
        if (!input) return;
        if (type === 'boolean') {
            input.checked = config[key] === true;
        } else if (type === 'select') {
            refreshSelectOptions(input, definition);
            input.value = config[key];
        } else {
            input.value = config[key];
            if (value) value.textContent = String(config[key]);
        }
    });
}

function createFluidControlPanel () {
    fluidControlPanel = document.createElement('div');
    fluidControlPanel.id = 'mcw-fluid-controls';
    fluidControlPanel.hidden = true;
    fluidControlPanel.innerHTML = '<div class="fluid-controls-header"><span>Fluid Effects</span><button type="button" class="fluid-collapse-button" data-fluid-action="collapse" title="Collapse controls">-</button></div><div class="fluid-controls-body"></div>';
    const body = fluidControlPanel.querySelector('.fluid-controls-body');

    fluidControlSections.forEach(([section, title]) => {
        const sectionEl = document.createElement('section');
        sectionEl.className = `fluid-control-section fluid-section-${section}`;
        sectionEl.innerHTML = `<div class="fluid-control-section-title">${title}</div>`;
        fluidControlDefinitions
            .filter(definition => definition.section === section)
            .forEach(definition => {
                sectionEl.appendChild(createFluidControlRow(definition));
            });
        body.appendChild(sectionEl);
    });

    const actions = document.createElement('div');
    actions.className = 'fluid-control-actions';
    actions.innerHTML = '<button type="button" data-fluid-action="save">Save</button><button type="button" data-fluid-action="default">Default</button>';
    body.appendChild(actions);
    document.body.appendChild(fluidControlPanel);

    fluidControlPanel.addEventListener('input', event => {
        const input = event.target.closest('[data-fluid-key]');
        if (!input) return;
        const key = input.dataset.fluidKey;
        const definition = fluidControlDefinitions.find(item => item.key === key);
        if (!definition) return;
        applyFluidConfig({ [key]: readFluidControlValue(input, definition) });
        if (key === 'LED_COLOR_NAME') {
            fluidLiveUpdatePending = true;
            saveFluidConfig('live', ['LED_COLOR_NAME'])
                .catch(() => {})
                .finally(() => {
                    fluidLiveUpdatePending = false;
                });
            return;
        }
        fluidControlsDirty = true;
    });

    fluidControlPanel.addEventListener('click', event => {
        const button = event.target.closest('[data-fluid-action]');
        if (!button) return;
        const action = button.dataset.fluidAction;
        if (action === 'collapse') {
            fluidControlsCollapsed = !fluidControlsCollapsed;
            updateFluidControlPanel();
            return;
        }
        if (action === 'default') {
            fluidControlsDirty = true;
            applyFluidConfig(defaultFluidConfig);
            return;
        }
        saveFluidConfig(action);
    });
}

function createFluidControlRow (definition) {
    const row = document.createElement('label');
    row.className = 'fluid-control-row';
    const name = document.createElement('span');
    name.textContent = definition.label;
    row.appendChild(name);

    if (definition.type === 'boolean') {
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.dataset.fluidKey = definition.key;
        row.appendChild(input);
        return row;
    }

    if (definition.type === 'select') {
        const select = document.createElement('select');
        select.dataset.fluidKey = definition.key;
        refreshSelectOptions(select, definition);
        row.appendChild(select);
        return row;
    }

    const value = document.createElement('output');
    value.dataset.fluidValue = definition.key;
    const input = document.createElement('input');
    input.type = 'range';
    input.min = definition.min;
    input.max = definition.max;
    input.step = definition.step;
    input.dataset.fluidKey = definition.key;
    row.appendChild(value);
    row.appendChild(input);
    return row;
}

function refreshSelectOptions (select, definition) {
    const options = typeof definition.options === 'function' ? definition.options() : definition.options;
    const currentOptions = Array.from(select.options).map(option => option.value);
    if (currentOptions.join('|') === options.join('|')) return;
    select.textContent = '';
    options.forEach(option => {
        const item = document.createElement('option');
        item.value = option;
        item.textContent = option;
        select.appendChild(item);
    });
}

function readFluidControlValue (input, definition) {
    if (definition.type === 'boolean') return input.checked;
    if (definition.type === 'select') return input.value;
    return Number(input.value);
}

async function saveFluidConfig (action, keys) {
    const configUrl = window.MCW_FLUID_CONFIG_URL;
    if (!configUrl) return;
    const definitions = Array.isArray(keys)
        ? fluidControlDefinitions.filter(definition => keys.includes(definition.key))
        : fluidControlDefinitions;
    const payload = {
        action,
        persist: action === 'save' || action === 'live',
        config: Object.fromEntries(definitions.map(definition => [definition.key, config[definition.key]]))
    };
    const response = await fetch(configUrl, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const body = await response.json();
    if (action === 'save') fluidControlsDirty = false;
    if (action === 'live' && fluidControlsDirty) {
        applyFluidConfig({
            CASTING_LED_COLORS: body.fluid_config.CASTING_LED_COLORS,
            LED_COLOR_NAME: body.fluid_config.LED_COLOR_NAME,
            LED_COLOR: body.fluid_config.LED_COLOR
        });
        return;
    }
    applyFluidConfig(body.fluid_config);
}

async function fetchFluidConfig () {
    const configUrl = window.MCW_FLUID_CONFIG_URL;
    if (!configUrl || fluidControlsDirty || fluidLiveUpdatePending) return;
    const response = await fetch(configUrl, {
        cache: 'no-store',
        credentials: 'include'
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const body = await response.json();
    if (fluidControlsDirty || fluidLiveUpdatePending) return;
    applyFluidConfig(body.fluid_config);
}

applyHomeAssistantConfig();

let pointers = [];
let splatStack = [];
pointers.push(new pointerPrototype());

const { gl, ext } = getWebGLContext(canvas);

if (isMobile()) {
    config.DYE_RESOLUTION = 512;
}
if (!ext.supportLinearFiltering) {
    config.DYE_RESOLUTION = 512;
    config.SHADING = false;
    config.BLOOM = false;
    config.SUNRAYS = false;
}

if (window.dat && new URLSearchParams(window.location.search).get('gui') === '1') {
    startGUI();
}

function getWebGLContext (canvas) {
    const params = { alpha: true, depth: false, stencil: false, antialias: false, preserveDrawingBuffer: false };

    let gl = canvas.getContext('webgl2', params);
    const isWebGL2 = !!gl;
    if (!isWebGL2)
        gl = canvas.getContext('webgl', params) || canvas.getContext('experimental-webgl', params);

    let halfFloat;
    let supportLinearFiltering;
    if (isWebGL2) {
        gl.getExtension('EXT_color_buffer_float');
        supportLinearFiltering = gl.getExtension('OES_texture_float_linear');
    } else {
        halfFloat = gl.getExtension('OES_texture_half_float');
        supportLinearFiltering = gl.getExtension('OES_texture_half_float_linear');
    }

    gl.clearColor(0.0, 0.0, 0.0, 1.0);

    const halfFloatTexType = isWebGL2 ? gl.HALF_FLOAT : halfFloat.HALF_FLOAT_OES;
    let formatRGBA;
    let formatRG;
    let formatR;

    if (isWebGL2)
    {
        formatRGBA = getSupportedFormat(gl, gl.RGBA16F, gl.RGBA, halfFloatTexType);
        formatRG = getSupportedFormat(gl, gl.RG16F, gl.RG, halfFloatTexType);
        formatR = getSupportedFormat(gl, gl.R16F, gl.RED, halfFloatTexType);
    }
    else
    {
        formatRGBA = getSupportedFormat(gl, gl.RGBA, gl.RGBA, halfFloatTexType);
        formatRG = getSupportedFormat(gl, gl.RGBA, gl.RGBA, halfFloatTexType);
        formatR = getSupportedFormat(gl, gl.RGBA, gl.RGBA, halfFloatTexType);
    }

    return {
        gl,
        ext: {
            formatRGBA,
            formatRG,
            formatR,
            halfFloatTexType,
            supportLinearFiltering
        }
    };
}

function getSupportedFormat (gl, internalFormat, format, type)
{
    if (!supportRenderTextureFormat(gl, internalFormat, format, type))
    {
        switch (internalFormat)
        {
            case gl.R16F:
                return getSupportedFormat(gl, gl.RG16F, gl.RG, type);
            case gl.RG16F:
                return getSupportedFormat(gl, gl.RGBA16F, gl.RGBA, type);
            default:
                return null;
        }
    }

    return {
        internalFormat,
        format
    }
}

function supportRenderTextureFormat (gl, internalFormat, format, type) {
    let texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texImage2D(gl.TEXTURE_2D, 0, internalFormat, 4, 4, 0, format, type, null);

    let fbo = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0);

    let status = gl.checkFramebufferStatus(gl.FRAMEBUFFER);
    return status == gl.FRAMEBUFFER_COMPLETE;
}

function startGUI () {
    var gui = new dat.GUI({ width: 300 });
    gui.add(config, 'DYE_RESOLUTION', { 'high': 1024, 'medium': 512, 'low': 256, 'very low': 128 }).name('quality').onFinishChange(initFramebuffers);
    gui.add(config, 'SIM_RESOLUTION', { '32': 32, '64': 64, '128': 128, '256': 256 }).name('sim resolution').onFinishChange(initFramebuffers);
    gui.add(config, 'DENSITY_DISSIPATION', 0, 4.0).name('density diffusion');
    gui.add(config, 'VELOCITY_DISSIPATION', 0, 4.0).name('velocity diffusion');
    gui.add(config, 'PRESSURE', 0.0, 1.0).name('pressure');
    gui.add(config, 'CURL', 0, 50).name('vorticity').step(1);
    gui.add(config, 'SPLAT_RADIUS', 0.01, 1.0).name('splat radius');
    gui.add(config, 'SHADING').name('shading').onFinishChange(updateKeywords);
    gui.add(config, 'COLORFUL').name('colorful');
    gui.add(config, 'PAUSED').name('paused').listen();

    gui.add({ fun: () => {
        splatStack.push(parseInt(Math.random() * 20) + 5);
    } }, 'fun').name('Random splats');

    let bloomFolder = gui.addFolder('Bloom');
    bloomFolder.add(config, 'BLOOM').name('enabled').onFinishChange(updateKeywords);
    bloomFolder.add(config, 'BLOOM_INTENSITY', 0.1, 2.0).name('intensity');
    bloomFolder.add(config, 'BLOOM_THRESHOLD', 0.0, 1.0).name('threshold');

    let sunraysFolder = gui.addFolder('Sunrays');
    sunraysFolder.add(config, 'SUNRAYS').name('enabled').onFinishChange(updateKeywords);
    sunraysFolder.add(config, 'SUNRAYS_WEIGHT', 0.3, 1.0).name('weight');

    if (isMobile())
        gui.close();
}

function isMobile () {
    return /Mobi|Android/i.test(navigator.userAgent);
}

function captureScreenshot () {
    let res = getResolution(config.CAPTURE_RESOLUTION);
    let target = createFBO(res.width, res.height, ext.formatRGBA.internalFormat, ext.formatRGBA.format, ext.halfFloatTexType, gl.NEAREST);
    render(target);

    let texture = framebufferToTexture(target);
    texture = normalizeTexture(texture, target.width, target.height);

    let captureCanvas = textureToCanvas(texture, target.width, target.height);
    let datauri = captureCanvas.toDataURL();
    downloadURI('fluid.png', datauri);
    URL.revokeObjectURL(datauri);
}

function framebufferToTexture (target) {
    gl.bindFramebuffer(gl.FRAMEBUFFER, target.fbo);
    let length = target.width * target.height * 4;
    let texture = new Float32Array(length);
    gl.readPixels(0, 0, target.width, target.height, gl.RGBA, gl.FLOAT, texture);
    return texture;
}

function normalizeTexture (texture, width, height) {
    let result = new Uint8Array(texture.length);
    let id = 0;
    for (let i = height - 1; i >= 0; i--) {
        for (let j = 0; j < width; j++) {
            let nid = i * width * 4 + j * 4;
            result[nid + 0] = clamp01(texture[id + 0]) * 255;
            result[nid + 1] = clamp01(texture[id + 1]) * 255;
            result[nid + 2] = clamp01(texture[id + 2]) * 255;
            result[nid + 3] = clamp01(texture[id + 3]) * 255;
            id += 4;
        }
    }
    return result;
}

function clamp01 (input) {
    return Math.min(Math.max(input, 0), 1);
}

function textureToCanvas (texture, width, height) {
    let captureCanvas = document.createElement('canvas');
    let ctx = captureCanvas.getContext('2d');
    captureCanvas.width = width;
    captureCanvas.height = height;

    let imageData = ctx.createImageData(width, height);
    imageData.data.set(texture);
    ctx.putImageData(imageData, 0, 0);

    return captureCanvas;
}

function downloadURI (filename, uri) {
    let link = document.createElement('a');
    link.download = filename;
    link.href = uri;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

class Material {
    constructor (vertexShader, fragmentShaderSource) {
        this.vertexShader = vertexShader;
        this.fragmentShaderSource = fragmentShaderSource;
        this.programs = [];
        this.activeProgram = null;
        this.uniforms = [];
    }

    setKeywords (keywords) {
        let hash = 0;
        for (let i = 0; i < keywords.length; i++)
            hash += hashCode(keywords[i]);

        let program = this.programs[hash];
        if (program == null)
        {
            let fragmentShader = compileShader(gl.FRAGMENT_SHADER, this.fragmentShaderSource, keywords);
            program = createProgram(this.vertexShader, fragmentShader);
            this.programs[hash] = program;
        }

        if (program == this.activeProgram) return;

        this.uniforms = getUniforms(program);
        this.activeProgram = program;
    }

    bind () {
        gl.useProgram(this.activeProgram);
    }
}

class Program {
    constructor (vertexShader, fragmentShader) {
        this.uniforms = {};
        this.program = createProgram(vertexShader, fragmentShader);
        this.uniforms = getUniforms(this.program);
    }

    bind () {
        gl.useProgram(this.program);
    }
}

function createProgram (vertexShader, fragmentShader) {
    let program = gl.createProgram();
    gl.attachShader(program, vertexShader);
    gl.attachShader(program, fragmentShader);
    gl.linkProgram(program);

    if (!gl.getProgramParameter(program, gl.LINK_STATUS))
        console.trace(gl.getProgramInfoLog(program));

    return program;
}

function getUniforms (program) {
    let uniforms = [];
    let uniformCount = gl.getProgramParameter(program, gl.ACTIVE_UNIFORMS);
    for (let i = 0; i < uniformCount; i++) {
        let uniformName = gl.getActiveUniform(program, i).name;
        uniforms[uniformName] = gl.getUniformLocation(program, uniformName);
    }
    return uniforms;
}

function compileShader (type, source, keywords) {
    source = addKeywords(source, keywords);

    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);

    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS))
        console.trace(gl.getShaderInfoLog(shader));

    return shader;
};

function addKeywords (source, keywords) {
    if (keywords == null) return source;
    let keywordsString = '';
    keywords.forEach(keyword => {
        keywordsString += '#define ' + keyword + '\n';
    });
    return keywordsString + source;
}

const baseVertexShader = compileShader(gl.VERTEX_SHADER, `
    precision highp float;

    attribute vec2 aPosition;
    varying vec2 vUv;
    varying vec2 vL;
    varying vec2 vR;
    varying vec2 vT;
    varying vec2 vB;
    uniform vec2 texelSize;

    void main () {
        vUv = aPosition * 0.5 + 0.5;
        vL = vUv - vec2(texelSize.x, 0.0);
        vR = vUv + vec2(texelSize.x, 0.0);
        vT = vUv + vec2(0.0, texelSize.y);
        vB = vUv - vec2(0.0, texelSize.y);
        gl_Position = vec4(aPosition, 0.0, 1.0);
    }
`);

const blurVertexShader = compileShader(gl.VERTEX_SHADER, `
    precision highp float;

    attribute vec2 aPosition;
    varying vec2 vUv;
    varying vec2 vL;
    varying vec2 vR;
    uniform vec2 texelSize;

    void main () {
        vUv = aPosition * 0.5 + 0.5;
        float offset = 1.33333333;
        vL = vUv - texelSize * offset;
        vR = vUv + texelSize * offset;
        gl_Position = vec4(aPosition, 0.0, 1.0);
    }
`);

const blurShader = compileShader(gl.FRAGMENT_SHADER, `
    precision mediump float;
    precision mediump sampler2D;

    varying vec2 vUv;
    varying vec2 vL;
    varying vec2 vR;
    uniform sampler2D uTexture;

    void main () {
        vec4 sum = texture2D(uTexture, vUv) * 0.29411764;
        sum += texture2D(uTexture, vL) * 0.35294117;
        sum += texture2D(uTexture, vR) * 0.35294117;
        gl_FragColor = sum;
    }
`);

const copyShader = compileShader(gl.FRAGMENT_SHADER, `
    precision mediump float;
    precision mediump sampler2D;

    varying highp vec2 vUv;
    uniform sampler2D uTexture;

    void main () {
        gl_FragColor = texture2D(uTexture, vUv);
    }
`);

const clearShader = compileShader(gl.FRAGMENT_SHADER, `
    precision mediump float;
    precision mediump sampler2D;

    varying highp vec2 vUv;
    uniform sampler2D uTexture;
    uniform float value;

    void main () {
        gl_FragColor = value * texture2D(uTexture, vUv);
    }
`);

const colorShader = compileShader(gl.FRAGMENT_SHADER, `
    precision mediump float;

    uniform vec4 color;

    void main () {
        gl_FragColor = color;
    }
`);

const checkerboardShader = compileShader(gl.FRAGMENT_SHADER, `
    precision highp float;
    precision highp sampler2D;

    varying vec2 vUv;
    uniform sampler2D uTexture;
    uniform float aspectRatio;

    #define SCALE 25.0

    void main () {
        vec2 uv = floor(vUv * SCALE * vec2(aspectRatio, 1.0));
        float v = mod(uv.x + uv.y, 2.0);
        v = v * 0.1 + 0.8;
        gl_FragColor = vec4(vec3(v), 1.0);
    }
`);

const displayShaderSource = `
    precision highp float;
    precision highp sampler2D;

    varying vec2 vUv;
    varying vec2 vL;
    varying vec2 vR;
    varying vec2 vT;
    varying vec2 vB;
    uniform sampler2D uTexture;
    uniform sampler2D uBloom;
    uniform sampler2D uSunrays;
    uniform sampler2D uDithering;
    uniform vec2 ditherScale;
    uniform vec2 texelSize;

    vec3 linearToGamma (vec3 color) {
        color = max(color, vec3(0));
        return max(1.055 * pow(color, vec3(0.416666667)) - 0.055, vec3(0));
    }

    void main () {
        vec3 c = texture2D(uTexture, vUv).rgb;

    #ifdef SHADING
        vec3 lc = texture2D(uTexture, vL).rgb;
        vec3 rc = texture2D(uTexture, vR).rgb;
        vec3 tc = texture2D(uTexture, vT).rgb;
        vec3 bc = texture2D(uTexture, vB).rgb;

        float dx = length(rc) - length(lc);
        float dy = length(tc) - length(bc);

        vec3 n = normalize(vec3(dx, dy, length(texelSize)));
        vec3 l = vec3(0.0, 0.0, 1.0);

        float diffuse = clamp(dot(n, l) + 0.7, 0.7, 1.0);
        c *= diffuse;
    #endif

    #ifdef BLOOM
        vec3 bloom = texture2D(uBloom, vUv).rgb;
    #endif

    #ifdef SUNRAYS
        float sunrays = texture2D(uSunrays, vUv).r;
        c *= sunrays;
    #ifdef BLOOM
        bloom *= sunrays;
    #endif
    #endif

    #ifdef BLOOM
        float noise = texture2D(uDithering, vUv * ditherScale).r;
        noise = noise * 2.0 - 1.0;
        bloom += noise / 255.0;
        bloom = linearToGamma(bloom);
        c += bloom;
    #endif

        float a = max(c.r, max(c.g, c.b));
        gl_FragColor = vec4(c, a);
    }
`;

const bloomPrefilterShader = compileShader(gl.FRAGMENT_SHADER, `
    precision mediump float;
    precision mediump sampler2D;

    varying vec2 vUv;
    uniform sampler2D uTexture;
    uniform vec3 curve;
    uniform float threshold;

    void main () {
        vec3 c = texture2D(uTexture, vUv).rgb;
        float br = max(c.r, max(c.g, c.b));
        float rq = clamp(br - curve.x, 0.0, curve.y);
        rq = curve.z * rq * rq;
        c *= max(rq, br - threshold) / max(br, 0.0001);
        gl_FragColor = vec4(c, 0.0);
    }
`);

const bloomBlurShader = compileShader(gl.FRAGMENT_SHADER, `
    precision mediump float;
    precision mediump sampler2D;

    varying vec2 vL;
    varying vec2 vR;
    varying vec2 vT;
    varying vec2 vB;
    uniform sampler2D uTexture;

    void main () {
        vec4 sum = vec4(0.0);
        sum += texture2D(uTexture, vL);
        sum += texture2D(uTexture, vR);
        sum += texture2D(uTexture, vT);
        sum += texture2D(uTexture, vB);
        sum *= 0.25;
        gl_FragColor = sum;
    }
`);

const bloomFinalShader = compileShader(gl.FRAGMENT_SHADER, `
    precision mediump float;
    precision mediump sampler2D;

    varying vec2 vL;
    varying vec2 vR;
    varying vec2 vT;
    varying vec2 vB;
    uniform sampler2D uTexture;
    uniform float intensity;

    void main () {
        vec4 sum = vec4(0.0);
        sum += texture2D(uTexture, vL);
        sum += texture2D(uTexture, vR);
        sum += texture2D(uTexture, vT);
        sum += texture2D(uTexture, vB);
        sum *= 0.25;
        gl_FragColor = sum * intensity;
    }
`);

const sunraysMaskShader = compileShader(gl.FRAGMENT_SHADER, `
    precision highp float;
    precision highp sampler2D;

    varying vec2 vUv;
    uniform sampler2D uTexture;

    void main () {
        vec4 c = texture2D(uTexture, vUv);
        float br = max(c.r, max(c.g, c.b));
        c.a = 1.0 - min(max(br * 20.0, 0.0), 0.8);
        gl_FragColor = c;
    }
`);

const sunraysShader = compileShader(gl.FRAGMENT_SHADER, `
    precision highp float;
    precision highp sampler2D;

    varying vec2 vUv;
    uniform sampler2D uTexture;
    uniform float weight;

    #define ITERATIONS 16

    void main () {
        float Density = 0.3;
        float Decay = 0.95;
        float Exposure = 0.7;

        vec2 coord = vUv;
        vec2 dir = vUv - 0.5;

        dir *= 1.0 / float(ITERATIONS) * Density;
        float illuminationDecay = 1.0;

        float color = texture2D(uTexture, vUv).a;

        for (int i = 0; i < ITERATIONS; i++)
        {
            coord -= dir;
            float col = texture2D(uTexture, coord).a;
            color += col * illuminationDecay * weight;
            illuminationDecay *= Decay;
        }

        gl_FragColor = vec4(color * Exposure, 0.0, 0.0, 1.0);
    }
`);

const splatShader = compileShader(gl.FRAGMENT_SHADER, `
    precision highp float;
    precision highp sampler2D;

    varying vec2 vUv;
    uniform sampler2D uTarget;
    uniform float aspectRatio;
    uniform vec3 color;
    uniform vec2 point;
    uniform float radius;

    void main () {
        vec2 p = vUv - point.xy;
        p.x *= aspectRatio;
        vec3 splat = exp(-dot(p, p) / radius) * color;
        vec3 base = texture2D(uTarget, vUv).xyz;
        gl_FragColor = vec4(base + splat, 1.0);
    }
`);

const advectionShader = compileShader(gl.FRAGMENT_SHADER, `
    precision highp float;
    precision highp sampler2D;

    varying vec2 vUv;
    uniform sampler2D uVelocity;
    uniform sampler2D uSource;
    uniform vec2 texelSize;
    uniform vec2 dyeTexelSize;
    uniform float dt;
    uniform float dissipation;

    vec4 bilerp (sampler2D sam, vec2 uv, vec2 tsize) {
        vec2 st = uv / tsize - 0.5;

        vec2 iuv = floor(st);
        vec2 fuv = fract(st);

        vec4 a = texture2D(sam, (iuv + vec2(0.5, 0.5)) * tsize);
        vec4 b = texture2D(sam, (iuv + vec2(1.5, 0.5)) * tsize);
        vec4 c = texture2D(sam, (iuv + vec2(0.5, 1.5)) * tsize);
        vec4 d = texture2D(sam, (iuv + vec2(1.5, 1.5)) * tsize);

        return mix(mix(a, b, fuv.x), mix(c, d, fuv.x), fuv.y);
    }

    void main () {
    #ifdef MANUAL_FILTERING
        vec2 coord = vUv - dt * bilerp(uVelocity, vUv, texelSize).xy * texelSize;
        vec4 result = bilerp(uSource, coord, dyeTexelSize);
    #else
        vec2 coord = vUv - dt * texture2D(uVelocity, vUv).xy * texelSize;
        vec4 result = texture2D(uSource, coord);
    #endif
        float decay = 1.0 + dissipation * dt;
        gl_FragColor = result / decay;
    }`,
    ext.supportLinearFiltering ? null : ['MANUAL_FILTERING']
);

const divergenceShader = compileShader(gl.FRAGMENT_SHADER, `
    precision mediump float;
    precision mediump sampler2D;

    varying highp vec2 vUv;
    varying highp vec2 vL;
    varying highp vec2 vR;
    varying highp vec2 vT;
    varying highp vec2 vB;
    uniform sampler2D uVelocity;

    void main () {
        float L = texture2D(uVelocity, vL).x;
        float R = texture2D(uVelocity, vR).x;
        float T = texture2D(uVelocity, vT).y;
        float B = texture2D(uVelocity, vB).y;

        vec2 C = texture2D(uVelocity, vUv).xy;
        if (vL.x < 0.0) { L = -C.x; }
        if (vR.x > 1.0) { R = -C.x; }
        if (vT.y > 1.0) { T = -C.y; }
        if (vB.y < 0.0) { B = -C.y; }

        float div = 0.5 * (R - L + T - B);
        gl_FragColor = vec4(div, 0.0, 0.0, 1.0);
    }
`);

const curlShader = compileShader(gl.FRAGMENT_SHADER, `
    precision mediump float;
    precision mediump sampler2D;

    varying highp vec2 vUv;
    varying highp vec2 vL;
    varying highp vec2 vR;
    varying highp vec2 vT;
    varying highp vec2 vB;
    uniform sampler2D uVelocity;

    void main () {
        float L = texture2D(uVelocity, vL).y;
        float R = texture2D(uVelocity, vR).y;
        float T = texture2D(uVelocity, vT).x;
        float B = texture2D(uVelocity, vB).x;
        float vorticity = R - L - T + B;
        gl_FragColor = vec4(0.5 * vorticity, 0.0, 0.0, 1.0);
    }
`);

const vorticityShader = compileShader(gl.FRAGMENT_SHADER, `
    precision highp float;
    precision highp sampler2D;

    varying vec2 vUv;
    varying vec2 vL;
    varying vec2 vR;
    varying vec2 vT;
    varying vec2 vB;
    uniform sampler2D uVelocity;
    uniform sampler2D uCurl;
    uniform float curl;
    uniform float dt;

    void main () {
        float L = texture2D(uCurl, vL).x;
        float R = texture2D(uCurl, vR).x;
        float T = texture2D(uCurl, vT).x;
        float B = texture2D(uCurl, vB).x;
        float C = texture2D(uCurl, vUv).x;

        vec2 force = 0.5 * vec2(abs(T) - abs(B), abs(R) - abs(L));
        force /= length(force) + 0.0001;
        force *= curl * C;
        force.y *= -1.0;

        vec2 velocity = texture2D(uVelocity, vUv).xy;
        velocity += force * dt;
        velocity = min(max(velocity, -1000.0), 1000.0);
        gl_FragColor = vec4(velocity, 0.0, 1.0);
    }
`);

const pressureShader = compileShader(gl.FRAGMENT_SHADER, `
    precision mediump float;
    precision mediump sampler2D;

    varying highp vec2 vUv;
    varying highp vec2 vL;
    varying highp vec2 vR;
    varying highp vec2 vT;
    varying highp vec2 vB;
    uniform sampler2D uPressure;
    uniform sampler2D uDivergence;

    void main () {
        float L = texture2D(uPressure, vL).x;
        float R = texture2D(uPressure, vR).x;
        float T = texture2D(uPressure, vT).x;
        float B = texture2D(uPressure, vB).x;
        float C = texture2D(uPressure, vUv).x;
        float divergence = texture2D(uDivergence, vUv).x;
        float pressure = (L + R + B + T - divergence) * 0.25;
        gl_FragColor = vec4(pressure, 0.0, 0.0, 1.0);
    }
`);

const gradientSubtractShader = compileShader(gl.FRAGMENT_SHADER, `
    precision mediump float;
    precision mediump sampler2D;

    varying highp vec2 vUv;
    varying highp vec2 vL;
    varying highp vec2 vR;
    varying highp vec2 vT;
    varying highp vec2 vB;
    uniform sampler2D uPressure;
    uniform sampler2D uVelocity;

    void main () {
        float L = texture2D(uPressure, vL).x;
        float R = texture2D(uPressure, vR).x;
        float T = texture2D(uPressure, vT).x;
        float B = texture2D(uPressure, vB).x;
        vec2 velocity = texture2D(uVelocity, vUv).xy;
        velocity.xy -= vec2(R - L, T - B);
        gl_FragColor = vec4(velocity, 0.0, 1.0);
    }
`);

const blit = (() => {
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, -1, 1, 1, 1, 1, -1]), gl.STATIC_DRAW);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array([0, 1, 2, 0, 2, 3]), gl.STATIC_DRAW);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    gl.enableVertexAttribArray(0);

    return (target, clear = false) => {
        if (target == null)
        {
            gl.viewport(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight);
            gl.bindFramebuffer(gl.FRAMEBUFFER, null);
        }
        else
        {
            gl.viewport(0, 0, target.width, target.height);
            gl.bindFramebuffer(gl.FRAMEBUFFER, target.fbo);
        }
        if (clear)
        {
            gl.clearColor(0.0, 0.0, 0.0, 1.0);
            gl.clear(gl.COLOR_BUFFER_BIT);
        }
        // CHECK_FRAMEBUFFER_STATUS();
        gl.drawElements(gl.TRIANGLES, 6, gl.UNSIGNED_SHORT, 0);
    }
})();

function CHECK_FRAMEBUFFER_STATUS () {
    let status = gl.checkFramebufferStatus(gl.FRAMEBUFFER);
    if (status != gl.FRAMEBUFFER_COMPLETE)
        console.trace("Framebuffer error: " + status);
}

let dye;
let velocity;
let divergence;
let curl;
let pressure;
let bloom;
let bloomFramebuffers = [];
let sunrays;
let sunraysTemp;

let ditheringTexture = createTextureAsync('LDR_LLL1_0.png');

const blurProgram            = new Program(blurVertexShader, blurShader);
const copyProgram            = new Program(baseVertexShader, copyShader);
const clearProgram           = new Program(baseVertexShader, clearShader);
const colorProgram           = new Program(baseVertexShader, colorShader);
const checkerboardProgram    = new Program(baseVertexShader, checkerboardShader);
const bloomPrefilterProgram  = new Program(baseVertexShader, bloomPrefilterShader);
const bloomBlurProgram       = new Program(baseVertexShader, bloomBlurShader);
const bloomFinalProgram      = new Program(baseVertexShader, bloomFinalShader);
const sunraysMaskProgram     = new Program(baseVertexShader, sunraysMaskShader);
const sunraysProgram         = new Program(baseVertexShader, sunraysShader);
const splatProgram           = new Program(baseVertexShader, splatShader);
const advectionProgram       = new Program(baseVertexShader, advectionShader);
const divergenceProgram      = new Program(baseVertexShader, divergenceShader);
const curlProgram            = new Program(baseVertexShader, curlShader);
const vorticityProgram       = new Program(baseVertexShader, vorticityShader);
const pressureProgram        = new Program(baseVertexShader, pressureShader);
const gradienSubtractProgram = new Program(baseVertexShader, gradientSubtractShader);

const displayMaterial = new Material(baseVertexShader, displayShaderSource);

function initFramebuffers () {
    let simRes = getResolution(config.SIM_RESOLUTION);
    let dyeRes = getResolution(config.DYE_RESOLUTION);

    const texType = ext.halfFloatTexType;
    const rgba    = ext.formatRGBA;
    const rg      = ext.formatRG;
    const r       = ext.formatR;
    const filtering = ext.supportLinearFiltering ? gl.LINEAR : gl.NEAREST;

    gl.disable(gl.BLEND);

    if (dye == null)
        dye = createDoubleFBO(dyeRes.width, dyeRes.height, rgba.internalFormat, rgba.format, texType, filtering);
    else
        dye = resizeDoubleFBO(dye, dyeRes.width, dyeRes.height, rgba.internalFormat, rgba.format, texType, filtering);

    if (velocity == null)
        velocity = createDoubleFBO(simRes.width, simRes.height, rg.internalFormat, rg.format, texType, filtering);
    else
        velocity = resizeDoubleFBO(velocity, simRes.width, simRes.height, rg.internalFormat, rg.format, texType, filtering);

    divergence = createFBO      (simRes.width, simRes.height, r.internalFormat, r.format, texType, gl.NEAREST);
    curl       = createFBO      (simRes.width, simRes.height, r.internalFormat, r.format, texType, gl.NEAREST);
    pressure   = createDoubleFBO(simRes.width, simRes.height, r.internalFormat, r.format, texType, gl.NEAREST);

    initBloomFramebuffers();
    initSunraysFramebuffers();
}

function initBloomFramebuffers () {
    let res = getResolution(config.BLOOM_RESOLUTION);

    const texType = ext.halfFloatTexType;
    const rgba = ext.formatRGBA;
    const filtering = ext.supportLinearFiltering ? gl.LINEAR : gl.NEAREST;

    bloom = createFBO(res.width, res.height, rgba.internalFormat, rgba.format, texType, filtering);

    bloomFramebuffers.length = 0;
    for (let i = 0; i < config.BLOOM_ITERATIONS; i++)
    {
        let width = res.width >> (i + 1);
        let height = res.height >> (i + 1);

        if (width < 2 || height < 2) break;

        let fbo = createFBO(width, height, rgba.internalFormat, rgba.format, texType, filtering);
        bloomFramebuffers.push(fbo);
    }
}

function initSunraysFramebuffers () {
    let res = getResolution(config.SUNRAYS_RESOLUTION);

    const texType = ext.halfFloatTexType;
    const r = ext.formatR;
    const filtering = ext.supportLinearFiltering ? gl.LINEAR : gl.NEAREST;

    sunrays     = createFBO(res.width, res.height, r.internalFormat, r.format, texType, filtering);
    sunraysTemp = createFBO(res.width, res.height, r.internalFormat, r.format, texType, filtering);
}

function createFBO (w, h, internalFormat, format, type, param) {
    gl.activeTexture(gl.TEXTURE0);
    let texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, param);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, param);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texImage2D(gl.TEXTURE_2D, 0, internalFormat, w, h, 0, format, type, null);

    let fbo = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0);
    gl.viewport(0, 0, w, h);
    gl.clear(gl.COLOR_BUFFER_BIT);

    let texelSizeX = 1.0 / w;
    let texelSizeY = 1.0 / h;

    return {
        texture,
        fbo,
        width: w,
        height: h,
        texelSizeX,
        texelSizeY,
        attach (id) {
            gl.activeTexture(gl.TEXTURE0 + id);
            gl.bindTexture(gl.TEXTURE_2D, texture);
            return id;
        }
    };
}

function createDoubleFBO (w, h, internalFormat, format, type, param) {
    let fbo1 = createFBO(w, h, internalFormat, format, type, param);
    let fbo2 = createFBO(w, h, internalFormat, format, type, param);

    return {
        width: w,
        height: h,
        texelSizeX: fbo1.texelSizeX,
        texelSizeY: fbo1.texelSizeY,
        get read () {
            return fbo1;
        },
        set read (value) {
            fbo1 = value;
        },
        get write () {
            return fbo2;
        },
        set write (value) {
            fbo2 = value;
        },
        swap () {
            let temp = fbo1;
            fbo1 = fbo2;
            fbo2 = temp;
        }
    }
}

function resizeFBO (target, w, h, internalFormat, format, type, param) {
    let newFBO = createFBO(w, h, internalFormat, format, type, param);
    copyProgram.bind();
    gl.uniform1i(copyProgram.uniforms.uTexture, target.attach(0));
    blit(newFBO);
    return newFBO;
}

function resizeDoubleFBO (target, w, h, internalFormat, format, type, param) {
    if (target.width == w && target.height == h)
        return target;
    target.read = resizeFBO(target.read, w, h, internalFormat, format, type, param);
    target.write = createFBO(w, h, internalFormat, format, type, param);
    target.width = w;
    target.height = h;
    target.texelSizeX = 1.0 / w;
    target.texelSizeY = 1.0 / h;
    return target;
}

function createTextureAsync (url) {
    let texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.REPEAT);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, 1, 1, 0, gl.RGB, gl.UNSIGNED_BYTE, new Uint8Array([255, 255, 255]));

    let obj = {
        texture,
        width: 1,
        height: 1,
        attach (id) {
            gl.activeTexture(gl.TEXTURE0 + id);
            gl.bindTexture(gl.TEXTURE_2D, texture);
            return id;
        }
    };

    let image = new Image();
    image.onload = () => {
        obj.width = image.width;
        obj.height = image.height;
        gl.bindTexture(gl.TEXTURE_2D, texture);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, image);
    };
    image.src = url;

    return obj;
}

function updateKeywords () {
    let displayKeywords = [];
    if (config.SHADING) displayKeywords.push("SHADING");
    if (config.BLOOM) displayKeywords.push("BLOOM");
    if (config.SUNRAYS) displayKeywords.push("SUNRAYS");
    displayMaterial.setKeywords(displayKeywords);
}

updateKeywords();
initFramebuffers();
//multipleSplats(parseInt(Math.random() * 20) + 5);
connectWandFluidStream();

let lastUpdateTime = Date.now();
let colorUpdateTimer = 0.0;
update();

function update () {
    const dt = calcDeltaTime();
    if (resizeCanvas())
        initFramebuffers();
    updateColors(dt);
    applyInputs();
    if (!config.PAUSED)
        step(dt);
    render(null);
    requestAnimationFrame(update);
}

function calcDeltaTime () {
    let now = Date.now();
    let dt = (now - lastUpdateTime) / 1000;
    dt = Math.min(dt, 0.016666);
    lastUpdateTime = now;
    return dt;
}

function resizeCanvas () {
    let width = scaleByPixelRatio(canvas.clientWidth);
    let height = scaleByPixelRatio(canvas.clientHeight);
    if (canvas.width != width || canvas.height != height) {
        canvas.width = width;
        canvas.height = height;
        return true;
    }
    return false;
}

function updateColors (dt) {
    if (config.MATCH_LED_COLOR) {
        pointers.forEach(p => {
            p.color = getConfiguredFluidColor();
        });
        return;
    }
    if (!config.COLORFUL) return;

    colorUpdateTimer += dt * config.COLOR_UPDATE_SPEED;
    if (colorUpdateTimer >= 1) {
        colorUpdateTimer = wrap(colorUpdateTimer, 0, 1);
        pointers.forEach(p => {
            p.color = generateColor();
        });
    }
}

function applyInputs () {
//    if (splatStack.length > 0)
//        multipleSplats(splatStack.pop());

    pointers.forEach(p => {
        if (p.moved) {
            p.moved = false;
            splatPointer(p);
        }
    });
}

function step (dt) {
    gl.disable(gl.BLEND);

    curlProgram.bind();
    gl.uniform2f(curlProgram.uniforms.texelSize, velocity.texelSizeX, velocity.texelSizeY);
    gl.uniform1i(curlProgram.uniforms.uVelocity, velocity.read.attach(0));
    blit(curl);

    vorticityProgram.bind();
    gl.uniform2f(vorticityProgram.uniforms.texelSize, velocity.texelSizeX, velocity.texelSizeY);
    gl.uniform1i(vorticityProgram.uniforms.uVelocity, velocity.read.attach(0));
    gl.uniform1i(vorticityProgram.uniforms.uCurl, curl.attach(1));
    gl.uniform1f(vorticityProgram.uniforms.curl, config.CURL);
    gl.uniform1f(vorticityProgram.uniforms.dt, dt);
    blit(velocity.write);
    velocity.swap();

    divergenceProgram.bind();
    gl.uniform2f(divergenceProgram.uniforms.texelSize, velocity.texelSizeX, velocity.texelSizeY);
    gl.uniform1i(divergenceProgram.uniforms.uVelocity, velocity.read.attach(0));
    blit(divergence);

    clearProgram.bind();
    gl.uniform1i(clearProgram.uniforms.uTexture, pressure.read.attach(0));
    gl.uniform1f(clearProgram.uniforms.value, config.PRESSURE);
    blit(pressure.write);
    pressure.swap();

    pressureProgram.bind();
    gl.uniform2f(pressureProgram.uniforms.texelSize, velocity.texelSizeX, velocity.texelSizeY);
    gl.uniform1i(pressureProgram.uniforms.uDivergence, divergence.attach(0));
    for (let i = 0; i < config.PRESSURE_ITERATIONS; i++) {
        gl.uniform1i(pressureProgram.uniforms.uPressure, pressure.read.attach(1));
        blit(pressure.write);
        pressure.swap();
    }

    gradienSubtractProgram.bind();
    gl.uniform2f(gradienSubtractProgram.uniforms.texelSize, velocity.texelSizeX, velocity.texelSizeY);
    gl.uniform1i(gradienSubtractProgram.uniforms.uPressure, pressure.read.attach(0));
    gl.uniform1i(gradienSubtractProgram.uniforms.uVelocity, velocity.read.attach(1));
    blit(velocity.write);
    velocity.swap();

    advectionProgram.bind();
    gl.uniform2f(advectionProgram.uniforms.texelSize, velocity.texelSizeX, velocity.texelSizeY);
    if (!ext.supportLinearFiltering)
        gl.uniform2f(advectionProgram.uniforms.dyeTexelSize, velocity.texelSizeX, velocity.texelSizeY);
    let velocityId = velocity.read.attach(0);
    gl.uniform1i(advectionProgram.uniforms.uVelocity, velocityId);
    gl.uniform1i(advectionProgram.uniforms.uSource, velocityId);
    gl.uniform1f(advectionProgram.uniforms.dt, dt);
    gl.uniform1f(advectionProgram.uniforms.dissipation, config.VELOCITY_DISSIPATION);
    blit(velocity.write);
    velocity.swap();

    if (!ext.supportLinearFiltering)
        gl.uniform2f(advectionProgram.uniforms.dyeTexelSize, dye.texelSizeX, dye.texelSizeY);
    gl.uniform1i(advectionProgram.uniforms.uVelocity, velocity.read.attach(0));
    gl.uniform1i(advectionProgram.uniforms.uSource, dye.read.attach(1));
    gl.uniform1f(advectionProgram.uniforms.dissipation, config.DENSITY_DISSIPATION);
    blit(dye.write);
    dye.swap();
}

function render (target) {
    if (config.BLOOM)
        applyBloom(dye.read, bloom);
    if (config.SUNRAYS) {
        applySunrays(dye.read, dye.write, sunrays);
        blur(sunrays, sunraysTemp, 1);
    }

    if (target == null || !config.TRANSPARENT) {
        gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
        gl.enable(gl.BLEND);
    }
    else {
        gl.disable(gl.BLEND);
    }

    if (!config.TRANSPARENT)
        drawColor(target, normalizeColor(config.BACK_COLOR));
    if (target == null && config.TRANSPARENT)
        drawCheckerboard(target);
    drawDisplay(target);
}

function drawColor (target, color) {
    colorProgram.bind();
    gl.uniform4f(colorProgram.uniforms.color, color.r, color.g, color.b, 1);
    blit(target);
}

function drawCheckerboard (target) {
    checkerboardProgram.bind();
    gl.uniform1f(checkerboardProgram.uniforms.aspectRatio, canvas.width / canvas.height);
    blit(target);
}

function drawDisplay (target) {
    let width = target == null ? gl.drawingBufferWidth : target.width;
    let height = target == null ? gl.drawingBufferHeight : target.height;

    displayMaterial.bind();
    if (config.SHADING)
        gl.uniform2f(displayMaterial.uniforms.texelSize, 1.0 / width, 1.0 / height);
    gl.uniform1i(displayMaterial.uniforms.uTexture, dye.read.attach(0));
    if (config.BLOOM) {
        gl.uniform1i(displayMaterial.uniforms.uBloom, bloom.attach(1));
        gl.uniform1i(displayMaterial.uniforms.uDithering, ditheringTexture.attach(2));
        let scale = getTextureScale(ditheringTexture, width, height);
        gl.uniform2f(displayMaterial.uniforms.ditherScale, scale.x, scale.y);
    }
    if (config.SUNRAYS)
        gl.uniform1i(displayMaterial.uniforms.uSunrays, sunrays.attach(3));
    blit(target);
}

function applyBloom (source, destination) {
    if (bloomFramebuffers.length < 2)
        return;

    let last = destination;

    gl.disable(gl.BLEND);
    bloomPrefilterProgram.bind();
    let knee = config.BLOOM_THRESHOLD * config.BLOOM_SOFT_KNEE + 0.0001;
    let curve0 = config.BLOOM_THRESHOLD - knee;
    let curve1 = knee * 2;
    let curve2 = 0.25 / knee;
    gl.uniform3f(bloomPrefilterProgram.uniforms.curve, curve0, curve1, curve2);
    gl.uniform1f(bloomPrefilterProgram.uniforms.threshold, config.BLOOM_THRESHOLD);
    gl.uniform1i(bloomPrefilterProgram.uniforms.uTexture, source.attach(0));
    blit(last);

    bloomBlurProgram.bind();
    for (let i = 0; i < bloomFramebuffers.length; i++) {
        let dest = bloomFramebuffers[i];
        gl.uniform2f(bloomBlurProgram.uniforms.texelSize, last.texelSizeX, last.texelSizeY);
        gl.uniform1i(bloomBlurProgram.uniforms.uTexture, last.attach(0));
        blit(dest);
        last = dest;
    }

    gl.blendFunc(gl.ONE, gl.ONE);
    gl.enable(gl.BLEND);

    for (let i = bloomFramebuffers.length - 2; i >= 0; i--) {
        let baseTex = bloomFramebuffers[i];
        gl.uniform2f(bloomBlurProgram.uniforms.texelSize, last.texelSizeX, last.texelSizeY);
        gl.uniform1i(bloomBlurProgram.uniforms.uTexture, last.attach(0));
        gl.viewport(0, 0, baseTex.width, baseTex.height);
        blit(baseTex);
        last = baseTex;
    }

    gl.disable(gl.BLEND);
    bloomFinalProgram.bind();
    gl.uniform2f(bloomFinalProgram.uniforms.texelSize, last.texelSizeX, last.texelSizeY);
    gl.uniform1i(bloomFinalProgram.uniforms.uTexture, last.attach(0));
    gl.uniform1f(bloomFinalProgram.uniforms.intensity, config.BLOOM_INTENSITY);
    blit(destination);
}

function applySunrays (source, mask, destination) {
    gl.disable(gl.BLEND);
    sunraysMaskProgram.bind();
    gl.uniform1i(sunraysMaskProgram.uniforms.uTexture, source.attach(0));
    blit(mask);

    sunraysProgram.bind();
    gl.uniform1f(sunraysProgram.uniforms.weight, config.SUNRAYS_WEIGHT);
    gl.uniform1i(sunraysProgram.uniforms.uTexture, mask.attach(0));
    blit(destination);
}

function blur (target, temp, iterations) {
    blurProgram.bind();
    for (let i = 0; i < iterations; i++) {
        gl.uniform2f(blurProgram.uniforms.texelSize, target.texelSizeX, 0.0);
        gl.uniform1i(blurProgram.uniforms.uTexture, target.attach(0));
        blit(temp);

        gl.uniform2f(blurProgram.uniforms.texelSize, 0.0, target.texelSizeY);
        gl.uniform1i(blurProgram.uniforms.uTexture, temp.attach(0));
        blit(target);
    }
}

function splatPointer (pointer) {
    let dx = pointer.deltaX * config.SPLAT_FORCE;
    let dy = pointer.deltaY * config.SPLAT_FORCE;
    splat(pointer.texcoordX, pointer.texcoordY, dx, dy, pointer.color);
}

function connectWandFluidStream () {
    const statusEl = document.getElementById('mcw-fluid-status');
    const spellEl = document.getElementById('mcw-fluid-spell');
    const debugEl = document.getElementById('mcw-fluid-debug');
    const stateUrl = window.MCW_FLUID_STATE_URL;
    const fallbackStateUrl = window.MCW_FLUID_DEFAULT_STATE_URL;
    const eventsUrl = window.MCW_FLUID_EVENTS_URL;
    if (!stateUrl) {
        if (statusEl) statusEl.textContent = 'NO BACKEND';
        return;
    }

    const wandPointer = new pointerPrototype();
    const wandPointerId = -9001;
    pointers.push(wandPointer);
    const wandTargetSmoothing = 0.5;
    const wandPointerSmoothing = 0.28;
    const wandMinStep = 1.2;
    let lastBackendMessage = Date.now();
    let lastMotionMessage = 0;
    let lastSpell = '';
    let spellFadeTimer = null;
    let wasActive = false;
    let wandConnected = false;
    let polling = false;
    let activeStateUrl = stateUrl;
    let streamConnected = false;
    let lastStreamMessage = 0;
    let streamReconnectTimer = null;
    let nextPollTimer = null;
    const wandMotion = {
        active: false,
        currentX: canvas.width / 2,
        currentY: canvas.height / 2,
        targetX: canvas.width / 2,
        targetY: canvas.height / 2,
        rawTargetX: canvas.width / 2,
        rawTargetY: canvas.height / 2,
        lastPacketAt: 0
    };

    const stopWandMotion = () => {
        wandMotion.active = false;
        wasActive = false;
        updatePointerUpData(wandPointer);
    };

    const smoothWandMotion = () => {
        requestAnimationFrame(smoothWandMotion);
        if (!wandMotion.active) return;

        if (Date.now() - wandMotion.lastPacketAt > 1200) {
            stopWandMotion();
            return;
        }

        if (!wandPointer.down || !wasActive) {
            wandMotion.currentX = canvas.width / 2;
            wandMotion.currentY = canvas.height / 2;
            updatePointerDownData(wandPointer, wandPointerId, wandMotion.currentX, wandMotion.currentY);
            wasActive = true;
        }
        if (config.MATCH_LED_COLOR) {
            wandPointer.color = getConfiguredFluidColor();
        }

        wandMotion.targetX += (wandMotion.rawTargetX - wandMotion.targetX) * wandTargetSmoothing;
        wandMotion.targetY += (wandMotion.rawTargetY - wandMotion.targetY) * wandTargetSmoothing;

        const dx = wandMotion.targetX - wandMotion.currentX;
        const dy = wandMotion.targetY - wandMotion.currentY;
        const distance = Math.hypot(dx, dy);
        if (distance > 0.5) {
            const maxStep = Math.max(8, Math.min(canvas.width, canvas.height) * 0.035);
            const step = Math.min(distance, Math.max(distance * wandPointerSmoothing, wandMinStep), maxStep);
            wandMotion.currentX += (dx / distance) * step;
            wandMotion.currentY += (dy / distance) * step;
        }

        updatePointerMoveData(wandPointer, wandMotion.currentX, wandMotion.currentY);
    };
    smoothWandMotion();

    const handlePayload = data => {
        lastBackendMessage = Date.now();
        if (data.fluid_config && !fluidControlsDirty && !fluidLiveUpdatePending) applyFluidConfig(data.fluid_config);
        wandConnected = data.connected === true;

        const spellText = formatSpellName(data.spell);
        if (spellText) {
            lastSpell = spellText;
            if (spellEl && spellEl.textContent !== spellText) {
                spellEl.textContent = spellText;
                spellEl.style.opacity = '1';
                if (spellFadeTimer) clearTimeout(spellFadeTimer);
                spellFadeTimer = setTimeout(() => {
                    if (spellEl.textContent === spellText) {
                        spellEl.style.opacity = '0';
                    }
                }, 20000);
            }
        }

        const hasPointer = Number.isFinite(data.x) && Number.isFinite(data.y);
        if (data.type === 'motion' || (data.active && hasPointer)) {
            lastMotionMessage = Date.now();
        }

        if (statusEl) {
            if (!wandConnected) statusEl.textContent = 'WAND DISCONNECTED';
            else if (data.drawing) statusEl.textContent = 'TRACKING';
            else if (data.any_button) statusEl.textContent = 'BUTTONS READY';
            else statusEl.textContent = 'READY';
        }

        if (!wandConnected) {
            if (debugEl) debugEl.style.display = 'none';
            stopWandMotion();
            return;
        }

        if (debugEl) debugEl.style.display = '';
        if (debugEl) {
            const motionLabel = data.error || data.status_detail || (data.has_motion || data.type === 'motion' ? 'IMU OK' : 'WAITING FOR WAND IMU DATA');
            const buttonLabel = data.button_combo ? 'CAST COMBO' : (data.any_button ? 'BUTTON HELD' : 'NO BUTTON');
            debugEl.textContent = `${motionLabel} / ${buttonLabel}${lastSpell ? ' / LAST: ' + lastSpell : ''}`;
        }

        if (!hasPointer) {
            if (data.active === false) stopWandMotion();
            return;
        }

        const posX = data.x * canvas.width;
        const posY = data.y * canvas.height;
        if (data.active === false) {
            stopWandMotion();
            return;
        }

        if (data.active === true && !wandMotion.active) {
            wandMotion.currentX = canvas.width / 2;
            wandMotion.currentY = canvas.height / 2;
            wandMotion.targetX = wandMotion.currentX;
            wandMotion.targetY = wandMotion.currentY;
            wandMotion.rawTargetX = wandMotion.currentX;
            wandMotion.rawTargetY = wandMotion.currentY;
            updatePointerDownData(wandPointer, wandPointerId, wandMotion.currentX, wandMotion.currentY);
            wasActive = true;
        }

        wandMotion.active = data.active === true;
        wandMotion.rawTargetX = posX;
        wandMotion.rawTargetY = posY;
        wandMotion.lastPacketAt = Date.now();
    };

    const fetchState = async (url, synthesizeErrors = false) => {
        const response = await fetch(url, {
            cache: 'no-store',
            credentials: 'include'
        });
        const text = await response.text();
        if (!response.ok) {
            if (!synthesizeErrors) throw new Error(`HTTP ${response.status}`);
            return {
                type: 'status',
                connected: false,
                has_motion: false,
                spell: lastSpell || 'awaiting',
                error: `HTTP ${response.status}${text ? ': ' + text.slice(0, 120) : ''}`
            };
        }
        try {
            return JSON.parse(text);
        } catch (err) {
            throw new Error(`BAD JSON: ${text.slice(0, 120)}`);
        }
    };

    const connectEventStream = () => {
        if (!eventsUrl || !window.EventSource) return;
        if (streamReconnectTimer) {
            clearTimeout(streamReconnectTimer);
            streamReconnectTimer = null;
        }

        const source = new EventSource(eventsUrl);
        source.onopen = () => {
            streamConnected = true;
            lastStreamMessage = Date.now();
        };
        source.addEventListener('wand', event => {
            try {
                streamConnected = true;
                lastStreamMessage = Date.now();
                handlePayload(JSON.parse(event.data));
            } catch (err) {
                if (debugEl) debugEl.textContent = `BAD STREAM DATA / ${err.message || err}`;
            }
        });
        source.onerror = () => {
            streamConnected = false;
            source.close();
            if (!streamReconnectTimer) {
                streamReconnectTimer = setTimeout(connectEventStream, 1500);
            }
        };
    };

    const poll = async () => {
        if (streamConnected && Date.now() - lastStreamMessage < 1000) {
            schedulePoll(2000);
            return;
        }
        if (polling) return;
        polling = true;
        let nextDelay = 1000;
        try {
            try {
                handlePayload(await fetchState(activeStateUrl, activeStateUrl === fallbackStateUrl));
            } catch (err) {
                if (!fallbackStateUrl || fallbackStateUrl === activeStateUrl) throw err;
                activeStateUrl = fallbackStateUrl;
                handlePayload(await fetchState(fallbackStateUrl, true));
            }
            nextDelay = wandMotion.active ? 250 : (streamConnected ? 1000 : 3000);
        } catch (err) {
            if (statusEl) statusEl.textContent = 'BACKEND WAITING';
            if (debugEl && wandConnected) debugEl.textContent = `BACKEND NOT READY / ${err.message || err}`;
            nextDelay = 5000;
        } finally {
            polling = false;
            schedulePoll(nextDelay);
        }
    };

    const schedulePoll = delay => {
        if (nextPollTimer) clearTimeout(nextPollTimer);
        nextPollTimer = setTimeout(poll, delay);
    };

    connectEventStream();
    fetchFluidConfig().catch(() => {});
    setInterval(() => {
        fetchFluidConfig().catch(() => {});
    }, 2500);
    poll();

    setInterval(() => {
        const now = Date.now();
        if (statusEl && now - lastBackendMessage > 5000) {
            statusEl.textContent = 'BACKEND WAITING';
        }
        if (debugEl && now - lastMotionMessage > 15000) {
            debugEl.textContent = 'WAITING FOR WAND IMU DATA';
        }
    }, 1000);
}

function formatSpellName (spell) {
    if (!spell || spell === 'awaiting') return '';
    return String(spell).replace(/_/g, ' ').toUpperCase();
}

//function multipleSplats (amount) {
//    for (let i = 0; i < amount; i++) {
//        const color = generateColor();
//        color.r *= 10.0;
//        color.g *= 10.0;
//        color.b *= 10.0;
//        const x = Math.random();
//        const y = Math.random();
//        const dx = 1000 * (Math.random() - 0.5);
//        const dy = 1000 * (Math.random() - 0.5);
//        splat(x, y, dx, dy, color);
//    }
//}

function splat (x, y, dx, dy, color) {
    splatProgram.bind();
    gl.uniform1i(splatProgram.uniforms.uTarget, velocity.read.attach(0));
    gl.uniform1f(splatProgram.uniforms.aspectRatio, canvas.width / canvas.height);
    gl.uniform2f(splatProgram.uniforms.point, x, y);
    gl.uniform3f(splatProgram.uniforms.color, dx, dy, 0.0);
    gl.uniform1f(splatProgram.uniforms.radius, correctRadius(config.SPLAT_RADIUS / 100.0));
    blit(velocity.write);
    velocity.swap();

    gl.uniform1i(splatProgram.uniforms.uTarget, dye.read.attach(0));
    gl.uniform3f(splatProgram.uniforms.color, color.r, color.g, color.b);
    blit(dye.write);
    dye.swap();
}

function correctRadius (radius) {
    let aspectRatio = canvas.width / canvas.height;
    if (aspectRatio > 1)
        radius *= aspectRatio;
    return radius;
}

canvas.addEventListener('mousedown', e => {
    let posX = scaleByPixelRatio(e.offsetX);
    let posY = scaleByPixelRatio(e.offsetY);
    let pointer = pointers.find(p => p.id == -1);
    if (pointer == null) {
        pointer = new pointerPrototype();
        pointers.push(pointer);
    }
    updatePointerDownData(pointer, -1, posX, posY);
});

canvas.addEventListener('mousemove', e => {
    let pointer = pointers[0];
    if (!pointer.down) return;
    let posX = scaleByPixelRatio(e.offsetX);
    let posY = scaleByPixelRatio(e.offsetY);
    updatePointerMoveData(pointer, posX, posY);
});

window.addEventListener('mouseup', () => {
    let pointer = pointers.find(p => p.id == -1);
    if (pointer != null) updatePointerUpData(pointer);
});

canvas.addEventListener('touchstart', e => {
    e.preventDefault();
    const touches = e.targetTouches;
    for (let i = 0; i < touches.length; i++) {
        let pointer = pointers.find(p => p.id == touches[i].identifier);
        if (pointer == null) {
            pointer = new pointerPrototype();
            pointers.push(pointer);
        }
        let posX = scaleByPixelRatio(touches[i].pageX);
        let posY = scaleByPixelRatio(touches[i].pageY);
        updatePointerDownData(pointer, touches[i].identifier, posX, posY);
    }
});

canvas.addEventListener('touchmove', e => {
    e.preventDefault();
    const touches = e.targetTouches;
    for (let i = 0; i < touches.length; i++) {
        let pointer = pointers.find(p => p.id == touches[i].identifier);
        if (pointer == null) continue;
        if (!pointer.down) continue;
        let posX = scaleByPixelRatio(touches[i].pageX);
        let posY = scaleByPixelRatio(touches[i].pageY);
        updatePointerMoveData(pointer, posX, posY);
    }
}, false);

window.addEventListener('touchend', e => {
    const touches = e.changedTouches;
    for (let i = 0; i < touches.length; i++)
    {
        let pointer = pointers.find(p => p.id == touches[i].identifier);
        if (pointer == null) continue;
        updatePointerUpData(pointer);
    }
});

window.addEventListener('keydown', e => {
    if (e.code === 'KeyP')
        config.PAUSED = !config.PAUSED;
    if (e.key === ' ')
        splatStack.push(parseInt(Math.random() * 20) + 5);
});

function updatePointerDownData (pointer, id, posX, posY) {
    pointer.id = id;
    pointer.down = true;
    pointer.moved = false;
    pointer.texcoordX = posX / canvas.width;
    pointer.texcoordY = 1.0 - posY / canvas.height;
    pointer.prevTexcoordX = pointer.texcoordX;
    pointer.prevTexcoordY = pointer.texcoordY;
    pointer.deltaX = 0;
    pointer.deltaY = 0;
    pointer.color = generateColor();
}

function updatePointerMoveData (pointer, posX, posY) {
    pointer.prevTexcoordX = pointer.texcoordX;
    pointer.prevTexcoordY = pointer.texcoordY;
    pointer.texcoordX = posX / canvas.width;
    pointer.texcoordY = 1.0 - posY / canvas.height;
    pointer.deltaX = correctDeltaX(pointer.texcoordX - pointer.prevTexcoordX);
    pointer.deltaY = correctDeltaY(pointer.texcoordY - pointer.prevTexcoordY);
    pointer.moved = Math.abs(pointer.deltaX) > 0 || Math.abs(pointer.deltaY) > 0;
}

function updatePointerUpData (pointer) {
    pointer.down = false;
}

function correctDeltaX (delta) {
    let aspectRatio = canvas.width / canvas.height;
    if (aspectRatio < 1) delta *= aspectRatio;
    return delta;
}

function correctDeltaY (delta) {
    let aspectRatio = canvas.width / canvas.height;
    if (aspectRatio > 1) delta /= aspectRatio;
    return delta;
}

function generateColor () {
    if (config.MATCH_LED_COLOR) return getConfiguredFluidColor();

    let c = HSVtoRGB(Math.random(), 1.0, 1.0); // replace this line with below for 1 colour.
	//let c = HSVtoRGB(0, 1.0, 1.0); // One colour by changing first number by 0.1
    c.r *= 0.15;
    c.g *= 0.15;
    c.b *= 0.15;
    return c;
}

function getConfiguredFluidColor () {
    const colorName = typeof config.LED_COLOR_NAME === 'string' ? config.LED_COLOR_NAME : '';
    if (colorName === 'White') {
        return { r: 0.15, g: 0.15, b: 0.15 };
    }
    if (Object.prototype.hasOwnProperty.call(fluidColorHues, colorName)) {
        const color = HSVtoRGB(fluidColorHues[colorName], 1.0, 1.0);
        color.r *= 0.15;
        color.g *= 0.15;
        color.b *= 0.15;
        return color;
    }

    const color = Array.isArray(config.LED_COLOR) ? config.LED_COLOR : [255, 255, 255];
    return {
        r: (Number(color[0]) || 0) / 255 * 0.15,
        g: (Number(color[1]) || 0) / 255 * 0.15,
        b: (Number(color[2]) || 0) / 255 * 0.15
    };
}

function HSVtoRGB (h, s, v) {
    let r, g, b, i, f, p, q, t;
    i = Math.floor(h * 6);
    f = h * 6 - i;
    p = v * (1 - s);
    q = v * (1 - f * s);
    t = v * (1 - (1 - f) * s);

    switch (i % 6) {
        case 0: r = v, g = t, b = p; break;
        case 1: r = q, g = v, b = p; break;
        case 2: r = p, g = v, b = t; break;
        case 3: r = p, g = q, b = v; break;
        case 4: r = t, g = p, b = v; break;
        case 5: r = v, g = p, b = q; break;
    }

    return {
        r,
        g,
        b
    };
}

function normalizeColor (input) {
    let output = {
        r: input.r / 255,
        g: input.g / 255,
        b: input.b / 255
    };
    return output;
}

function wrap (value, min, max) {
    let range = max - min;
    if (range == 0) return min;
    return (value - min) % range + min;
}

function getResolution (resolution) {
    let aspectRatio = gl.drawingBufferWidth / gl.drawingBufferHeight;
    if (aspectRatio < 1)
        aspectRatio = 1.0 / aspectRatio;

    let min = Math.round(resolution);
    let max = Math.round(resolution * aspectRatio);

    if (gl.drawingBufferWidth > gl.drawingBufferHeight)
        return { width: max, height: min };
    else
        return { width: min, height: max };
}

function getTextureScale (texture, width, height) {
    return {
        x: width / texture.width,
        y: height / texture.height
    };
}

function scaleByPixelRatio (input) {
    let pixelRatio = window.devicePixelRatio || 1;
    return Math.floor(input * pixelRatio);
}

function hashCode (s) {
    if (s.length == 0) return 0;
    let hash = 0;
    for (let i = 0; i < s.length; i++) {
        hash = (hash << 5) - hash + s.charCodeAt(i);
        hash |= 0; // Convert to 32bit integer
    }
    return hash;
};
