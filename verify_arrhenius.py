import numpy as np
import time
from physics_engine import PhysicsEngine
from config import *

def run_simulation(temp, ea, steps=500):
    # Override constants for test
    # We need to hack the global variables in config or pass them?
    # PhysicsEngine takes constants from config at __init__.
    # But init_particles_numba uses TEMPERATURE global.
    # We might need to monkeypatch config or create a modified PhysicsEngine.
    
    # Actually, PhysicsEngine.__init__ uses constants.
    # But resolve_collisions takes temp as arg.
    # So we can just init one engine and manually force params.
    
    engine = PhysicsEngine() # uses default T=300
    
    # Force params
    engine.temperature = temp
    engine.activation_energy = ea
    # Re-init particles to match new temp velocity distribution
    # We can just scale velocities
    current_temp = 300.0 # Default in config
    scale = np.sqrt(temp / current_temp)
    engine.vel *= scale
    
    # Run simulation
    start_obs = 100
    
    reactants = []
    times = []
    
    dt = DT
    
    for i in range(steps):
        engine.update(dt)
        if i > start_obs:
            reactants.append(engine.n - engine.get_product_count()) # A count
            times.append(i * dt)
            
    return times, reactants

def calculate_k(times, reactants):
    # Second order: 1/[A] = 1/[A]0 + kt
    # Slope of 1/[A] vs t is k.
    
    inv_A = 1.0 / np.array(reactants)
    t = np.array(times)
    
    # Linear regression
    slope, intercept = np.polyfit(t, inv_A, 1)
    return slope

if __name__ == "__main__":
    print("=== Arrhenius Verification ===")
    
    temps = [200, 300, 400, 500]
    ea = 30.0 # From config
    kb = 0.1  # From config
    
    k_values = []
    inv_T_values = []
    
    print(f"Ea = {ea}, Kb = {kb}")
    print(f"{'Temp (K)':<10} | {'1/T':<10} | {'Measured k':<15} | {'Ln(k)':<10}")
    print("-" * 55)
    
    for T in temps:
        times, reactants = run_simulation(T, ea)
        k = calculate_k(times, reactants)
        ln_k = np.log(k)
        inv_T = 1.0 / T
        
        k_values.append(k)
        inv_T_values.append(inv_T)
        
        print(f"{T:<10} | {inv_T:<10.5f} | {k:<15.5e} | {ln_k:<10.5f}")
        
    # Fit Arrhenius: ln(k) = ln(A) - (Ea/Kb) * (1/T)
    # Slope should be -Ea/Kb
    
    slope, intercept = np.polyfit(inv_T_values, np.log(k_values), 1)
    
    measured_Ea = -slope * kb
    pre_exponential_A = np.exp(intercept)
    
    print("-" * 55)
    print(f"Measured Activation Energy (Ea) = {measured_Ea:.4f}")
    print(f"Target Activation Energy      = {ea:.4f}")
    print(f"Error                         = {abs(measured_Ea - ea)/ea * 100:.2f}%")
    print(f"Pre-exponential Factor (A)    = {pre_exponential_A:.4e}")
    
    # Theoretical A according to Hard Sphere?
    # k = 4 * pi * R^2 * v_rel * exp(...) / V
    # A_theory = 4 * pi * R^2 * v_rel_factor / V ?
    # Wait, v_rel depends on T. v_rel ~ sqrt(T).
    # So ln(k) vs 1/T is not perfectly linear, it has a 0.5 * ln(T) term.
    # But for small T range, linear approx is close.
    # The 'Slope' extraction might be slightly affected by sqrt(T).
    # d(ln k)/d(1/T) = -Ea/k - T/2 * ... 
    # Actually ln(k) = C - Ea/kT + 0.5 ln(T).
    # d(ln k)/d(1/T) = -Ea/k - 0.5 T. 
    # So Measured Ea should be slightly different?
    # Let's just trust the fit first.
