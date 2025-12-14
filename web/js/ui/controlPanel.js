/**
 * 控制面板模块
 * 处理用户交互：参数调节、启动/暂停/重置
 * 
 * 交互规则：
 * - 温度可在运行中实时调节
 * - 活化能在模拟启动后锁定，重置后解锁
 */

import { stateManager } from '../state.js';
import { wsManager } from '../websocket.js';

export class ControlPanel {
    constructor() {
        this.elements = {
            tempSlider: document.getElementById('temp-slider'),
            tempValue: document.getElementById('temp-value'),
            eaSlider: document.getElementById('ea-slider'),
            eaValue: document.getElementById('ea-value'),
            btnStart: document.getElementById('btn-start'),
            btnPause: document.getElementById('btn-pause'),
            btnReset: document.getElementById('btn-reset'),
        };

        // 活化能锁定状态
        this.eaLocked = false;

        this.init();
    }

    /**
     * 初始化控制面板
     */
    init() {
        this.bindEvents();
        this.subscribeToState();
    }

    /**
     * 绑定 DOM 事件
     */
    bindEvents() {
        // 温度滑块 - input 事件实时生效
        this.elements.tempSlider.addEventListener('input', (e) => {
            const value = parseFloat(e.target.value);
            this.elements.tempValue.textContent = value.toFixed(1);
            // 实时发送到后端
            wsManager.updateConfig({ temperature: value });
            // 实时更新理论曲线（前端预测）
            stateManager.updateTheoryCurve(value);
        });

        // 活化能滑块
        this.elements.eaSlider.addEventListener('input', (e) => {
            if (this.eaLocked) {
                // 阻止修改，恢复原值
                e.target.value = stateManager.getState().config.activationEnergy;
                return;
            }
            const value = parseFloat(e.target.value);
            this.elements.eaValue.textContent = value.toFixed(1);
        });

        this.elements.eaSlider.addEventListener('change', (e) => {
            if (this.eaLocked) return;
            const value = parseFloat(e.target.value);
            wsManager.updateConfig({ activationEnergy: value });
        });

        // 启动按钮
        this.elements.btnStart.addEventListener('click', () => {
            wsManager.start();
            this.lockActivationEnergy();
            this.updateButtonStates(true);
            // 通知前端开始记录数据
            stateManager.update('simulation', { running: true, started: true });
        });

        // 暂停按钮
        this.elements.btnPause.addEventListener('click', () => {
            wsManager.pause();
            this.updateButtonStates(false);
        });

        // 重置按钮
        this.elements.btnReset.addEventListener('click', () => {
            wsManager.reset();
            this.unlockActivationEnergy();
            this.updateButtonStates(false);
        });
    }

    /**
     * 锁定活化能滑块
     */
    lockActivationEnergy() {
        this.eaLocked = true;
        this.elements.eaSlider.classList.add('locked');
        this.elements.eaSlider.style.opacity = '0.5';
        this.elements.eaSlider.style.cursor = 'not-allowed';
    }

    /**
     * 解锁活化能滑块
     */
    unlockActivationEnergy() {
        this.eaLocked = false;
        this.elements.eaSlider.classList.remove('locked');
        this.elements.eaSlider.style.opacity = '1';
        this.elements.eaSlider.style.cursor = 'pointer';
    }

    /**
     * 订阅状态变化
     */
    subscribeToState() {
        // 订阅配置变化
        stateManager.subscribe('config', (config) => {
            this.elements.tempSlider.value = config.temperature;
            this.elements.tempValue.textContent = config.temperature.toFixed(1);

            // 仅在未锁定时更新活化能滑块
            if (!this.eaLocked) {
                this.elements.eaSlider.value = config.activationEnergy;
                this.elements.eaValue.textContent = config.activationEnergy.toFixed(1);
            }
        });

        // 订阅运行状态变化
        stateManager.subscribe('simulation', (simulation) => {
            this.updateButtonStates(simulation.running);
        });
    }

    /**
     * 更新按钮状态
     * @param {boolean} running - 是否正在运行
     */
    updateButtonStates(running) {
        if (running) {
            this.elements.btnStart.classList.remove('active');
            this.elements.btnPause.classList.add('active');
        } else {
            this.elements.btnStart.classList.add('active');
            this.elements.btnPause.classList.remove('active');
        }
    }
}
