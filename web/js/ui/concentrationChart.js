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

        // DOM 元素
        this.concentrationA = document.getElementById('concentration-a');
        this.concentrationP = document.getElementById('concentration-p');

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

        stateManager.subscribe('concentration', (concentration) => {
            if (this.concentrationA) {
                this.concentrationA.textContent = `[A] = ${concentration.reactantCount}`;
            }
            if (this.concentrationP) {
                this.concentrationP.textContent = `[B] = ${concentration.productCount}`;
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

        // Y 轴固定范围
        const yMin = CONFIG.CHART.CONCENTRATION.Y_MIN;
        const yMax = CONFIG.CHART.CONCENTRATION.Y_MAX;

        // 绘制 Y 轴刻度
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

        if (this.data.length < 2) {
            return;
        }

        // 计算滚动偏移
        const visiblePoints = CONFIG.CHART.X_AXIS_VISIBLE_POINTS;
        const scrollOffset = Math.max(0, this.data.length - visiblePoints);
        const visibleData = this.data.slice(scrollOffset);

        // X 轴范围
        const xPointCount = Math.min(visibleData.length, visiblePoints);

        /**
         * 绘制曲线
         */
        const drawCurve = (getValue, color, dashed = false) => {
            ctx.strokeStyle = color;
            ctx.lineWidth = CONFIG.CHART.LINE_WIDTH;

            if (dashed) {
                ctx.setLineDash([4, 4]);
            } else {
                ctx.setLineDash([]);
            }

            ctx.beginPath();

            for (let i = 0; i < visibleData.length; i++) {
                const point = visibleData[i];
                const value = getValue(point);

                const x = plotOriginX + (i / visiblePoints) * plotWidth;
                const y = plotOriginY - (value / yMax) * plotHeight;

                if (i === 0) {
                    ctx.moveTo(x, y);
                } else {
                    ctx.lineTo(x, y);
                }
            }

            ctx.stroke();
            ctx.setLineDash([]);
        };

        // 绘制反应物曲线（实线，红色）- 直接显示 A
        drawCurve(p => p.reactant, curveColors.reactant, false);

        // 绘制产物曲线（实线，蓝色）- 直接显示 B
        drawCurve(p => p.product, curveColors.product, false);

        // 绘制预计算理论曲线（虚线）
        // 理论曲线在启动时就完整生成，固定显示
        const theoryCurve = stateManager.getState().chartData.theoryCurve;
        if (theoryCurve && theoryCurve.length >= 2 && visibleData.length >= 2) {
            ctx.strokeStyle = curveColors.theory;
            ctx.lineWidth = CONFIG.CHART.LINE_WIDTH;
            ctx.setLineDash([4, 4]);
            ctx.beginPath();

            // 动态对齐：基于实际数据的当前时间窗口计算映射关系
            const tStart = visibleData[0].time;
            const tEnd = visibleData[visibleData.length - 1].time;
            const timeSpan = tEnd - tStart;

            // 如果时间跨度太小（刚开始），则跳过或使用默认
            if (timeSpan > 0.001) {
                // 计算 x 轴的时间缩放比例 (pixels per second)
                // 实际数据占据的宽度
                const dataWidth = (visibleData.length - 1) / visiblePoints * plotWidth;
                const pxPerSec = dataWidth / timeSpan;

                let firstPoint = true;
                for (const point of theoryCurve) {
                    // 计算 x 坐标：相对于当前窗口起始时间的偏移
                    const timeOffset = point.time - tStart;
                    const x = plotOriginX + timeOffset * pxPerSec;

                    // 性能优化：只绘制在显示范围附近的点
                    if (x < plotOriginX - 10 || x > width) continue;

                    const y = plotOriginY - (point.product / yMax) * plotHeight;

                    if (firstPoint) {
                        ctx.moveTo(x, y);
                        firstPoint = false;
                    } else {
                        ctx.lineTo(x, y);
                    }
                }
                ctx.stroke();
            }

            ctx.setLineDash([]);
        }
    }
}
