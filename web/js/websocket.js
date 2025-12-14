/**
 * WebSocket 通信模块
 * 负责与后端的实时通信
 */

import { CONFIG } from './config.js';
import { stateManager } from './state.js';

class WebSocketManager {
    constructor() {
        this.socket = null;
        this.connected = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.theoryCurveGenerated = false;  // 理论曲线是否已生成
    }

    /**
     * 连接到服务器
     */
    connect() {
        if (this.socket) {
            return;
        }

        console.log('[WebSocket] Connecting to', CONFIG.WS_URL);

        // 使用 Socket.IO 客户端
        this.socket = io(CONFIG.WS_URL, {
            transports: ['websocket', 'polling'],
            reconnection: true,
            reconnectionAttempts: this.maxReconnectAttempts,
            reconnectionDelay: 1000,
        });

        this.setupEventHandlers();
    }

    /**
     * 设置事件处理器
     */
    setupEventHandlers() {
        // 连接成功
        this.socket.on('connect', () => {
            console.log('[WebSocket] Connected');
            this.connected = true;
            this.reconnectAttempts = 0;
        });

        // 断开连接
        this.socket.on('disconnect', (reason) => {
            console.log('[WebSocket] Disconnected:', reason);
            this.connected = false;
        });

        // 连接错误
        this.socket.on('connect_error', (error) => {
            console.error('[WebSocket] Connection error:', error);
            this.reconnectAttempts++;
        });

        // 接收配置
        this.socket.on('config', (data) => {
            console.log('[WebSocket] Config received:', data);
            stateManager.update('config', {
                temperature: data.temperature,
                activationEnergy: data.activationEnergy,
                numParticles: data.numParticles,
            });
        });

        // 接收状态更新
        this.socket.on('state_update', (data) => {
            stateManager.updateFromServer(data);

            // 当后端估算出 k 值时，生成理论曲线
            if (data.kEstimated && !this.theoryCurveGenerated) {
                const numParticles = stateManager.getState().config.numParticles || 10000;
                stateManager.generateTheoryCurve(data.kEstimated, numParticles, 100);
                this.theoryCurveGenerated = true;
            }
        });

        // 接收运行状态
        this.socket.on('status', (data) => {
            stateManager.update('simulation', { running: data.running });
        });
    }

    /**
     * 发送启动命令
     */
    start() {
        if (this.socket && this.connected) {
            this.socket.emit('start');
        }
    }

    /**
     * 发送暂停命令
     */
    pause() {
        if (this.socket && this.connected) {
            this.socket.emit('pause');
        }
    }

    /**
     * 发送重置命令
     */
    reset() {
        if (this.socket && this.connected) {
            this.socket.emit('reset');
            this.theoryCurveGenerated = false;  // 允许重新生成理论曲线
            stateManager.reset();
        }
    }

    /**
     * 更新配置
     * @param {Object} config - 配置对象
     */
    updateConfig(config) {
        if (this.socket && this.connected) {
            this.socket.emit('update_config', config);
        }
    }

    /**
     * 断开连接
     */
    disconnect() {
        if (this.socket) {
            this.socket.disconnect();
            this.socket = null;
            this.connected = false;
        }
    }
}

// 导出单例
export const wsManager = new WebSocketManager();
