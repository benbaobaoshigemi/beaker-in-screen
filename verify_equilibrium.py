# -*- coding: utf-8 -*-
"""
平衡常数验证脚本

验证模拟达到的平衡态是否与热力学理论预测一致。

对于反应 2A ⇌ B:
  - 正反应（二级碰撞）: 2A → B, Ea_f
  - 逆反应（一级分解）: B → 2A, Ea_r
  
理论平衡常数:
  K = [B]_eq / [A]_eq² ∝ exp(-(Ea_f - Ea_r) / kT)

注意：对于我们的模拟，由于使用粒子数而非浓度:
  K_sim = N_B / (N_A² / V) = N_B * V / N_A²
"""

import numpy as np
import time
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from runtime_config import RuntimeConfig, SubstanceConfig, ReactionConfig
from server import PhysicsEngineAdapter


def run_equilibrium_simulation(config: RuntimeConfig, 
                                max_time: float = 2.0,
                                sample_interval: float = 0.1,
                                equilibration_time: float = 0.5) -> dict:
    """
    运行模拟直到平衡态，收集统计数据
    
    Args:
        config: 运行时配置
        max_time: 最大模拟时间（模拟单位）
        sample_interval: 采样间隔
        equilibration_time: 平衡化时间（采样前的预热时间）
    
    Returns:
        包含平衡态统计的字典
    """
    engine = PhysicsEngineAdapter(config)
    
    samples = []
    dt = config.dt
    steps_per_sample = int(sample_interval / dt)
    
    print(f"运行模拟: max_time={max_time}s, dt={dt}, steps_per_sample={steps_per_sample}")
    
    step = 0
    start_time = time.time()
    
    while engine.sim_time < max_time:
        engine.update()
        step += 1
        
        if step % steps_per_sample == 0:
            # 收集粒子数统计
            n_a = int(np.sum(engine.types == 0))
            n_b = int(np.sum(engine.types == 1))
            
            sample = {
                'time': engine.sim_time,
                'N_A': n_a,
                'N_B': n_b,
                'total': n_a + 2 * n_b  # 守恒量（原子数）
            }
            
            if engine.sim_time >= equilibration_time:
                samples.append(sample)
            
            # 进度输出
            if step % (steps_per_sample * 10) == 0:
                elapsed = time.time() - start_time
                print(f"  t={engine.sim_time:.3f}s, N_A={n_a}, N_B={n_b}, real_time={elapsed:.1f}s")
    
    elapsed = time.time() - start_time
    print(f"模拟完成: {len(samples)} 个样本, 耗时 {elapsed:.1f}s")
    
    return {
        'samples': samples,
        'config': config,
        'V': config.box_size ** 3,
    }


def analyze_equilibrium(result: dict) -> dict:
    """
    分析平衡态统计，计算平衡常数
    """
    samples = result['samples']
    V = result['V']
    config = result['config']
    
    if len(samples) < 5:
        print("警告: 样本数量过少，统计不可靠")
        return None
    
    # 提取数据
    n_a_values = np.array([s['N_A'] for s in samples])
    n_b_values = np.array([s['N_B'] for s in samples])
    
    # 平均值
    n_a_avg = np.mean(n_a_values)
    n_b_avg = np.mean(n_b_values)
    
    # 标准误差
    n_a_sem = np.std(n_a_values) / np.sqrt(len(samples))
    n_b_sem = np.std(n_b_values) / np.sqrt(len(samples))
    
    # 计算模拟平衡常数
    # K_c = [B] / [A]² = (N_B/V) / (N_A/V)² = N_B * V / N_A²
    if n_a_avg > 0:
        K_sim = n_b_avg * V / (n_a_avg ** 2)
    else:
        K_sim = float('inf')
    
    # 理论平衡常数
    # 对于 2A ⇌ B:
    # K = exp(-(Ea_f - Ea_r) / kT)
    # 
    # 但由于二级反应的速率依赖于碰撞频率 Z ∝ [A]²:
    # k_f = Z * exp(-Ea_f/kT) 有浓度依赖
    # k_r = A_r * exp(-Ea_r/kT) 无浓度依赖
    #
    # 在平衡态: k_f * [A]² = k_r * [B]
    # K_c = [B]/[A]² = k_f / k_r
    #
    # 如果我们假设 A_r 是与碰撞频率自洽的，则:
    # K_c ≈ exp(-(Ea_f - Ea_r) / kT)
    
    T = config.temperature
    kB = config.boltzmann_k
    
    # 获取反应参数
    if len(config.reactions) > 0:
        rxn = config.reactions[0]
        Ea_f = rxn.ea_forward
        Ea_r = rxn.ea_reverse
    else:
        Ea_f = 20.0
        Ea_r = 30.0
    
    delta_Ea = Ea_f - Ea_r  # 放热反应 < 0
    K_theory = np.exp(-delta_Ea / (kB * T))
    
    # 计算偏差
    if K_theory > 0:
        relative_error = (K_sim - K_theory) / K_theory * 100
    else:
        relative_error = float('inf')
    
    return {
        'N_A_avg': n_a_avg,
        'N_A_sem': n_a_sem,
        'N_B_avg': n_b_avg,
        'N_B_sem': n_b_sem,
        'K_sim': K_sim,
        'K_theory': K_theory,
        'relative_error': relative_error,
        'T': T,
        'Ea_f': Ea_f,
        'Ea_r': Ea_r,
        'delta_Ea': delta_Ea,
    }


