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

# 提前导入物理引擎函数，避免在循环中重复导入
from physics_engine import (
    update_positions_numba, 
    build_cell_list, 
    resolve_collisions
)

# ============================================================================
# 物理引擎适配层（使用运行时配置）
# ============================================================================

class PhysicsEngineAdapter:
    """
    物理引擎适配器
    封装原有物理引擎，支持可逆反应配置
    
    可逆反应: 2A ⇌ 2B
    """
    
    def __init__(self, runtime_config: RuntimeConfig):
        self.config = runtime_config
        
        # 从可逆反应配置获取参数
        rev_config = runtime_config.reversible_reaction
        self.n = rev_config.get_total_particles()
        self.initial_count_a = rev_config.initial_count_a
        self.initial_count_b = rev_config.initial_count_b
        
        self.box_size = runtime_config.box_size
        self.radius_a = rev_config.radius_a
        self.radius_b = rev_config.radius_b
        self.mass = runtime_config.mass
        self.dt = runtime_config.dt
        
        # Cell 划分（使用较大的半径）
        max_radius = max(self.radius_a, self.radius_b)
        self.cell_divs = int(self.box_size // (max_radius * 3.0))
        if self.cell_divs < 1:
            self.cell_divs = 1
        
        # 初始化粒子
        self._init_particles()
        
        # 模拟时间
        self.sim_time = 0.0
        
        # 半衰期跟踪
        self.half_life_forward_detected = False
        self.half_life_reverse_detected = False
        self.initial_a_count = self.initial_count_a
        self.initial_b_count = self.initial_count_b
        
    def _init_particles(self):
        """初始化粒子位置和速度"""
        n = self.n
        box_size = self.box_size
        temp_k = self.config.temperature
        boltzmann_k = self.config.boltzmann_k
        mass = self.mass
        
        # 位置: 均匀随机分布
        self.pos = np.random.rand(n, 3) * box_size
        
        # 速度: 麦克斯韦-玻尔兹曼分布
        sigma = math.sqrt(boltzmann_k * temp_k / mass)
        self.vel = np.random.normal(0, sigma, (n, 3))
        
        # 去除整体漂移
        v_mean = np.mean(self.vel, axis=0)
        self.vel -= v_mean
        
        # 类型: 根据初始浓度设置
        # 前 initial_count_a 个为 A (0)，后 initial_count_b 个为 B (1)
        self.types = np.zeros(n, dtype=np.int32)
        if self.initial_count_b > 0:
            self.types[self.initial_count_a:] = 1  # B 粒子
    
    def update(self):
        """执行一步物理更新"""
        dt = self.dt
        box_size = self.box_size
        
        # 获取可逆反应参数
        rev_config = self.config.reversible_reaction
        ea_forward = rev_config.ea_forward
        ea_reverse = rev_config.ea_reverse
        
        # 恒温器 (Thermostat)
        v_sq = np.sum(self.vel ** 2)
        current_temp = (self.mass * v_sq) / (3 * self.n * self.config.boltzmann_k)
        
        if current_temp > 0:
            scale = math.sqrt(self.config.temperature / current_temp)
            # 调试日志：每 60 帧打印一次温度状态
            if self.sim_time % 1.0 < dt:
                print(f"[Physics] Target Temp: {self.config.temperature:.1f}, Current Temp: {current_temp:.1f}, Scale: {scale:.4f}")
            
            scale = np.clip(scale, 0.99, 1.01)
            self.vel *= scale

        # 1. 更新位置
        update_positions_numba(self.pos, self.vel, dt, box_size)
        
        # 2. 构建 Cell List
        head, next_particle = build_cell_list(
            self.pos, self.n, box_size, self.cell_divs
        )
        
        # 3. 碰撞处理与可逆反应
        resolve_collisions(
            self.pos, self.vel, self.types,
            head, next_particle,
            self.cell_divs, box_size, dt,
            ea_forward,                     # 正反应活化能
            ea_reverse,                     # 逆反应活化能
            self.config.temperature,        # 温度 (K)
            self.config.boltzmann_k,        # 玻尔兹曼常数
            rev_config.radius_a,            # A 粒子半径
            rev_config.radius_b             # B 粒子半径
        )
        
        self.sim_time += dt
        
        # 半衰期检测
        self._check_half_life()
    
    def _check_half_life(self):
        """检测并记录半衰期"""
        current_a = self.get_reactant_count()
        current_b = self.get_product_count()
        
        # 正反应半衰期: A 减少到初始值的一半
        if not self.half_life_forward_detected and self.initial_a_count > 0:
            if current_a <= self.initial_a_count / 2:
                self.config.half_life_forward = self.sim_time
                self.half_life_forward_detected = True
                print(f"[PhysicsEngine] Forward half-life detected: {self.sim_time:.2f}s")
        
        # 逆反应半衰期: B 减少到初始值的一半（仅当初始有 B 时有意义）
        if not self.half_life_reverse_detected and self.initial_b_count > 0:
            if current_b <= self.initial_b_count / 2:
                self.config.half_life_reverse = self.sim_time
                self.half_life_reverse_detected = True
                print(f"[PhysicsEngine] Reverse half-life detected: {self.sim_time:.2f}s")
    
    def get_product_count(self) -> int:
        """获取产物 B 数量"""
        return int(np.sum(self.types == 1))
    
    def get_reactant_count(self) -> int:
        """获取反应物 A 数量"""
        return int(np.sum(self.types == 0))
    
    def get_visible_particles(self) -> List[Dict[str, Any]]:
        """获取可见粒子（切片内）用于前端渲染，包含能量信息"""
        z_mid = self.box_size / 2
        z_half_thick = self.config.slice_thickness / 2
        
        # 筛选可见粒子（排除已消耗的粒子 type=2，虽然可逆反应不再使用）
        z_vals = self.pos[:, 2]
        visible_mask = (np.abs(z_vals - z_mid) <= z_half_thick) & (self.types != 2)
        
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
        """获取完整状态（不再包含理论曲线）"""
        product_count = self.get_product_count()
        reactant_count = self.get_reactant_count()
        
        return {
            "time": self.sim_time,
            "productCount": product_count,
            "reactantCount": reactant_count,
            "halfLifeForward": self.config.half_life_forward,
            "halfLifeReverse": self.config.half_life_reverse,
            "particles": self.get_visible_particles(),
        }
    
    def reset(self):
        """重置模拟"""
        self._init_particles()
        self.sim_time = 0.0
        self.half_life_forward_detected = False
        self.half_life_reverse_detected = False
        self.config.half_life_forward = None
        self.config.half_life_reverse = None


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
    
    # 如果物理引擎存在，更新其配置引用
    if physics_engine is not None:
        physics_engine.config = runtime_config
    
    emit('config', runtime_config.to_dict(), broadcast=True)
    print(f'[Server] Config updated: {data}')


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
