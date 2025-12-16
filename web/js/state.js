/**
 * 全局状态管理
 * 发布-订阅模式，解耦数据与视图
 */

class StateManager {
    constructor() {
        // 状态存储
        this.state = {
            // 模拟配置（可逆反应）
            config: {
                temperature: 300.0,
                // 可逆反应参数
                radiusA: 0.3,
                radiusB: 0.3,
                initialCountA: 10000,
                initialCountB: 0,
                eaForward: 30,
                eaReverse: 30,
                // 锁定状态
                propertiesLocked: false,
                // 半衰期
                halfLifeForward: null,
                halfLifeReverse: null,
                // 兼容
                numParticles: 10000,
            },

            // 模拟运行状态
            simulation: {
                running: false,
                time: 0,
                fps: 0,
            },

            // 粒子数据
            particles: [],

            // 浓度数据
            concentration: {
                reactantCount: 10000,
                productCount: 0,
                halfLifeForward: null,
                halfLifeReverse: null,
            },

            // 图表历史数据
            chartData: {
                // 浓度曲线数据（实际模拟）
                concentrationHistory: [],
                // 速率曲线数据
                rateHistory: [],
            },

            // 组分列表
            components: [
                { id: 'A', name: '反应物 A', count: 10000 },
                { id: 'B', name: '产物 B', count: 0 },
            ],
        };

        // 订阅者列表
        this.listeners = new Map();

        // 上一帧的产物数用于计算速率
        this.lastProductCount = 0;
        this.lastTime = 0;
    }

    /**
     * 订阅状态变化
     * @param {string} key - 状态键
     * @param {Function} callback - 回调函数
     * @returns {Function} 取消订阅函数
     */
    subscribe(key, callback) {
        if (!this.listeners.has(key)) {
            this.listeners.set(key, []);
        }
        this.listeners.get(key).push(callback);

        // 返回取消订阅函数
        return () => {
            const callbacks = this.listeners.get(key);
            const index = callbacks.indexOf(callback);
            if (index > -1) {
                callbacks.splice(index, 1);
            }
        };
    }

