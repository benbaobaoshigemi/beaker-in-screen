# -*- coding: utf-8 -*-
"""
运行时配置模块
支持热更新参数，预埋多组分和竞争反应接口
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class ReversibleReactionConfig:
    """
    可逆反应配置
    
    反应方程: 2A ⇌ 2B
    - 正反应: 2A → 2B (活化能 ea_forward)
    - 逆反应: 2B → 2A (活化能 ea_reverse)
    
    设计原则：
    - A 和 B 使用完全对称的碰撞逻辑
    - 便于后期扩展为连续反应 A → B → C
    """
    # A 粒子属性
    radius_a: float = 0.3
    initial_count_a: int = 10000  # 初始全部为 A
    
    # B 粒子属性
    radius_b: float = 0.3
    initial_count_b: int = 0
    
    # 正反应活化能 (2A → 2B)
    ea_forward: float = 30.0
    
    # 逆反应活化能 (2B → 2A)
    ea_reverse: float = 30.0
    
    def get_equation_string(self) -> str:
        """获取反应方程式字符串"""
        return "2A ⇌ 2B"
    
    def get_total_particles(self) -> int:
        """获取总粒子数"""
        return self.initial_count_a + self.initial_count_b
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "radiusA": self.radius_a,
            "radiusB": self.radius_b,
            "initialCountA": self.initial_count_a,
            "initialCountB": self.initial_count_b,
            "eaForward": self.ea_forward,
            "eaReverse": self.ea_reverse,
            "equation": self.get_equation_string(),
        }


# 保留旧的 ReactionConfig 以保持兼容性（后续可删除）
@dataclass
class ReactionConfig:
    """旧版反应配置（保留兼容性）"""
    reactants: List[str] = field(default_factory=lambda: ["A"])
    reactant_coeffs: List[int] = field(default_factory=lambda: [2])
    products: List[str] = field(default_factory=lambda: ["B"])
    product_coeffs: List[int] = field(default_factory=lambda: [1])
    activation_energy: float = 0.5
    
    def get_equation_string(self) -> str:
        reactant_str = " + ".join(
            f"{c if c > 1 else ''}{r}"
            for r, c in zip(self.reactants, self.reactant_coeffs)
        )
        product_str = " + ".join(
            f"{c if c > 1 else ''}{p}"
            for p, c in zip(self.products, self.product_coeffs)
        )
        return f"{reactant_str} → {product_str}"
    
    def get_total_reactant_consumed(self) -> int:
        return sum(self.reactant_coeffs)
    
    def get_total_product_created(self) -> int:
        return sum(self.product_coeffs)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "reactants": self.reactants,
            "reactantCoeffs": self.reactant_coeffs,
            "products": self.products,
            "productCoeffs": self.product_coeffs,
            "activationEnergy": self.activation_energy,
            "equation": self.get_equation_string(),
        }


@dataclass
class RuntimeConfig:
    """
    运行时可配置参数
    
    设计原则：
    - 属性参数（模拟开始后锁定）：半径、初始浓度、活化能
    - 控制参数（运行时可调）：温度
    - 支持序列化为字典用于前端通信
    """
    
    # ========== 控制参数（运行时可调）==========
    temperature: float = 300.0       # 真实单位：开尔文 (200-500K)
    
    # ========== 可逆反应配置（属性参数）==========
    reversible_reaction: ReversibleReactionConfig = field(default_factory=ReversibleReactionConfig)
    
    # ========== 属性锁定标志 ==========
    properties_locked: bool = False
    
    # ========== 系统参数（不可调）==========
    box_size: float = 40.0
    mass: float = 1.0
    boltzmann_k: float = 0.1  # 模拟单位
    dt: float = 0.002
    slice_thickness: float = 4.0
    
    # ========== 半衰期统计（由模拟计算）==========
    half_life_forward: Optional[float] = None  # 正反应半衰期
    half_life_reverse: Optional[float] = None  # 逆反应半衰期
    
    # 保留旧字段以兼容（将被弃用）
    activation_energy: float = 30.0
    num_particles: int = 10000
    particle_radius: float = 0.3
    reaction: ReactionConfig = field(default_factory=ReactionConfig)
    reactions: List[ReactionConfig] = field(default_factory=list)
    components: List[str] = field(default_factory=lambda: ["A", "B"])
    delta_h: float = 0.0
    delta_s: float = 0.0
    equilibrium_k: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典，用于前端通信"""
        return {
            # 控制参数
            "temperature": self.temperature,
            # 可逆反应配置
            "reversibleReaction": self.reversible_reaction.to_dict(),
            # 属性锁定状态
            "propertiesLocked": self.properties_locked,
            # 系统参数
            "boxSize": self.box_size,
            "mass": self.mass,
            "dt": self.dt,
            "sliceThickness": self.slice_thickness,
            # 半衰期
            "halfLifeForward": self.half_life_forward,
            "halfLifeReverse": self.half_life_reverse,
            # 兼容旧版
            "numParticles": self.reversible_reaction.get_total_particles(),
            "particleRadius": self.reversible_reaction.radius_a,
            "activationEnergy": self.reversible_reaction.ea_forward,
            "reaction": self.reaction.to_dict(),
            "components": self.components,
        }
    
    def update_from_dict(self, data: Dict[str, Any]) -> None:
        """从字典更新配置"""
        # 控制参数（始终可更新）
        if "temperature" in data:
            self.temperature = float(data["temperature"])
        
        # 属性参数（仅在未锁定时可更新）
        if not self.properties_locked:
            # 可逆反应参数
            if "radiusA" in data:
                self.reversible_reaction.radius_a = float(data["radiusA"])
            if "radiusB" in data:
                self.reversible_reaction.radius_b = float(data["radiusB"])
            if "initialCountA" in data:
                self.reversible_reaction.initial_count_a = int(data["initialCountA"])
            if "initialCountB" in data:
                self.reversible_reaction.initial_count_b = int(data["initialCountB"])
            if "eaForward" in data:
                self.reversible_reaction.ea_forward = float(data["eaForward"])
            if "eaReverse" in data:
                self.reversible_reaction.ea_reverse = float(data["eaReverse"])
            
            # 兼容旧版
            if "particleRadius" in data:
                self.reversible_reaction.radius_a = float(data["particleRadius"])
                self.reversible_reaction.radius_b = float(data["particleRadius"])
            if "activationEnergy" in data:
                self.reversible_reaction.ea_forward = float(data["activationEnergy"])
        
        # 切片厚度
        if "sliceThickness" in data:
            self.slice_thickness = float(data["sliceThickness"])
    
    def lock_properties(self) -> None:
        """锁定属性参数"""
        self.properties_locked = True
    
    def unlock_properties(self) -> None:
        """解锁属性参数"""
        self.properties_locked = False
    
    def clone(self) -> 'RuntimeConfig':
        """创建配置副本"""
        return RuntimeConfig(
            temperature=self.temperature,
            reversible_reaction=ReversibleReactionConfig(
                radius_a=self.reversible_reaction.radius_a,
                radius_b=self.reversible_reaction.radius_b,
                initial_count_a=self.reversible_reaction.initial_count_a,
                initial_count_b=self.reversible_reaction.initial_count_b,
                ea_forward=self.reversible_reaction.ea_forward,
                ea_reverse=self.reversible_reaction.ea_reverse,
            ),
            properties_locked=self.properties_locked,
            box_size=self.box_size,
            mass=self.mass,
            boltzmann_k=self.boltzmann_k,
            dt=self.dt,
            slice_thickness=self.slice_thickness,
            half_life_forward=self.half_life_forward,
            half_life_reverse=self.half_life_reverse,
            components=self.components.copy(),
        )

