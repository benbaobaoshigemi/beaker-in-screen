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
    封装原有物理引擎，支持运行时配置
    """
    
    def __init__(self, runtime_config: RuntimeConfig):
        self.config = runtime_config
        self.n = runtime_config.num_particles
        self.box_size = runtime_config.box_size
        self.radius = runtime_config.particle_radius
        self.mass = runtime_config.mass
        self.dt = runtime_config.dt
        
        # Cell 划分
        self.cell_divs = int(self.box_size // (self.radius * 3.0))
        if self.cell_divs < 1:
            self.cell_divs = 1
        
        # 初始化粒子
        self._init_particles()
        
        # 模拟时间
        self.sim_time = 0.0
        
        # 理论曲线参数估算
        self.k_estimated: Optional[float] = None
        self.estimation_data: List[tuple] = []
        
    def _init_particles(self):
        """初始化粒子位置和速度"""
        n = self.n
        box_size = self.box_size
        temp_k = self.config.temperature
        boltzmann_k = self.config.boltzmann_k
        mass = self.mass
        
        # 位置: 均匀随机分布
        # 随机分布更符合真实物理，虽然可能有少量初始重叠，
        # 但通过碰撞处理会自然分散开
        self.pos = np.random.rand(n, 3) * box_size
        
        # 速度: 麦克斯韦-玻尔兹曼分布
        sigma = math.sqrt(boltzmann_k * temp_k / mass)
        self.vel = np.random.normal(0, sigma, (n, 3))
        
        # 去除整体漂移
        v_mean = np.mean(self.vel, axis=0)
        self.vel -= v_mean
        
        # 类型: 全部为 A (0)
        self.types = np.zeros(n, dtype=np.int32)
    
    def update(self):
        """执行一步物理更新"""
        dt = self.dt
        box_size = self.box_size
        
        # 使用运行时活化能
        activation_energy = self.config.activation_energy
        
        # 物理优化 2: 恒温器 (Thermostat)
        # 简单的速度重缩放以维持 NVT 系综，防止反应放热导致温度失控
        # T = 2*KE / (3*N*k)
        v_sq = np.sum(self.vel ** 2)
        current_temp = (self.mass * v_sq) / (3 * self.n * self.config.boltzmann_k)
        
        if current_temp > 0:
            # 限制单步调整幅度 (0.99-1.01)，模拟软耦合热浴，避免数值震荡
            scale = math.sqrt(self.config.temperature / current_temp)
            scale = np.clip(scale, 0.99, 1.01)
            self.vel *= scale

        # 1. 更新位置
        update_positions_numba(self.pos, self.vel, dt, box_size)
        
        # 2. 构建 Cell List
        head, next_particle = build_cell_list(
            self.pos, self.n, box_size, self.cell_divs
        )
        
        # 3. 碰撞处理与反应（阿伦尼乌斯方程实现）
        # 传入活化能、温度和玻尔兹曼常数，用于计算反应概率 P = exp(-Ea/kT)
        resolve_collisions(
            self.pos, self.vel, self.types,
            head, next_particle,
            self.cell_divs, box_size, dt,
            activation_energy,          # 活化能
            self.config.temperature,    # 温度 (K)
            self.config.boltzmann_k     # 玻尔兹曼常数
        )
        
        self.sim_time += dt
        
        # 收集数据用于 k 估算
        product_count = self.get_product_count()
        
        # 仅在未完成估算时收集数据，防止内存无限增长
        if self.k_estimated is None:
            self.estimation_data.append((self.sim_time, product_count))
            
        if self.k_estimated is None and len(self.estimation_data) >= 100:
            self._estimate_k()
    
    def _estimate_k(self):
        """
        估算反应速率常数 k
        
        对于 nA → mB 反应:
        - 速率方程: -d[A]/dt = k[A]^2 (二级反应)
        - 积分形式: 1/[A] - 1/[A]0 = k*t
        - 产物关系: [B] = ([A]0 - [A]) / n * m
        """
        A0 = self.n
        k_values = []
        
        # 从反应配置获取系数
        n_reactant = self.config.reaction.get_total_reactant_consumed()  # 消耗的反应物数
        n_product = self.config.reaction.get_total_product_created()      # 生成的产物数
        
        # FIX: 使用所有可用数据进行估算，而不仅仅是前100个
        for i in range(10, len(self.estimation_data), 5):
            t, B = self.estimation_data[i]  # B 是产物数量
            # 根据 nA → mB，消耗的 A = B * n / m
            consumed_A = B * n_reactant / n_product
            A = A0 - consumed_A
            if A > 100 and t > 0.01:
                k = (1.0/A - 1.0/A0) / t
                if k > 0:
                    k_values.append(k)
        
        if k_values:
            k_values.sort()
            self.k_estimated = k_values[len(k_values) // 2]
            print(f"[PhysicsEngine] Auto-estimated k = {self.k_estimated:.6f}")
            # 估算完成后清空数据以释放内存
            self.estimation_data = []
    
    def get_product_count(self) -> int:
        """获取产物数量"""
        return int(np.sum(self.types == 1))
    
    def get_reactant_count(self) -> int:
        """获取反应物数量"""
        return int(np.sum(self.types == 0))
    
    def get_theory_value(self, t: float) -> float:
        """
        计算理论曲线值 (产物 B 的数量)
        
        对于 nA → mB 反应:
        - 1/[A] - 1/[A]0 = k*t
        - [A] = [A]0 / (1 + k*[A]0*t)
        - [B] = ([A]0 - [A]) * m / n
        """
        if self.k_estimated is None:
            return 0.0
        
        # 从反应配置获取系数
        n_reactant = self.config.reaction.get_total_reactant_consumed()
        n_product = self.config.reaction.get_total_product_created()
        
        k = self.k_estimated
        A0 = self.n
        denom = 1 + k * A0 * t
        if denom <= 0:
            return float(A0 * n_product / n_reactant)  # 最大产物数
        A_t = A0 / denom
        B_t = (A0 - A_t) * n_product / n_reactant
        return B_t
    
    def get_visible_particles(self) -> List[Dict[str, Any]]:
        """获取可见粒子（切片内）用于前端渲染，包含能量信息"""
        z_mid = self.box_size / 2
        z_half_thick = self.config.slice_thickness / 2
        
        # 筛选可见粒子（排除已消耗的粒子 type=2）
        z_vals = self.pos[:, 2]
        visible_mask = (np.abs(z_vals - z_mid) <= z_half_thick) & (self.types != 2)
        
        visible_pos = self.pos[visible_mask]
        visible_types = self.types[visible_mask]
        visible_vel = self.vel[visible_mask]
        
        # 计算动能: KE = 0.5 * m * v^2
        # 归一化能量用于亮度映射
        speed_sq = np.sum(visible_vel ** 2, axis=1)
        kinetic_energy = 0.5 * self.mass * speed_sq
        
        # 绝对能量映射：使用固定的能量范围
        # 最高温度 500K 时的 3σ 能量作为最大参考值
        max_temp = 500.0  # 滑块最大温度
        sigma_max = math.sqrt(self.config.boltzmann_k * max_temp / self.mass)
        max_speed = 3 * sigma_max * math.sqrt(3)  # 3σ 三个方向
        max_energy_absolute = 0.5 * self.mass * max_speed ** 2
        
        # 归一化能量到 [0, 1]（绝对映射：相对于最高温度下的最大能量）
        normalized_energy = np.clip(kinetic_energy / max_energy_absolute, 0, 1)
        
        # 转换为前端格式 - 发送归一化坐标 (0-1)
        # TODO: 性能优化 - 建议改为扁平数组 [x, y, type, energy, ...] 以减少 JSON 体积
        particles = []
        
        for i in range(len(visible_pos)):
            particles.append({
                # 归一化坐标 (0-1)，前端根据 canvas 尺寸自行缩放
                "x": float(visible_pos[i, 0] / self.box_size),
                "y": float(visible_pos[i, 1] / self.box_size),
                "type": int(visible_types[i]),
                "energy": float(normalized_energy[i]),  # 归一化能量 [0, 1]
            })
        
        return particles
    
    def get_state(self) -> Dict[str, Any]:
        """获取完整状态"""
        product_count = self.get_product_count()
        reactant_count = self.get_reactant_count()
        
        return {
            "time": self.sim_time,
            "productCount": product_count,
            "reactantCount": reactant_count,
            "theoryValue": self.get_theory_value(self.sim_time),
            "kEstimated": self.k_estimated,
            "particles": self.get_visible_particles(),
        }
    
    def reset(self):
        """重置模拟"""
        self._init_particles()
        self.sim_time = 0.0
        self.k_estimated = None
        self.estimation_data = []


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
    """后台模拟循环"""
    global simulation_running, physics_engine
    
    target_fps = 60
    frame_time = 1.0 / target_fps
    
    while True:
        with simulation_lock:
            if not simulation_running or physics_engine is None:
                time.sleep(0.1)
                continue
            
            # 执行多步物理更新（提高效率）
            steps_per_frame = 2
            for _ in range(steps_per_frame):
                physics_engine.update()
            
            # 获取状态并推送
            state = physics_engine.get_state()
        
        # 推送到所有客户端
        socketio.emit('state_update', state)
        
        time.sleep(frame_time)


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
    print('[Server] Client connected')
    emit('config', runtime_config.to_dict())
    
    # 如果引擎存在，发送当前状态
    if physics_engine is not None:
        emit('state_update', physics_engine.get_state())


@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开"""
    print('[Server] Client disconnected')


@socketio.on('start')
def handle_start():
    """启动模拟"""
    global simulation_running, physics_engine
    
    with simulation_lock:
        if physics_engine is None:
            physics_engine = PhysicsEngineAdapter(runtime_config)
        simulation_running = True
    
    emit('status', {'running': True}, broadcast=True)
    print('[Server] Simulation started')


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
        physics_engine = PhysicsEngineAdapter(runtime_config)
        state = physics_engine.get_state()
    
    emit('status', {'running': False}, broadcast=True)
    emit('state_update', state, broadcast=True)
    print('[Server] Simulation reset')


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
    print("=" * 50)
    print(" 化学反应粒子模拟器 Web 服务")
    print(" http://localhost:5000")
    print("=" * 50)
    
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
