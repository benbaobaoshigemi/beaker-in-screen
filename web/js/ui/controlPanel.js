/**
 * 控制面板模块
 * 处理属性面板和控制面板的交互
 */

import { wsManager } from '../websocket.js';
import { stateManager } from '../state.js';

export class ControlPanel {
    constructor() {
        this.init();
    }

    init() {
        this.setupPropertySliders();
        this.setupControlSliders();
        this.setupButtons();
        this.subscribeToState();
    }

    /**
     * 设置属性滑条（模拟开始后锁定）
     */
    setupPropertySliders() {
        // A 半径
        this.bindSlider('radius-a-slider', 'radius-a-value', (val) => {
            wsManager.updateConfig({ radiusA: parseFloat(val) });
        }, (val) => parseFloat(val).toFixed(2));

        // B 半径
        this.bindSlider('radius-b-slider', 'radius-b-value', (val) => {
            wsManager.updateConfig({ radiusB: parseFloat(val) });
        }, (val) => parseFloat(val).toFixed(2));

        // A 初始数量
        this.bindSlider('count-a-slider', 'count-a-value', (val) => {
            wsManager.updateConfig({ initialCountA: parseInt(val) });
        });

        // B 初始数量
        this.bindSlider('count-b-slider', 'count-b-value', (val) => {
            wsManager.updateConfig({ initialCountB: parseInt(val) });
        });

        // 正反应活化能
        this.bindSlider('ea-forward-slider', 'ea-forward-value', (val) => {
            wsManager.updateConfig({ eaForward: parseFloat(val) });
        });

        // 逆反应活化能
        this.bindSlider('ea-reverse-slider', 'ea-reverse-value', (val) => {
            wsManager.updateConfig({ eaReverse: parseFloat(val) });
        });
    }

    /**
     * 设置控制滑条（运行时可调）
     */
    setupControlSliders() {
        // 温度
        this.bindSlider('temp-slider', 'temp-value', (val) => {
            wsManager.updateConfig({ temperature: parseFloat(val) });
        });
    }

    /**
     * 设置控制按钮
     */
    setupButtons() {
        const startBtn = document.getElementById('btn-start');
        const pauseBtn = document.getElementById('btn-pause');
        const resetBtn = document.getElementById('btn-reset');

        if (startBtn) {
            startBtn.addEventListener('click', () => {
                wsManager.start();
                // 标记模拟已启动
                stateManager.update('simulation', { started: true });
            });
        }

        if (pauseBtn) {
            pauseBtn.addEventListener('click', () => {
                wsManager.pause();
            });
        }

        if (resetBtn) {
            resetBtn.addEventListener('click', () => {
                wsManager.reset();
            });
        }
    }

    /**
     * 订阅状态更新
     */
    subscribeToState() {
        // 监听配置变化以同步 UI
        stateManager.subscribe('config', (config) => {
            this.updateSliderValue('radius-a-slider', 'radius-a-value', config.radiusA, (v) => v.toFixed(2));
            this.updateSliderValue('radius-b-slider', 'radius-b-value', config.radiusB, (v) => v.toFixed(2));
            this.updateSliderValue('count-a-slider', 'count-a-value', config.initialCountA);
            this.updateSliderValue('count-b-slider', 'count-b-value', config.initialCountB);
            this.updateSliderValue('ea-forward-slider', 'ea-forward-value', config.eaForward);
            this.updateSliderValue('ea-reverse-slider', 'ea-reverse-value', config.eaReverse);
            this.updateSliderValue('temp-slider', 'temp-value', config.temperature);
        });
    }

    /**
     * 绑定滑条事件
     */
    bindSlider(sliderId, valueId, onChange, formatter = (v) => v) {
        const slider = document.getElementById(sliderId);
        const valueDisplay = document.getElementById(valueId);

        if (!slider) return;

        slider.addEventListener('input', (e) => {
            const value = e.target.value;
            if (valueDisplay) {
                valueDisplay.textContent = formatter(value);
            }
            onChange(value);
        });
    }

    /**
     * 更新滑条显示值
     */
    updateSliderValue(sliderId, valueId, value, formatter = (v) => v) {
        const slider = document.getElementById(sliderId);
        const valueDisplay = document.getElementById(valueId);

        if (slider && value !== undefined && value !== null) {
            slider.value = value;
        }
        if (valueDisplay && value !== undefined && value !== null) {
            valueDisplay.textContent = formatter(value);
        }
    }
}
