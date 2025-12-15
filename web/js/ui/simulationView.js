/**
 * 模拟视图模块
 * 使用 Canvas 渲染粒子（圆形，辉光效果基于能量）
 * 
 * 设计原则：
 * - 粒子颜色从 CSS 变量读取（红色=反应物A，蓝色=产物B）
 * - 能量通过辉光效果体现：高能量=强辉光，低能量=弱辉光
 * - Canvas 填满父容器
 */

import { CONFIG } from '../config.js';
import { stateManager } from '../state.js';

export class SimulationView {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d', { alpha: false });

        // 性能统计
        this.frameCount = 0;
        this.lastFpsUpdate = performance.now();
        this.currentFps = 0;

        // DOM 元素
        this.statsTime = document.getElementById('stats-time');
        this.statsFps = document.getElementById('stats-fps');

        // 粒子数据
        this.particles = [];

        // 缓存
        this.glowTextureA = null;
        this.glowTextureB = null;
        this.lastRadiusA = 0;
        this.lastRadiusB = 0;

        // 高能高亮阈值（服务端 energy 已按 1000K 上限归一化到 [0,1]）
        // 采用“绝对阈值”而非分位数阈值，确保 100K/1000K 高亮数量有明显变化
        this.highlightEnergyThreshold = 0.10;

