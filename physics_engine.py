import numpy as np
from numba import njit, prange
import math
from config import *

# Type constants
TYPE_A = 0
TYPE_P = 1

@njit
def init_particles_numba(n, box_size, temp_k):
    # Positions: Uniform random
    pos = np.random.rand(n, 3) * box_size
    
    # Velocities: Maxwell-Boltzmann
    # Standard deviation sigma = sqrt(k_B * T / m)
    sigma = math.sqrt(BOLTZMANN_K * temp_k / MASS)
    vel = np.random.normal(0, sigma, (n, 3))
    
    # Subtract mean velocity to remove drift
    v_mean = np.sum(vel, axis=0) / n
    vel -= v_mean
    
    types = np.zeros(n, dtype=np.int32) # All start as A
    
    return pos, vel, types

@njit
def get_pbc_dist(pos_i, pos_j, box_size):
    dx = pos_i[0] - pos_j[0]
    dy = pos_i[1] - pos_j[1]
    dz = pos_i[2] - pos_j[2]
    
    # Minimum image convention
    if dx > box_size * 0.5: dx -= box_size
    elif dx < -box_size * 0.5: dx += box_size
    
    if dy > box_size * 0.5: dy -= box_size
    elif dy < -box_size * 0.5: dy += box_size
    
    if dz > box_size * 0.5: dz -= box_size
    elif dz < -box_size * 0.5: dz += box_size
    
    dist_sq = dx*dx + dy*dy + dz*dz
    return dx, dy, dz, dist_sq

@njit(parallel=True, cache=True)
def update_positions_numba(pos, vel, dt, box_size):
    for i in prange(len(pos)):
        pos[i] += vel[i] * dt
        # PBC wrapping
        pos[i] = pos[i] % box_size


@njit(cache=True)
def apply_thermostat_numba(vel, types, target_temp, mass, boltzmann_k, thermostat_enabled):
    """
    Numba 加速的恒温器
    
    计算当前温度并重标定速度到目标温度。
    仅处理活跃粒子（type >= 0）。
    
    返回: 活跃粒子数
    """
    n = len(types)
    v_sq_sum = 0.0
    n_active = 0
    
    # 计算动能
    for i in range(n):
        if types[i] >= 0:
            v_sq = vel[i, 0]**2 + vel[i, 1]**2 + vel[i, 2]**2
            v_sq_sum += v_sq
            n_active += 1
    
    if n_active == 0:
        return 0
    
    # 计算当前温度 (3D: 3 个自由度)
    current_temp = (mass * v_sq_sum) / (3.0 * n_active * boltzmann_k)
    
    if thermostat_enabled and current_temp > 0:
        # 温和缩放因子 (避免剧烈温度跳变)
        scale = math.sqrt(target_temp / current_temp)
        # 限制缩放范围
        if scale < 0.99:
            scale = 0.99
        elif scale > 1.01:
            scale = 1.01
        
        # 缩放活跃粒子速度
        for i in range(n):
            if types[i] >= 0:
                vel[i, 0] *= scale
                vel[i, 1] *= scale
                vel[i, 2] *= scale
    
    return n_active


@njit(cache=True)
def find_inactive_slot(types, max_particles):
    """查找一个失活粒子槽位用于激活新粒子"""
    for k in range(max_particles):
        if types[k] == -1:
            return k
    return -1  # 无可用槽位


@njit(cache=True)
def process_1body_reactions(types, pos, vel, reactions_1body, 
                            temperature, boltzmann_k, dt, box_size, mass):
    """
    处理一级反应（自发分解）
    
    参数:
        reactions_1body: [reactant, p0, p1, ea, frequency_factor] 数组
    
    物理原理：
        - 速率常数 k = A * exp(-Ea / kT)
        - 每个时间步分解概率 p = k * dt
    """
    n_particles = len(types)
    n_reactions = len(reactions_1body)
    
    if n_reactions == 0:
        return
    
    for i in range(n_particles):
        if types[i] < 0:  # 跳过失活粒子
            continue
        
        for r in range(n_reactions):
            reactant = int(reactions_1body[r, 0])
            p0 = int(reactions_1body[r, 1])
            p1 = int(reactions_1body[r, 2])
            ea = reactions_1body[r, 3]
            freq_factor = reactions_1body[r, 4]
            
            if types[i] == reactant:
                # 计算分解概率（Arrhenius）
                k = freq_factor * math.exp(-ea / (boltzmann_k * temperature))
                prob = k * dt
                
                # 限制概率在合理范围
                if prob > 1.0:
                    prob = 1.0
                
                if np.random.random() < prob:
                    # 发生分解
                    types[i] = p0
                    
                    # 如果有第二个产物，需要激活一个新粒子
                    if p1 >= 0:
                        slot = find_inactive_slot(types, n_particles)
                        if slot >= 0:
                            types[slot] = p1
                            # 复制位置，给予随机速度
                            pos[slot, 0] = pos[i, 0]
                            pos[slot, 1] = pos[i, 1]
                            pos[slot, 2] = pos[i, 2]
                            sigma = math.sqrt(boltzmann_k * temperature / mass)
                            vel[slot, 0] = np.random.normal(0, sigma)
                            vel[slot, 1] = np.random.normal(0, sigma)
                            vel[slot, 2] = np.random.normal(0, sigma)
                    
                    break  # 粒子已反应，跳出反应循环

