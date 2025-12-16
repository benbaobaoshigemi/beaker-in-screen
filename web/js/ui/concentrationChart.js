/**
 * 浓度图模块
 * 显示产物浓度随时间的变化（模拟曲线 + 理论曲线）
 * 特性：
 * - Y 轴固定范围，不自动缩放
 * - X 轴自动左右滚动
 * - 曲线颜色与粒子颜色一致
 * - 细线条
 */

import { CONFIG } from '../config.js';
import { stateManager } from '../state.js';

export class ConcentrationChart {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');

        // 数据
        this.data = [];

        // 视窗控制（用于暂停态左右平移/水平缩放）
        this.followLatest = true;
        this.viewEndIndex = null; // slice 的 end
        this.defaultWindowPoints = CONFIG.CHART.X_AXIS_VISIBLE_POINTS;
        this.windowPoints = this.defaultWindowPoints;
        // 允许缩小视图(看更全局)：窗口可变大到全部数据；允许放大回默认比例
        this.minWindowPoints = 2;
        this.maxWindowPoints = CONFIG.CHART.MAX_POINTS;

        // 运行状态
        this.isRunning = false;
        this.isStarted = false;

        // 指针交互状态
        this.activePointers = new Map();
        this.gestureMode = null; // 'pan' | 'pinch' | null
        this.gestureStart = null;

        // Y 轴范围（根据配置的总粒子数动态初始化）
        this.yMax = CONFIG.CHART.CONCENTRATION.Y_MAX;

