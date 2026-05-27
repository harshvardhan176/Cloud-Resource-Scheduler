"""
ML Prediction Service — port 8003.

Wraps the EnsemblePredictor. Exposes:
  POST /ml/predict     — given a history window, return a forecast
  GET  /ml/models      — model metadata for the dashboard
"""
from __future__ import annotations
import logging
import time
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field

from ml_engine.predictor import predictor

logger = logging.getLogger("ml")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s : %(message)s")

PREDICTIONS = Counter("ml_predictions_total", "ML predictions", ["status"])
LATENCY = Histogram("ml_prediction_seconds", "Prediction latency",
                    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1))

app = FastAPI(title="CloudBrain · ML Prediction", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class PredictRequest(BaseModel):
    history: list[float] = Field(..., min_length=5, max_length=600)
    horizon: int = Field(30, ge=1, le=120)
    metric:  Literal["cpu", "memory", "requests"] = "cpu"
    model:   Literal["lstm", "xgboost", "prophet", "ensemble"] = "ensemble"


class Forecast(BaseModel):
    values: list[float]
    confidence: list[float]
    model: str
    mae_estimate: float
    horizon: int
    served_at: float


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "ml-prediction",
            "models_loaded": predictor.loaded_models()}


@app.get("/metrics", include_in_schema=False)
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/ml/predict", response_model=Forecast)
async def predict(req: PredictRequest):
    with LATENCY.time():
        try:
            p = predictor.predict(req.history, horizon=req.horizon)
            PREDICTIONS.labels("ok").inc()
        except Exception as e:
            PREDICTIONS.labels("error").inc()
            raise HTTPException(400, str(e))
    return Forecast(
        values=p.values,
        confidence=p.confidence,
        model=p.used_model,
        mae_estimate=p.mae_estimate,
        horizon=req.horizon,
        served_at=time.time(),
    )


@app.get("/ml/models")
async def list_models():
    """Dashboard reads this to render the model leaderboard."""
    loaded = predictor.loaded_models()
    weights = predictor.weights
    maes    = predictor.mae
    trained = predictor.last_trained

    models = []
    for name in ("lstm", "xgboost", "prophet"):
        models.append({
            "name":         name,
            "loaded":       name in loaded,
            "weight":       weights.get(name),
            "mae":          maes.get(name),
            "last_trained": trained.get(name),
            "active":       False,
        })
    models.append({
        "name":         "ensemble",
        "loaded":       True,
        "weight":       1.0,
        "mae":          maes.get("ensemble"),
        "last_trained": max(trained.values()) if trained else None,
        "active":       True,
    })
    return {"default": "ensemble", "models": models}
