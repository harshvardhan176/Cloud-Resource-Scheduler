# How to Run This

A complete walkthrough for running the four microservices, written assuming
you've never used Docker before.

---

## Phase 0 — Install the tools (one time, ~30 minutes)

Install **Docker Desktop**:
- Windows / Mac: https://www.docker.com/products/docker-desktop/
- Linux: https://docs.docker.com/engine/install/

After installing, **start Docker Desktop** (it takes ~1 min to boot the
first time). On Windows/Mac you'll see a whale icon in the system tray.

Verify it works — open Command Prompt / Terminal and run:

```bash
docker --version
docker compose version
```

Both should print version numbers. If they error out, Docker Desktop
isn't running yet — open it and wait.

---

## Phase 1 — Run just the Workload Service (Day 1, ~15 minutes)

This is the "hello world" of the project. It runs entirely on your laptop,
needs no AWS account, and proves your environment works.

### Step 1.1: Open a terminal in the unzipped folder

```bash
cd path/to/microservices
ls
```

You should see: `workload-service`, `metrics-collector`, `forecast-client`,
`rl-decision-service`, `docker-compose.yml`, `README.md`, `HOW_TO_RUN.md`.

### Step 1.2: Build the workload service image

```bash
cd workload-service
docker build -t workload-service:dev .
```

The first build takes 1–2 minutes (downloads the Python base image).
You'll see a long stream of output ending in:

```
Successfully tagged workload-service:dev
```

### Step 1.3: Run the container

```bash
docker run --rm -p 5000:5000 workload-service:dev
```

You should see gunicorn starting up:

```
[INFO] Starting gunicorn 21.2.0
[INFO] Listening at: http://0.0.0.0:5000
[INFO] Booting worker with pid: 7
```

**Leave this terminal running.** The service is now live.

### Step 1.4: Test it from a SECOND terminal