        this.init();
    }

    /**
     * 初始化
     */
    init() {
        this.setupCanvas();
        this.subscribeToState();
        this.attachInteractions();
        this.startRenderLoop();
    }

    /**
     * 设置 Canvas（支持高清屏）
     */
    setupCanvas() {
        const container = this.canvas.parentElement;
        const rect = container.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;

        // 存储 CSS 尺寸（渲染时使用）
        this.cssWidth = rect.width || 400;
        this.cssHeight = rect.height || 200;

        // 设置实际像素尺寸
        this.canvas.width = this.cssWidth * dpr;
        this.canvas.height = this.cssHeight * dpr;

        // 设置 CSS 显示尺寸
        this.canvas.style.width = this.cssWidth + 'px';
        this.canvas.style.height = this.cssHeight + 'px';

        // 缩放绘制上下文
        this.ctx.setTransform(1, 0, 0, 1, 0, 0);
        this.ctx.scale(dpr, dpr);

        window.addEventListener('resize', () => {
            const rect = container.getBoundingClientRect();
            const dpr = window.devicePixelRatio || 1;

            this.cssWidth = rect.width || 400;
            this.cssHeight = rect.height || 200;

            this.canvas.width = this.cssWidth * dpr;
            this.canvas.height = this.cssHeight * dpr;
            this.canvas.style.width = this.cssWidth + 'px';
            this.canvas.style.height = this.cssHeight + 'px';

            this.ctx.setTransform(1, 0, 0, 1, 0, 0);
            this.ctx.scale(dpr, dpr);
        });
    }

    /**
     * 订阅状态
     */
    subscribeToState() {
        stateManager.subscribe('chartData', (chartData) => {
            this.data = chartData.concentrationHistory;

            // 自动跟随最新数据（仅在运行态）
            if (this.followLatest) {
                this.viewEndIndex = null;
            } else {
                const maxEnd = this.data.length;
                if (typeof this.viewEndIndex === 'number') {
                    this.viewEndIndex = Math.max(2, Math.min(maxEnd, this.viewEndIndex));
                }
            }
        });

        stateManager.subscribe('simulation', (sim) => {
            const wasRunning = this.isRunning;
            this.isRunning = !!sim?.running;
            this.isStarted = !!sim?.started;

            if (this.isRunning) {
                // 运行时固定跟随最新
                this.followLatest = true;
                this.viewEndIndex = null;
                // 运行态回到默认窗口，避免暂停时放大/缩小影响运行体验
                this.windowPoints = this.defaultWindowPoints;
            } else if (wasRunning && !this.isRunning) {
                // 从运行切到暂停：固定当前视窗
                this.followLatest = false;
                this.viewEndIndex = this.data.length;
            }
        });

        // 动态更新浓度值显示
        stateManager.subscribe('concentration', (concentration) => {
            const valuesContainer = document.getElementById('concentration-values');
            if (!valuesContainer) return;

            const counts = concentration.substanceCounts || {};
            valuesContainer.innerHTML = Object.entries(counts)
                .map(([id, count]) => `<span>[${id}] = ${count}</span>`)
                .join('');
        });

        // 订阅配置变化，动态调整 Y 轴范围
        stateManager.subscribe('config', (config) => {
            if (config && config.substances) {
                // 计算总粒子数，Y 轴范围设为总粒子数的 1.2 倍（留出余量）
                const totalParticles = config.substances.reduce((sum, s) => sum + (s.initialCount || 0), 0);
                if (totalParticles > 0) {
                    // 向上取整到合适的刻度（1000的倍数）
                    this.yMax = Math.ceil(totalParticles * 1.2 / 1000) * 1000;
                }
            }
        });
    }

    /**
     * 暂停态交互：
     * - 单指/鼠标拖拽：左右平移时间窗口
     * - 滚轮 / 双指：水平缩放（调整窗口长度）
     */
    attachInteractions() {
        if (!this.canvas) return;

        // 允许接收 pointer 事件（避免浏览器默认手势抢占）
        this.canvas.style.touchAction = 'none';

        const ensureManualView = () => {
            if (this.followLatest) {
                this.followLatest = false;
                this.viewEndIndex = this.data.length;
            }
            if (typeof this.viewEndIndex !== 'number') {
                this.viewEndIndex = this.data.length;
            }
        };

        const clampWindowPoints = (n) => {
            const max = Math.max(this.minWindowPoints, Math.min(this.maxWindowPoints, this.data.length || this.maxWindowPoints));
            return Math.max(this.minWindowPoints, Math.min(max, n));
        };

        const clampEndIndex = (n) => {
            const maxEnd = this.data.length;
            if (maxEnd < 2) return maxEnd;
            // 下限设为当前窗口大小，确保 startIndex = endIndex - windowPoints >= 0
            // 这样用户可以完整拖动到最左边查看从时间0开始的数据
            const minEnd = Math.min(this.windowPoints, maxEnd);
            return Math.max(minEnd, Math.min(maxEnd, n));
        };

        const getPlotWidth = () => {
            const width = this.cssWidth || this.canvas.width;
            const padding = CONFIG.CHART.PADDING;
            return Math.max(10, width - padding.LEFT - padding.RIGHT);
        };

        const toDistance = (p1, p2) => {
            const dx = p2.x - p1.x;
            const dy = p2.y - p1.y;
            return Math.hypot(dx, dy);
        };

        const onPointerDown = (e) => {
            // 仅在暂停态允许拖拽/缩放
            if (this.isRunning) return;
            if (!this.data || this.data.length < 2) return;

            this.canvas.setPointerCapture(e.pointerId);
            this.activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

            ensureManualView();

            if (this.activePointers.size === 1) {
                this.gestureMode = 'pan';
                this.gestureStart = {
                    x: e.clientX,
                    endIndex: this.viewEndIndex,
                    windowPoints: this.windowPoints,
                };
            } else if (this.activePointers.size === 2) {
                const pts = Array.from(this.activePointers.values());
                this.gestureMode = 'pinch';
                this.gestureStart = {
                    distance: toDistance(pts[0], pts[1]),
                    endIndex: this.viewEndIndex,
                    windowPoints: this.windowPoints,
                };
            }
        };

        const onPointerMove = (e) => {
            if (!this.activePointers.has(e.pointerId)) return;
            this.activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

            if (!this.gestureMode || !this.gestureStart) return;

            if (this.gestureMode === 'pan' && this.activePointers.size === 1) {
                const dx = e.clientX - this.gestureStart.x;
                const plotWidth = getPlotWidth();
                const pointsPerPixel = this.windowPoints / plotWidth;
                const deltaPoints = Math.round(dx * pointsPerPixel);

                // 右拖（dx>0）=> 看更早的数据 => endIndex 变小
                const nextEnd = clampEndIndex(this.gestureStart.endIndex - deltaPoints);
                this.viewEndIndex = nextEnd;
            }

            if (this.gestureMode === 'pinch' && this.activePointers.size === 2) {
                const pts = Array.from(this.activePointers.values());
                const dist = toDistance(pts[0], pts[1]);
                const startDist = this.gestureStart.distance || 1;
                if (startDist < 1e-6) return;

                // 双指拉开（dist变大）=> 缩小窗口（更“放大”）
                const zoomRatio = startDist / dist;
                const rawNextWindow = Math.round(this.gestureStart.windowPoints * zoomRatio);
                // 允许缩小视图(窗口变大)到全局，也允许放大回默认比例(窗口变小到默认值)
                this.windowPoints = clampWindowPoints(rawNextWindow);

                // 缩放后保持 endIndex 合法
                this.viewEndIndex = clampEndIndex(this.viewEndIndex);
            }
        };

        const onPointerUp = (e) => {
            if (this.activePointers.has(e.pointerId)) {
                this.activePointers.delete(e.pointerId);
            }
            if (this.activePointers.size === 0) {
                this.gestureMode = null;
                this.gestureStart = null;
                return;
            }
            if (this.activePointers.size === 1) {
                // 从 pinch 回落到 pan
                const only = Array.from(this.activePointers.values())[0];
                this.gestureMode = 'pan';
                this.gestureStart = {
                    x: only.x,
                    endIndex: this.viewEndIndex,
                    windowPoints: this.windowPoints,
                };
            }
        };

        const onWheel = (e) => {
            if (this.isRunning) return;
            if (!this.data || this.data.length < 2) return;

            // 仅在指针位于画布上时缩放，避免影响其他区域
            e.preventDefault();
            ensureManualView();

            // 滚轮上滑：更“放大”(窗口变小，但不小于默认)；滚轮下滑：更“全局”(窗口变大)
            const zoomIn = e.deltaY < 0;
            const factor = zoomIn ? 0.9 : 1.1;
            this.windowPoints = clampWindowPoints(Math.round(this.windowPoints * factor));
            this.viewEndIndex = clampEndIndex(this.viewEndIndex);
        };

        this.canvas.addEventListener('pointerdown', onPointerDown);
        this.canvas.addEventListener('pointermove', onPointerMove);
        this.canvas.addEventListener('pointerup', onPointerUp);
        this.canvas.addEventListener('pointercancel', onPointerUp);
        this.canvas.addEventListener('wheel', onWheel, { passive: false });
    }

    /**
     * 启动渲染循环
     */
    startRenderLoop() {
        const render = () => {
            this.render();
            requestAnimationFrame(render);
        };
        requestAnimationFrame(render);
    }

    /**
     * 渲染
     */
    render() {
        const ctx = this.ctx;
        const width = this.cssWidth || this.canvas.width;
        const height = this.cssHeight || this.canvas.height;
        const padding = CONFIG.CHART.PADDING;

        // 获取颜色
        const colors = CONFIG.getColors();
        const curveColors = CONFIG.getCurveColors();

        // 清空画布
        ctx.fillStyle = colors.surface;
        ctx.fillRect(0, 0, width, height);

        // 绘图区域
        const plotWidth = width - padding.LEFT - padding.RIGHT;
        const plotHeight = height - padding.TOP - padding.BOTTOM;
        const plotOriginX = padding.LEFT;
        const plotOriginY = height - padding.BOTTOM;

        // 绘制坐标轴
        ctx.strokeStyle = colors.border;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(plotOriginX, padding.TOP);
        ctx.lineTo(plotOriginX, plotOriginY);
        ctx.lineTo(width - padding.RIGHT, plotOriginY);
        ctx.stroke();

        // Y 轴动态范围（根据配置的总粒子数自动调整）
        const yMin = CONFIG.CHART.CONCENTRATION.Y_MIN;
        const yMax = this.yMax;

        // 绘制左侧 Y 轴刻度
        ctx.fillStyle = colors.textMuted;
        ctx.font = '12px Inter, sans-serif';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';

        const tickCount = 5;
        for (let i = 0; i <= tickCount; i++) {
            const value = (yMax / tickCount) * i;
            const y = plotOriginY - (value / yMax) * plotHeight;
            ctx.fillText(value.toFixed(0), plotOriginX - 5, y);

            // 绘制网格线
            ctx.strokeStyle = colors.border;
            ctx.globalAlpha = 0.3;
            ctx.beginPath();
            ctx.moveTo(plotOriginX, y);
            ctx.lineTo(width - padding.RIGHT, y);
            ctx.stroke();
            ctx.globalAlpha = 1.0;
        }
        if (this.data.length < 2) {
            return;
        }

        // 计算可视窗口（运行态自动滚动；暂停态允许平移/缩放）
        const endIndex = this.followLatest ? this.data.length : (typeof this.viewEndIndex === 'number' ? this.viewEndIndex : this.data.length);
        const windowPoints = Math.max(2, this.windowPoints);
        const startIndex = Math.max(0, endIndex - windowPoints);
        const visibleData = this.data.slice(startIndex, endIndex);

        if (visibleData.length < 2) return;

        const tStart = visibleData[0].time;
        const tEnd = visibleData[visibleData.length - 1].time;
        const timeSpan = tEnd - tStart;

        if (timeSpan < 1e-9) return;

        const pxPerSec = plotWidth / timeSpan;

        // 绘制横轴刻度（时间）
        ctx.fillStyle = colors.textMuted;
        ctx.font = '12px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';

        const xTickCount = 5;
        for (let i = 0; i <= xTickCount; i++) {
            const frac = i / xTickCount;
            const x = plotOriginX + frac * plotWidth;
            const t = tStart + frac * timeSpan;
            const decimals = timeSpan < 1 ? 2 : (timeSpan < 10 ? 1 : 0);
            ctx.fillText(t.toFixed(decimals), x, plotOriginY + 8);

            // 竖向网格线
            ctx.strokeStyle = colors.border;
            ctx.globalAlpha = 0.15;
            ctx.beginPath();
            ctx.moveTo(x, padding.TOP);
            ctx.lineTo(x, plotOriginY);
            ctx.stroke();
            ctx.globalAlpha = 1.0;
        }

        // 获取配置中的物质列表
        const config = stateManager.getState().config;
        const substances = config.substances || [];

        // 为每个物质绘制曲线
        for (const substance of substances) {
            const id = substance.id;
            const colorHue = substance.colorHue || 0;
            const color = `hsl(${colorHue}, 70%, 50%)`;

            ctx.strokeStyle = color;
            ctx.lineWidth = CONFIG.CHART.LINE_WIDTH;
            ctx.setLineDash([]);
            ctx.beginPath();

            let firstPoint = true;
            for (const point of visibleData) {
                const t = point.time;
                if (t < tStart || t > tEnd) continue;

                const x = plotOriginX + (t - tStart) * pxPerSec;
                const value = point.counts?.[id] || 0;
                const y = plotOriginY - (value / yMax) * plotHeight;

                if (x < plotOriginX - 10) continue;
                if (x > width + 10) break;

                if (firstPoint) {
                    ctx.moveTo(x, y);
                    firstPoint = false;
                } else {
                    ctx.lineTo(x, y);
                }
            }
            ctx.stroke();
        }
    }
}

