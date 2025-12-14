import time
import numpy as np
from physics_engine import PhysicsEngine
from config import *

def test_physics():
    print("Initializing Physics Engine...")
    start_time = time.time()
    physics = PhysicsEngine()
    init_time = time.time() - start_time
    print(f"Initialization took {init_time:.4f}s")
    
    print(f"Particles: {NUM_PARTICLES}")
    print(f"Box Size: {BOX_SIZE}")
    print(f"Initial Product Count: {physics.get_product_count()}")
    
    # Run for 100 steps
    steps = 100
    print(f"\nRunning {steps} steps...")
    
    t0 = time.time()
    for i in range(steps):
        physics.update(DT)
        if i % 20 == 0:
            count = physics.get_product_count()
            print(f"Step {i}: Products = {count}")
            
    total_time = time.time() - t0
    ops_per_sec = steps / total_time
    print(f"\nCompleted {steps} steps in {total_time:.4f}s")
    print(f"SPS (Steps Per Second): {ops_per_sec:.2f}")
    
    if ops_per_sec < 10:
        print("WARNING: Performance is low!")
    else:
        print("Performance looks good.")
        
    final_count = physics.get_product_count()
    print(f"Final Product Count: {final_count}")
    
    # Check bounds
    in_bounds = np.all((physics.pos >= 0) & (physics.pos <= BOX_SIZE))
    # Due to float precision or visual wrapping, strictly 0..Box might be violated slightly before wrap?
    # Our update logic: pos += v*dt; pos = pos % box.
    # % operator always returns [0, box).
    # So it should be strictly in bounds.
    print(f"Particles strictly in bounds: {in_bounds}")
    if not in_bounds:
        print("Min:", np.min(physics.pos))
        print("Max:", np.max(physics.pos))

if __name__ == "__main__":
    test_physics()