Open a new terminal window (don't close the first one) and run:

```bash
curl "http://localhost:5000/health"
curl "http://localhost:5000/process?duration_ms=300"
curl "http://localhost:5000/metrics"
```

You should get JSON responses. Try the same URLs in your browser:
- http://localhost:5000/health
- http://localhost:5000/process?duration_ms=500
- http://localhost:5000/metrics

### Step 1.5: Stop it

Go back to the first terminal and press **Ctrl+C**. The container stops
and is automatically removed (because of the `--rm` flag).

---

## Phase 2 — Build all four images (Day 2, ~15 minutes)

Build each service's image. Run these from the `microservices/` root:

```bash
docker build -t workload-service:dev      ./workload-service
docker build -t metrics-collector:dev     ./metrics-collector
docker build -t forecast-client:dev       ./forecast-client
docker build -t rl-decision-service:dev   ./rl-decision-service
```

The **rl-decision-service build is slow** (5+ minutes) because it pulls
PyTorch. Be patient. After this, all subsequent builds use the cache.

Verify all four images exist:

```bash
docker images | grep -E "workload-service|metrics-collector|forecast-client|rl-decision"
```

You should see four lines.

---

## Phase 3 — Run the full stack with docker compose (Week 2)

> **Important:** This phase needs real AWS resources. The forecast-client
> needs a deployed SageMaker endpoint. The rl-decision-service needs a
> trained `rl-policy.zip` in S3. **Do not attempt this until you've done
> the AWS setup.** If you don't have AWS yet, stop at Phase 2.

### Step 3.1: Set environment variables

On Mac/Linux:

```bash
export AWS_ACCESS_KEY_ID=AKIA...your-key...
export AWS_SECRET_ACCESS_KEY=...your-secret...
export AWS_REGION=ap-south-1
export S3_BUCKET=your-project-bucket
export SAGEMAKER_ENDPOINT=deepar-forecasting-endpoint
export MODEL_S3_BUCKET=your-project-bucket
```

On Windows (PowerShell):

```powershell
$env:AWS_ACCESS_KEY_ID="AKIA..."
$env:AWS_SECRET_ACCESS_KEY="..."
$env:AWS_REGION="ap-south-1"
$env:S3_BUCKET="your-project-bucket"
$env:SAGEMAKER_ENDPOINT="deepar-forecasting-endpoint"
$env:MODEL_S3_BUCKET="your-project-bucket"
```

### Step 3.2: Bring everything up

```bash
docker compose up --build
```

You'll see logs from three services interleaved. Each line is prefixed
with the service name so you can tell what's going on.

The RL service will try to download the model from S3 on startup. If it
fails (e.g. you haven't uploaded one yet), it logs an error but keeps
running with the rule-based fallback — so the demo doesn't break.

### Step 3.3: Test all three from another terminal

```bash
# Workload service (port 5000)
curl "http://localhost:5000/process?duration_ms=200"

# Forecast client (port 5001)
curl -X POST http://localhost:5001/forecast \
  -H "Content-Type: application/json" \
  -d '{"horizon_minutes": 15}'

# RL decision service (port 5002)
curl -X POST http://localhost:5002/decide \
  -H "Content-Type: application/json" \
  -d '{"current_pod_count":3,"current_cpu_pct":65,"recent_request_rate":420,"predicted_request_rate":850}'
```

### Step 3.4: Shut it down

Ctrl+C in the compose terminal, then:

```bash
docker compose down
```

This removes the containers and the network compose created.

---

## Phase 4 — Deploy to Kubernetes / EKS (Week 2–3)

You'll need Kubernetes YAML files for this — they're not in the zip yet.
Once you have them:

```bash
# Push images to ECR
aws ecr get-login-password | docker login --username AWS \
  --password-stdin <your-account>.dkr.ecr.<region>.amazonaws.com

docker tag workload-service:dev <ecr-uri>/workload-service:v1
docker push <ecr-uri>/workload-service:v1
# ... repeat for the other three

# Apply Kubernetes manifests
kubectl apply -f infra/k8s/
```

Ask Claude for the Kubernetes YAMLs when you reach this stage.

---

## Common errors and fixes

| Error | Meaning | Fix |
|---|---|---|
| `Cannot connect to the Docker daemon` | Docker Desktop isn't running | Open Docker Desktop and wait |
| `bind: address already in use` | Port 5000/5001/5002 is busy | Stop whatever's using it, or change the port mapping (e.g. `-p 5005:5000`) |
| Build hangs at "pulling python:3.11-slim" | Slow internet or Docker registry rate limit | Wait. Retry. Try a different network. |
| `docker: 'compose' is not a docker command` | Old Docker version | Update Docker Desktop |
| `Failed to load model at startup` in RL service logs | No `rl-policy.zip` in S3 yet | Expected on first run. Service falls back to rule-based decisions. |
| `ExpiredTokenException` from boto3 | AWS creds expired | Refresh creds, restart the container |
| RL service build takes forever | PyTorch is huge | Normal. First build ~5 min. Cached after that. |

---

## What runs where, summary

| Phase | What runs | Where | When |
|---|---|---|---|
| 1 | 1 service | Your laptop, single container | Day 1 |
| 2 | 4 images built | Your laptop | Day 2 |
| 3 | 3–4 services | Your laptop, docker compose | Week 2, after AWS setup |
| 4 | All services | EKS cluster on AWS | Week 2–3, final deployment |

Don't try to skip phases. Each one teaches something the next one assumes.

---

## What you should do RIGHT NOW

1. Install Docker Desktop and confirm `docker --version` works
2. Do Phase 1 end to end — get the workload service running, hit it with curl
3. Read `workload-service/app/main.py` line by line until you understand it
4. Then do Phase 2 — build the other three images (don't run them yet)
5. Tomorrow: start AWS account setup so Phase 3 isn't blocked

That's enough for one day. The full deployment can wait until you have
AWS resources.
