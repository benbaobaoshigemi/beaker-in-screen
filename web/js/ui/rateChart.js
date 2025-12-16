/**
 * 反应速率图模块
 * 显示反应速率 (dP/dt) 随时间的变化
 * 特性：
 * - Y 轴固定初始范围，可根据数据动态调整
 * - X 轴自动左右滚动
 * - 细线条
 */

import { CONFIG } from '../config.js';
import { stateManager } from '../state.js';

export class RateChart {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');

        // DOM 元素
        this.rateCurrent = document.getElementById('rate-current');
        this.rateK = document.getElementById('rate-k');
        this.legendContainer = document.getElementById('rate-legend');

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

        // 物种可见状态（用于图例开关）
        this.visibleSubstances = {};  // { 'A': { forward: true, reverse: true }, ... }

        // 动态 Y 轴最大值（只允许向上扩展，不允许缩小）
        this.yMax = CONFIG.CHART.RATE.Y_MAX;
        this.yMaxHistory = CONFIG.CHART.RATE.Y_MAX;  // 历史最大值

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
            const newData = chartData.rateHistory;

            // 检测重置：新数据为空，但旧数据非空
            if (newData.length === 0 && this.data.length > 0) {
                // 重置 Y 轴历史最大值
                this.yMaxHistory = CONFIG.CHART.RATE.Y_MAX;
                this.yMax = this.yMaxHistory;
            }

            this.data = newData;

            // 自动跟随最新数据（仅在运行态）
            if (this.followLatest) {
                this.viewEndIndex = null;
            } else {
                const maxEnd = this.data.length;
                if (typeof this.viewEndIndex === 'number') {
                    this.viewEndIndex = Math.max(2, Math.min(maxEnd, this.viewEndIndex));
                }
            }

