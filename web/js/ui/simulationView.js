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
        this.ctx = this.canvas.getContext('2d');

        // 性能统计
        this.frameCount = 0;
        this.lastFpsUpdate = performance.now();
        this.currentFps = 0;

        // DOM 元素
        this.statsTime = document.getElementById('stats-time');
        this.statsFps = document.getElementById('stats-fps');

        // 粒子数据
        this.particles = [];

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

        // 动态获取粒子半径（A 和 B 分别）
        const physicsRadiusA = config.radiusA || 0.3;
        const physicsRadiusB = config.radiusB || 0.3;
        const boxSize = CONFIG.SIMULATION.BOX_SIZE;
        // 取 width 和 height 中较小的作为基准，保持圆形
        const screenScale = Math.min(width, height);
        const radiusA = (physicsRadiusA / boxSize) * screenScale;
        const radiusB = (physicsRadiusB / boxSize) * screenScale;

        const scaleX = width;
        const scaleY = height;

        // 渲染每个粒子 - 实心圆，无辉光，纯色
        ctx.shadowBlur = 0; // 确保无阴影

        for (let i = 0; i < particles.length; i++) {
            const p = particles[i];
            const energy = p.energy !== undefined ? p.energy : 0.5;
            const color = CONFIG.getParticleColor(p.type, energy);

            const x = p.x * scaleX;
            const y = p.y * scaleY;

            // 根据粒子类型选择半径
            const radius = p.type === 0 ? radiusA : radiusB;

            ctx.fillStyle = color;
            ctx.beginPath();
            ctx.arc(x, y, radius, 0, Math.PI * 2);
            ctx.fill();
        }

        // 重置阴影
        ctx.shadowBlur = 0;
    }
}

