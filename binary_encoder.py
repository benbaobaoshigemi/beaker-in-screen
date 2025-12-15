# -*- coding: utf-8 -*-
"""
二进制数据编码模块
将粒子数据编码为紧凑的二进制格式，减少网络传输量约90%

格式说明：
- 每个粒子占用6字节
- x: float16 (2字节) - 归一化坐标 [0, 1]
- y: float16 (2字节) - 归一化坐标 [0, 1]
- type: uint8 (1字节) - 粒子类型
- energy: uint8 (1字节) - 归一化能量 [0, 255]

使用方法：
    encoder = BinaryEncoder(box_size=40.0, mass=1.0, boltzmann_k=0.1)
    binary_data = encoder.encode_particles(positions, velocities, types, slice_mask)
"""

import struct
import numpy as np
import math


class BinaryEncoder:
    """
    粒子数据二进制编码器
    
    设计原则：
    - 模块化：独立于服务器逻辑
    - 高效：使用numpy向量化操作
    - 紧凑：每粒子6字节 vs JSON约40字节
    """
    
    # 消息类型常量
    MSG_PARTICLES = 0x01
    MSG_STATE = 0x02
    
    def __init__(self, box_size: float = 40.0, mass: float = 1.0, boltzmann_k: float = 0.1):
        self.box_size = box_size
        self.mass = mass
        self.boltzmann_k = boltzmann_k
        
        # 预计算能量归一化常量
        max_temp = 1000.0
        sigma_max = math.sqrt(boltzmann_k * max_temp / mass)
        max_speed = 3 * sigma_max * math.sqrt(3)
        self._max_energy = 0.5 * mass * max_speed ** 2
        self._box_inv = 1.0 / box_size
    
    def encode_particles(self, 
                         positions: np.ndarray, 
                         velocities: np.ndarray, 
                         types: np.ndarray,
                         visible_mask: np.ndarray = None) -> bytes:
        """
        将粒子数据编码为二进制格式
        
        参数:
            positions: (N, 3) 粒子位置
            velocities: (N, 3) 粒子速度
            types: (N,) 粒子类型
            visible_mask: (N,) 可见粒子掩码，None表示全部
        
        返回:
            bytes: 二进制数据
                   格式: [msg_type(1) + count(4) + particles(count * 6)]
        """
        if visible_mask is not None:
            pos = positions[visible_mask]
            vel = velocities[visible_mask]
            typ = types[visible_mask]
        else:
            pos = positions
            vel = velocities
            typ = types
        
        n = len(pos)
        if n == 0:
            return struct.pack('<BI', self.MSG_PARTICLES, 0)
        
        # 归一化坐标到 [0, 1]
        norm_x = (pos[:, 0] * self._box_inv).astype(np.float16)
        norm_y = (pos[:, 1] * self._box_inv).astype(np.float16)
        
        # 计算归一化能量 [0, 255]
        speed_sq = np.sum(vel ** 2, axis=1)
        kinetic_energy = 0.5 * self.mass * speed_sq
        norm_energy = np.clip(kinetic_energy / self._max_energy * 255, 0, 255).astype(np.uint8)
        
        # 类型转换
        types_u8 = typ.astype(np.uint8)
        
        # 打包数据
        # Header: 消息类型(1) + 粒子数(4)
        header = struct.pack('<BI', self.MSG_PARTICLES, n)
        
        # 交织数据便于前端解包
        # [x0, y0, t0, e0, x1, y1, t1, e1, ...]
        data_array = np.empty(n * 3, dtype=np.float16)  # 临时，实际用混合类型
        
        # 使用memoryview高效打包
        particle_data = bytearray(n * 6)
        for i in range(n):
            offset = i * 6
            struct.pack_into('<eeBB', particle_data, offset,
                             float(norm_x[i]), float(norm_y[i]),
                             types_u8[i], norm_energy[i])
        
        return header + bytes(particle_data)
    
    def encode_state_header(self, 
                            sim_time: float,
                            substance_counts: dict,
                            active_count: int,
                            energy_stats: dict) -> bytes:
        """
        编码状态头部信息（JSON保持兼容性）
        
        粒子数据走二进制通道，元数据仍用JSON
        """
        # 这部分仍然用JSON，因为结构不固定
        import json
        state = {
            "time": sim_time,
            "substanceCounts": substance_counts,
            "activeCount": active_count,
            "energyStats": energy_stats,
        }
        return json.dumps(state).encode('utf-8')


class BinaryDecoder:
    """
    前端使用的二进制解码器（JavaScript版本在前端实现）
    此类用于测试
    """
    
    @staticmethod
    def decode_particles(data: bytes) -> list:
        """解码二进制粒子数据（测试用）"""
        if len(data) < 5:
            return []
        
        msg_type, count = struct.unpack('<BI', data[:5])
        if msg_type != BinaryEncoder.MSG_PARTICLES:
            return []
        
        particles = []
        for i in range(count):
            offset = 5 + i * 6
            x, y, typ, energy = struct.unpack('<eeBB', data[offset:offset+6])
            particles.append({
                'x': float(x),
                'y': float(y),
                'type': int(typ),
                'energy': int(energy) / 255.0
            })
        
        return particles
