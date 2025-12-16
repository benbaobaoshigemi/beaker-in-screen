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
    
    Parameters:
        reactions_1body: [reactant, p0, p1, ea, frequency_factor, q_val] array
    
    Physics:
        - Rate constant k = A * exp(-Ea / kT)
        - Probability p = k * dt
        - Energy conservation: E_final = E_initial + Q
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
                
                # 限制概率
                if prob > 1.0: prob = 1.0
                
                if np.random.random() < prob:
                    # 获取反应热 (第6列)
                    q_val = reactions_1body[r, 5]
                    
                    # 能量检查 (对于吸热反应)
                    # 假设 1->2 分解，质量翻倍 (m -> 2m)
                    # 动量守恒要求 v_new = v_old / 2
                    # 能量方程: E_final = E_initial + Q
                    # m(v/2)^2 + m(v/2)^2 + m(dv)^2 = 0.5mv^2 + Q
                    # 0.5mv^2 + m(dv)^2 = 0.5mv^2 + Q
                    # m(dv)^2 = Q
                    # 此处推导显示：如果 v_new = v_old/2，则平动动能耗散一半，正好给分离提供能量？
                    # 让我们重新推导:
                    # Initial: p=mv, E = p^2/2m + Q_in (internal potential converted)
                    # Final: p1+p2=p. E = p1^2/2m + p2^2/2m.
                    # let p1 = p/2 + q, p2 = p/2 - q (q is relative momentum)
                    # E = 2 * (p^2/4 + q^2) / 2m = p^2/4m + q^2/m
                    # Delta E = E_final - E_initial = -p^2/4m + q^2/m
                    # We have energy source Q_val.
                    # So Q_val = Delta E = q^2/m - p^2/4m
                    # q^2/m = Q_val + p^2/4m
                    # separation velocity dv = q/m
                    # m dv^2 = Q_val + 0.25 m v^2
                    # dv = sqrt(Q_val/m + 0.25 v^2)
                    
                    v_sq = vel[i, 0]**2 + vel[i, 1]**2 + vel[i, 2]**2
                    energy_budget = q_val/mass + 0.25*v_sq
                    
                    if energy_budget < 0:
                        # 能量不足以发生反应（吸热太多且动能不足）
                        continue
                        
                    delta_v = math.sqrt(energy_budget)
                    
                    # 生成随机分离方向
                    theta = np.random.random() * 2 * np.pi
                    phi = np.random.random() * np.pi
                    dx = math.sin(phi) * math.cos(theta)
                    dy = math.sin(phi) * math.sin(theta)
                    dz = math.cos(phi)
                    
                    # 基础速度 (动量守恒 v_base = v / 2)
                    vx_base = vel[i, 0] * 0.5
                    vy_base = vel[i, 1] * 0.5
                    vz_base = vel[i, 2] * 0.5
                    
                    # 更新粒子 i
                    types[i] = p0
                    vel[i, 0] = vx_base + dx * delta_v
                    vel[i, 1] = vy_base + dy * delta_v
                    vel[i, 2] = vz_base + dz * delta_v
                    
                    # 如果有第二个产物
                    if p1 >= 0:
                        slot = find_inactive_slot(types, n_particles)
                        if slot >= 0:
                            types[slot] = p1
                            # 相同位置
                            pos[slot, 0] = pos[i, 0]
                            pos[slot, 1] = pos[i, 1]
                            pos[slot, 2] = pos[i, 2]
                            # 反向分离
                            vel[slot, 0] = vx_base - dx * delta_v
                            vel[slot, 1] = vy_base - dy * delta_v
                            vel[slot, 2] = vz_base - dz * delta_v
                    
                    break  # 粒子已反应

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
                                        
                                        # 收集所有匹配且能量足够的反应
                                        # 竞争反应需要按概率选择，而不是先到先得
                                        reacted = False
                                        energy_change = 0.0
                                        n_matched = 0
                                        matched_indices = np.zeros(n_reactions, dtype=np.int32)
                                        matched_weights = np.zeros(n_reactions, dtype=np.float64)
                                        
                                        for r in range(n_reactions):
                                            r0 = int(reactions_2body[r, 0])
                                            r1 = int(reactions_2body[r, 1])
                                            ea_forward = reactions_2body[r, 4]
                                            
                                            # 检查是否匹配反应物
                                            matched = False
                                            if (type_i == r0 and type_j == r1) or (type_i == r1 and type_j == r0):
                                                matched = True
                                            
                                            if matched and e_coll >= ea_forward:
                                                # 记录匹配的反应及其 Boltzmann 权重
                                                # 权重 = exp(-Ea/kT)，Ea 越低权重越大
                                                kT = boltzmann_k * max(temperature, 1.0)
                                                weight = math.exp(-ea_forward / kT)
                                                matched_indices[n_matched] = r
                                                matched_weights[n_matched] = weight
                                                n_matched += 1
                                        
                                        # 如果有匹配的反应，按权重随机选择一个
                                        if n_matched > 0:
                                            # 归一化权重
                                            total_weight = 0.0
                                            for m in range(n_matched):
                                                total_weight += matched_weights[m]
                                            
                                            # 随机选择
                                            rand_val = np.random.random() * total_weight
                                            cumsum = 0.0
                                            selected_r = matched_indices[0]
                                            for m in range(n_matched):
                                                cumsum += matched_weights[m]
                                                if rand_val < cumsum:
                                                    selected_r = matched_indices[m]
                                                    break
                                            
                                            # 执行选中的反应
                                            p0 = int(reactions_2body[selected_r, 2])
                                            p1 = int(reactions_2body[selected_r, 3])
                                            ea_forward = reactions_2body[selected_r, 4]
                                            ea_reverse = reactions_2body[selected_r, 5]
                                            
                                            types[i] = p0
                                            types[j] = p1  # 可能是 -1（失活）
                                            reacted = True
                                            
                                            # 计算反应焓释放的能量 Q = -ΔH = Ea_rev - Ea_fwd
                                            # 注意：Code previously used delta_h = ea_forward - ea_reverse.
                                            # If ea_fwd < ea_rev (exo), delta_h < 0. Energy release > 0.
                                            # We want q_val > 0 for exothermic.
                                            # q_val = ea_reverse - ea_forward
                                            q_val = ea_reverse - ea_forward
                                        
                                        # -------------------------------------------------------------
                                        # 严格的能量动量更新
                                        # -------------------------------------------------------------
                                        
                                        # 如果发生反应，调整相对动能
                                        if reacted:
                                            # 法向相对速度平方 v_n^2
                                            # 碰撞能量 E_coll = 0.5 * mu * vn^2  (vn < 0)
                                            # 新能量 E_new = E_coll + Q_val
                                            # 0.5 * mu * vn_new^2 = 0.5 * mu * vn^2 + Q_val
                                            # vn_new^2 = vn^2 + 2 * Q_val / mu
                                            # mu = m/2 => 2/mu = 4/m
                                            
                                            vn_sq = vn * vn
                                            vn_new_sq = vn_sq + (4.0 * q_val / mass)
                                            
                                            # 理论上应该总是 >= 0，因为我们检查了 E_coll >= Ea_fwd
                                            # 且 E_new = E_coll + (Ea_rev - Ea_fwd) >= Ea_rev >= 0
                                            if vn_new_sq < 0: vn_new_sq = 0.0
                                            
                                            # 反应后总是分离 (vn_new > 0)
                                            vn_new = math.sqrt(vn_new_sq)
                                            
                                            # 速度增量向量
                                            # 原始反弹: dv = -2*vn (goes from vn to -vn)
                                            # 反应反弹: dv = vn_new - vn (goes from vn to vn_new)
                                            # Vector change dV = (vn_new - vn) * n
                                            
                                            # Update velocities
                                            # Impulse apply: v_i += dV * (mu/m_i) = dV * 0.5
                                            #                v_j -= dV * 0.5
                                            
                                            impulse = (vn_new - vn) * 0.5
                                            
                                            vel[i, 0] += impulse * nx
                                            vel[i, 1] += impulse * ny
                                            vel[i, 2] += impulse * nz
                                            vel[j, 0] -= impulse * nx
                                            vel[j, 1] -= impulse * ny
                                            vel[j, 2] -= impulse * nz

                                        else:
                                            # 普通弹性碰撞
                                            # v_n' = -v_n
                                            # change = -v_n - v_n = -2v_n
                                            # impulse = -vn
                                            
                                            impulse = -vn
                                            
                                            vel[i, 0] += impulse * nx
                                            vel[i, 1] += impulse * ny
                                            vel[i, 2] += impulse * nz
                                            vel[j, 0] -= impulse * nx
                                            vel[j, 1] -= impulse * ny
                                            vel[j, 2] -= impulse * nz
                                
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
