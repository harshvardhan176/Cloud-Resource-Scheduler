
# Intelligent Cloud Resource Scheduler — Microservices

> ML/RL-driven auto-scaler for cloud workloads, built on AWS EKS.

[![Python](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![Kubernetes](https://img.shields.io/badge/kubernetes-EKS-326CE5.svg?logo=kubernetes&logoColor=white)](https://aws.amazon.com/eks/)
[![AWS](https://img.shields.io/badge/AWS-SageMaker%20%7C%20Lambda%20%7C%20EKS-FF9900.svg?logo=amazonaws&logoColor=white)](https://aws.amazon.com/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

A cloud-native system that **predicts** future workload and **proactively scales** infrastructure using a reinforcement learning agent. Three small Flask microservices, deployed as Docker containers on Amazon EKS, integrated with 8+ AWS services.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [The Three Microservices](#the-three-microservices)
- [AWS Services Used](#aws-services-used)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Quick Start (Local)](#quick-start-local)
- [Full Deployment (AWS)](#full-deployment-aws)
- [API Reference](#api-reference)
- [Project Structure](#project-structure)
- [Roadmap](#roadmap)
- [Team](#team)
- [License](#license)

---

## Overview

Traditional auto-scaling is **reactive** — it adds capacity only after load has already spiked, leaving users to suffer slow responses while new servers boot up. This project replaces reactive scaling with a **predictive + learned** approach:

1. A **forecasting model** (SageMaker DeepAR) predicts the next 15 minutes of load
2. A **reinforcement learning agent** (DQN, trained offline) decides scaling actions that balance cost vs SLA
3. **AWS Lambda** orchestrates the loop every 5 minutes, scaling Kubernetes pods up or down

The result: capacity expands **before** spikes hit, and contracts when demand falls — saving cost without sacrificing latency.

### Why this matters

| | Default Kubernetes HPA | This project |
|---|---|---|
| Reacts to | Current CPU only | Forecasted demand + current state |
| Decision logic | Threshold rule | Learned RL policy |
| Spike handling | Lags by 30–60s | Pre-scales before spike |
| Cost optimization | None | Built into reward function |

---

## Architecture

```
                                 ┌──────────────────┐
                                 │  EventBridge     │
                                 │  (5-min trigger) │
                                 └────────┬─────────┘
                                          │
                                          ▼
                                 ┌──────────────────┐
                                 │  Lambda          │
                                 │  Orchestrator    │
                                 └─────┬──────┬─────┘
                                       │      │
                  ┌────────────────────┘      └────────────────┐
                  ▼                                            ▼
         ┌─────────────────┐                          ┌─────────────────┐
         │ Forecast Client │ ───► SageMaker DeepAR    │ RL Decision     │
         │ (port 5001)     │      Endpoint            │ (port 5002)     │
         └─────────────────┘                          └────────┬────────┘
                                                               │
                                                               ▼
                                                      Kubernetes API
                                                      (patch replicas)
                                                               │
                                                               ▼
                                              ┌────────────────────────────┐
                                              │ Workload Service           │
                                              │ (1–10 pods, scales)        │
                                              └────────────┬───────────────┘
                                                           │
                                                           ▼
                                                  Application Load Balancer
                                                           │
                                                           ▼
                                                       Locust traffic
```

CloudWatch Container Insights collects pod-level metrics automatically — no custom collector service needed.

---

## The Three Microservices

### 1. Workload Service (`workload/`)

The application being scaled. A Flask app with a `/process` endpoint that simulates work by sleeping for a configurable duration.

- **Port:** 5000
- **Scales:** 1–10 pods, controlled by the RL agent
- **Dependencies:** Flask only

### 2. Forecast Client (`forecast/`)

Wraps the SageMaker DeepAR endpoint. Pulls recent CloudWatch history, formats it, calls SageMaker, returns the prediction.

- **Port:** 5001
- **Scales:** 1 pod (no need for more)
- **Requires:** `SAGEMAKER_ENDPOINT` env var, AWS credentials

### 3. RL Decision Service (`rl-decision/`)

Loads a trained DQN policy from S3 on startup. On `/decide`, runs the policy against the current state and returns a scaling action.

- **Port:** 5002
- **Scales:** 1 pod (single source of truth)
- **Requires:** `MODEL_S3_BUCKET` env var, AWS credentials, `rl-policy.zip` uploaded to S3

---

## AWS Services Used

This project integrates **10 AWS services**, satisfying the requirement of 6–8 services minimum:

| Service | Purpose |
|---|---|
| **EKS** | Managed Kubernetes — runs all three microservices |
| **EC2** | Underlying compute for EKS worker nodes |
| **ECR** | Stores Docker images for the three services |
| **ALB** | Routes external traffic to the workload service |
| **Lambda** | Orchestrates the 5-minute scaling cycle |
| **EventBridge** | Schedules the Lambda invocations |
| **SageMaker** | Trains and serves the DeepAR forecasting model |
| **S3** | Stores RL model artifact and training data |
| **CloudWatch** | Metrics, logs, dashboards (with Container Insights) |
| **IAM** | Permissions for service-to-service AWS access |

---

## Tech Stack

**Languages & Frameworks**
- Python 3.11
- Flask 3.0
- PyTorch 2.2 (CPU)
- stable-baselines3 2.2 (DQN agent)

**Infrastructure**
- Docker
- Kubernetes / Amazon EKS
- AWS Lambda
- Amazon SageMaker (DeepAR built-in algorithm)

**Tools**
- `kubectl`, `eksctl`, AWS CLI
- Locust (load generation)

---

## Prerequisites

To run locally:
- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Python 3.11+ (for tests outside containers)

To deploy on AWS:
- AWS account with admin access
- AWS CLI configured (`aws configure`)
- `kubectl` and `eksctl` installed
- A trained `rl-policy.zip` uploaded to S3
- A deployed SageMaker DeepAR endpoint

---

## Quick Start (Local)

### Run just the Workload Service (no AWS needed)

```bash
cd workload
docker build -t workload .
docker run --rm -p 5000:5000 workload
```

Test it:

```bash
curl http://localhost:5000/health
curl "http://localhost:5000/process?duration_ms=300"
```

### Run all three services together

Requires AWS credentials and pre-existing AWS resources.

```bash
export AWS_ACCESS_KEY_ID=AKIA...
export AWS_SECRET_ACCESS_KEY=...
export AWS_REGION=ap-south-1
export SAGEMAKER_ENDPOINT=deepar-forecasting-endpoint
export MODEL_S3_BUCKET=your-project-bucket

docker compose up --build
```

---

## Full Deployment (AWS)

### 1. Create EKS cluster

```bash
eksctl create cluster \
  --name intelligent-scheduler \
  --region ap-south-1 \
  --nodes 2 \
  --node-type t3.medium
```

### 2. Push images to ECR

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=ap-south-1
ECR=${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com

aws ecr get-login-password --region $REGION | \
  docker login --username AWS --password-stdin $ECR

for service in workload forecast rl-decision; do
  aws ecr create-repository --repository-name $service --region $REGION
  docker build -t $ECR/$service:v1 ./$service
  docker push $ECR/$service:v1
done
```

### 3. Install CloudWatch Container Insights

```bash
ClusterName=intelligent-scheduler
RegionName=ap-south-1
curl https://raw.githubusercontent.com/aws-samples/amazon-cloudwatch-container-insights/latest/k8s-deployment-manifest-templates/deployment-mode/daemonset/container-insights-monitoring/quickstart/cwagent-fluent-bit-quickstart.yaml \
  | sed "s/{{cluster_name}}/${ClusterName}/;s/{{region_name}}/${RegionName}/" \
  | kubectl apply -f -
```

### 4. Deploy services

```bash
kubectl apply -f infra/k8s/
```

(Kubernetes manifests in `infra/k8s/` — see [`infra/`](infra/) for the YAMLs.)

### 5. Set up the Lambda + EventBridge

See [`lambda/README.md`](lambda/) for orchestrator deployment.

---

## API Reference

### Workload Service

| Method | Endpoint | Description |
|---|---|---|
| GET | `/process?duration_ms=200` | Simulate work for N ms |
| GET | `/health` | Liveness check |

**Example:**

```bash
curl "http://workload-svc/process?duration_ms=200"
# {"status":"ok","pod":"workload-7f9d-x8k","processed_in_ms":200}
```

### Forecast Client

| Method | Endpoint | Description |
|---|---|---|
| POST | `/forecast` | Predict request rate over horizon |
| GET | `/health` | Liveness check |

**Example:**

```bash
curl -X POST http://forecast-svc/forecast \
  -H "Content-Type: application/json" \
  -d '{"horizon_minutes": 15}'
# {"predicted_request_rate": 720.4}
```

### RL Decision Service

| Method | Endpoint | Description |
|---|---|---|
| POST | `/decide` | Get scaling decision |
| GET | `/health` | Liveness check |

**Example:**

```bash
curl -X POST http://rl-svc/decide \
  -H "Content-Type: application/json" \
  -d '{
    "current_pod_count": 3,
    "current_cpu_pct": 65,
    "recent_request_rate": 420,
    "predicted_request_rate": 850
  }'
# {"new_pod_count": 5, "delta": 2}
```

---

## Project Structure

```
.
├── workload/               # Service 1: app being scaled
│   ├── app.py
│   ├── requirements.txt
│   └── Dockerfile
├── forecast/               # Service 2: SageMaker wrapper
│   ├── app.py
│   ├── requirements.txt
│   └── Dockerfile
├── rl-decision/            # Service 3: RL policy server
│   ├── app.py
│   ├── requirements.txt
│   └── Dockerfile
├── docker-compose.yml      # Local development
├── infra/                  # Kubernetes manifests (TBD)
├── lambda/                 # Lambda orchestrator (TBD)
├── simulator/              # RL training environment (TBD)
└── README.md
```

---

## Roadmap

- [x] Three microservices (Flask + Docker)
- [x] Local docker-compose setup
- [ ] Kubernetes manifests for EKS
- [ ] RL simulator + training script
- [ ] SageMaker DeepAR training notebook
- [ ] Lambda orchestrator
- [ ] CloudWatch dashboard
- [ ] Comparison experiments (default HPA vs forecast-driven vs RL)
- [ ] Final report

---

## Team

Built as a 3-week semester project for **Cloud Computing**.

| Role | Responsibilities |
|---|---|
| Cloud Infrastructure | EKS, ECR, IAM, networking, Kubernetes manifests, Lambda deployment |
| Microservices + ML | Service code, SageMaker training & deployment, Lambda logic |
| RL & Experiments | Simulator, DQN training, comparison experiments, dashboard |

---

## License

MIT — see [LICENSE](LICENSE) for details.

## Acknowledgments

- [Amazon SageMaker DeepAR](https://docs.aws.amazon.com/sagemaker/latest/dg/deepar.html) for the forecasting model
- [stable-baselines3](https://stable-baselines3.readthedocs.io/) for the RL framework
- [eksctl](https://eksctl.io/) for making EKS cluster creation painless
