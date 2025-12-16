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
    process_1body_reactions,
    apply_thermostat_numba
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
        
        # DEBUG: 打印反应数组
        print(f'[PhysicsEngine] 2-body reactions: {self.reactions_2body}')
        print(f'[PhysicsEngine] 1-body reactions: {self.reactions_1body}')
        
        # Cell 划分
        max_radius = max(self.radii) if len(self.radii) > 0 and max(self.radii) > 0 else 0.15
        self.cell_divs = int(self.box_size // (max_radius * 3.0))
        if self.cell_divs < 1:
            self.cell_divs = 1
        
        # 预分配 Cell List 数组（性能优化：避免每帧重新分配）
        num_cells = self.cell_divs ** 3
        self._head = np.full(num_cells, -1, dtype=np.int32)
        self._next_particle = np.full(self.max_particles, -1, dtype=np.int32)
        
        # 初始化粒子
        self._init_particles()
        
        # 缓存活跃粒子数（性能优化：避免每帧重新计算）
        self._active_count = self.initial_active
        
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
        """获取活跃粒子数（使用缓存值）"""
        return self._active_count
    
    def _update_active_count(self) -> int:
        """重新计算活跃粒子数并更新缓存"""
        self._active_count = int(np.sum(self.types >= 0))
        return self._active_count
    
    def update(self):
        """执行一步物理更新"""
        dt = self.dt
        box_size = self.box_size
        n_active = self.get_active_count()
        
        if n_active == 0:
            self.sim_time += dt
            return
        
        # 性能监控（累计到类属性）
        if not hasattr(self, '_perf_stats'):
            self._perf_stats = {'thermostat': 0, 'position': 0, 'cell_list': 0, 
                               'collision': 0, 'reaction_1body': 0, 'count': 0}
        
        import time
        
        # 恒温器（使用 Numba 加速版本）
        t0 = time.perf_counter()
        n_active = apply_thermostat_numba(
            self.vel, self.types, 
            self.config.temperature, 
            self.mass, 
            self.config.boltzmann_k,
            self.config.use_thermostat
        )
        t1 = time.perf_counter()
        self._perf_stats['thermostat'] += (t1 - t0) * 1000
        
        # 1. 更新位置（只更新活跃粒子）
        update_positions_numba(self.pos, self.vel, dt, box_size)
        t2 = time.perf_counter()
        self._perf_stats['position'] += (t2 - t1) * 1000
        
        # 2. 构建 Cell List（复用预分配数组）
        head, next_particle = build_cell_list(
            self.pos, self.max_particles, box_size, self.cell_divs, self.types,
            out_head=self._head, out_next=self._next_particle
        )
        t3 = time.perf_counter()
        self._perf_stats['cell_list'] += (t3 - t2) * 1000
        
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
        t4 = time.perf_counter()
        self._perf_stats['collision'] += (t4 - t3) * 1000
        
        # 4. 一级反应（自发分解）
        if len(self.reactions_1body) > 0:
            process_1body_reactions(
                self.types, self.pos, self.vel,
                self.reactions_1body,
                self.config.temperature,
                self.config.boltzmann_k,
                dt, box_size, self.mass
            )
        t5 = time.perf_counter()
        self._perf_stats['reaction_1body'] += (t5 - t4) * 1000
        
        # 更新活跃粒子数缓存（仅在有反应时才需要重新计算）
        if len(self.reactions_2body) > 0 or len(self.reactions_1body) > 0:
            self._update_active_count()
        
        self._perf_stats['count'] += 1
        
        # 每1000步输出一次详细性能报告
        if self._perf_stats['count'] >= 1000:
            total = sum(v for k, v in self._perf_stats.items() if k != 'count')
            print(f"[PHYSICS] 恒温器: {self._perf_stats['thermostat']:.1f}ms | "
                  f"位置: {self._perf_stats['position']:.1f}ms | "
                  f"Cell: {self._perf_stats['cell_list']:.1f}ms | "
                  f"碰撞: {self._perf_stats['collision']:.1f}ms | "
                  f"1级反应: {self._perf_stats['reaction_1body']:.1f}ms | "
                  f"总计: {total:.1f}ms")
            self._perf_stats = {'thermostat': 0, 'position': 0, 'cell_list': 0, 
                               'collision': 0, 'reaction_1body': 0, 'count': 0}
        
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
        # 与前端温度滑条范围对齐，避免高温时 energy 归一化饱和
        max_temp = 1000.0
        sigma_max = math.sqrt(self.config.boltzmann_k * max_temp / self.mass)
        max_speed = 3 * sigma_max * math.sqrt(3)
        max_energy_absolute = 0.5 * self.mass * max_speed ** 2
        
        # 向量化归一化
        normalized_energy = np.clip(kinetic_energy / max_energy_absolute, 0, 1)
        
        # 向量化坐标归一化
        norm_x = visible_pos[:, 0] / self.box_size
        norm_y = visible_pos[:, 1] / self.box_size
        
        # 构建粒子数据（坐标需3位小数避免点阵效应，能量2位足够）
        particles = [
            {"x": round(float(norm_x[i]), 3), "y": round(float(norm_y[i]), 3), 
             "type": int(visible_types[i]), "energy": round(float(normalized_energy[i]), 2)}
            for i in range(n_visible)
        ]
        
        return particles

    def rescale_velocities_to_target_temperature(self) -> None:
        """立即将活跃粒子速度重标定到目标温度（用于临时调温，保证能量/高亮立刻响应）"""
        active_mask = self.types >= 0
        n_active = int(np.sum(active_mask))
        if n_active <= 0:
            return

        v_sq = float(np.sum(self.vel[active_mask] ** 2))
        current_temp = (self.mass * v_sq) / (3 * n_active * self.config.boltzmann_k)
        if current_temp <= 0:
            return

        scale = math.sqrt(self.config.temperature / current_temp)
        # 仅做安全钳制，避免极端数值导致爆炸
        scale = float(np.clip(scale, 0.1, 10.0))
        self.vel[active_mask] *= scale
    
    def get_state(self) -> Dict[str, Any]:
        """获取完整状态"""
        # 统计各物质数量
        substance_counts = {}
        for substance in self.config.substances:
            count = int(np.sum(self.types == substance.type_id))
            substance_counts[substance.id] = count
        # 高能阈值（硬编码但有物理意义）：
        # 以 1000K 参考温度下的“平均动能”对应的归一化能量作为阈值。
        # 这样阈值是常量，但粒子能量分布随温度线性缩放 -> 不同温度高亮数量会明显不同。
        kb = self.config.boltzmann_k
        max_temp = 1000.0
        sigma_max = math.sqrt(kb * max_temp / self.mass)
        max_speed = 3 * sigma_max * math.sqrt(3)
        max_energy_absolute = 0.5 * self.mass * max_speed ** 2

        mean_energy_ref = 1.5 * kb * max_temp
        threshold_norm = float(np.clip(mean_energy_ref / max_energy_absolute, 0.0, 1.0))

        energy_stats = {
            "threshold": round(float(threshold_norm), 6),
            "refTemp": max_temp,
        }
        
        # 计算实时温度（绝热模式下前端需要同步显示）
        current_temperature = self.config.temperature  # 默认值
        n_active = self.get_active_count()
        if n_active > 0:
            active_mask = self.types >= 0
            v_sq_sum = float(np.sum(self.vel[active_mask] ** 2))
            # T = (m * Σv²) / (3 * N * kB)
            current_temperature = (self.mass * v_sq_sum) / (3.0 * n_active * kb)

        return {
            "time": self.sim_time,
            "substanceCounts": substance_counts,
            "activeCount": self.get_active_count(),
            "particles": self.get_visible_particles(),
            "energyStats": energy_stats,
            "currentTemperature": round(current_temperature, 1),
        }
    
    def reset(self):
        """重置模拟"""
        self.reload_config()
        
        # 重新初始化粒子
        self._init_particles()
        self.sim_time = 0.0

    def reload_config(self):
        """重新加载配置（更新反应参数等）"""
        self.reactions_2body = self.config.build_reactions_2body()
        self.reactions_1body = self.config.build_reactions_1body()
        self.radii = self.config.build_radii_array()
        
        # 同步 box_size
        old_box_size = self.box_size
        self.box_size = self.config.box_size
        
        # 重新计算 Cell 划分
        max_radius = max(self.radii) if len(self.radii) > 0 and max(self.radii) > 0 else 0.15
        self.cell_divs = int(self.box_size // (max_radius * 3.0))
        if self.cell_divs < 1:
            self.cell_divs = 1
        
        # 如果 box_size 变化，重新分配 Cell List 数组
        if self.box_size != old_box_size:
            num_cells = self.cell_divs ** 3
            self._head = np.full(num_cells, -1, dtype=np.int32)
            self._next_particle = np.full(self.max_particles, -1, dtype=np.int32)
    
    def update_box_size(self, new_box_size: float):
        """
        热更新容器体积
        缩放粒子位置以适应新盒子尺寸
        """
        old_box_size = self.box_size
        if abs(new_box_size - old_box_size) < 1e-6:
            return
        
        # 缩放粒子位置
        scale = new_box_size / old_box_size
        active_mask = self.types >= 0
        self.pos[active_mask] *= scale
        
        # 更新盒子尺寸
        self.box_size = new_box_size
        
        # 重新计算 Cell 划分
        max_radius = max(self.radii) if len(self.radii) > 0 and max(self.radii) > 0 else 0.15
        self.cell_divs = int(self.box_size // (max_radius * 3.0))
        if self.cell_divs < 1:
            self.cell_divs = 1
        
        # 重新分配 Cell List 数组
        num_cells = self.cell_divs ** 3
        self._head = np.full(num_cells, -1, dtype=np.int32)
        self._next_particle = np.full(self.max_particles, -1, dtype=np.int32)
        
        print(f'[Physics] Box size updated: {old_box_size:.1f} -> {new_box_size:.1f}, cell_divs={self.cell_divs}')


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
    
    # 性能监控
    perf_samples = []
    perf_report_interval = 100  # 每100帧报告一次
    
    while True:
        start_time = time.perf_counter()
        
        with simulation_lock:
            if not simulation_running or physics_engine is None:
                time.sleep(0.1)
                continue
            
            # 1. 物理更新计时
            t_physics_start = time.perf_counter()
            steps_per_frame = 10
            for _ in range(steps_per_frame):
                physics_engine.update()
            t_physics_end = time.perf_counter()
            
            # 2. 状态获取计时
            t_state_start = time.perf_counter()
            state = physics_engine.get_state()
            t_state_end = time.perf_counter()
        
        # 3. 网络推送计时
        t_emit_start = time.perf_counter()
        socketio.emit('state_update', state)
        t_emit_end = time.perf_counter()
        
        # 记录性能数据
        perf_samples.append({
            'physics': (t_physics_end - t_physics_start) * 1000,  # ms
            'state': (t_state_end - t_state_start) * 1000,
            'emit': (t_emit_end - t_emit_start) * 1000,
            'particles': len(state.get('particles', [])),
        })
        
        # 定期输出性能报告
        if len(perf_samples) >= perf_report_interval:
            avg_physics = sum(s['physics'] for s in perf_samples) / len(perf_samples)
            avg_state = sum(s['state'] for s in perf_samples) / len(perf_samples)
            avg_emit = sum(s['emit'] for s in perf_samples) / len(perf_samples)
            avg_particles = sum(s['particles'] for s in perf_samples) / len(perf_samples)
            total = avg_physics + avg_state + avg_emit
            
            print(f"[PERF] 物理: {avg_physics:.2f}ms ({avg_physics/total*100:.0f}%) | "
                  f"状态: {avg_state:.2f}ms ({avg_state/total*100:.0f}%) | "
                  f"推送: {avg_emit:.2f}ms ({avg_emit/total*100:.0f}%) | "
                  f"总计: {total:.2f}ms | 粒子数: {avg_particles:.0f}")
            perf_samples.clear()
        
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
    """客户端断开时关闭服务器
    
    实现前端与后端的绑定：当前端页面关闭时，后端自动退出
    """
    global simulation_running
    
    with simulation_lock:
        simulation_running = False
        
    print('[Server] Client disconnected - 服务器即将关闭')
    
    # 延迟关闭，让响应先发送完成
    import threading
    def shutdown():
        import time
        time.sleep(0.5)
        print('[Server] 服务器已关闭')
        import os
        os._exit(0)
    
    threading.Thread(target=shutdown, daemon=True).start()


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
    """更新运行时配置
    
    快速路径：仅温度更新时不重新加载配置
    """
    global physics_engine
    
    # 检查是否仅为温度更新
    is_temperature_only = list(data.keys()) == ['temperature']
    
    runtime_config.update_from_dict(data)
    
    # 快速路径：仅温度更新
    if is_temperature_only:
        # 温度已经通过 update_from_dict 更新到 runtime_config
        # physics_engine.config 引用了 runtime_config，所以无需额外操作
        if physics_engine is not None:
            with simulation_lock:
                physics_engine.rescale_velocities_to_target_temperature()
        emit('config', runtime_config.to_dict(), broadcast=True)
        print(f'[Server] Temperature updated: {data["temperature"]}K')
        return
    
    # 如果模拟未运行且更新涉及物质/反应配置，重建物理引擎
    should_preview = 'substances' in data or 'reactions' in data
    
    if not simulation_running and should_preview:
        with simulation_lock:
            physics_engine = PhysicsEngineAdapter(runtime_config)
            state = physics_engine.get_state()
            emit('state_update', state, broadcast=True)
    
    # 容器体积更新（热更新，支持预览）
    if 'boxSize' in data and physics_engine is not None:
        with simulation_lock:
            physics_engine.update_box_size(runtime_config.box_size)
            if not simulation_running:
                state = physics_engine.get_state()
                emit('state_update', state, broadcast=True)
    
    # 如果物理引擎已存在，热更新配置参数
    if physics_engine is not None and not is_temperature_only:
        with simulation_lock:
            physics_engine.reload_config()
            
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
    
    # --- 物理引擎预热 (触发 Numba JIT 编译) ---
    try:
        print("[Server] 正在预热物理引擎 (Numba JIT 编译可能需要几秒钟)...")
        # 创建临时引擎
        warmup_engine = PhysicsEngineAdapter(runtime_config)
        # 运行几次物理步，触发 update_physics 及其子函数的编译
        for _ in range(5):
            warmup_engine.update()
        # 触发 get_visible_particles 及相关计算的编译（如果有）
        warmup_engine.get_visible_particles()
        print("[Server] 物理引擎预热完成！启动后将无卡顿。")
    except Exception as e:
        print(f"[Server] 预热警告: {e}")
        import traceback
        traceback.print_exc()
    # ----------------------------------------

    socketio.run(app, host='0.0.0.0', port=PORT, debug=False)
