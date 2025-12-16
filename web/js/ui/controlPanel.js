/**
 * 控制面板模块
 * 处理反应配置和动态物质配置
 */

import { wsManager } from '../websocket.js';
import { stateManager } from '../state.js';

// 默认物质色相（A-E）
const DEFAULT_HUES = { A: 0, B: 210, C: 120, D: 60, E: 300 };

export class ControlPanel {
    constructor() {
        this.substances = new Map(); // id -> { radius, initialCount, colorHue }
        this.init();
    }

    init() {
        this.setupReactionInputs();
        this.setupControlSliders();
        this.setupVolumeSlider();
        this.setupButtons();
        this.setupThermostatControls();
        this.parseReactionsAndBuildUI();
        this.subscribeToTemperatureUpdates();

        // 监听配置更新，同步 UI
        stateManager.subscribe('config', (config) => {
            if (config) {
                this.syncThermostatUI(config.useThermostat);
                this.syncVolumeUI(config.boxSize);
            }
        });
    }

    /**
     * 设置反应输入框
     */
    setupReactionInputs() {
        for (let i = 1; i <= 3; i++) {
            const eqInput = document.getElementById(`reaction-${i}-eq`);
            const eaForwardInput = document.getElementById(`reaction-${i}-ea-forward`);
            const eaReverseInput = document.getElementById(`reaction-${i}-ea-reverse`);

            if (eqInput) {
                eqInput.addEventListener('change', () => this.parseReactionsAndBuildUI());
                eqInput.addEventListener('blur', () => this.parseReactionsAndBuildUI());
            }
            if (eaForwardInput) {
                eaForwardInput.addEventListener('change', () => this.sendConfig());
            }
            if (eaReverseInput) {
                eaReverseInput.addEventListener('change', () => this.sendConfig());
            }
        }
    }

    /**
     * 解析反应式，提取物质，构建 UI
     */
    parseReactionsAndBuildUI() {
        const substanceIds = new Set();

        for (let i = 1; i <= 3; i++) {
            const eqInput = document.getElementById(`reaction-${i}-eq`);
            if (!eqInput) continue;

            const eq = eqInput.value.trim().toUpperCase();
            if (!eq) continue;

            // 解析反应式中的物质 (限制 A-E)
            const matches = eq.match(/[A-E]/g);
            if (matches) {
                matches.forEach(id => substanceIds.add(id));
            }
        }

        // 按字母顺序排序
        const sortedIds = Array.from(substanceIds).sort();

        // 更新 substances Map
        const oldSubstances = new Map(this.substances);
        this.substances.clear();

        sortedIds.forEach((id, index) => {
            if (oldSubstances.has(id)) {
                this.substances.set(id, oldSubstances.get(id));
            } else {
                this.substances.set(id, {
                    radius: 0.15,
                    initialCount: index === 0 ? 5000 : 0, // 第一个物质默认 5000
                    colorHue: DEFAULT_HUES[id] || 0
                });
            }
        });

        this.renderSubstancesUI();
        this.sendConfig();
    }

    /**
     * 渲染物质配置 UI
     */
    renderSubstancesUI() {
        const container = document.getElementById('substances-container');
        if (!container) return;

        container.innerHTML = '';

        this.substances.forEach((config, id) => {
            const div = document.createElement('div');
            div.className = 'flex items-center gap-sm p-sm bg-bg rounded-lg border border-border/50';
            div.innerHTML = `
                <span class="w-6 h-6 rounded-full" style="background: hsl(${config.colorHue}, 70%, 50%)"></span>
                <span class="text-sm font-medium w-6">${id}</span>
                <div class="flex-1 flex items-center gap-xs">
                    <span class="text-xs text-text-muted">半径:</span>
                    <input type="number" class="substance-input w-14 bg-surface border border-border rounded px-xs py-xs text-xs text-center"
                           data-substance="${id}" data-field="radius" value="${config.radius}" step="0.01" min="0.05" max="0.5">
                </div>
                <div class="flex-1 flex items-center gap-xs">
                    <span class="text-xs text-text-muted">数量:</span>
                    <input type="number" class="substance-input w-16 bg-surface border border-border rounded px-xs py-xs text-xs text-center"
                           data-substance="${id}" data-field="initialCount" value="${config.initialCount}" step="100" min="0" max="20000">
                </div>
            `;
            container.appendChild(div);
        });

        // 绑定事件
        container.querySelectorAll('.substance-input').forEach(input => {
            input.addEventListener('change', (e) => {
                const id = e.target.dataset.substance;
                const field = e.target.dataset.field;
                const value = parseFloat(e.target.value);
                if (this.substances.has(id)) {
                    this.substances.get(id)[field] = value;
                    this.sendConfig();
                }
            });
        });

        // 更新图例
        this.updateLegend();
    }

    /**
     * 更新浓度图图例
     */
    updateLegend() {
        const legendContainer = document.getElementById('concentration-legend');
        if (!legendContainer) return;

        legendContainer.innerHTML = '';
        this.substances.forEach((config, id) => {
            const div = document.createElement('div');
            div.className = 'flex items-center gap-xs';
            div.innerHTML = `
                <span class="w-2 h-2 rounded-full" style="background: hsl(${config.colorHue}, 70%, 50%)"></span>
                <span>[${id}]</span>
            `;
            legendContainer.appendChild(div);
        });
    }

    /**
     * 设置控制滑条（温度）
     */
    setupControlSliders() {
        const tempSlider = document.getElementById('temp-slider');
        const tempValue = document.getElementById('temp-value');

        if (tempSlider) {
            let debounceTimer;
            tempSlider.addEventListener('input', (e) => {
                const value = e.target.value;
                if (tempValue) tempValue.textContent = value;

                // 防抖: 100ms
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(() => {
                    wsManager.updateConfig({ temperature: parseFloat(value) });
                }, 100);
            });
        }
    }

