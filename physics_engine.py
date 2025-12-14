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

@njit(parallel=True)
def update_positions_numba(pos, vel, dt, box_size):
    for i in prange(len(pos)):
        pos[i] += vel[i] * dt
        # PBC wrapping
        pos[i] = pos[i] % box_size

@njit
def build_cell_list(pos, n, box_size, cell_divisions):
    # Determine cell size
    cell_size = box_size / cell_divisions
    
    # Head array and Next array (Linked List in flat arrays)
    # head[cell_index] -> returns particle index
    # next_particle[particle_index] -> returns next particle index in chain
    
    num_cells = cell_divisions**3
    head = np.full(num_cells, -1, dtype=np.int32)
    next_particle = np.full(n, -1, dtype=np.int32)
    
    for i in range(n):
        cx = int(pos[i, 0] / cell_size)
        cy = int(pos[i, 1] / cell_size)
        cz = int(pos[i, 2] / cell_size)
        
        # Clamp to be safe (though PBC should handle usually)
        if cx >= cell_divisions: cx = cell_divisions - 1
        if cy >= cell_divisions: cy = cell_divisions - 1
        if cz >= cell_divisions: cz = cell_divisions - 1
        if cx < 0: cx = 0
        if cy < 0: cy = 0
        if cz < 0: cz = 0
        
        cell_idx = cx + cy * cell_divisions + cz * cell_divisions*cell_divisions
        
        # Insert at head
        next_particle[i] = head[cell_idx]
        head[cell_idx] = i
        
    return head, next_particle

@njit
def resolve_collisions(pos, vel, types, head, next_particle, cell_divisions, box_size, dt,
                       ea_forward, ea_reverse, temperature, boltzmann_k, 
                       radius_a, radius_b):
    """
    碰撞处理与可逆反应判定
    
    可逆反应方程: 2A ⇌ 2B
    - 正反应: A + A → B + B (活化能 ea_forward)
    - 逆反应: B + B → A + A (活化能 ea_reverse)
    
    参数:
        ea_forward: 正反应活化能
        ea_reverse: 逆反应活化能
        temperature: 温度
        boltzmann_k: 玻尔兹曼常数
        radius_a: A 粒子半径
        radius_b: B 粒子半径
    """
    cell_size = box_size / cell_divisions
    
    # 预计算温度安全值
    temp_safe = max(temperature, 1.0)
    
    for cx in range(cell_divisions):
        for cy in range(cell_divisions):
            for cz in range(cell_divisions):
                
                cell_idx = cx + cy * cell_divisions + cz * cell_divisions*cell_divisions
                
                i = head[cell_idx]
                while i != -1:
                    
                    # Check neighbors (including self cell)
                    for ox in range(-1, 2):
                        for oy in range(-1, 2):
                            for oz in range(-1, 2):
                                
                                # Wrap neighbor coordinates for PBC logic
                                ncx = (cx + ox + cell_divisions) % cell_divisions
                                ncy = (cy + oy + cell_divisions) % cell_divisions
                                ncz = (cz + oz + cell_divisions) % cell_divisions
                                
                                n_cell_idx = ncx + ncy * cell_divisions + ncz * cell_divisions*cell_divisions
                                
                                j = head[n_cell_idx]
                                while j != -1:
                                    if i < j: # Avoid double check and self-check
                                        
                                        # 获取粒子类型
                                        type_i = types[i]
                                        type_j = types[j]
                                        
                                        # 跳过已消耗的粒子
                                        if type_i == 2 or type_j == 2:
                                            j = next_particle[j]
                                            continue
                                        
                                        # 根据粒子类型选择半径
                                        # A=0, B=1
                                        r_i = radius_a if type_i == 0 else radius_b
                                        r_j = radius_a if type_j == 0 else radius_b
                                        
                                        # 碰撞距离 = 半径之和
                                        collision_dist = r_i + r_j
                                        collision_dist_sq = collision_dist * collision_dist
                                        
                                        dx, dy, dz, dist_sq = get_pbc_dist(pos[i], pos[j], box_size)
                                        
                                        if dist_sq < collision_dist_sq and dist_sq > 1e-9:
                                            dist = math.sqrt(dist_sq)
                                            
                                            # Relative velocity
                                            dvx = vel[i, 0] - vel[j, 0]
                                            dvy = vel[i, 1] - vel[j, 1]
                                            dvz = vel[i, 2] - vel[j, 2]
                                            
                                            # Normal vector
                                            nx = dx / dist
                                            ny = dy / dist
                                            nz = dz / dist
                                            
                                            # Impact speed (projected on normal)
                                            vn = dvx * nx + dvy * ny + dvz * nz
                                            
                                            if vn < 0:
                                                # Kinetic Energy along line of collision
                                                reduced_mass = MASS / 2.0
                                                e_coll = 0.5 * reduced_mass * vn * vn
                                                
                                                # ========== 可逆反应判定 ==========
                                                # 正反应: A + A → B + B
                                                if type_i == TYPE_A and type_j == TYPE_A:
                                                    if e_coll >= ea_forward:
                                                        types[i] = TYPE_P  # A → B
                                                        types[j] = TYPE_P  # A → B
                                                
                                                # 逆反应: B + B → A + A
                                                elif type_i == TYPE_P and type_j == TYPE_P:
                                                    if e_coll >= ea_reverse:
                                                        types[i] = TYPE_A  # B → A
                                                        types[j] = TYPE_A  # B → A
                                                
                                                # A + B 碰撞：仅弹性碰撞，无反应
                                                # (保持原状)
                                                
                                                # Elastic Collision Response (Always bounce)
                                                vel[i, 0] -= vn * nx
                                                vel[i, 1] -= vn * ny
                                                vel[i, 2] -= vn * nz
                                                vel[j, 0] += vn * nx
                                                vel[j, 1] += vn * ny
                                                vel[j, 2] += vn * nz
                                    
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
