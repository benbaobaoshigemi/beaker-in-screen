"""
诊断脚本：分析为什么反应速率是线性而不是二级动力学
"""
import numpy as np
import time
from physics_engine import PhysicsEngine
from config import *

def diagnose():
    print("=== 二级动力学诊断 ===\n")
    
    physics = PhysicsEngine()
    
    # 收集数据
    times = []
    products = []
    reactants = []
    
    total_steps = 500
    sample_interval = 10
    
    print(f"粒子数: {NUM_PARTICLES}")
    print(f"盒子大小: {BOX_SIZE}")
    print(f"活化能: {ACTIVATION_ENERGY}")
    print(f"温度: {TEMPERATURE}")
    print(f"密度 (N/V): {NUM_PARTICLES / BOX_SIZE**3:.4f}")
    print()
    
    sim_time = 0.0
    
    for step in range(total_steps):
        physics.update(DT)
        sim_time += DT
        
        if step % sample_interval == 0:
            p_count = physics.get_product_count()
            a_count = NUM_PARTICLES - p_count
            times.append(sim_time)
            products.append(p_count)
            reactants.append(a_count)
            
    # 分析
    times = np.array(times)
    products = np.array(products)
    reactants = np.array(reactants)
    
    # 计算反应速率 d[P]/dt
    rates = np.diff(products) / np.diff(times)
    mid_times = (times[:-1] + times[1:]) / 2
    mid_reactants = (reactants[:-1] + reactants[1:]) / 2
    
    print("时间 | 产物数 | 反应物数 | 反应速率 d[P]/dt")
    print("-" * 50)
    for i in range(0, len(times), 5):
        if i < len(rates):
            print(f"{times[i]:.2f}  | {products[i]:5d}  | {reactants[i]:5d}   | {rates[i]:.2f}")
        else:
            print(f"{times[i]:.2f}  | {products[i]:5d}  | {reactants[i]:5d}   | --")
    
    print("\n=== 关键分析 ===")
    
    # 理论上：d[P]/dt ∝ [A]^2 (二级反应)
    # 如果是线性增长，说明 d[P]/dt = 常数
    
    # 检查反应速率是否随 [A] 变化
    early_rate = np.mean(rates[:5])
    late_rate = np.mean(rates[-5:])
    
    print(f"早期反应速率 (平均): {early_rate:.2f}")
    print(f"后期反应速率 (平均): {late_rate:.2f}")
    print(f"速率下降比例: {late_rate/early_rate:.2%}")
    
    if late_rate / early_rate > 0.8:
        print("\n⚠️ 问题确认：反应速率几乎恒定，不符合二级动力学！")
        print("   可能原因：活化能太高，反应速率受限于'达到活化能的碰撞数'，")
        print("   而不是'总碰撞数'。高能碰撞频率由温度决定，与浓度关系较弱。")
        print("\n   解决方案：大幅降低活化能，使大部分碰撞都能触发反应。")
    else:
        print("\n✓ 反应速率正在下降，符合二级动力学趋势。")

if __name__ == "__main__":
    diagnose()
