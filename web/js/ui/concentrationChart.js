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

        this.init();
    }

    /**
     * 初始化
     */
    init() {
        this.setupCanvas();
        this.subscribeToState();
        this.startRenderLoop();
    }

    /**
     * 设置 Canvas
     */
    setupCanvas() {
        const container = this.canvas.parentElement;
        const rect = container.getBoundingClientRect();

        this.canvas.width = rect.width || 400;
        this.canvas.height = rect.height || 200;

        window.addEventListener('resize', () => {
            const rect = container.getBoundingClientRect();
            this.canvas.width = rect.width || 400;
            this.canvas.height = rect.height || 200;
        });
    }

    /**
     * 订阅状态
     */
    subscribeToState() {
        stateManager.subscribe('chartData', (chartData) => {
            this.data = chartData.concentrationHistory;
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
        const width = this.canvas.width;
        const height = this.canvas.height;
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

        // Y 轴固定范围（浓度）
        const yMin = CONFIG.CHART.CONCENTRATION.Y_MIN;
        const yMax = CONFIG.CHART.CONCENTRATION.Y_MAX;

        // 反应商 Q 的范围 (0 到 ∞，我们用对数刻度不合适，用线性 0-10)
        const qMax = 10;

        // 绘制左侧 Y 轴刻度（浓度）
        ctx.fillStyle = colors.textMuted;
        ctx.font = '10px Inter, sans-serif';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';

        const yTicks = [0, 2500, 5000, 7500, 10000];  // 完整范围 0-10000
        yTicks.forEach(tick => {
            const y = plotOriginY - (tick / yMax) * plotHeight;
            ctx.fillText(tick.toString(), plotOriginX - 5, y);

            // 绘制网格线
            ctx.strokeStyle = colors.border;
            ctx.globalAlpha = 0.3;
            ctx.beginPath();
            ctx.moveTo(plotOriginX, y);
            ctx.lineTo(width - padding.RIGHT, y);
            ctx.stroke();
            ctx.globalAlpha = 1.0;
        });

        // 绘制右侧 Y 轴刻度（反应商 Q = [B]/[A]）
        ctx.fillStyle = '#ffffff';  // 白色
        ctx.textAlign = 'left';
        const qTicks = [0, 2, 4, 6, 8, 10];
        qTicks.forEach(tick => {
            const y = plotOriginY - (tick / qMax) * plotHeight;
            ctx.fillText(tick.toString(), width - padding.RIGHT + 5, y);
        });

        // 右侧 Y 轴标签
        ctx.save();
        ctx.translate(width - 5, height / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.textAlign = 'center';
        ctx.fillText('Q = [B]/[A]', 0, 0);
        ctx.restore();

        if (this.data.length < 2) {
            return;
        }

        // 计算滚动偏移
        const visiblePoints = CONFIG.CHART.X_AXIS_VISIBLE_POINTS;
        const scrollOffset = Math.max(0, this.data.length - visiblePoints);
        const visibleData = this.data.slice(scrollOffset);

        if (visibleData.length < 2) return;

        const tStart = visibleData[0].time;
        const tEnd = visibleData[visibleData.length - 1].time;
        const timeSpan = tEnd - tStart;

        if (timeSpan < 1e-9) return;

        const pxPerSec = plotWidth / timeSpan;

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

