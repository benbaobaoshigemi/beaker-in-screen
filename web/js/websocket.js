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
        // autoConnect: false 让我们能先设置事件处理器
        this.socket = io(CONFIG.WS_URL, {
            transports: ['websocket', 'polling'],
            reconnection: true,
            reconnectionAttempts: this.maxReconnectAttempts,
            reconnectionDelay: 1000,
            autoConnect: false,
        });

        // 先设置事件处理器
        this.setupEventHandlers();

        // 然后手动连接
        this.socket.connect();
    }

    /**
     * 设置事件处理器
     */
    setupEventHandlers() {
        // 连接成功
        this.socket.on('connect', () => {
            console.log('[WebSocket] Connected - setting connected=true');
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

            // 更新可逆反应配置
            const revConfig = data.reversibleReaction || {};
            stateManager.update('config', {
                temperature: data.temperature,
                // 可逆反应参数
                radiusA: revConfig.radiusA || 0.3,
                radiusB: revConfig.radiusB || 0.3,
                initialCountA: revConfig.initialCountA || 10000,
                initialCountB: revConfig.initialCountB || 0,
                eaForward: revConfig.eaForward || 30,
                eaReverse: revConfig.eaReverse || 30,
                // 锁定状态
                propertiesLocked: data.propertiesLocked || false,
                // 半衰期
                halfLifeForward: data.halfLifeForward,
                halfLifeReverse: data.halfLifeReverse,
                // 兼容旧版
                numParticles: data.numParticles || 10000,
            });

            // 更新 UI 锁定状态
            this.updatePropertyLockUI(data.propertiesLocked);
        });

        // 接收状态更新
        this.socket.on('state_update', (data) => {
            stateManager.updateFromServer(data);
            // 不再生成理论曲线
        });

        // 接收运行状态
        this.socket.on('status', (data) => {
            stateManager.update('simulation', { running: data.running });
        });

        // 接收重置确认 - 此时可以安全清空前端状态
        this.socket.on('reset_ack', (data) => {
            console.log('[WebSocket] Reset acknowledged');
            stateManager.reset();
            // 重置后立即应用后端发来的初始状态
            stateManager.updateFromServer(data);
        });
    }

    /**
     * 更新属性锁定 UI 状态
     */
    updatePropertyLockUI(locked) {
        const lockIndicator = document.getElementById('lock-indicator');
        const propertySliders = document.querySelectorAll('.property-slider');

        if (lockIndicator) {
            if (locked) {
                lockIndicator.classList.add('locked');
            } else {
                lockIndicator.classList.remove('locked');
            }
        }

        propertySliders.forEach(slider => {
            slider.disabled = locked;
        });
    }

    /**
     * 发送启动命令
     */
    start() {
        console.log('[WebSocket] start() called, socket:', !!this.socket, 'connected:', this.connected);
        if (this.socket && this.connected) {
            console.log('[WebSocket] Emitting start event');
            this.socket.emit('start');
        } else {
            console.error('[WebSocket] Cannot start - not connected!');
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
            // 只发送重置命令，不立即清空状态
            // 等待后端 reset_ack 事件后再清空，避免竞态条件
            this.socket.emit('reset');
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
