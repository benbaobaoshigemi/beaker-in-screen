/**
 * GPU加速粒子渲染模块
 * 使用PIXI.js WebGL/WebGPU渲染，性能比Canvas 2D提升10-100倍
 */

import { CONFIG } from '../config.js';
import { stateManager } from '../state.js';

export class SimulationViewGPU {
    constructor(canvasId) {
        this.canvasElement = document.getElementById(canvasId);
        this.container = this.canvasElement.parentElement;

        // 性能统计
        this.frameCount = 0;
        this.lastFpsUpdate = performance.now();
        this.currentFps = 0;

        // DOM元素
        this.statsTime = document.getElementById('stats-time');
        this.statsFps = document.getElementById('stats-fps');

        // 粒子数据
        this.particles = [];

        // 高能高亮阈值
        this.highlightEnergyThreshold = 0.10;

        // PIXI状态
        this.app = null;
        this.particleContainer = null;
        this.glowContainer = null;
        this.sprites = [];
        this.glowSprites = [];
        this.baseTextures = {};  // 按颜色缓存纹理
        this.glowTextures = {};  // 按颜色缓存辉光纹理

        this.init();
    }

    async init() {
        await this.initPixi();
        this.startRenderLoop();  // 先启动渲染循环
        this.subscribeToState(); // 再订阅数据
        console.log('[GPU Renderer] Initialization complete');
    }

    async initPixi() {
        // 直接从CDN加载PIXI.js
        const PIXI = await import('https://cdn.jsdelivr.net/npm/pixi.js@8/dist/pixi.min.mjs');
        this.PIXI = PIXI;

        // 隐藏原始canvas，PIXI会创建自己的canvas
        this.canvasElement.style.display = 'none';

        // 创建PIXI应用
        this.app = new PIXI.Application();
        await this.app.init({
            width: this.container.clientWidth,
            height: this.container.clientHeight,
            backgroundColor: 0x000000,  // 纯黑色背景
            antialias: false,  // 禁用抗锯齿提升性能
            resolution: window.devicePixelRatio || 1,
            autoDensity: true,
            powerPreference: 'high-performance',
        });

        // 添加到容器
        this.app.canvas.style.position = 'absolute';
        this.app.canvas.style.top = '0';
        this.app.canvas.style.left = '0';
        this.app.canvas.style.width = '100%';
        this.app.canvas.style.height = '100%';
        this.container.appendChild(this.app.canvas);

        // 创建粒子容器（高性能模式）
        this.particleContainer = new PIXI.Container();
        this.glowContainer = new PIXI.Container();
        this.glowContainer.blendMode = 'add';  // 加法混合实现辉光

        // 注意顺序：先添加粒子，再添加辉光（辉光在上层）
        this.app.stage.addChild(this.particleContainer);
        this.app.stage.addChild(this.glowContainer);

        // 处理窗口大小变化
        this.setupResize();

        console.log('[GPU Renderer] PIXI.js initialized with WebGL/WebGPU');
    }

    setupResize() {
        const resize = () => {
            const width = this.container.clientWidth;
            const height = this.container.clientHeight;
            if (this.app && width > 0 && height > 0) {
                this.app.renderer.resize(width, height);
            }
        };

        window.addEventListener('resize', resize);

        if (typeof ResizeObserver !== 'undefined') {
            const observer = new ResizeObserver(resize);
            observer.observe(this.container);
        }
    }

    // 创建圆形粒子纹理（使用整数key确保缓存命中）
    createParticleTexture(colorHue, radiusPixels) {
        const radiusInt = Math.round(radiusPixels);
        const key = `${colorHue}_${radiusInt}`;
        if (this.baseTextures[key]) {
            return this.baseTextures[key];
        }

        const PIXI = this.PIXI;
        const graphics = new PIXI.Graphics();
        const color = this.hslToHex(colorHue, 70, 50);
        const r = radiusInt || 5;

        graphics.circle(r, r, r);
        graphics.fill(color);

        const texture = this.app.renderer.generateTexture(graphics);
        this.baseTextures[key] = texture;
        graphics.destroy();

        return texture;
    }

    // 创建辉光纹理（使用整数key确保缓存命中）
    createGlowTexture(colorHue, radiusPixels) {
        const radiusInt = Math.round(radiusPixels);
        const key = `glow_${colorHue}_${radiusInt}`;
        if (this.glowTextures[key]) {
            return this.glowTextures[key];
        }

        const PIXI = this.PIXI;
        const r = radiusInt || 5;
        const glowRadius = r * 3;
        const size = Math.ceil(glowRadius * 2) + 4;

        // 使用临时canvas创建渐变纹理
        const canvas = document.createElement('canvas');
        canvas.width = size;
        canvas.height = size;
        const ctx = canvas.getContext('2d');

        const centerX = size / 2;
        const centerY = size / 2;
        const gradient = ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, glowRadius);

        const hslColor = `hsl(${colorHue}, 70%, 50%)`;
        const lightColor = `hsl(${colorHue}, 70%, 80%)`;

        gradient.addColorStop(0.0, 'rgba(255, 255, 255, 1)');
        gradient.addColorStop(0.2, lightColor);
        gradient.addColorStop(0.5, hslColor);
        gradient.addColorStop(1.0, 'rgba(0, 0, 0, 0)');

        ctx.fillStyle = gradient;
        ctx.fillRect(0, 0, size, size);

