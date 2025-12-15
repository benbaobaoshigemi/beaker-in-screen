/**
 * 应用入口
 * 初始化所有模块并建立连接
 */

import { wsManager } from './websocket.js';
import { stateManager } from './state.js';
import { ControlPanel } from './ui/controlPanel.js';
// GPU加速渲染器替换Canvas 2D渲染器
import { SimulationViewGPU as SimulationView } from './ui/simulationViewGPU.js';
import { ConcentrationChart } from './ui/concentrationChart.js';
import { RateChart } from './ui/rateChart.js';


/**
 * 应用类
 */
class App {
    constructor() {
        this.modules = {};
    }

    /**
     * 初始化应用
     */
    init() {
        console.log('[App] Initializing...');

        // 初始化 UI 模块
        this.modules.controlPanel = new ControlPanel();
        this.modules.simulationView = new SimulationView('simulation-canvas');
        this.modules.concentrationChart = new ConcentrationChart('concentration-chart');
        this.modules.rateChart = new RateChart('rate-chart');

        // 连接 WebSocket
        wsManager.connect();

        console.log('[App] Initialized');
    }
}

// DOM 加载完成后启动应用
document.addEventListener('DOMContentLoaded', () => {
    const app = new App();
    app.init();
});
