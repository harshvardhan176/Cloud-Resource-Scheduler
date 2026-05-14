import gymnasium as gym
from gymnasium import spaces
import numpy as np

class CloudScalingEnv(gym.Env):
    """
    A simplified cloud scaling environment for RL training.

    State: [current_pods, current_cpu_pct, recent_request_rate, predicted_request_rate]
    Actions: 0: -2, 1: -1, 2: 0, 3: +1, 4: +2 (delta in pods)
    """
    def __init__(self, min_pods=1, max_pods=10, pod_capacity=50):
        super(CloudScalingEnv, self).__init__()

        self.min_pods = min_pods
        self.max_pods = max_pods
        self.pod_capacity = pod_capacity # Each pod handles 50 req/s comfortably

        # Action space: index into [-2, -1, 0, 1, 2]
        self.action_space = spaces.Discrete(5)
        self.actions = [-2, -1, 0, 1, 2]

        # Observation space: [pods, cpu, rate, pred]
        # We'll use normalized or at least bounded values
        self.observation_space = spaces.Box(
            low=np.array([min_pods, 0, 0, 0]),
            high=np.array([max_pods, 200, 1000, 1000]),
            dtype=np.float32
        )

        self.state = None
        self.steps = 0
        self.max_steps = 100 # per episode

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)

        current_pods = np.random.randint(self.min_pods, self.max_pods + 1)
        rate = np.random.uniform(10, 500)
        cpu = (rate / (current_pods * self.pod_capacity)) * 100
        pred = rate + np.random.uniform(-20, 50)

        self.state = np.array([current_pods, cpu, rate, pred], dtype=np.float32)
        self.steps = 0

        return self.state, {}

    def step(self, action_idx):
        delta = self.actions[action_idx]
        current_pods, current_cpu, recent_rate, _ = self.state

        # 1. Apply Action
        new_pods = np.clip(current_pods + delta, self.min_pods, self.max_pods)

        # 2. Simulate next time step workload
        # Workload follows a random walk with some daily-like cycle or just random spikes
        next_rate = recent_rate + np.random.uniform(-50, 50)
        next_rate = np.clip(next_rate, 0, 800)

        # 3. Compute new CPU and predicted rate
        next_cpu = (next_rate / (new_pods * self.pod_capacity)) * 100
        next_pred = next_rate + np.random.uniform(-30, 60) # Forecasting is imperfect

        # 4. Calculate Reward
        # Reward = -Cost - Penalty(SLA Violation)
        cost = new_pods * 0.1 # Each pod costs something

        sla_penalty = 0
        if next_cpu > 90:
            sla_penalty = (next_cpu - 90) * 0.5 # Heavy penalty for overload
        elif next_cpu < 20:
            sla_penalty = (20 - next_cpu) * 0.05 # Smaller penalty for under-utilization

        reward = -(cost + sla_penalty)

        self.state = np.array([new_pods, next_cpu, next_rate, next_pred], dtype=np.float32)
        self.steps += 1

        done = self.steps >= self.max_steps
        truncated = False

        return self.state, reward, done, truncated, {}

    def render(self):
        print(f"Step {self.steps}: Pods={self.state[0]}, CPU={self.state[1]:.1f}%, Rate={self.state[2]:.1f}, Reward={self.reward:.2f}")
