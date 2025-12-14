import pygame
import numpy as np
import sys
from config import *
from physics_engine import PhysicsEngine, TYPE_A, TYPE_P
from chart_renderer import ChartRenderer

def map_to_screen(x, y):
    # Center the box on screen
    # Box coordinates: 0 to BOX_SIZE
    # Screen center: WIDTH/2, HEIGHT/2
    
    # Offset to center
    centered_x = x - BOX_SIZE / 2
    centered_y = y - BOX_SIZE / 2
    
    # Scale and move to screen center
    screen_x = int(SCREEN_WIDTH / 2 + centered_x * SCALE_FACTOR)
    screen_y = int(SCREEN_HEIGHT / 2 + centered_y * SCALE_FACTOR)
    
    return screen_x, screen_y

def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("3D Arrhenius Tomography Simulator")
    clock = pygame.time.Clock()
    
    # Initialize Subsystems
    physics = PhysicsEngine()
    chart = ChartRenderer()
    
    running = True
    sim_time = 0.0
    
    # Font for stats
    font = pygame.font.SysFont("Consolas", 16)
    
    while running:
        # 1. Event Handling
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                    
        # 2. Physics Update
        physics.update(DT)
        sim_time += DT
        
        # 3. Data Update
        product_count = physics.get_product_count()
        # Only update chart every few frames to save performance usually, 
        # but for smooth curve we can do every frame or every 5.
        chart.add_data_point(sim_time, product_count)
        
        # 4. Rendering
        screen.fill(COLOR_BG)
        
        # --- Tomography Slice Rendering ---
        # Draw Box Boundary (2D Slice)
        box_rect_x, box_rect_y = map_to_screen(0, 0)
        box_rect_w = int(BOX_SIZE * SCALE_FACTOR)
        box_rect_h = int(BOX_SIZE * SCALE_FACTOR)
        pygame.draw.rect(screen, (50, 50, 60), (box_rect_x, box_rect_y, box_rect_w, box_rect_h), 2)
        
        # Get Data
        # We need to access the numpy arrays directly.
        # Physics engine stores them in self.pos, self.types
        # Numba functions modified them in place.
        
        positions = physics.pos
        types = physics.types
        
        # Tomography Filter: Z-slice
        z_mid = BOX_SIZE / 2
        z_half_thick = SLICE_THICKNESS / 2
        
        # Boolean mask for visibility
        # Use simple numpy operations
        # Check Z distance from center (taking PBC into account? 
        # Usually Tomography is just a geometric slice of the box volume. 
        # PBC wraps particles, but the visual slice is usually static in space 0..L)
        
        # Z coordinate is 0..BOX_SIZE.
        # Simple slab check:
        # visible if z_mid - half <= z <= z_mid + half
        
        z_vals = positions[:, 2]
        visible_mask = np.abs(z_vals - z_mid) <= z_half_thick
        
        # Extract visible particles
        visible_pos = positions[visible_mask]
        visible_types = types[visible_mask]
        
        # Render particles
        # Using a loop here. 
        # Visible count ~ 1000. Loop is fine.
        
        for i in range(len(visible_pos)):
            px = visible_pos[i, 0]
            py = visible_pos[i, 1]
            p_type = visible_types[i]
            
            sx, sy = map_to_screen(px, py)
            
            # Draw
            color = COLOR_A if p_type == TYPE_A else COLOR_P
            
            # Size could depend on depth (fake 3D) or just flat
            # To make "appearing/disappearing" smoother, could fade alpha based on z-dist?
            # Pygame alpha blit is slow.
            # Just changing radius slightly?
            dist_from_center = abs(visible_pos[i, 2] - z_mid)
            # radius 1 to 3 pixels?
            # normalized dist 0..1 (1 at edge)
            norm_dist = dist_from_center / z_half_thick
            # size = max(1, int(4 * (1.0 - norm_dist*0.5))) 
            
            pygame.draw.circle(screen, color, (sx, sy), 3)

        # Draw Chart
        chart.render(screen)
        
        # Draw Stats
        fps = clock.get_fps()
        stats_text = f"FPS: {fps:.1f} | N: {NUM_PARTICLES} | Time: {sim_time:.1f}"
        screen.blit(font.render(stats_text, True, (255, 255, 255)), (10, 10))
        
        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()
