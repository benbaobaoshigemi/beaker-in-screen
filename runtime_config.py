# -*- coding: utf-8 -*-
"""
运行时配置模块
支持一级/二级反应的通用配置
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import re
import numpy as np


# ============================================================================
# 物质配置
# ============================================================================

@dataclass
class SubstanceConfig:
    """
    物质配置
    
    属性:
        id: 物质标识符 ("A", "B", "C", ...)
        type_id: 内部类型ID (0, 1, 2, ...)
        color_hue: 色相 (0-359)
        radius: 粒子半径
        initial_count: 初始数量
    """
    id: str
    type_id: int
    color_hue: int = 0
    radius: float = 0.15
    initial_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "typeId": self.type_id,
            "colorHue": self.color_hue,
            "radius": self.radius,
            "initialCount": self.initial_count,
        }


# ============================================================================
# 反应配置
# ============================================================================

@dataclass
class ReactionConfig:
    """
    通用反应配置
    
    支持类型:
        - 二级反应（碰撞触发）: 2A→B, A+B→C, 2A→2B, A+B→C+D
        - 一级反应（自发分解）: B→2A, C→A+B
    
    约束:
        - 反应物: 1-2 个粒子
        - 产物: 1-2 个粒子
    """
    equation: str = ""
    reactant_types: List[int] = field(default_factory=list)  # 展开后的类型列表
    product_types: List[int] = field(default_factory=list)
    ea_forward: float = 30.0
    ea_reverse: float = 30.0
    frequency_factor: float = 1.0  # 一级反应的 A 因子（模拟单位）
    
    def get_order(self) -> int:
        """获取反应级数"""
        return len(self.reactant_types)
    
    def is_first_order(self) -> bool:
        """是否为一级反应（自发分解）"""
        return len(self.reactant_types) == 1
    
    def is_second_order(self) -> bool:
        """是否为二级反应（碰撞触发）"""
        return len(self.reactant_types) == 2
    
    def is_valid(self) -> bool:
        """验证反应是否合法"""
        if not (1 <= len(self.reactant_types) <= 2):
            return False
        if not (1 <= len(self.product_types) <= 2):
            return False
        if self.ea_forward < 0 or self.ea_reverse < 0:
            return False
        return True
    
    def get_display_equation(self, substances: List[SubstanceConfig]) -> str:
        """生成显示用的美化反应式"""
        id_map = {s.type_id: s.id for s in substances}
        
        def format_side(type_ids: List[int]) -> str:
            counts = {}
            for t in type_ids:
                counts[t] = counts.get(t, 0) + 1
            terms = []
            for t, c in counts.items():
                name = id_map.get(t, "?")
                if c == 1:
                    terms.append(name)
                else:
                    terms.append(f"{c}{name}")
            return " + ".join(terms)
        
        left = format_side(self.reactant_types)
        right = format_side(self.product_types)
        return f"{left} = {right}"
    
    def to_dict(self, substances: List[SubstanceConfig] = None) -> Dict[str, Any]:
        return {
            "equation": self.equation,
            "displayEquation": self.get_display_equation(substances) if substances else self.equation,
            "reactantTypes": self.reactant_types,
            "productTypes": self.product_types,
            "eaForward": self.ea_forward,
            "eaReverse": self.ea_reverse,
            "frequencyFactor": self.frequency_factor,
            "order": self.get_order(),
            "isValid": self.is_valid(),
        }


def parse_reaction_equation(equation: str, substances: List[SubstanceConfig]) -> Optional[ReactionConfig]:
    """解析反应式字符串，如 "2A=B" 或 "A+B=C" """
    id_to_type = {s.id.upper(): s.type_id for s in substances}
    # 支持多种箭头符号：ASCII (->) 和 Unicode (→, ⇌)
    eq = equation.replace(" ", "").replace("→", "=").replace("⇌", "=").replace("->", "=").upper()
    
    if "=" not in eq:
        return None
    parts = eq.split("=")
    if len(parts) != 2:
        return None
    
    left_str, right_str = parts
    
    def parse_side(side_str: str) -> Optional[List[int]]:
        if not side_str:
            return None
        terms = side_str.split("+")
        result = []
        for term in terms:
            if not term:
                return None
            match = re.match(r'^(\d*)([A-Z]+)$', term)
            if not match:
                return None
            coeff_str, name = match.groups()
            coeff = int(coeff_str) if coeff_str else 1
            if name not in id_to_type:
                return None
            result.extend([id_to_type[name]] * coeff)
        return result
    
    reactant_types = parse_side(left_str)
    product_types = parse_side(right_str)
    
    if reactant_types is None or product_types is None:
        return None
    
    config = ReactionConfig(
        equation=equation,
        reactant_types=reactant_types,
        product_types=product_types,
    )
    return config if config.is_valid() else None


# ============================================================================
# 运行时配置
# ============================================================================

@dataclass
class RuntimeConfig:
    """
    模拟运行时配置
    """
    # 控制参数
    temperature: float = 300.0
    use_thermostat: bool = True  # 是否启用恒温器 (True=恒温, False=绝热)
    
    # 物质配置
    substances: List[SubstanceConfig] = field(default_factory=list)
    
    # 反应配置
    reactions: List[ReactionConfig] = field(default_factory=list)
    
    # 属性锁定
    properties_locked: bool = False
    
    # 系统参数
    box_size: float = 17.5  # 默认值对应滑条 1/4 位置
    box_size_min: float = 10.0  # 最小容器尺寸
    box_size_max: float = 40.0  # 最大容器尺寸
    mass: float = 1.0
    boltzmann_k: float = 0.1
    dt: float = 0.002
    slice_thickness: float = 4.375  # box_size * 0.25
    
    # 粒子管理
    max_particles: int = 20000
    
    # 最大限制
    MAX_SUBSTANCES: int = 5
    MAX_REACTIONS: int = 3
    
    def __post_init__(self):
        if not self.substances:
            self._init_default_substances()
        if not self.reactions:
            self._init_default_reactions()
    
    def _init_default_substances(self):
        """默认物质：A(红), B(蓝)"""
        self.substances = [
            SubstanceConfig(id="A", type_id=0, color_hue=0,   radius=0.15, initial_count=5000),
            SubstanceConfig(id="B", type_id=1, color_hue=210, radius=0.15, initial_count=0),
        ]
    
    def _init_default_reactions(self):
        """默认反应：2A ⇌ B
        
        物理参数设计：
        - kB = 0.1, T = 300K → kT = 30 模拟能量单位
        - Ea_forward = 20 → Ea/kT ≈ 0.67 → 碰撞反应概率约 50%
        - Ea_reverse = 30 → Ea/kT = 1.0 → 碰撞反应概率约 37%
        - ΔH = 20 - 30 = -10（放热10单位）
        
        绝热模式预期：
        - 初始 5000 粒子，约 2500 次正反应完成
        - 总释放能量 ≈ 2500 × 10 = 25000 单位
        - 系统热容 C = 1.5 × N × kB ≈ 750
        - 预期温升 ΔT ≈ 25000 / 750 ≈ 33K（合理范围）
        """
        self.reactions = [
            ReactionConfig(
                equation="2A=B",
                reactant_types=[0, 0],  # 2A
                product_types=[1],       # B
                ea_forward=20.0,   # 正反应活化能（较低，反应容易发生）
                ea_reverse=30.0,   # 逆反应活化能（较高，逆反应困难）
                # ΔH = 20 - 30 = -10（放热反应）
            ),
        ]
    
    def get_total_initial_particles(self) -> int:
        """获取初始活跃粒子数"""
        return sum(s.initial_count for s in self.substances)
    
    def get_substance_by_type(self, type_id: int) -> Optional[SubstanceConfig]:
        for s in self.substances:
            if s.type_id == type_id:
                return s
        return None
    
    def build_radii_array(self) -> np.ndarray:
        """构建各类型粒子的半径数组"""
        radii = np.zeros(self.MAX_SUBSTANCES, dtype=np.float64)
        for s in self.substances:
            if s.type_id < self.MAX_SUBSTANCES:
                radii[s.type_id] = s.radius
        return radii
    
    def compute_collision_frequency(self, radius: float = 0.15, delta_n: int = 0) -> float:
        """
        计算与碰撞模型自洽的频率因子
        
        物理推导（从第一性原理）：
        ============================
        
        【二级反应 2A → B】
        碰撞频率密度（避免重复计数）:
            Z = N_A² × σ × v_rel / (2V)
        
        正反应速率:
            d(N_B)/dt = Z × P(E > Ea_f)
                      = N_A² × σ × v_rel × exp(-Ea_f/kT) / (2V)
        
        【一级逆反应 B → 2A】
        分解速率:
            d(N_B)/dt = -N_B × A × exp(-Ea_r/kT)
        
        【平衡条件】
        正向 = 逆向:
            N_A² × σ × v_rel × exp(-Ea_f/kT) / (2V) = N_B × A × exp(-Ea_r/kT)
        
        整理得平衡常数:
            K = N_B × V / N_A² = (σ × v_rel / 2) × exp(-ΔEa/kT) / A
        
        【热力学约束】
        K = exp(-ΔEa/kT)  (假设 ΔG ≈ ΔH)
        
        【自洽条件】
        A = σ × v_rel / 2
        
        这保证了模拟的平衡常数与热力学一致。
        
        参数:
            radius: 粒子半径
            delta_n: 未使用（保留接口兼容性）
        
        返回:
            频率因子 A [时间⁻¹]
        """
        # 碰撞截面 σ = π(2r)²
        sigma = np.pi * (2 * radius) ** 2
        
        # 平均相对速度（Maxwell-Boltzmann 分布）
        # v_avg = √(8kT/πm), v_rel = √2 × v_avg
        v_avg = np.sqrt(8 * self.boltzmann_k * self.temperature / (np.pi * self.mass))
        v_rel = v_avg * np.sqrt(2)
        
        # 自洽频率因子：A = σ × v_rel / 2
        # 因子 2 来自碰撞对计数（避免 i-j 和 j-i 重复）
        A = sigma * v_rel / 2.0
        
        return A
    
    def build_reactions_2body(self) -> np.ndarray:
        """
        构建二级反应数组（碰撞触发）
        
        每行: [r0, r1, p0, p1, ea_forward, ea_reverse]
        r0, r1: 反应物类型 (r1=-1 如果单反应物)
        p0, p1: 产物类型 (-1 表示失活/无)
        """
        reactions_2 = []
        for rxn in self.reactions:
            if rxn.is_valid() and rxn.is_second_order():
                r0, r1 = rxn.reactant_types[0], rxn.reactant_types[1]
                p0 = rxn.product_types[0] if len(rxn.product_types) > 0 else -1
                p1 = rxn.product_types[1] if len(rxn.product_types) > 1 else -1
                reactions_2.append([r0, r1, p0, p1, rxn.ea_forward, rxn.ea_reverse])
                
                # 自动生成 2级 逆反应 (如 A+B=C+D 或 2A=2B)
                if len(rxn.product_types) == 2:
                    r0_rev, r1_rev = rxn.product_types[0], rxn.product_types[1]
                    p0_rev, p1_rev = rxn.reactant_types[0], rxn.reactant_types[1]
                    # 对于逆反应，交换 EaForward 和 EaReverse
                    reactions_2.append([r0_rev, r1_rev, p0_rev, p1_rev, rxn.ea_reverse, rxn.ea_forward])
        
        if not reactions_2:
            return np.zeros((0, 6), dtype=np.float64)
        return np.array(reactions_2, dtype=np.float64)
    
    def build_reactions_1body(self) -> np.ndarray:
        """
        构建一级反应数组（自发分解）
        
        每行: [reactant, p0, p1, ea, frequency_factor]
        
        对于二级反应的逆反应（如 2A→B 的逆反应 B→2A），
        使用与碰撞模型自洽的频率因子，确保平衡常数正确。
        """
        reactions_1 = []
        
        # 获取典型半径（用于计算碰撞频率）
        typical_radius = 0.15
        if self.substances:
            typical_radius = self.substances[0].radius
        
        for rxn in self.reactions:
            if rxn.is_valid() and rxn.is_first_order():
                r0 = rxn.reactant_types[0]
                p0 = rxn.product_types[0] if len(rxn.product_types) > 0 else -1
                p1 = rxn.product_types[1] if len(rxn.product_types) > 1 else -1
                # 计算反应热 Q = -ΔH = Ea_rev - Ea_fwd
                q_reaction = rxn.ea_reverse - rxn.ea_forward
                
                # 正向反应: A -> B
                reactions_1.append([r0, p0, p1, rxn.ea_forward, rxn.frequency_factor, q_reaction])
                
                # 自动生成逆反应: B -> A (仅当产物单一时)
                if len(rxn.product_types) == 1:
                    # 逆反应热 = -Q
                    reactions_1.append([p0, r0, -1, rxn.ea_reverse, rxn.frequency_factor, -q_reaction])
        
        # 自动生成逆反应（二级反应的一级分解逆反应）
        for rxn in self.reactions:
            if rxn.is_valid() and rxn.is_second_order():
                # 二级反应的逆反应可能是一级分解
                # 如 2A→B 的逆反应 B→2A 是一级反应
                if len(rxn.product_types) == 1:
                    # 产物单一，逆反应是一级分解
                    r0 = rxn.product_types[0]
                    p0 = rxn.reactant_types[0]
                    p1 = rxn.reactant_types[1] if len(rxn.reactant_types) > 1 else -1
                    
                    # 计算粒子数变化 delta_n = n_产物 - n_反应物
                    # 对于 B → 2A：n_产物 = 2, n_反应物 = 1, delta_n = +1
                    n_products = len(rxn.reactant_types)  # 逆反应的产物是正反应的反应物
                    n_reactants = len(rxn.product_types)  # 逆反应的反应物是正反应的产物
                    delta_n = n_products - n_reactants
                    
                    # 使用自洽的频率因子（包含熵修正），确保平衡常数正确
                    collision_freq = self.compute_collision_frequency(typical_radius, delta_n)
                    
                    # 逆反应热 Q_rev = Ea_fwd - Ea_rev (相对于原反应的逆)
                    # 原反应 2A->B: ΔH = Ef - Er. Q = -ΔH = Er - Ef.
                    # 逆反应 B->2A: ΔH' = -ΔH = Er - Ef. Q' = -ΔH' = Ef - Er.
                    q_val = rxn.ea_forward - rxn.ea_reverse
                    
                    reactions_1.append([r0, p0, p1, rxn.ea_reverse, collision_freq, q_val])
        
        if not reactions_1:
            return np.zeros((0, 6), dtype=np.float64)
        return np.array(reactions_1, dtype=np.float64)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "temperature": self.temperature,
            "useThermostat": self.use_thermostat,
            "substances": [s.to_dict() for s in self.substances],
            "reactions": [r.to_dict(self.substances) for r in self.reactions],
            "propertiesLocked": self.properties_locked,
            "boxSize": self.box_size,
            "boxSizeMin": self.box_size_min,
            "boxSizeMax": self.box_size_max,
            "mass": self.mass,
            "dt": self.dt,
            "sliceThickness": self.slice_thickness,
            "maxParticles": self.max_particles,
        }
    
    def update_from_dict(self, data: Dict[str, Any]) -> None:
        if "temperature" in data:
            self.temperature = float(data["temperature"])
        
        if "useThermostat" in data:
            self.use_thermostat = bool(data["useThermostat"])
        
        if not self.properties_locked:
            if "substances" in data:
                self.substances = []
                for i, sd in enumerate(data["substances"][:self.MAX_SUBSTANCES]):
                    self.substances.append(SubstanceConfig(
                        id=sd.get("id", chr(65 + i)),
                        type_id=i,
                        color_hue=sd.get("colorHue", i * 60),
                        radius=sd.get("radius", 0.15),
                        initial_count=sd.get("initialCount", 0),
                    ))
            
            if "reactions" in data:
                self.reactions = []
                for rd in data["reactions"][:self.MAX_REACTIONS]:
                    if "equation" in rd:
                        parsed = parse_reaction_equation(rd["equation"], self.substances)
                        if parsed:
                            parsed.ea_forward = rd.get("eaForward", 30.0)
                            parsed.ea_reverse = rd.get("eaReverse", 30.0)
                            parsed.frequency_factor = rd.get("frequencyFactor", 1.0)
                            self.reactions.append(parsed)
        
        if "sliceThickness" in data:
            self.slice_thickness = float(data["sliceThickness"])
        
        # 容器体积更新（仅在未锁定时允许）
        if not self.properties_locked and "boxSize" in data:
            new_box = float(data["boxSize"])
            # 限制范围
            new_box = max(self.box_size_min, min(self.box_size_max, new_box))
            self.box_size = new_box
            # 自动调节 slice_thickness = 25% of box_size
            self.slice_thickness = new_box * 0.25
    
    def lock_properties(self) -> None:
        self.properties_locked = True
    
    def unlock_properties(self) -> None:
        self.properties_locked = False