    /**
     * 设置容器体积滑条
     */
    setupVolumeSlider() {
        const volumeSlider = document.getElementById('volume-slider');
        const volumeValue = document.getElementById('volume-value');

        if (volumeSlider) {
            let debounceTimer;
            volumeSlider.addEventListener('input', (e) => {
                const value = e.target.value;
                if (volumeValue) volumeValue.textContent = value;

                // 防抖: 150ms
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(() => {
                    wsManager.updateConfig({ boxSize: parseFloat(value) });
                }, 150);
            });
        }
    }

    /**
     * 同步容器体积 UI
     */
    syncVolumeUI(boxSize) {
        if (typeof boxSize !== 'number') return;

        const volumeSlider = document.getElementById('volume-slider');
        const volumeValue = document.getElementById('volume-value');

        if (volumeSlider) volumeSlider.value = boxSize;
        if (volumeValue) volumeValue.textContent = boxSize.toFixed(1);
    }

    /**
     * 订阅温度更新（绝热模式下同步温度滑条）
     */
    subscribeToTemperatureUpdates() {
        stateManager.subscribe('simulation', (sim) => {
            // 绝热模式下，同步显示实时温度
            const config = stateManager.getState().config;
            if (config && !config.useThermostat && sim.currentTemperature !== undefined) {
                const tempSlider = document.getElementById('temp-slider');
                const tempValue = document.getElementById('temp-value');

                const roundedTemp = Math.round(sim.currentTemperature);
                // 限制在滑条范围内
                const clampedTemp = Math.max(100, Math.min(1000, roundedTemp));

                if (tempSlider) tempSlider.value = clampedTemp;
                if (tempValue) tempValue.textContent = roundedTemp;
            }
        });
    }

    /**
     * 设置恒温器控制
     */
    setupThermostatControls() {
        const radios = document.getElementsByName('thermostat-mode');
        radios.forEach(radio => {
            radio.addEventListener('change', (e) => {
                if (e.target.checked) {
                    const useThermostat = e.target.value === 'true';
                    console.log('Sending useThermostat:', useThermostat);
                    wsManager.updateConfig({
                        useThermostat: useThermostat
                    });
                }
            });
        });
    }

    /**
     * 同步恒温器 UI 状态
     */
    syncThermostatUI(useThermostat) {
        if (typeof useThermostat !== 'boolean') return;

        const radios = document.getElementsByName('thermostat-mode');
        radios.forEach(radio => {
            // value is string "true" or "false"
            radio.checked = (radio.value === 'true') === useThermostat;
        });
    }

    /**
     * 设置控制按钮
     */
    setupButtons() {
        const startBtn = document.getElementById('btn-start');
        const pauseBtn = document.getElementById('btn-pause');
        const resetBtn = document.getElementById('btn-reset');

        // 初始禁用start按钮，等待WebSocket连接
        if (startBtn) {
            startBtn.disabled = true;
            startBtn.classList.add('opacity-50', 'cursor-not-allowed');

            startBtn.addEventListener('click', () => {
                // 仅在首次启动时发送配置，暂停后恢复不需要重新发送
                const simState = stateManager.getState().simulation;
                if (!simState.started) {
                    this.sendConfig();
                }
                wsManager.start();
                stateManager.update('simulation', { started: true });
            });
        }

        // 监听WebSocket连接状态，启用/禁用start按钮
        stateManager.subscribe('connection', (conn) => {
            if (startBtn) {
                if (conn.connected) {
                    startBtn.disabled = false;
                    startBtn.classList.remove('opacity-50', 'cursor-not-allowed');
                } else {
                    startBtn.disabled = true;
                    startBtn.classList.add('opacity-50', 'cursor-not-allowed');
                }
            }
        });

        if (pauseBtn) {
            pauseBtn.addEventListener('click', () => wsManager.pause());
        }

        if (resetBtn) {
            resetBtn.addEventListener('click', () => {
                wsManager.reset();
                stateManager.update('simulation', { started: false });
            });
        }
    }

    /**
     * 发送完整配置到后端
     */
    sendConfig() {
        // 构建 substances 数组
        const substances = [];
        let typeId = 0;
        this.substances.forEach((config, id) => {
            substances.push({
                id: id,
                typeId: typeId++,
                colorHue: config.colorHue,
                radius: config.radius,
                initialCount: Math.round(config.initialCount)
            });
        });

        // 构建 reactions 数组
        const reactions = [];
        for (let i = 1; i <= 3; i++) {
            const eqInput = document.getElementById(`reaction-${i}-eq`);
            const eaForwardInput = document.getElementById(`reaction-${i}-ea-forward`);
            const eaReverseInput = document.getElementById(`reaction-${i}-ea-reverse`);

            if (!eqInput) continue;
            let eq = eqInput.value.trim();
            if (!eq) continue;

            // 统一将各种箭头和等号替换为 ASCII 等号
            eq = eq.replace(/→/g, '=')     // Unicode 右箭头
                .replace(/⇌/g, '=')     // Unicode 双向箭头
                .replace(/->/g, '=')     // ASCII 箭头
                .replace(/＝/g, '=');    // 中文等号

            reactions.push({
                equation: eq,
                eaForward: parseFloat(eaForwardInput?.value || 30),
                eaReverse: parseFloat(eaReverseInput?.value || 30)
            });
        }

        // 发送配置
        wsManager.updateConfig({
            substances: substances,
            reactions: reactions
        });

        // 更新本地状态
        stateManager.update('config', { substances, reactions });
    }
}