        this.init();
    }

    init() {
        this.setupCanvas();
        this.subscribeToState();
        this.startRenderLoop();
    }

    setupCanvas() {
        const container = this.canvas.parentElement;

        const updateSize = () => {
            const rect = container.getBoundingClientRect();
            const width = rect.width;
            const height = rect.height;

            if (width > 0 && height > 0) {
                this.canvas.width = width;
                this.canvas.height = height;
            }
        };

        requestAnimationFrame(() => {
            updateSize();
            setTimeout(updateSize, 100);
        });

        window.addEventListener('resize', updateSize);

        if (typeof ResizeObserver !== 'undefined') {
            const resizeObserver = new ResizeObserver(() => {
                requestAnimationFrame(updateSize);
            });
            resizeObserver.observe(container);
        }
    }

    subscribeToState() {
        stateManager.subscribe('particles', (particles) => {
            this.particles = particles;
        });

        // 接收来自后端的能量统计（归一化）：包含 mean/std/threshold/nSigma
        stateManager.subscribe('energyStats', (stats) => {
            if (stats && typeof stats.threshold === 'number') {
                // 使用服务端计算的物理阈值（normalized）
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
        const fps = 60;
        const interval = 1000 / fps;
        let lastTime = 0;

        const render = (currentTime) => {
            requestAnimationFrame(render);

            const elapsed = currentTime - lastTime;

            // 如果间隔大于目标帧间隔，则渲染
            if (elapsed > interval) {
                // 校正上次渲染时间，扣除超出部分（避免累积漂移）
                lastTime = currentTime - (elapsed % interval);

                this.render();
                this.updateFps();
            }
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
        const ctx = this.ctx;
        const width = this.canvas.width;
        const height = this.canvas.height;

        const colors = CONFIG.getColors();

        // 清空画布
        ctx.fillStyle = colors.bg;
        ctx.fillRect(0, 0, width, height);

        // 绘制边框
        ctx.strokeStyle = colors.border;
        ctx.lineWidth = 1;
        ctx.strokeRect(0, 0, width, height);

        if (!this.particles || this.particles.length === 0) {
            return;
        }

        const particles = this.particles;
        const config = stateManager.getState().config;
        const substances = config.substances || [];

        // 预构建 typeId -> substance 映射，避免在热点循环中反复 find
        const substanceByType = new Map();
        for (const s of substances) {
            if (s && typeof s.typeId === 'number') {
                substanceByType.set(s.typeId, s);
            }
        }
        const boxSize = CONFIG.SIMULATION.BOX_SIZE;
        const screenScale = Math.min(width, height);

        const scaleX = width;
        const scaleY = height;

        // 按物质类型分组绘制
        for (const substance of substances) {
            const typeId = substance.typeId;
            const colorHue = substance.colorHue || 0;
            const physicsRadius = substance.radius || 0.15;
            const radius = (physicsRadius / boxSize) * screenScale;
            const color = `hsl(${colorHue}, 70%, 50%)`;

            // 确保有辉光纹理缓存
            if (!this.glowTextures) this.glowTextures = {};
            const cacheKey = `${typeId}_${colorHue}_${radius.toFixed(2)}`;
            if (!this.glowTextures[cacheKey]) {
                this.glowTextures[cacheKey] = this.createGlowTexture(radius, color);
            }

            // 绘制该类型的所有粒子
            ctx.beginPath();
            ctx.fillStyle = color;
            for (let i = 0; i < particles.length; i++) {
                if (particles[i].type === typeId) {
                    const p = particles[i];
                    const x = p.x * scaleX;
                    const y = p.y * scaleY;
                    ctx.moveTo(x + radius, y);
                    ctx.arc(x, y, radius, 0, Math.PI * 2);
                }
            }
            ctx.fill();
        };

        // 高能粒子判定阈值：绝对阈值（随温度改变能量整体水平，从而改变高亮数量）
        const threshold = this.highlightEnergyThreshold;

        // 第二遍：绘制高能粒子辉光（使用预渲染纹理）
        ctx.globalCompositeOperation = 'lighter';

        for (let i = 0; i < particles.length; i++) {
            const p = particles[i];
            const energy = p.energy !== undefined ? p.energy : 0;

            if (energy >= threshold) {
                const x = p.x * scaleX;
                const y = p.y * scaleY;

                // 从缓存获取辉光纹理
                const substance = substanceByType.get(p.type);
                if (!substance) continue;

                const physicsRadius = substance.radius || 0.15;
                const radius = (physicsRadius / boxSize) * screenScale;
                const colorHue = substance.colorHue || 0;
                const cacheKey = `${p.type}_${colorHue}_${radius.toFixed(2)}`;
                const texture = this.glowTextures?.[cacheKey];

                if (texture) {
                    const offset = texture.width / 2;
                    ctx.drawImage(texture, x - offset, y - offset, texture.width, texture.height);
                }
            }
        }

        ctx.globalCompositeOperation = 'source-over';
    }

    /**
     * 创建辉光纹理 (电影级效果，模拟 Bloom)
     * 使用径向渐变：白核 -> 高亮色 -> 衰减色 -> 透明
     */
    createGlowTexture(radius, colorStr) {
        // 辉光不得溢出超过半径的一倍 -> 总辉光半径 = 2 * 粒子半径
        const glowSize = radius * 2;
        const size = Math.ceil(glowSize * 2);

        const canvas = document.createElement('canvas');
        canvas.width = size;
        canvas.height = size;
        const ctx = canvas.getContext('2d');

        const centerX = size / 2;
        const centerY = size / 2;

        // 创建径向渐变
        const gradient = ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, glowSize);

        // 简单处理颜色：提亮
        let lightColor = colorStr;
        try {
            // 简单的字符串替换，将亮度调高
            // 假设格式为 hsl(h, 100%, 50%) -> hsl(h, 100%, 80%)
            lightColor = colorStr.replace(/, \d+%\)/, ', 80%)');
        } catch (e) {
            console.warn('Color replace failed', e);
        }

        // 核心：纯白 (模拟高温/高能) - 非常小，仅占 5%
        gradient.addColorStop(0.0, 'rgba(255, 255, 255, 1)');
        // 核心边缘：高亮色 - 占 20%
        gradient.addColorStop(0.2, lightColor);
        // 主体光晕：原色 - 占 50%
        gradient.addColorStop(0.5, colorStr);
        // 边缘衰减：透明
        gradient.addColorStop(1.0, 'rgba(0, 0, 0, 0)');

        ctx.fillStyle = gradient;
        // 填充整个画布
        ctx.fillRect(0, 0, size, size);

        return canvas;
    }
}
