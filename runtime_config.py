# -*- coding: utf-8 -*-
"""
运行时配置模块
支持热更新参数，预埋多组分和竞争反应接口
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class ReactionConfig:
    """
    单个反应的配置
    
    反应方程格式: n_a * A + n_b * B -> n_c * C + n_d * D
    
    示例:
    - 2A -> B: reactant_coeffs = [2], product_coeffs = [1]
    - A + A -> P + P: reactant_coeffs = [1, 1], product_coeffs = [1, 1]
    """
    # 反应物及其系数
    reactants: List[str] = field(default_factory=lambda: ["A"])
    reactant_coeffs: List[int] = field(default_factory=lambda: [2])  # 2A
    
    # 产物及其系数
    products: List[str] = field(default_factory=lambda: ["B"])
    product_coeffs: List[int] = field(default_factory=lambda: [1])   # -> B
    
    # 活化能
    activation_energy: float = 0.5
    
    def get_equation_string(self) -> str:
        """获取反应方程式字符串"""
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
        """获取反应消耗的总反应物数量"""
        return sum(self.reactant_coeffs)
    
    def get_total_product_created(self) -> int:
        """获取反应生成的总产物数量"""
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
    - 所有可调节参数集中在此类
    - 预埋多组分、竞争反应、热力学参数接口
    - 支持序列化为字典用于前端通信
    """
    
    # 基础物理参数
    temperature: float = 300.0       # 真实单位：开尔文 (200-500K)
    activation_energy: float = 30.0  # 活化能 (1-100)，默认值使反应概率适中
    num_particles: int = 10000
    box_size: float = 40.0
    particle_radius: float = 0.3
    mass: float = 1.0
    
    # 玻尔兹曼常数（模拟单位）
    # 设计：使 Ea/(kB*T) 在用户可调范围内约为 0.1-10
    boltzmann_k: float = 0.1
    
    # 时间步长
    dt: float = 0.02
    
    # 切片显示参数
    slice_thickness: float = 4.0
    
    # ========== 反应配置（解耦） ==========
    # 当前反应
    reaction: ReactionConfig = field(default_factory=ReactionConfig)
    
    # 预埋：多反应支持
    reactions: List[ReactionConfig] = field(default_factory=list)
    
    # 组分列表（预埋多组分）
    components: List[str] = field(default_factory=lambda: ["A", "B"])
    
    # 热力学参数预埋
    delta_h: float = 0.0         # 反应焓变 (kJ/mol)
    delta_s: float = 0.0         # 反应熵变 (J/(mol·K))
    equilibrium_k: Optional[float] = None  # 平衡常数
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典，用于前端通信"""
        return {
            "temperature": self.temperature,
            "activationEnergy": self.activation_energy,
            "numParticles": self.num_particles,
            "boxSize": self.box_size,
            "particleRadius": self.particle_radius,
            "mass": self.mass,
            "dt": self.dt,
            "sliceThickness": self.slice_thickness,
            # 反应配置
            "reaction": self.reaction.to_dict(),
            "components": self.components,
            # 热力学参数
            "deltaH": self.delta_h,
            "deltaS": self.delta_s,
            "equilibriumK": self.equilibrium_k,
        }
    
    def update_from_dict(self, data: Dict[str, Any]) -> None:
        """从字典更新配置"""
        if "temperature" in data:
            self.temperature = float(data["temperature"])
        if "activationEnergy" in data:
            self.activation_energy = float(data["activationEnergy"])
            self.reaction.activation_energy = self.activation_energy
        if "numParticles" in data:
            self.num_particles = int(data["numParticles"])
        if "boxSize" in data:
            self.box_size = float(data["boxSize"])
        if "sliceThickness" in data:
            self.slice_thickness = float(data["sliceThickness"])
        # 热力学参数
        if "deltaH" in data:
            self.delta_h = float(data["deltaH"])
        if "deltaS" in data:
            self.delta_s = float(data["deltaS"])
    
    def clone(self) -> 'RuntimeConfig':
        """创建配置副本"""
        return RuntimeConfig(
            temperature=self.temperature,
            activation_energy=self.activation_energy,
            num_particles=self.num_particles,
            box_size=self.box_size,
            particle_radius=self.particle_radius,
            mass=self.mass,
            boltzmann_k=self.boltzmann_k,
            dt=self.dt,
            slice_thickness=self.slice_thickness,
            reaction=ReactionConfig(
                reactants=self.reaction.reactants.copy(),
                reactant_coeffs=self.reaction.reactant_coeffs.copy(),
                products=self.reaction.products.copy(),
                product_coeffs=self.reaction.product_coeffs.copy(),
                activation_energy=self.reaction.activation_energy,
            ),
            components=self.components.copy(),
            delta_h=self.delta_h,
            delta_s=self.delta_s,
            equilibrium_k=self.equilibrium_k,
        )
