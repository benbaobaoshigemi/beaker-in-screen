import numpy as np
import math
from physics_engine import PhysicsEngine
from config import *

# Monkey patch physics engine to count collisions
# usage: python diagnose_physics.py

# We need to access the internal counter if we add one, 
# but Numba makes it hard to patch compiled functions.
# Instead, we will replicate the collision theory calc and
# comparing it with 'run_simulation' result from verify_arrhenius 
# is indirect.

# I will write a script that runs the engine and prints 
# debug info by modifying the engine code temporarily? 
# No, that's messy.

# I will assume the parameters are correct and calculate 
# Z_theory explicitly here to confirm my hand calc.

def calculate_z_theory():
    N = NUM_PARTICLES
    V = BOX_SIZE ** 3
    R = RADIUS
    T = TEMPERATURE
    M = MASS
    KB = BOLTZMANN_K
    
    sigma = 4 * math.pi * R**2
    v_rel = 4 * math.sqrt(KB * T / (math.pi * M))
    
    # Z_total = 1/2 * (N/V)^2 * sigma * v_rel * V
    # = 1/2 * N^2/V * sigma * v_rel
    
    Z = 0.5 * (N**2 / V) * sigma * v_rel
    
    print(f"--- Theoretical Parameters ---")
    print(f"N: {N}")
    print(f"V: {V}")
    print(f"R: {R} -> Sigma: {sigma:.4f}")
    print(f"T: {T}, M: {M}, KB: {KB} -> v_rel: {v_rel:.4f}")
    print(f"Z_theory (collisions/sec): {Z:.2f}")
    print(f"Z_theory (collisions/step, dt={DT}): {Z * DT:.2f}")
    return Z

if __name__ == "__main__":
    calculate_z_theory()
    
    from physics_engine import PhysicsEngine

    dt_values = [0.05, 0.02, 0.01, 0.005]
    
    print("\n--- dt Sensitivity Analysis ---")
    print(f"{'dt':<10} | {'Measured Z':<15} | {'Theory Z*dt':<15} | {'Ratio':<10}")
    print("-" * 60)
    
    for test_dt in dt_values:
        engine = PhysicsEngine()
        engine.activation_energy = 0.0
        
        steps = int(1.0 / test_dt) # Run for 1 simulation second
        total_reacts = 0
        
        for i in range(steps):
            engine.types.fill(0) 
            engine.update(test_dt)
            total_reacts += engine.get_product_count() // 1 # Each product count is 1 reaction event (types[i]=P)
        
        avg_reacts = total_reacts / steps
        
        # Recalculate theory Z for this dt (Z_per_second * dt)
        z_theory_per_sec = 218.43 # From previous run
        z_theory_step = z_theory_per_sec * test_dt
        
        ratio = avg_reacts / z_theory_step if z_theory_step > 0 else 0
        
        print(f"{test_dt:<10} | {avg_reacts:<15.4f} | {z_theory_step:<15.4f} | {ratio:<10.4f}")
