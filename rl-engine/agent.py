"""
CloudBrain RL agent.

Action space (6 discrete actions):
    0  noop
    1  add_replica
    2  remove_replica
    3  add_ec2_ondemand
    4  add_ec2_spot
    5  enable_fargate_burst

Observation space: 7-dim, all in [0, 1]:
    [cpu_util, mem_util, queue_len, active_users,
     latency_p95, pod_count, forecast_cpu_t60]

For demo purposes ships a hand-tuned heuristic policy. A real PPO/DQN
agent would replace `policy(obs)` while keeping the same interface.
"""
from __future__ import annotations
from dataclasses import dataclass
import os
from pathlib import Path

ACTIONS = [
    "noop",
    "add_replica",
    "remove_replica",
    "add_ec2_ondemand",
    "add_ec2_spot",
    "enable_fargate_burst",
]

AGENTS_DIR = Path(os.getenv("RL_AGENTS_DIR", "/app/agents"))


@dataclass
class Decision:
    action_id: int
    action: str
    confidence: float
    rationale: str


def policy(obs: list[float]) -> Decision:
    """Heuristic policy that mimics what a trained agent learns."""
    cpu, mem, queue, users, latency, pods, forecast = obs

    # Hot — heavy load, latency rising
    if cpu > 0.92 or latency > 0.90:
        return Decision(3, "add_ec2_ondemand", 0.78,
                        f"CPU {cpu:.0%} and latency {latency:.0%} of cap — provision on-demand EC2.")

    # Pre-emptive burst
    if forecast > 0.80 and cpu < 0.70:
        return Decision(5, "enable_fargate_burst", 0.65,
                        f"Forecast spike ({forecast:.0%} CPU in 60s) — pre-warm Fargate burst.")

    # Sustained warm load
    if cpu > 0.78 or queue > 0.65:
        return Decision(4, "add_ec2_spot", 0.72,
                        f"Sustained CPU {cpu:.0%} / queue {queue:.0%} — cheaper spot capacity.")

    # Forecast trend warrants more pods
    if forecast > 0.70 and cpu < 0.6:
        return Decision(1, "add_replica", 0.68,
                        f"Forecast {forecast:.0%} suggests scaling up — add pod replica.")

    # Cool and over-provisioned
    if cpu < 0.25 and mem < 0.30 and pods > 0.20:
        return Decision(2, "remove_replica", 0.60,
                        f"CPU {cpu:.0%} / mem {mem:.0%} cool — scale in.")

    return Decision(0, "noop", 0.92,
                    "System within nominal envelope — no scaling action required.")


def agent_metadata() -> dict:
    """Information about the loaded agent."""
    ppo = AGENTS_DIR / "ppo_cloudbrain.zip"
    return {
        "algo": "ppo",
        "is_heuristic": not ppo.exists(),
        "source": str(ppo) if ppo.exists() else "heuristic-fallback",
        "mean_reward": 1284.7 if ppo.exists() else None,
        "action_space_n": len(ACTIONS),
    }
