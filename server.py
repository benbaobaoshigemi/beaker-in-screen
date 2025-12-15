# -*- coding: utf-8 -*-
"""
Flask + Socket.IO 服务端
提供 Web 前端与物理引擎的通信桥梁
"""

import os
import sys
import math
import threading
import time
from typing import Optional, Dict, Any, List

import numpy as np
from flask import Flask, send_from_directory, jsonify
from flask_socketio import SocketIO, emit

from runtime_config import RuntimeConfig

# 动态导入物理引擎所需的配置
import config as static_config

# 导入物理引擎函数
from physics_engine import (
    update_positions_numba, 
    build_cell_list, 
    resolve_collisions,
    resolve_collisions_generic,
    process_1body_reactions
)

# ============================================================================
# 物理引擎适配层（使用运行时配置）
# ============================================================================

class PhysicsEngineAdapter:
    """
    物理引擎适配器
    支持一级/二级反应，粒子激活/失活
    """
    
    def __init__(self, runtime_config: RuntimeConfig):
        self.config = runtime_config
        
        # 粒子数管理
        self.max_particles = runtime_config.max_particles
        self.initial_active = runtime_config.get_total_initial_particles()
        
        # 系统参数
        self.box_size = runtime_config.box_size
        self.mass = runtime_config.mass
        self.dt = runtime_config.dt
        
        # 构建反应数组
        self.reactions_2body = runtime_config.build_reactions_2body()
        self.reactions_1body = runtime_config.build_reactions_1body()
        self.radii = runtime_config.build_radii_array()
        
        # Cell 划分
        max_radius = max(self.radii) if len(self.radii) > 0 and max(self.radii) > 0 else 0.15
        self.cell_divs = int(self.box_size // (max_radius * 3.0))
        if self.cell_divs < 1:
            self.cell_divs = 1
        
        # 初始化粒子
        self._init_particles()
        
        # 模拟时间
        self.sim_time = 0.0
    
    def _init_particles(self):
        """初始化粒子数组（预分配）"""
        n = self.max_particles
        
        # 预分配大数组
        self.pos = np.zeros((n, 3), dtype=np.float64)
        self.vel = np.zeros((n, 3), dtype=np.float64)
        self.types = np.full(n, -1, dtype=np.int32)  # -1 = 失活
        
        # 只初始化活跃粒子
        box_size = self.box_size
        temp_k = self.config.temperature
        boltzmann_k = self.config.boltzmann_k
        
        sigma = math.sqrt(boltzmann_k * temp_k / self.mass)
        
        offset = 0
        for substance in self.config.substances:
            count = substance.initial_count
            for _ in range(count):
                if offset >= n:
                    break
                # 位置随机
                self.pos[offset, 0] = np.random.random() * box_size
                self.pos[offset, 1] = np.random.random() * box_size
                self.pos[offset, 2] = np.random.random() * box_size
                # 速度 Maxwell-Boltzmann
                self.vel[offset, 0] = np.random.normal(0, sigma)
                self.vel[offset, 1] = np.random.normal(0, sigma)
                self.vel[offset, 2] = np.random.normal(0, sigma)
                # 类型
                self.types[offset] = substance.type_id
                offset += 1
        
        # 去除平均漂移
        if offset > 0:
            v_mean = np.mean(self.vel[:offset], axis=0)
            self.vel[:offset] -= v_mean
    
    def get_active_count(self) -> int:
        """获取活跃粒子数"""
        return int(np.sum(self.types >= 0))
    
    def update(self):
        """执行一步物理更新"""
        dt = self.dt
        box_size = self.box_size
        n_active = self.get_active_count()
        
        if n_active == 0:
            self.sim_time += dt
            return
        
        # 恒温器
        active_mask = self.types >= 0
        v_sq = np.sum(self.vel[active_mask] ** 2)
        current_temp = (self.mass * v_sq) / (3 * n_active * self.config.boltzmann_k)
        
        if current_temp > 0:
            scale = math.sqrt(self.config.temperature / current_temp)
            scale = np.clip(scale, 0.99, 1.01)
            self.vel[active_mask] *= scale
        
        # 1. 更新位置（只更新活跃粒子）
        update_positions_numba(self.pos, self.vel, dt, box_size)
        
        # 2. 构建 Cell List（跳过失活粒子）
        head, next_particle = build_cell_list(
            self.pos, self.max_particles, box_size, self.cell_divs, self.types
        )
        
        # 3. 二级反应（碰撞触发）
        if len(self.reactions_2body) > 0:
            resolve_collisions_generic(
                self.pos, self.vel, self.types,
                head, next_particle,
                self.cell_divs, box_size, dt,
                self.reactions_2body,
                self.radii,
                self.config.temperature,
                self.config.boltzmann_k,
                self.mass
            )
        
        # 4. 一级反应（自发分解）
        if len(self.reactions_1body) > 0:
            process_1body_reactions(
                self.types, self.pos, self.vel,
                self.reactions_1body,
                self.config.temperature,
                self.config.boltzmann_k,
                dt, box_size, self.mass
            )
        
        self.sim_time += dt
    
    def get_visible_particles(self) -> List[Dict[str, Any]]:
        """获取可见粒子（切片内）用于前端渲染，包含能量信息"""
        z_mid = self.box_size / 2
        z_half_thick = self.config.slice_thickness / 2
        
        # 筛选可见粒子（排除失活粒子 type=-1）
        z_vals = self.pos[:, 2]
        visible_mask = (np.abs(z_vals - z_mid) <= z_half_thick) & (self.types >= 0)
        
        visible_pos = self.pos[visible_mask]
        visible_types = self.types[visible_mask]
        visible_vel = self.vel[visible_mask]
        
        n_visible = len(visible_pos)
        if n_visible == 0:
            return []
        
        # 向量化计算能量
        speed_sq = np.sum(visible_vel ** 2, axis=1)
        kinetic_energy = 0.5 * self.mass * speed_sq
        
        # 预计算常量
        max_temp = 500.0
        sigma_max = math.sqrt(self.config.boltzmann_k * max_temp / self.mass)
        max_speed = 3 * sigma_max * math.sqrt(3)
        max_energy_absolute = 0.5 * self.mass * max_speed ** 2
        
        # 向量化归一化
        normalized_energy = np.clip(kinetic_energy / max_energy_absolute, 0, 1)
        
        # 向量化坐标归一化
        norm_x = visible_pos[:, 0] / self.box_size
        norm_y = visible_pos[:, 1] / self.box_size
        
        particles = [
            {"x": float(norm_x[i]), "y": float(norm_y[i]), 
             "type": int(visible_types[i]), "energy": float(normalized_energy[i])}
            for i in range(n_visible)
        ]
        
        return particles
    
    def get_state(self) -> Dict[str, Any]:
        """获取完整状态"""
        # 统计各物质数量
        substance_counts = {}
        for substance in self.config.substances:
            count = int(np.sum(self.types == substance.type_id))
            substance_counts[substance.id] = count
        
        return {
            "time": self.sim_time,
            "substanceCounts": substance_counts,
            "activeCount": self.get_active_count(),
            "particles": self.get_visible_particles(),
        }
    
    def reset(self):
        """重置模拟"""
        # 重新构建反应数组
        self.reactions_2body = self.config.build_reactions_2body()
        self.reactions_1body = self.config.build_reactions_1body()
        self.radii = self.config.build_radii_array()
        
        # 重新计算 Cell 划分
        max_radius = max(self.radii) if len(self.radii) > 0 and max(self.radii) > 0 else 0.15
        self.cell_divs = int(self.box_size // (max_radius * 3.0))
        if self.cell_divs < 1:
            self.cell_divs = 1
        
        # 重新初始化粒子
        self._init_particles()
        self.sim_time = 0.0


# ============================================================================
# Flask 应用
# ============================================================================

app = Flask(__name__, static_folder='web', static_url_path='')
app.config['SECRET_KEY'] = 'particle-simulator-secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# 全局状态
runtime_config = RuntimeConfig()
physics_engine: Optional[PhysicsEngineAdapter] = None
simulation_running = False
simulation_lock = threading.Lock()


def simulation_loop():
    """后台模拟循环
    
    性能优化策略：
    - 降低推送帧率到30FPS（人眼足够流畅）
    - 每帧10步物理更新（10 * 0.002 = 0.02s 物理时间/帧）
    - 总物理时间速率 = 0.02 * 30 = 0.6x 实时（合理）
    """
    global simulation_running, physics_engine
    
    target_fps = 30  # 降低到30FPS减少推送频率
    frame_time = 1.0 / target_fps
    
    while True:
        start_time = time.perf_counter()
        
        with simulation_lock:
            if not simulation_running or physics_engine is None:
                time.sleep(0.1)
                continue
            
            # 每帧10步物理更新（平衡精度与性能）
            steps_per_frame = 10
            for _ in range(steps_per_frame):
                physics_engine.update()
            
            # 获取状态并推送
            state = physics_engine.get_state()
        
        # 推送到所有客户端
        socketio.emit('state_update', state)
        
        # 精确帧时间控制
        elapsed = time.perf_counter() - start_time
        sleep_time = frame_time - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)


# 启动后台线程
simulation_thread = threading.Thread(target=simulation_loop, daemon=True)
simulation_thread.start()


# ============================================================================
# 路由
# ============================================================================

@app.route('/')
def index():
    """主页"""
    return send_from_directory('web', 'index.html')


@app.route('/api/config')
def get_config():
    """获取当前配置"""
    return jsonify(runtime_config.to_dict())


# ============================================================================
# Socket.IO 事件处理
# ============================================================================

@socketio.on('connect')
def handle_connect():
    """客户端连接"""
    global physics_engine, simulation_running
    
    print('[Server] Client connected')
    
    # 每次连接时重置物理引擎，确保干净的初始状态
    with simulation_lock:
        simulation_running = False
        physics_engine = PhysicsEngineAdapter(runtime_config)
    
    emit('config', runtime_config.to_dict())
    emit('state_update', physics_engine.get_state())


@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开"""
    global simulation_running
    
    with simulation_lock:
        simulation_running = False
        
    print('[Server] Client disconnected - Simulation stopped')


@socketio.on('start')
def handle_start():
    """启动模拟"""
    global simulation_running, physics_engine
    
    with simulation_lock:
        if physics_engine is None:
            physics_engine = PhysicsEngineAdapter(runtime_config)
        # 锁定属性参数
        runtime_config.lock_properties()
        simulation_running = True
    
    emit('status', {'running': True}, broadcast=True)
    emit('config', runtime_config.to_dict(), broadcast=True)  # 通知前端属性已锁定
    print('[Server] Simulation started - Properties locked')


@socketio.on('pause')
def handle_pause():
    """暂停模拟"""
    global simulation_running
    
    with simulation_lock:
        simulation_running = False
    
    emit('status', {'running': False}, broadcast=True)
    print('[Server] Simulation paused')


@socketio.on('reset')
def handle_reset():
    """重置模拟"""
    global physics_engine, simulation_running
    
    with simulation_lock:
        simulation_running = False
        # 解锁属性参数
        runtime_config.unlock_properties()
        physics_engine = PhysicsEngineAdapter(runtime_config)
        state = physics_engine.get_state()
    
    emit('status', {'running': False}, broadcast=True)
    emit('config', runtime_config.to_dict(), broadcast=True)  # 通知前端属性已解锁
    # 发送重置确认，前端收到后才清空状态
    emit('reset_ack', state, broadcast=True)
    print('[Server] Simulation reset - Properties unlocked')


@socketio.on('update_config')
def handle_update_config(data: Dict[str, Any]):
    """更新运行时配置"""
    global physics_engine
    
    runtime_config.update_from_dict(data)
    
    # 如果模拟未运行且更新涉及物质/反应配置，重建物理引擎
    should_preview = 'substances' in data or 'reactions' in data
    
    if not simulation_running and should_preview:
        with simulation_lock:
            physics_engine = PhysicsEngineAdapter(runtime_config)
            state = physics_engine.get_state()
            emit('state_update', state, broadcast=True)
            
    emit('config', runtime_config.to_dict(), broadcast=True)
    print(f'[Server] Config updated: {list(data.keys())}')


# ============================================================================
# 主入口
# ============================================================================

if __name__ == '__main__':
    import socket
    
    PORT = 5000
    
    # 端口冲突检测：检查是否已有服务器在运行
    def is_port_in_use(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('0.0.0.0', port))
                return False
            except OSError:
                return True
    
    if is_port_in_use(PORT):
        print("=" * 50)
        print(f" ❌ 错误：端口 {PORT} 已被占用！")
        print(" 可能原因：另一个服务器实例正在运行。")
        print(" 解决方案：请先关闭已有的服务器进程。")
        print("=" * 50)
        sys.exit(1)
    
    print("=" * 50)
    print(" 化学反应粒子模拟器 Web 服务")
    print(f" http://localhost:{PORT}")
    print("=" * 50)
    
    socketio.run(app, host='0.0.0.0', port=PORT, debug=False)
