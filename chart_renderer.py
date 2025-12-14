import pygame
import collections
import math
from config import *

class ChartRenderer:
    def __init__(self):
        self.rect = pygame.Rect(CHART_RECT)
        self.surface = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        self.history = collections.deque(maxlen=CHART_HISTORY_LEN)
        
        # Theory constants
        self.A0 = NUM_PARTICLES
        self.k_estimated = None  # Will be estimated from data
        self.estimation_done = False
        self.estimation_frame_count = 100  # Use first 100 frames to estimate k
        
        # Font
        self.font = pygame.font.SysFont("Arial", 14)
        
    def add_data_point(self, current_time, product_count):
        self.history.append((current_time, product_count))
        
        # Auto-estimate k after collecting enough data
        if not self.estimation_done and len(self.history) >= self.estimation_frame_count:
            self._estimate_k()
            
    def _estimate_k(self):
        """
        从初始数据估算 k 值。
        
        二级反应: -d[A]/dt = k[A]^2
        积分形式: 1/[A] - 1/[A]0 = k*t
        
        所以 k = (1/[A] - 1/[A]0) / t
        
        我们取多个时间点的平均值来估算 k。
        """
        if len(self.history) < 10:
            return
            
        k_values = []
        A0 = self.A0
        
        # Skip the first few points (noisy), use middle portion
        start_idx = 10
        end_idx = min(len(self.history), self.estimation_frame_count)
        
        for i in range(start_idx, end_idx, 5):
            t, P = self.history[i]
            A = A0 - P
            
            if A > 100 and t > 0.01:  # Avoid division issues
                # k = (1/A - 1/A0) / t
                k = (1.0/A - 1.0/A0) / t
                if k > 0:
                    k_values.append(k)
        
        if k_values:
            # Use median for robustness
            k_values.sort()
            self.k_estimated = k_values[len(k_values) // 2]
            self.estimation_done = True
            print(f"[ChartRenderer] Auto-estimated k = {self.k_estimated:.6f}")
        
    def calculate_theory_value(self, t):
        """
        理论曲线: [P] = [A]0 - [A]0 / (1 + k*[A]0*t)
        """
        if self.k_estimated is None:
            return 0
            
        k = self.k_estimated
        A0 = self.A0
        
        denom = 1 + k * A0 * t
        if denom <= 0:
            return A0
        A_t = A0 / denom
        P_t = A0 - A_t
        return P_t

    def render(self, screen):
        # Clear Chart Surface
        self.surface.fill(CHART_BG_COLOR)
        
        # Draw Border
        pygame.draw.rect(self.surface, CHART_BORDER_COLOR, (0, 0, self.rect.width, self.rect.height), 2)
        
        if len(self.history) < 2:
            screen.blit(self.surface, self.rect.topleft)
            return

        # Determine Ranges
        t_current = self.history[-1][0]
        t_start = self.history[0][0]
        time_span = t_current - t_start
        if time_span < 1e-3:
            time_span = 1.0
        
        # Y Axis: 0 to NUM_PARTICLES
        y_max = NUM_PARTICLES
        
        # Coordinate mapping
        def get_chart_pos(t, y):
            rel_t = (t - t_start) / time_span if time_span > 0 else 0
            px = int(rel_t * (self.rect.width - 40)) + 30  # More left padding for axis
            
            rel_y = y / y_max
            py = int((1.0 - rel_y) * (self.rect.height - 40)) + 20  # More top padding
            return (px, py)
            
        # Draw Axes
        origin = get_chart_pos(t_start, 0)
        x_end = get_chart_pos(t_current, 0)
        y_end = get_chart_pos(t_start, y_max)
        
        pygame.draw.line(self.surface, (100, 100, 100), origin, x_end, 1)  # X axis
        pygame.draw.line(self.surface, (100, 100, 100), origin, y_end, 1)  # Y axis
            
        # 1. Experimental Curve (Red Solid)
        points = []
        for t, count in self.history:
            points.append(get_chart_pos(t, count))
            
        if len(points) > 1:
            pygame.draw.lines(self.surface, (255, 80, 80), False, points, 2)
            
        # 2. Theoretical Curve (White/Yellow Dashed)
        if self.k_estimated is not None:
            theory_points = []
            num_samples = 60
            for i in range(num_samples + 1):
                sample_t = t_start + (time_span * i / num_samples)
                theo_y = self.calculate_theory_value(sample_t)
                theory_points.append(get_chart_pos(sample_t, theo_y))
                
            # Draw dashed by alternating segments
            if len(theory_points) > 1:
                for i in range(0, len(theory_points) - 1, 2):
                    p1 = theory_points[i]
                    p2 = theory_points[min(i+1, len(theory_points)-1)]
                    pygame.draw.line(self.surface, (255, 255, 100), p1, p2, 2)
        
        # Labels
        # Title
        title = self.font.render("Products [P] vs Time", True, (200, 200, 200))
        self.surface.blit(title, (self.rect.width // 2 - 60, 3))
        
        # Current count
        current_count = self.history[-1][1]
        count_lbl = self.font.render(f"[P] = {current_count}", True, (255, 80, 80))
        self.surface.blit(count_lbl, (10, self.rect.height - 20))
        
        # K value
        if self.k_estimated is not None:
            k_lbl = self.font.render(f"k = {self.k_estimated:.5f}", True, (255, 255, 100))
            self.surface.blit(k_lbl, (10, self.rect.height - 38))
        else:
            k_lbl = self.font.render("Estimating k...", True, (150, 150, 150))
            self.surface.blit(k_lbl, (10, self.rect.height - 38))
        
        # Legend
        # Experimental
        pygame.draw.line(self.surface, (255, 80, 80), 
                         (self.rect.width - 120, 20), (self.rect.width - 90, 20), 2)
        exp_lbl = self.font.render("Simulation", True, (255, 80, 80))
        self.surface.blit(exp_lbl, (self.rect.width - 85, 13))
        
        # Theory
        pygame.draw.line(self.surface, (255, 255, 100), 
                         (self.rect.width - 120, 38), (self.rect.width - 90, 38), 2)
        theo_lbl = self.font.render("Theory", True, (255, 255, 100))
        self.surface.blit(theo_lbl, (self.rect.width - 85, 31))
        
        # Blit to main screen
        screen.blit(self.surface, self.rect.topleft)