    /**
     * 更新状态
     * @param {string} key - 状态键
     * @param {*} value - 新值（可以是对象，会合并）
     */
    update(key, value) {
        if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
            this.state[key] = { ...this.state[key], ...value };
        } else {
            this.state[key] = value;
        }
        this.notify(key);
    }

    /**
     * 通知订阅者
     * @param {string} key - 状态键
     */
    notify(key) {
        const callbacks = this.listeners.get(key) || [];
        callbacks.forEach(cb => cb(this.state[key]));
    }

    /**
     * 获取完整状态
     */
    getState() {
        return this.state;
    }

    /**
     * 从后端状态更新
     * @param {Object} serverState - 后端推送的状态
     */
    updateFromServer(serverState) {
        // 更新模拟时间和实时温度
        this.update('simulation', {
            time: serverState.time,
            currentTemperature: serverState.currentTemperature,
        });

        // 更新粒子
        this.update('particles', serverState.particles);

        // 更新能量统计（用于前端高亮阈值）
        if (serverState.energyStats) {
            this.update('energyStats', serverState.energyStats);
        }

        // 更新浓度（新格式：substanceCounts）
        const substanceCounts = serverState.substanceCounts || {};
        this.update('concentration', {
            substanceCounts: substanceCounts,
            activeCount: serverState.activeCount || 0,
        });

        // 检测是否重置 (服务器时间回退)
        const serverTime = serverState.time;
        if (serverTime < this.lastTime) {
            this.state.chartData.concentrationHistory = [];
            this.state.chartData.rateHistory = [];
            this.lastRate = undefined;

            // 重置速率平滑缓存，避免重置后用到旧历史造成时间/幅值假象
            this.forwardRateEMA = undefined;
            this.reverseRateEMA = undefined;
            this.lastSubstanceCounts = undefined;
        }

        // 图表数据：记录所有物质的浓度
        const chartData = this.state.chartData;

        // 防止重复数据：检查时间戳是否已存在（避免反复描画）
        const lastConcentrationEntry = chartData.concentrationHistory[chartData.concentrationHistory.length - 1];
        const serverTimeRounded = Math.round(serverState.time * 1000) / 1000; // 保留3位小数
        const shouldAddConcentration = !lastConcentrationEntry ||
            Math.abs(lastConcentrationEntry.time - serverTimeRounded) > 1e-6;

        if (shouldAddConcentration) {
            chartData.concentrationHistory.push({
                time: serverTimeRounded,
                counts: { ...substanceCounts },
            });
        }

        // 增大历史数据容量：5000点，约等于 5000/30 ≈ 166秒的数据
        const maxHistoryPoints = 5000;
        if (chartData.concentrationHistory.length > maxHistoryPoints) {
            chartData.concentrationHistory.shift();
        }

        // 按物种计算正反应速率（消耗）和逆反应速率（生成）
        const currentTime = serverState.time;
        const rates = {};  // { substance: { forward: number, reverse: number } }

        // 速率代表区间平均值：时间戳放在区间中点，避免曲线“滞后”
        let rateTime = currentTime;
        let hasValidRate = false;

        if (this.lastTime > 0 && currentTime > this.lastTime) {
            const dt = currentTime - this.lastTime;
            rateTime = this.lastTime + dt / 2;
            hasValidRate = true;

            // 初始化 EMA 缓存（使用指数移动平均代替 SMA，避免窗口填充导致的拐点）
            if (!this.forwardRateEMA) {
                this.forwardRateEMA = {};
            }
            if (!this.reverseRateEMA) {
                this.reverseRateEMA = {};
            }
            if (!this.lastSubstanceCounts) {
                this.lastSubstanceCounts = {};
            }

            // EMA 平滑系数：alpha = 2/(N+1)，N=15 对应 alpha ≈ 0.125
            // 较小的 alpha 意味着更平滑但响应更慢
            const emaAlpha = 0.125;

            // 计算每个物种的正逆反应速率
            for (const [substance, count] of Object.entries(substanceCounts)) {
                const lastCount = this.lastSubstanceCounts[substance] || count;
                const dN = count - lastCount;

                // 正反应速率：消耗 (dN < 0)
                const forwardRate = dN < 0 ? Math.abs(dN / dt) : 0;
                // 逆反应速率：生成 (dN > 0)
                const reverseRate = dN > 0 ? dN / dt : 0;

                // EMA 平滑正反应速率
                // EMA = alpha * current + (1 - alpha) * previous
                if (this.forwardRateEMA[substance] === undefined) {
                    this.forwardRateEMA[substance] = forwardRate; // 首次初始化为当前值，避免从0开始
                } else {
                    this.forwardRateEMA[substance] = emaAlpha * forwardRate + (1 - emaAlpha) * this.forwardRateEMA[substance];
                }

                // EMA 平滑逆反应速率
                if (this.reverseRateEMA[substance] === undefined) {
                    this.reverseRateEMA[substance] = reverseRate;
                } else {
                    this.reverseRateEMA[substance] = emaAlpha * reverseRate + (1 - emaAlpha) * this.reverseRateEMA[substance];
                }

                rates[substance] = {
                    forward: this.forwardRateEMA[substance],
                    reverse: this.reverseRateEMA[substance],
                };
            }
        }

        this.lastTime = currentTime;
        this.lastSubstanceCounts = { ...substanceCounts };

        // 首帧/无 dt 时不推入空速率点，避免曲线出现"从 0 突跳"的视觉时间差
        if (hasValidRate) {
            // 防止重复数据：检查时间戳是否已存在（避免反复描画）
            const rateTimeRounded = Math.round(rateTime * 1000) / 1000;
            const lastRateEntry = chartData.rateHistory[chartData.rateHistory.length - 1];
            const shouldAddRate = !lastRateEntry ||
                Math.abs(lastRateEntry.time - rateTimeRounded) > 1e-6;

            if (shouldAddRate) {
                chartData.rateHistory.push({
                    time: rateTimeRounded,
                    rates: rates,  // { substance: { forward, reverse } }
                });
            }
        }

        // 限制速率历史长度（复用浓度数据的容量限制）
        if (chartData.rateHistory.length > maxHistoryPoints) {
            chartData.rateHistory.shift();
        }

        this.update('chartData', chartData);
    }

    /**
     * 计算绝对理论速率常数 k (基于硬球碰撞理论)
     * Hard Sphere Collision Theory: k = σ * v_rel * exp(-Ea/kT) / V
     * 
     * Constants (Must match config.py):
     * R = 0.3
     * Box = 40.0
     * Mass = 1.0
     * Kb = 0.1
     */
    calculateTheoreticalK(T, Ea) {
        // 动态获取当前配置的半径
        // R 越大 -> Sigma 越大 -> A 越大 -> k 越大
        const R = this.state.config.particleRadius || 0.3; // Default fallback
        const BOX_SIZE = 40.0; // Volume = 40^3 = 64000
        const MASS = 1.0;
        const KB = 0.1;

        const Volume = BOX_SIZE * BOX_SIZE * BOX_SIZE;

        // 1. 碰撞截面 σ = 4πR^2
        const sigma = 4 * Math.PI * R * R;
        const v_rel = 4 * Math.sqrt((KB * T) / (Math.PI * MASS));
        const arrhenius = Math.exp(-Ea / (KB * T));

        // 移除校准因子，回归纯理论公式
        const k_count = (sigma * v_rel * arrhenius) / Volume;

        return k_count;
    }

    /**
     * 生成预计算理论曲线
     * 忽略传入的 k (估算值)，强制使用理论计算值
     */
    generateTheoryCurve(ignoredK, numParticles, maxTime = 60) {
        const T = this.state.config.temperature;
        const Ea = this.state.config.activationEnergy;
        // 强制使用绝对理论计算
        const k = this.calculateTheoreticalK(T, Ea);

        console.log(`[Theory] Absolute k calculated: ${k.toExponential(4)} (vs Estimated: ${ignoredK?.toExponential(4)})`);

        const theoryCurve = [];
        const A0 = numParticles;
        const dt = 0.1;

        for (let t = 0; t <= maxTime; t += dt) {
            const denom = 1 + k * A0 * t;
            const A_t = A0 / denom;
            const B_t = (A0 - A_t) / 2;

            theoryCurve.push({
                time: t,
                reactant: A_t,
                product: B_t,
            });
        }

        this.state.chartData.theoryCurve = theoryCurve;
        this.notify('chartData');
    }

    /**
     * 更新理论曲线（响应温度变化）
     * 严格基于 Arrhenius 方程和硬球理论预测
     * 直接计算新 T 下的绝对 k 值
     */
    updateTheoryCurve(newTemp) {
        const Ea = this.state.config.activationEnergy;
        const k_new = this.calculateTheoreticalK(newTemp, Ea);

        // 获取当前实际状态作为起点
        const currentTime = this.state.simulation.time;
        const currentA = this.state.concentration.reactantCount;

        // 构建新曲线：
        // 1. 历史部分：保留历史实际轨迹
        const history = this.state.chartData.concentrationHistory
            .filter(p => p.time <= currentTime)
            .map(p => ({
                time: p.time,
                reactant: p.reactant,
                product: p.product
            }));

        const newCurve = [...history];

        // 2. 未来部分
        let A_t = currentA;
        const startT = currentTime;
        const maxTime = Math.max(60, startT + 50);
        const step = 0.1;

        const invA_start = 1 / A_t;

        for (let t = startT + step; t <= maxTime; t += step) {
            const dt_accum = t - startT;
            const A_pred = 1 / (invA_start + k_new * dt_accum);
            const B_pred = (this.state.config.numParticles - A_pred) / 2;

            newCurve.push({
                time: t,
                reactant: A_pred,
                product: B_pred,
            });
        }

        this.state.chartData.theoryCurve = newCurve;
        this.notify('chartData');
    }

    /**
     * 重置状态
     */
    reset() {
        this.state.simulation.time = 0;
        this.state.particles = [];

        // 兼容当前多物质实现：substanceCounts
        const substances = this.state.config.substances || [];
        const substanceCounts = {};
        let totalActive = 0;
        for (const s of substances) {
            const count = Math.max(0, Math.round(s.initialCount || 0));
            substanceCounts[s.id] = count;
            totalActive += count;
        }
        this.state.concentration = {
            substanceCounts,
            activeCount: totalActive,
        };
        this.state.chartData = {
            concentrationHistory: [],
            rateHistory: [],
        };
        this.state.simulation.started = false;
        this.lastProductCount = 0;
        this.lastReactantCount = undefined;
        this.lastTime = 0;

        // 清空速率 EMA 平滑缓存（按物种）
        this.forwardRateEMA = undefined;
        this.reverseRateEMA = undefined;
        this.lastSubstanceCounts = undefined;

        // 通知所有相关订阅者
        this.notify('simulation');
        this.notify('particles');
        this.notify('concentration');
        this.notify('chartData');
    }

    /**
     * 获取可导出的历史数据
     * 用于后续实现 CSV/JSON 导出功能
     * @returns {Object} 结构化的导出数据
     */
    getExportData() {
        const chartData = this.state.chartData;
        const config = this.state.config;

        // 获取物质列表
        const substances = config.substances || [];
        const substanceIds = substances.map(s => s.id);

        // 构建浓度数据表格
        const concentrationData = chartData.concentrationHistory.map(point => {
            const row = { time: point.time };
            for (const id of substanceIds) {
                row[`count_${id}`] = point.counts?.[id] || 0;
            }
            return row;
        });

        // 构建速率数据表格
        const rateData = chartData.rateHistory.map(point => {
            const row = { time: point.time };
            for (const id of substanceIds) {
                const rates = point.rates?.[id] || { forward: 0, reverse: 0 };
                row[`forward_${id}`] = rates.forward;
                row[`reverse_${id}`] = rates.reverse;
            }
            return row;
        });

        return {
            metadata: {
                exportTime: new Date().toISOString(),
                simulationTime: this.state.simulation.time,
                substances: substances.map(s => ({ id: s.id, name: s.name || s.id })),
                temperature: config.temperature,
            },
            concentrationHistory: concentrationData,
            rateHistory: rateData,
        };
    }
}

// 导出单例
export const stateManager = new StateManager();