def main():
    print("=" * 60)
    print("平衡常数验证")
    print("=" * 60)
    
    # 创建测试配置
    config = RuntimeConfig()
    config.temperature = 300.0
    config.use_thermostat = True
    config.box_size = 15.0
    config.max_particles = 10000
    
    # 物质配置
    config.substances = [
        SubstanceConfig(id="A", type_id=0, color_hue=0,   radius=0.15, initial_count=4000),
        SubstanceConfig(id="B", type_id=1, color_hue=210, radius=0.15, initial_count=0),
    ]
    
    # 反应配置: 2A ⇌ B
    config.reactions = [
        ReactionConfig(
            equation="2A=B",
            reactant_types=[0, 0],
            product_types=[1],
            ea_forward=20.0,   # 正反应活化能
            ea_reverse=30.0,   # 逆反应活化能 (ΔH = -10, 放热)
        ),
    ]
    
    print(f"\n配置:")
    print(f"  温度 T = {config.temperature} K")
    print(f"  kB = {config.boltzmann_k}")
    print(f"  kT = {config.boltzmann_k * config.temperature}")
    print(f"  盒子尺寸 = {config.box_size}")
    print(f"  体积 V = {config.box_size**3}")
    print(f"  初始 N_A = {config.substances[0].initial_count}")
    print(f"  Ea_f = {config.reactions[0].ea_forward}, Ea_r = {config.reactions[0].ea_reverse}")
    print(f"  ΔEa = {config.reactions[0].ea_forward - config.reactions[0].ea_reverse}")
    
    # 运行模拟
    print(f"\n开始模拟...")
    result = run_equilibrium_simulation(
        config, 
        max_time=3.0,  # 更长时间以确保平衡
        sample_interval=0.05,
        equilibration_time=1.0
    )
    
    # 分析结果
    analysis = analyze_equilibrium(result)
    
    if analysis is None:
        print("分析失败")
        return
    
    print(f"\n" + "=" * 60)
    print("结果分析")
    print("=" * 60)
    print(f"  平均 N_A = {analysis['N_A_avg']:.1f} ± {analysis['N_A_sem']:.1f}")
    print(f"  平均 N_B = {analysis['N_B_avg']:.1f} ± {analysis['N_B_sem']:.1f}")
    print(f"  原子守恒检验: N_A + 2*N_B = {analysis['N_A_avg'] + 2*analysis['N_B_avg']:.1f}")
    print(f"\n平衡常数:")
    print(f"  K_sim    = {analysis['K_sim']:.4e}")
    print(f"  K_theory = {analysis['K_theory']:.4e}")
    print(f"  相对偏差 = {analysis['relative_error']:.1f}%")
    
    # 判定
    print(f"\n" + "=" * 60)
    if abs(analysis['relative_error']) < 50:
        print("✅ 平衡常数在合理范围内（偏差 < 50%）")
    elif abs(analysis['relative_error']) < 100:
        print("⚠️ 平衡常数偏差较大，但在可接受范围内")
    else:
        print("❌ 平衡常数偏差过大，需要检查频率因子自洽性")
    print("=" * 60)


if __name__ == "__main__":
    main()