@njit(cache=True)
def build_cell_list(pos, n, box_size, cell_divisions, types=None, out_head=None, out_next=None):
    """构建 Cell List，可选跳过失活粒子
    
    优化：支持复用预分配的数组，避免每帧重新分配内存
    - out_head: 预分配的 head 数组 (num_cells,)
    - out_next: 预分配的 next_particle 数组 (n,)
    """
    cell_size = box_size / cell_divisions
    num_cells = cell_divisions**3
    
    # 复用或新建数组
    if out_head is not None:
        head = out_head
        head[:] = -1  # 重置
    else:
        head = np.full(num_cells, -1, dtype=np.int32)
    
    if out_next is not None:
        next_particle = out_next
        next_particle[:] = -1  # 重置
    else:
        next_particle = np.full(n, -1, dtype=np.int32)
    
    for i in range(n):
        # 如果提供了 types，跳过失活粒子
        if types is not None and types[i] < 0:
            continue
            
        cx = int(pos[i, 0] / cell_size)
        cy = int(pos[i, 1] / cell_size)
        cz = int(pos[i, 2] / cell_size)
        
        if cx >= cell_divisions: cx = cell_divisions - 1
        if cy >= cell_divisions: cy = cell_divisions - 1
        if cz >= cell_divisions: cz = cell_divisions - 1
        if cx < 0: cx = 0
        if cy < 0: cy = 0
        if cz < 0: cz = 0
        
        cell_idx = cx + cy * cell_divisions + cz * cell_divisions*cell_divisions
        
        next_particle[i] = head[cell_idx]
        head[cell_idx] = i
        
    return head, next_particle


@njit
def resolve_collisions(pos, vel, types, head, next_particle, cell_divisions, box_size, dt,
                       ea_forward, ea_reverse, temperature, boltzmann_k, 
                       radius_a, radius_b):
    """
    碰撞处理与可逆反应判定（兼容旧版接口）
    
    可逆反应方程: 2A ⇌ 2B
    - 正反应: A + A → B + B (活化能 ea_forward)
    - 逆反应: B + B → A + A (活化能 ea_reverse)
    """
    cell_size = box_size / cell_divisions
    temp_safe = max(temperature, 1.0)
    
    for cx in range(cell_divisions):
        for cy in range(cell_divisions):
            for cz in range(cell_divisions):
                
                cell_idx = cx + cy * cell_divisions + cz * cell_divisions*cell_divisions
                
                i = head[cell_idx]
                while i != -1:
                    
                    for ox in range(-1, 2):
                        for oy in range(-1, 2):
                            for oz in range(-1, 2):
                                
                                ncx = (cx + ox + cell_divisions) % cell_divisions
                                ncy = (cy + oy + cell_divisions) % cell_divisions
                                ncz = (cz + oz + cell_divisions) % cell_divisions
                                
                                n_cell_idx = ncx + ncy * cell_divisions + ncz * cell_divisions*cell_divisions
                                
                                j = head[n_cell_idx]
                                while j != -1:
                                    if i < j:
                                        type_i = types[i]
                                        type_j = types[j]
                                        
                                        if type_i == 2 or type_j == 2:
                                            j = next_particle[j]
                                            continue
                                        
                                        r_i = radius_a if type_i == 0 else radius_b
                                        r_j = radius_a if type_j == 0 else radius_b
                                        
                                        collision_dist = r_i + r_j
                                        collision_dist_sq = collision_dist * collision_dist
                                        
                                        dx, dy, dz, dist_sq = get_pbc_dist(pos[i], pos[j], box_size)
                                        
                                        if dist_sq < collision_dist_sq and dist_sq > 1e-9:
                                            dist = math.sqrt(dist_sq)
                                            
                                            dvx = vel[i, 0] - vel[j, 0]
                                            dvy = vel[i, 1] - vel[j, 1]
                                            dvz = vel[i, 2] - vel[j, 2]
                                            
                                            nx = dx / dist
                                            ny = dy / dist
                                            nz = dz / dist
                                            
                                            vn = dvx * nx + dvy * ny + dvz * nz
                                            
                                            if vn < 0:
                                                reduced_mass = MASS / 2.0
                                                e_coll = 0.5 * reduced_mass * vn * vn
                                                
                                                if type_i == TYPE_A and type_j == TYPE_A:
                                                    if e_coll >= ea_forward:
                                                        types[i] = TYPE_P
                                                        types[j] = TYPE_P
                                                
                                                elif type_i == TYPE_P and type_j == TYPE_P:
                                                    if e_coll >= ea_reverse:
                                                        types[i] = TYPE_A
                                                        types[j] = TYPE_A
                                                
                                                vel[i, 0] -= vn * nx
                                                vel[i, 1] -= vn * ny
                                                vel[i, 2] -= vn * nz
                                                vel[j, 0] += vn * nx
                                                vel[j, 1] += vn * ny
                                                vel[j, 2] += vn * nz
                                    
                                    j = next_particle[j]
                    
                    i = next_particle[i]


