# Microservices — Intelligent Cloud Resource Scheduler

Four containerized services that together implement an ML/RL-driven
auto-scaler for an EKS cluster.

```
microservices/
├── workload-service/      Service 1 — fake app being scaled
├── metrics-collector/     Service 2 — ships metrics to CloudWatch + S3
├── forecast-client/       Service 3 — wraps SageMaker DeepAR endpoint
├── rl-decision-service/   Service 4 — runs trained DQN policy
└── docker-compose.yml     Local dev orchestration
```

## Quick start (local)

```bash
# Build a single service
cd workload-service
docker build -t workload-service:dev .
docker run -p 5000:5000 workload-service:dev

# Test it
curl "http://localhost:5000/process?duration_ms=300"
curl http://localhost:5000/metrics
```

## Required environment variables

| Service              | Variable               | Purpose                              |
|----------------------|------------------------|--------------------------------------|
| metrics-collector    | `S3_BUCKET`            | Where to write the CSV history       |
| metrics-collector    | `NAMESPACE`            | Kubernetes namespace (default: default) |
| forecast-client      | `SAGEMAKER_ENDPOINT`   | Name of deployed DeepAR endpoint     |
| rl-decision-service  | `MODEL_S3_BUCKET`      | Bucket containing rl-policy.zip      |
| rl-decision-service  | `MODEL_S3_KEY`         | Object key (default: rl-policy.zip)  |

## API contracts

### Workload Service (port 5000)

```
GET  /process?duration_ms=200    -> {"status":"ok","pod":"...","processed_in_ms":200}
GET  /health                     -> {"status":"healthy"}
GET  /ready                      -> {"status":"ready"}
GET  /metrics                    -> {"request_count":N,"avg_latency_ms":X,"rps":Y,...}
```

### Forecast Client (port 5001)

```
POST /forecast
Body: {"horizon_minutes": 15}
Resp: {"predicted_request_rate": 850.4, "predicted_p90": 1100.2, ...}
```

### RL Decision Service (port 5002)

```
POST /decide
Body: {
  "current_pod_count": 3,
  "current_cpu_pct": 65,
  "recent_request_rate": 420,
  "predicted_request_rate": 850
}
Resp: {"action":"scale_up","new_pod_count":5,"delta":2,"source":"rl"}

POST /reload      -> pull new model from S3
GET  /health      -> liveness
GET  /ready       -> 200 only if model is loaded
```

## Notes on the code

- All services log to stdout (Kubernetes/CloudWatch picks this up).
- Health and ready probes are separate so Kubernetes can distinguish
  "process alive" from "able to serve traffic".
- The RL service has a **rule-based fallback** built in: if the model
  fails to load, it returns sensible decisions based on capacity heuristics.
  This protects your demo from a single point of failure.
- Forecast Client caches predictions for 60s to reduce SageMaker invocations.
- The Metrics Collector uses an `in-cluster` Kubernetes config — it only
  works when running as a pod with a properly configured ServiceAccount.
