import math

# --- Physics Constants ---
NUM_PARTICLES = 10000
BOX_SIZE = 40.0  # Reduced from 100.0 to increase density for collisions
RADIUS = 0.3     # Slightly smaller radius
MASS = 1.0

# === 阿伦尼乌斯单位系统 ===
# 设计目标：使用户调节温度(200-500K)和活化能(1-100)时，
# 阿伦尼乌斯因子 Ea/(kB*T) 在 0.1 ~ 10 范围内变化，
# 对应反应概率从 ~90% 到 ~0.005%

# 温度控制速度分布 (真实单位：开尔文)
TEMPERATURE = 300.0  # 室温 300K (范围 200-500K)

# 玻尔兹曼常数 (模拟单位)
# 设计：在 T=300K, Ea=30 时，Ea/(kB*T) ≈ 1，反应概率 ≈ 37%
# kB = Ea_typical / (T_typical * factor_typical) = 30 / (300 * 1) = 0.1
BOLTZMANN_K = 0.1

# Arrhenius Parameters
# 活化能范围 1-100
# Ea=10, T=300: Ea/(kB*T) = 10/(0.1*300) = 0.33, P = 72%
# Ea=50, T=300: Ea/(kB*T) = 50/(0.1*300) = 1.67, P = 19%
# Ea=100, T=300: Ea/(kB*T) = 100/(0.1*300) = 3.33, P = 3.6%
# Ea=50, T=500: Ea/(kB*T) = 50/(0.1*500) = 1.0, P = 37%
# Ea=50, T=200: Ea/(kB*T) = 50/(0.1*200) = 2.5, P = 8.2%
ACTIVATION_ENERGY = 30.0  # 默认值，给予适中的反应概率

# Time step
DT = 0.02 # Smaller step for higher density stability

# --- Rendering Constants ---
SCREEN_WIDTH = 1200
SCREEN_HEIGHT = 800
FPS = 60

# Tomography
SLICE_THICKNESS = 4.0  # ~10% of box size
SCALE_FACTOR = 18.0     # Pixels per physics unit (Zoomed in for smaller box)

# Colors (R, G, B)
COLOR_BG = (10, 10, 15)
COLOR_A = (0, 200, 255)   # Cyan
COLOR_P = (255, 50, 50)   # Red

# --- Chart Constants ---
CHART_RECT = (800, 500, 380, 280)  # x, y, w, h
CHART_BG_COLOR = (30, 30, 30, 200) # RGBA with alpha
CHART_BORDER_COLOR = (100, 100, 100)
CHART_HISTORY_LEN = 600 # Frames to keep

# Theoretical Curve
# k_theory is the effective rate constant for the second order reaction
# This needs to be tuned to match the simulation roughly
THEORY_K = 0.0003
