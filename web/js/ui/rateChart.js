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

        // 数据
        this.data = [];

        // 动态 Y 轴最大值
        this.yMax = CONFIG.CHART.RATE.Y_MAX;

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
            this.data = chartData.rateHistory;

            // 更新当前速率显示
            if (this.data.length > 0 && this.rateCurrent) {
                const lastRate = this.data[this.data.length - 1].value;
                this.rateCurrent.textContent = `当前速率: ${lastRate.toFixed(1)}`;
            }
        });

        stateManager.subscribe('concentration', (concentration) => {
            if (this.rateK && concentration.kEstimated !== null) {
                this.rateK.textContent = `k = ${concentration.kEstimated.toFixed(6)}`;
            }
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

        // 动态计算 Y 轴范围（基于数据最大值）
        if (this.data.length > 0) {
            const maxValue = Math.max(...this.data.map(d => d.value));
            this.yMax = Math.max(CONFIG.CHART.RATE.Y_MAX, maxValue * 1.2);
        }

        const yMax = this.yMax;

        // 绘制 Y 轴刻度
        ctx.fillStyle = colors.textMuted;
        ctx.font = '10px Inter, sans-serif';
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
            return;
        }

        // 计算滚动偏移
        const visiblePoints = CONFIG.CHART.X_AXIS_VISIBLE_POINTS;
        const scrollOffset = Math.max(0, this.data.length - visiblePoints);
        const visibleData = this.data.slice(scrollOffset);

        // 绘制曲线
        ctx.strokeStyle = curveColors.rate;
        ctx.lineWidth = CONFIG.CHART.LINE_WIDTH;
        ctx.beginPath();

        for (let i = 0; i < visibleData.length; i++) {
            const point = visibleData[i];
            const x = plotOriginX + (i / visiblePoints) * plotWidth;
            const y = plotOriginY - (point.value / yMax) * plotHeight;

            if (i === 0) {
                ctx.moveTo(x, y);
            } else {
                ctx.lineTo(x, y);
            }
        }

        ctx.stroke();
    }
}