            // 更新当前速率显示（按物种，正/逆）
            if (this.rateCurrent) {
                if (this.data.length > 0) {
                    const last = this.data[this.data.length - 1];
                    const rates = last.rates || {};
                    const rateStr = Object.entries(rates)
                        .map(([s, r]) => {
                            const fwd = (r.forward || 0).toFixed(1);
                            const rev = (r.reverse || 0).toFixed(1);
                            return `${s}:正${fwd}/逆${rev}`;
                        })
                        .join(' ');
                    this.rateCurrent.textContent = rateStr || '速率: --';
                } else {
                    this.rateCurrent.textContent = '速率: --';
                }
            }
        });

        stateManager.subscribe('simulation', (sim) => {
            const wasRunning = this.isRunning;
            this.isRunning = !!sim?.running;
            this.isStarted = !!sim?.started;

            if (this.isRunning) {
                this.followLatest = true;
                this.viewEndIndex = null;
                // 运行态回到默认窗口，避免暂停时缩放影响运行体验
                this.windowPoints = this.defaultWindowPoints;
            } else if (wasRunning && !this.isRunning) {
                this.followLatest = false;
                this.viewEndIndex = this.data.length;
            }
        });

        stateManager.subscribe('concentration', (concentration) => {
            // kEstimated / t1/2 logic removed
        });
    }

    /**
     * 暂停态交互：
     * - 单指/鼠标拖拽：左右平移时间窗口
     * - 滚轮 / 双指：水平缩放（调整窗口长度）
     */
    attachInteractions() {
        if (!this.canvas) return;

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
            return Math.max(2, Math.min(maxEnd, n));
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

                const nextEnd = clampEndIndex(this.gestureStart.endIndex - deltaPoints);
                this.viewEndIndex = nextEnd;
            }

            if (this.gestureMode === 'pinch' && this.activePointers.size === 2) {
                const pts = Array.from(this.activePointers.values());
                const dist = toDistance(pts[0], pts[1]);
                const startDist = this.gestureStart.distance || 1;
                if (startDist < 1e-6) return;

                const zoomRatio = startDist / dist;
                const rawNextWindow = Math.round(this.gestureStart.windowPoints * zoomRatio);
                // 允许缩小视图(窗口变大)到全局，也允许放大回默认比例(窗口变小到默认值)
                this.windowPoints = clampWindowPoints(rawNextWindow);
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
     * 更新图例 UI（每条曲线独立切换）
     */
    updateLegendUI(substances) {
        // 延迟获取 DOM 元素（以防它在构造函数时还不存在）
        if (!this.legendContainer) {
            this.legendContainer = document.getElementById('rate-legend');
        }
        if (!this.legendContainer) return;

        // 存储当前 substances 以便在点击时重新渲染
        this.currentSubstances = substances;

        const substanceColors = {
            'A': 'hsl(0, 80%, 60%)',
            'B': 'hsl(210, 80%, 60%)',
            'C': 'hsl(120, 60%, 50%)',
            'D': 'hsl(60, 80%, 50%)',
            'E': 'hsl(280, 60%, 60%)',
        };

        this.legendContainer.innerHTML = '';

        let substanceIndex = 0;
        for (const substance of substances) {
            // 初始化可见状态
            if (!this.visibleSubstances[substance]) {
                this.visibleSubstances[substance] = { forward: true, reverse: true };
            }

            const color = substanceColors[substance] || `hsl(${substanceIndex * 72}, 70%, 55%)`;
            const visibility = this.visibleSubstances[substance];

            // 正反应图例（实线）
            const fwdDiv = document.createElement('div');
            fwdDiv.className = 'flex items-center gap-0.5 cursor-pointer select-none px-1';
            const fwdLine = document.createElement('span');
            fwdLine.className = 'inline-block w-3 border-t';
            fwdLine.style.borderColor = color;
            fwdLine.style.opacity = visibility.forward ? '1' : '0.3';
            const fwdText = document.createElement('span');
            fwdText.className = 'text-[10px]';
            fwdText.style.color = color;
            fwdText.style.opacity = visibility.forward ? '1' : '0.4';
            fwdText.textContent = '正';
            fwdDiv.appendChild(fwdLine);
            fwdDiv.appendChild(fwdText);
            fwdDiv.addEventListener('click', () => {
                this.visibleSubstances[substance].forward = !this.visibleSubstances[substance].forward;
                const newOpacity = this.visibleSubstances[substance].forward ? '1' : '0.3';
                const newTextOpacity = this.visibleSubstances[substance].forward ? '1' : '0.4';
                fwdLine.style.opacity = newOpacity;
                fwdText.style.opacity = newTextOpacity;
            });
            this.legendContainer.appendChild(fwdDiv);

            // 逆反应图例（虚线）
            const revDiv = document.createElement('div');
            revDiv.className = 'flex items-center gap-0.5 cursor-pointer select-none px-1';
            const revLine = document.createElement('span');
            revLine.className = 'inline-block w-3 border-t border-dashed';
            revLine.style.borderColor = color;
            revLine.style.opacity = visibility.reverse ? '1' : '0.3';
            const revText = document.createElement('span');
            revText.className = 'text-[10px]';
            revText.style.color = color;
            revText.style.opacity = visibility.reverse ? '1' : '0.4';
            revText.textContent = '逆';
            revDiv.appendChild(revLine);
            revDiv.appendChild(revText);
            revDiv.addEventListener('click', () => {
                this.visibleSubstances[substance].reverse = !this.visibleSubstances[substance].reverse;
                const newOpacity = this.visibleSubstances[substance].reverse ? '1' : '0.3';
                const newTextOpacity = this.visibleSubstances[substance].reverse ? '1' : '0.4';
                revLine.style.opacity = newOpacity;
                revText.style.opacity = newTextOpacity;
            });
            this.legendContainer.appendChild(revDiv);

            substanceIndex++;
        }
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

        // 动态计算 Y 轴范围（只允许向上扩展，不允许缩小）
        if (this.data.length > 0) {
            let maxValue = 0;
            for (const point of this.data) {
                const rates = point.rates || {};
                for (const rateObj of Object.values(rates)) {
                    const fwd = rateObj.forward || 0;
                    const rev = rateObj.reverse || 0;
                    if (fwd > maxValue) maxValue = fwd;
                    if (rev > maxValue) maxValue = rev;
                }
            }
            // 计算所需的最大值（带 20% 余量）
            const requiredMax = Math.max(CONFIG.CHART.RATE.Y_MAX, maxValue * 1.2);
            // 只允许向上扩展，不允许缩小（保持历史最大值）
            this.yMaxHistory = Math.max(this.yMaxHistory, requiredMax);
            this.yMax = this.yMaxHistory;
        }

        const yMax = this.yMax;

        // 绘制 Y 轴刻度
        ctx.fillStyle = colors.textMuted;
        ctx.font = '12px Inter, sans-serif';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';

        const tickCount = 5;
        for (let i = 0; i <= tickCount; i++) {
            const value = (yMax / tickCount) * i;
            const y = plotOriginY - (value / yMax) * plotHeight;
            ctx.fillText(value.toFixed(0), plotOriginX - 5, y);

            // 网格线
            ctx.strokeStyle = colors.border;
            ctx.globalAlpha = 0.3;
            ctx.beginPath();
            ctx.moveTo(plotOriginX, y);
            ctx.lineTo(width - padding.RIGHT, y);
            ctx.stroke();
            ctx.globalAlpha = 1.0;
        }

        if (this.data.length < 2) {
            // 数据不足时仍显示坐标轴，不绘制曲线
            return;
        }

        // 计算可视窗口（运行态自动滚动；暂停态允许平移/缩放）
        const endIndex = this.followLatest ? this.data.length : (typeof this.viewEndIndex === 'number' ? this.viewEndIndex : this.data.length);
        const windowPoints = Math.max(2, this.windowPoints);
        const startIndex = Math.max(0, endIndex - windowPoints);
        const visibleData = this.data.slice(startIndex, endIndex);

        if (visibleData.length < 2) {
            return;
        }

        // 隐藏尾端“时间差”：当视窗包含最新点时，将速率点时间整体平移，使最后一个速率点对齐到当前模拟时间
        let timeShift = 0;
        if (endIndex === this.data.length) {
            const simTime = stateManager.getState()?.simulation?.time;
            const lastRateTime = this.data.length ? this.data[this.data.length - 1].time : undefined;
            if (Number.isFinite(simTime) && Number.isFinite(lastRateTime)) {
                const delta = simTime - lastRateTime;
                // 仅平移小幅差异，避免在重置/跳变时造成轴错位
                if (Math.abs(delta) < 2.0) {
                    timeShift = delta;
                }
            }
        }

        const tStart = visibleData[0].time + timeShift;
        const tEnd = visibleData[visibleData.length - 1].time + timeShift;
        const timeSpan = tEnd - tStart;
        if (timeSpan < 1e-9) {
            return;
        }

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

            ctx.strokeStyle = colors.border;
            ctx.globalAlpha = 0.15;
            ctx.beginPath();
            ctx.moveTo(x, padding.TOP);
            ctx.lineTo(x, plotOriginY);
            ctx.stroke();
            ctx.globalAlpha = 1.0;
        }

        // 收集所有物种
        const substances = new Set();
        for (const point of visibleData) {
            const rates = point.rates || {};
            for (const s of Object.keys(rates)) {
                substances.add(s);
            }
        }

        // 只在 substances 变化时才更新图例 UI（避免每帧重建）
        const substanceKey = Array.from(substances).sort().join(',');
        if (substanceKey !== this.lastSubstanceKey) {
            this.lastSubstanceKey = substanceKey;
            this.updateLegendUI(substances);
        }

        // 为每个物种绘制正反应（实线）和逆反应（虚线）曲线
        const substanceColors = {
            'A': 'hsl(0, 80%, 60%)',   // 红色
            'B': 'hsl(210, 80%, 60%)', // 蓝色
            'C': 'hsl(120, 60%, 50%)', // 绿色
            'D': 'hsl(60, 80%, 50%)',  // 黄色
            'E': 'hsl(280, 60%, 60%)', // 紫色
        };

        let substanceIndex = 0;
        for (const substance of substances) {
            const color = substanceColors[substance] || `hsl(${substanceIndex * 72}, 70%, 55%)`;
            const visibility = this.visibleSubstances[substance] || { forward: true, reverse: true };

            // 绘制正反应速率（实线）- 只在可见时绘制
            if (visibility.forward) {
                ctx.strokeStyle = color;
                ctx.lineWidth = CONFIG.CHART.LINE_WIDTH;
                ctx.setLineDash([]);  // 实线
                ctx.beginPath();
                for (let i = 0; i < visibleData.length; i++) {
                    const point = visibleData[i];
                    const rates = point.rates || {};
                    const rateObj = rates[substance] || { forward: 0, reverse: 0 };
                    const rate = rateObj.forward || 0;
                    const x = plotOriginX + ((point.time + timeShift) - tStart) * pxPerSec;
                    const y = plotOriginY - (rate / yMax) * plotHeight;
                    if (i === 0) {
                        ctx.moveTo(x, y);
                    } else {
                        ctx.lineTo(x, y);
                    }
                }
                ctx.stroke();
            }

            // 绘制逆反应速率（虚线）- 只在可见时绘制
            if (visibility.reverse) {
                ctx.strokeStyle = color;
                ctx.lineWidth = CONFIG.CHART.LINE_WIDTH;
                ctx.setLineDash([5, 3]);  // 虚线
                ctx.beginPath();
                for (let i = 0; i < visibleData.length; i++) {
                    const point = visibleData[i];
                    const rates = point.rates || {};
                    const rateObj = rates[substance] || { forward: 0, reverse: 0 };
                    const rate = rateObj.reverse || 0;
                    const x = plotOriginX + ((point.time + timeShift) - tStart) * pxPerSec;
                    const y = plotOriginY - (rate / yMax) * plotHeight;
                    if (i === 0) {
                        ctx.moveTo(x, y);
                    } else {
                        ctx.lineTo(x, y);
                    }
                }
                ctx.stroke();
                ctx.setLineDash([]);  // 恢复实线
            }

            substanceIndex++;
        }
    }
}
