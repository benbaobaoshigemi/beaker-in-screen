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
        this.maxReconnectAttempts = Infinity; // 无限重试，避免 Server 重启时间过长导致断连
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
            stateManager.update('connection', { connected: true });
        });

        // 断开连接
        this.socket.on('disconnect', (reason) => {
            console.log('[WebSocket] Disconnected:', reason);
            this.connected = false;
            stateManager.update('connection', { connected: false });
        });

        // 连接错误
        this.socket.on('connect_error', (error) => {
            console.error('[WebSocket] Connection error:', error);
            this.reconnectAttempts++;
        });

        // 接收配置
        this.socket.on('config', (data) => {
            console.log('[WebSocket] Config received');

            // 新格式：substances 和 reactions
            stateManager.update('config', {
                temperature: data.temperature,
                substances: data.substances || [],
                reactions: data.reactions || [],
                propertiesLocked: data.propertiesLocked || false,
                boxSize: data.boxSize || 40,
                maxParticles: data.maxParticles || 20000,
            });

            // 更新 UI 锁定状态
            this.updatePropertyLockUI(data.propertiesLocked);
        });

        // 接收状态更新
        this.socket.on('state_update', (data) => {
            // 简单判断：如果模拟刚开始运行且时间很短，可能是第一帧
            if (data.simulation && data.simulation.running && data.simulation.time < 0.1) {
                // 注意：这里可能会在每次暂停恢复后重置时间时触发，仅作调试参考
                console.timeEnd('Startup-to-FirstData');
            }
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
            console.time('Startup-to-FirstData'); // 开始计时：从点击启动到收到第一帧数据
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
