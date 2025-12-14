/**
 * 全局状态管理
 * 发布-订阅模式，解耦数据与视图
 */

class StateManager {
    constructor() {
        // 状态存储
        this.state = {
            // 模拟配置
            config: {
                temperature: 3.0,
                activationEnergy: 0.5,
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
                theoryValue: 0,
                kEstimated: null,
            },

            // 图表历史数据
            chartData: {
                // 浓度曲线数据（实际模拟）
                concentrationHistory: [],
                // 速率曲线数据
                rateHistory: [],
                // 预计算理论曲线（启动时一次性生成）
                theoryCurve: [],
            },

            // 预埋：多组分支持
            components: [
                { id: 'A', name: '反应物 A', count: 10000 },
                { id: 'P', name: '产物 P', count: 0 },
            ],

            // 预埋：反应列表
            reactions: [
                { type: 'A+A->P+P', rate: 0 },
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
        // 更新模拟时间
        this.update('simulation', {
            time: serverState.time,
        });

        // 更新粒子
        this.update('particles', serverState.particles);

        // 更新浓度
        const concentration = {
            reactantCount: serverState.reactantCount,
            productCount: serverState.productCount,
            theoryValue: serverState.theoryValue,
            kEstimated: serverState.kEstimated,
        };
        this.update('concentration', concentration);

        // 计算反应速率 (dP/dt)
        const dt = serverState.time - this.lastTime;
        let rate = 0;
        if (dt > 0) {
            rate = (serverState.productCount - this.lastProductCount) / dt;
        }
        this.lastProductCount = serverState.productCount;
        this.lastTime = serverState.time;

        // 速率平滑：使用移动平均
        if (!this.rateHistory) {
            this.rateHistory = [];
        }
        this.rateHistory.push(rate);
        const smoothWindow = 5;  // 5点移动平均
        if (this.rateHistory.length > smoothWindow) {
            this.rateHistory.shift();
        }
        const smoothedRate = this.rateHistory.reduce((a, b) => a + b, 0) / this.rateHistory.length;

        // 更新图表数据
        const chartData = this.state.chartData;

        // 添加浓度历史点（包含反应物和产物）
        chartData.concentrationHistory.push({
            time: serverState.time,
            reactant: serverState.reactantCount,  // 反应物 A
            product: serverState.productCount,     // 产物 B
            theory: serverState.theoryValue,
        });

        // 添加速率历史点（使用平滑后的值）
        chartData.rateHistory.push({
            time: serverState.time,
            value: Math.max(0, smoothedRate),
        });

        // 限制历史长度
        const maxPoints = 600;
        if (chartData.concentrationHistory.length > maxPoints) {
            chartData.concentrationHistory.shift();
        }
        if (chartData.rateHistory.length > maxPoints) {
            chartData.rateHistory.shift();
        }

        this.update('chartData', chartData);
    }

    /**
     * 生成预计算理论曲线（二级反应动力学）
     * 在模拟启动时调用，一次性生成完整理论曲线
     */
    generateTheoryCurve(k, numParticles, maxTime = 60) {
        // 保存基准参数，用于后续动态调整
        this.baseParams = {
            k: k,
            temp: this.state.config.temperature,
            ea: this.state.config.activationEnergy,
            kb: 0.1 // 固定的玻尔兹曼常数
        };

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
        console.log(`[StateManager] Theory curve generated with k=${k.toExponential(3)}, ${theoryCurve.length} points`);
    }

    /**
     * 更新理论曲线（响应温度变化）
     * 严格基于 Arrhenius 方程预测
     * 用户要求："让K被'设置'，渲染跟着设置走"
     * 
     * 逻辑：
     * 1. 严格使用基准参数 (k0, T0) 和当前设置 (T_new) 计算新的理论 K。
     * 2. 不进行任何基于"历史实际速率"的自适应校准（避免逻辑混淆）。
     * 3. 曲线从当前实际浓度 [A]_current 开始延伸，展示"如果按照当前设置运行，未来的理论轨迹"。
     */
    updateTheoryCurve(newTemp) {
        if (!this.baseParams) return;

        const { k: k0, temp: T0, ea: Ea, kb } = this.baseParams;
        const T1 = newTemp;

        // 阿伦尼乌斯缩放: k1 / k0 = sqrt(T1/T0) * exp(-Ea/kb * (1/T1 - 1/T0))
        const preExponential = Math.sqrt(T1 / T0);
        const exponential = Math.exp((-Ea / kb) * (1 / T1 - 1 / T0));
        const k1 = k0 * preExponential * exponential;

        // 获取当前实际状态作为起点
        const currentTime = this.state.simulation.time;
        const currentA = this.state.concentration.reactantCount;

        // 构建新曲线：
        // 1. 历史部分：保留历史实际轨迹（视觉上的诚实）
        const history = this.state.chartData.concentrationHistory
            .filter(p => p.time <= currentTime)
            .map(p => ({
                time: p.time,
                reactant: p.reactant,
                product: p.product
            }));

        const newCurve = [...history];

        // 2. 未来部分：基于计算出的 k1 进行纯理论预测
        let A_t = currentA;
        const startT = currentTime;
        const maxTime = Math.max(60, startT + 50);
        const step = 0.1;

        // 二级反应积分: 1/[A] - 1/[A]0 = k * t
        const invA_start = 1 / A_t;

        for (let t = startT + step; t <= maxTime; t += step) {
            const dt_accum = t - startT;
            const A_pred = 1 / (invA_start + k1 * dt_accum);
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
        this.state.concentration = {
            reactantCount: this.state.config.numParticles,
            productCount: 0,
            theoryValue: 0,
            kEstimated: null,
        };
        this.state.chartData = {
            concentrationHistory: [],
            rateHistory: [],
            theoryCurve: [],
        };
        this.state.simulation.started = false;
        this.lastProductCount = 0;
        this.lastTime = 0;

        // 通知所有相关订阅者
        this.notify('simulation');
        this.notify('particles');
        this.notify('concentration');
        this.notify('chartData');
    }
}

// 导出单例
export const stateManager = new StateManager();
