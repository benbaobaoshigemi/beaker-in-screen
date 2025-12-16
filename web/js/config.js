/**
 * 前端配置常量
 * 所有可配置项集中管理
 */

export const CONFIG = {
    // WebSocket 连接
    WS_URL: `http://${window.location.hostname}:5000`,

    // 图表配置
    CHART: {
        MAX_POINTS: 600,           // 最大历史数据点数
        LINE_WIDTH: 1,             // 细线条
        X_AXIS_VISIBLE_POINTS: 300, // 可见时间窗口（数据点数）
        PADDING: {
            TOP: 30,
            RIGHT: 20,
            BOTTOM: 40,
            LEFT: 50,
        },
        // Y 轴固定范围，不自动缩放
        CONCENTRATION: {
            Y_MIN: 0,
            Y_MAX: 10000,  // 显示完整的粒子数量范围（默认5000粒子）
        },
        RATE: {
            Y_MIN: 0,
            Y_MAX: 100,  // 速率最大值，会根据实际数据动态调整
        },
    },

    // 模拟显示配置
    SIMULATION: {
        PARTICLE_RADIUS: 1.5,  // 圆形粒子半径（缩小一半）
        BOX_SIZE: 40.0,        // 物理空间大小（与后端一致）
    },

    /**
     * 获取粒子颜色配置（从 CSS 变量读取）
     * 用于 HSL 颜色计算
     */
    getParticleColorConfig: () => {
        const style = getComputedStyle(document.documentElement);

        // 从 CSS 变量读取值并转换
        const parseValue = (name) => {
            const val = style.getPropertyValue(name).trim();
            return parseFloat(val) || 0;
        };

        const parsePercent = (name) => {
            const val = style.getPropertyValue(name).trim();
            return parseFloat(val) / 100 || 0;
        };

        return {
            // 反应物 A - 红色
            A: {
                hue: parseValue('--color-particle-a-hue'),
                saturation: parsePercent('--color-particle-a-saturation'),
                baseLightness: parsePercent('--color-particle-a-base-lightness'),
            },
            // 产物 B - 蓝色
            B: {
                hue: parseValue('--color-particle-b-hue'),
                saturation: parsePercent('--color-particle-b-saturation'),
                baseLightness: parsePercent('--color-particle-b-base-lightness'),
            },
            // 能量-亮度映射范围
            energy: {
                minLightness: parsePercent('--energy-min-lightness'),
                maxLightness: parsePercent('--energy-max-lightness'),
            },
        };
    },

    /**
     * 根据粒子类型获取颜色
     * 使用幂函数映射增强亮度对比：energy^gamma
     * gamma < 1 会让更多粒子变亮，增加高亮粒子占比
     * @param {number} type - 粒子类型 (0=A, 1=B)
     * @param {number} energy - 归一化能量 [0, 1]
     * @returns {string} HSL 颜色字符串
     */
    getParticleColor: function (type, energy) {
        const config = this.getParticleColorConfig();
        const particleConfig = type === 0 ? config.A : config.B;

        // 移除亮度随能量变化逻辑，保持同色
        // 亮度固定为基本亮度 (通常 50%)
        const lightness = 50;

        return `hsl(${particleConfig.hue}, 100%, ${lightness}%)`;
    },

    // 获取曲线颜色
    getCurveColors: () => {
        const style = getComputedStyle(document.documentElement);
        return {
            reactant: style.getPropertyValue('--color-curve-reactant').trim(),
            product: style.getPropertyValue('--color-curve-product').trim(),
            theory: style.getPropertyValue('--color-curve-theory').trim(),
            rate: style.getPropertyValue('--color-curve-rate').trim(),
        };
    },

    // 获取背景颜色
    getColors: () => {
        const style = getComputedStyle(document.documentElement);
        return {
            bg: style.getPropertyValue('--color-bg').trim(),
            surface: style.getPropertyValue('--color-surface').trim(),
            border: style.getPropertyValue('--color-border').trim(),
            textPrimary: style.getPropertyValue('--color-text-primary').trim(),
            textSecondary: style.getPropertyValue('--color-text-secondary').trim(),
            textMuted: style.getPropertyValue('--color-text-muted').trim(),
        };
    },
};