        const texture = PIXI.Texture.from(canvas);
        this.glowTextures[key] = texture;

        return texture;
    }

    // HSL转16进制颜色
    hslToHex(h, s, l) {
        s /= 100;
        l /= 100;
        const a = s * Math.min(l, 1 - l);
        const f = n => {
            const k = (n + h / 30) % 12;
            const color = l - a * Math.max(Math.min(k - 3, 9 - k, 1), -1);
            return Math.round(255 * color).toString(16).padStart(2, '0');
        };
        return parseInt(`${f(0)}${f(8)}${f(4)}`, 16);
    }

    subscribeToState() {
        stateManager.subscribe('particles', (particles) => {
            this.particles = particles;
        });

        stateManager.subscribe('energyStats', (stats) => {
            if (stats && typeof stats.threshold === 'number') {
                this.highlightEnergyThreshold = Math.max(0, Math.min(1, stats.threshold));
            }
        });

        stateManager.subscribe('simulation', (simulation) => {
            if (this.statsTime) {
                this.statsTime.textContent = `时间: ${simulation.time.toFixed(2)}`;
            }
        });
    }

    startRenderLoop() {
        const render = () => {
            requestAnimationFrame(render);
            this.render();
            this.updateFps();
        };
        requestAnimationFrame(render);
    }

    updateFps() {
        this.frameCount++;
        const now = performance.now();
        const elapsed = now - this.lastFpsUpdate;

        if (elapsed >= 1000) {
            this.currentFps = Math.round(this.frameCount * 1000 / elapsed);
            this.frameCount = 0;
            this.lastFpsUpdate = now;

            if (this.statsFps) {
                this.statsFps.textContent = `FPS: ${this.currentFps}`;
            }
        }
    }

    render() {
        if (!this.app || !this.particles || this.particles.length === 0) {
            return;
        }

        const particles = this.particles;
        const config = stateManager.getState().config;
        const substances = config.substances || [];
        // 优先使用后端下发的 boxSize
        const boxSize = config.boxSize || CONFIG.SIMULATION.BOX_SIZE;

        const width = this.app.screen.width;
        const height = this.app.screen.height;
        const screenScale = Math.min(width, height);
        const threshold = this.highlightEnergyThreshold;

        // 构建物质类型映射
        const substanceByType = new Map();
        for (const s of substances) {
            if (s && typeof s.typeId === 'number') {
                substanceByType.set(s.typeId, s);
            }
        }

        // 性能诊断：记录渲染过程
        if (!this._hasRenderedOnce && particles.length > 0) {
            console.time('GPU-First-Render');
        }

        // 确保有足够的精灵
        this.ensureSprites(particles.length, substanceByType, boxSize, screenScale);

        // 更新精灵位置和可见性
        let glowIndex = 0;
        for (let i = 0; i < particles.length; i++) {
            const p = particles[i];
            const sprite = this.sprites[i];

            if (!sprite) continue;

            const x = p.x * width;
            const y = p.y * height;

            sprite.position.set(x, y);
            sprite.visible = true;

            // 更新粒子纹理（如果类型变化）
            const substance = substanceByType.get(p.type);
            if (substance) {
                const colorHue = substance.colorHue || 0;
                const physicsRadius = substance.radius || 0.15;
                const radius = (physicsRadius / boxSize) * screenScale;
                const texture = this.createParticleTexture(colorHue, radius);

                if (sprite.texture !== texture) {
                    sprite.texture = texture;
                    sprite.anchor.set(0.5);
                }

                // 高能粒子辉光
                const energy = p.energy !== undefined ? p.energy : 0;
                if (energy >= threshold) {
                    if (glowIndex < this.glowSprites.length) {
                        const glowSprite = this.glowSprites[glowIndex];
                        const glowTexture = this.createGlowTexture(colorHue, radius);
                        glowSprite.texture = glowTexture;
                        glowSprite.position.set(x, y);
                        glowSprite.anchor.set(0.5);
                        glowSprite.visible = true;
                        glowSprite.alpha = 0.9;  // 增强辉光alpha
                        glowIndex++;
                    }
                }
            }
        }

        // 隐藏多余的精灵
        for (let i = particles.length; i < this.sprites.length; i++) {
            if (this.sprites[i]) this.sprites[i].visible = false;
        }
        for (let i = glowIndex; i < this.glowSprites.length; i++) {
            if (this.glowSprites[i]) this.glowSprites[i].visible = false;
        }

        if (!this._hasRenderedOnce && particles.length > 0) {
            console.timeEnd('GPU-First-Render');
            console.log(`[GPU Renderer] First frame rendered with ${particles.length} particles`);
            this._hasRenderedOnce = true;
        }
    }

    ensureSprites(count, substanceByType, boxSize, screenScale) {
        const PIXI = this.PIXI;

        // 创建足够的粒子精灵
        while (this.sprites.length < count) {
            const sprite = new PIXI.Sprite();
            sprite.anchor.set(0.5);
            this.particleContainer.addChild(sprite);
            this.sprites.push(sprite);
        }

        // 创建足够的辉光精灵（假设最多30%的粒子需要辉光）
        const maxGlow = Math.ceil(count * 0.3);
        while (this.glowSprites.length < maxGlow) {
            const sprite = new PIXI.Sprite();
            sprite.anchor.set(0.5);
            sprite.visible = false;
            this.glowContainer.addChild(sprite);
            this.glowSprites.push(sprite);
        }
    }
}
