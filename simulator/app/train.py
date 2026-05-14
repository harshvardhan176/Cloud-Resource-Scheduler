import os
from stable_baselines3 import DQN
from env import CloudScalingEnv

def train():
    print("Initializing environment...")
    env = CloudScalingEnv()

    print("Initializing DQN model...")
    model = DQN(
        "MlpPolicy",
        env,
        verbose=1,
        learning_rate=1e-3,
        buffer_size=10000,
        learning_starts=1000,
        batch_size=64,
        tau=1.0,
        gamma=0.99,
        train_freq=4,
        gradient_steps=1,
        target_update_interval=500,
        exploration_fraction=0.1,
        exploration_final_eps=0.05,
    )

    print("Starting training...")
    model.learn(total_timesteps=20000, log_interval=10)

    print("Saving model...")
    model.save("rl-policy")
    print("Model saved as rl-policy.zip")

    # Also move it to a location where rl-decision-service can find it if needed
    # os.rename("rl-policy.zip", "../microservices/rl-decision-service/rl-policy.zip")

if __name__ == "__main__":
    train()