@njit(parallel=True, cache=True)
def resolve_collisions_generic(pos, vel, types, head, next_particle, cell_divisions, box_size, dt,
                                reactions_2body, radii, temperature, boltzmann_k, mass):
    """
    通用碰撞处理与二级反应判定（并行版本）
    
    使用 prange 并行处理每个 cell，利用多核 CPU 加速。
    由于 i < j 条件确保每对粒子只处理一次，不会产生数据竞争。
    
    参数:
        reactions_2body: 形状 (N, 6) 的数组
            每行: [r0, r1, p0, p1, ea_forward, ea_reverse]
            r0, r1: 反应物类型
            p0, p1: 产物类型 (-1 表示失活)
        radii: 各类型粒子的半径数组
    """
    n_reactions = len(reactions_2body)
    max_type = len(radii) - 1
    reduced_mass = mass / 2.0  # Hoisted constant
    num_cells = cell_divisions * cell_divisions * cell_divisions
    
    # 并行处理每个 cell
    for cell_idx in prange(num_cells):
        # 从扁平索引恢复 3D 坐标
        cx = cell_idx % cell_divisions
        cy = (cell_idx // cell_divisions) % cell_divisions
        cz = cell_idx // (cell_divisions * cell_divisions)
        
        i = head[cell_idx]
        while i != -1:
            
            for ox in range(-1, 2):
                for oy in range(-1, 2):
                    for oz in range(-1, 2):
                        
                        ncx = (cx + ox + cell_divisions) % cell_divisions
                        ncy = (cy + oy + cell_divisions) % cell_divisions
                        ncz = (cz + oz + cell_divisions) % cell_divisions
                        
                        n_cell_idx = ncx + ncy * cell_divisions + ncz * cell_divisions * cell_divisions
                        
                        j = head[n_cell_idx]
                        while j != -1:
                            if i < j:
                                type_i = types[i]
                                type_j = types[j]
                                
                                # 跳过失活或无效类型
                                if type_i < 0 or type_j < 0 or type_i > max_type or type_j > max_type:
                                    j = next_particle[j]
                                    continue
                                
                                r_i = radii[type_i]
                                r_j = radii[type_j]
                                
                                collision_dist = r_i + r_j
                                collision_dist_sq = collision_dist * collision_dist
                                
                                dx, dy, dz, dist_sq = get_pbc_dist(pos[i], pos[j], box_size)
                                
                                if dist_sq < collision_dist_sq and dist_sq > 1e-9:
                                    dist = math.sqrt(dist_sq)
                                    
                                    dvx = vel[i, 0] - vel[j, 0]
                                    dvy = vel[i, 1] - vel[j, 1]
                                    dvz = vel[i, 2] - vel[j, 2]
                                    
                                    nx = dx / dist
                                    ny = dy / dist
                                    nz = dz / dist
                                    
                                    vn = dvx * nx + dvy * ny + dvz * nz
                                    
                                    if vn < 0:  # 接近中
                                        e_coll = 0.5 * reduced_mass * vn * vn
                                        
                                        # 遍历反应列表检查匹配
                                        reacted = False
                                        energy_change = 0.0  # 反应释放/吸收的能量
                                        
                                        for r in range(n_reactions):
                                            r0 = int(reactions_2body[r, 0])
                                            r1 = int(reactions_2body[r, 1])
                                            p0 = int(reactions_2body[r, 2])
                                            p1 = int(reactions_2body[r, 3])
                                            ea_forward = reactions_2body[r, 4]
                                            ea_reverse = reactions_2body[r, 5]
                                            
                                            # 检查是否匹配反应物
                                            matched = False
                                            if (type_i == r0 and type_j == r1) or (type_i == r1 and type_j == r0):
                                                matched = True
                                            
                                            if matched and e_coll >= ea_forward:
                                                # 执行反应
                                                types[i] = p0
                                                types[j] = p1  # 可能是 -1（失活）
                                                reacted = True
                                                
                                                # 计算反应焓 ΔH = Ea_forward - Ea_reverse
                                                # 若 ΔH < 0（放热），释放能量给产物
                                                # 若 ΔH > 0（吸热），从动能中吸收能量
                                                delta_h = ea_forward - ea_reverse
                                                energy_change = -delta_h  # 放热为正
                                                
                                                break
                                        
                                        # 硬球弹性碰撞响应（等质量）
                                        # 交换法向速度分量
                                        vel[i, 0] -= vn * nx
                                        vel[i, 1] -= vn * ny
                                        vel[i, 2] -= vn * nz
                                        vel[j, 0] += vn * nx
                                        vel[j, 1] += vn * ny
                                        vel[j, 2] += vn * nz
                                        
                                        # 如果发生反应，将能量变化分配给两个粒子
                                        # 放热反应：产物获得额外动能，沿法向分离
                                        if reacted and abs(energy_change) > 1e-9:
                                            # 计算额外速度分量
                                            # E = 0.5 * m * v^2 => v = sqrt(2E/m)
                                            # 每个粒子分得一半能量
                                            e_per_particle = abs(energy_change) / 2.0
                                            v_extra = math.sqrt(2.0 * e_per_particle / mass)
                                            
                                            if energy_change > 0:  # 放热，加速分离
                                                vel[i, 0] += v_extra * nx
                                                vel[i, 1] += v_extra * ny
                                                vel[i, 2] += v_extra * nz
                                                vel[j, 0] -= v_extra * nx
                                                vel[j, 1] -= v_extra * ny
                                                vel[j, 2] -= v_extra * nz
                                            else:  # 吸热，减速分离
                                                vel[i, 0] -= v_extra * nx
                                                vel[i, 1] -= v_extra * ny
                                                vel[i, 2] -= v_extra * nz
                                                vel[j, 0] += v_extra * nx
                                                vel[j, 1] += v_extra * ny
                                                vel[j, 2] += v_extra * nz
                                
                            j = next_particle[j]
            
            i = next_particle[i]


class PhysicsEngine:
    """独立运行的物理引擎（用于 Pygame 客户端）"""
    
    def __init__(self):
        self.n = NUM_PARTICLES
        self.box_size = BOX_SIZE
        self.temperature = TEMPERATURE
        self.boltzmann_k = BOLTZMANN_K
        self.activation_energy = ACTIVATION_ENERGY
        self.radius = RADIUS
        
        # Determine cell divisions
        self.cell_divs = int(self.box_size // (self.radius * 3.0))
        if self.cell_divs < 1: self.cell_divs = 1
        
        self.pos, self.vel, self.types = init_particles_numba(self.n, self.box_size, TEMPERATURE)

    def update(self, dt):
        # 1. Update Positions
        update_positions_numba(self.pos, self.vel, dt, self.box_size)
        
        # 2. Build Cell List
        head, next_particle = build_cell_list(self.pos, self.n, self.box_size, self.cell_divs)
        
        # 3. Resolve Collisions & Reactions (阿伦尼乌斯方程)
        resolve_collisions(
            self.pos, self.vel, self.types, 
            head, next_particle, 
            self.cell_divs, self.box_size, dt,
            self.activation_energy,
            self.temperature,
            self.boltzmann_k,
            self.radius
        )


    def get_product_count(self):
        return np.sum(self.types == TYPE_P)
