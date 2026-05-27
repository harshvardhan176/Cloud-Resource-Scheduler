"""Shared configuration for all CloudBrain microservices."""
import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Core
    environment: str = "dev"
    log_level: str = "INFO"

    # JWT
    jwt_secret: str = "cloudbrain-dev-secret-change-in-prod"
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60

    # AWS
    aws_region: str = "us-east-1"

    # AWS resource names — Terraform fills these in via env vars
    dynamodb_users_table:    str = "cloudbrain-users"
    dynamodb_decisions_table: str = "cloudbrain-decisions"
    dynamodb_audit_table:    str = "cloudbrain-audit"
    s3_models_bucket:        str = "cloudbrain-models"
    sns_alerts_topic_arn:    str = ""

    # Inter-service URLs
    api_gateway_url:           str = "http://api-gateway:8000"
    auth_service_url:          str = "http://auth-service:8001"
    ml_prediction_service_url: str = "http://ml-prediction-service:8003"
    rl_scheduler_service_url:  str = "http://rl-scheduler-service:8004"
    executor_service_url:      str = "http://executor-service:8005"
    observability_service_url: str = "http://observability-service:8007"
    dashboard_backend_url:     str = "http://dashboard-backend-service:8008"

    # Prometheus (when deployed in cluster)
    prometheus_url: str = "http://prometheus:9090"

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
