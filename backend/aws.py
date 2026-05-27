"""boto3 client factories. All clients are lazy-cached."""
from functools import lru_cache
import boto3
from .config import get_settings


@lru_cache()
def get_dynamodb(region: str | None = None):
    return boto3.resource("dynamodb", region_name=region or get_settings().aws_region)


@lru_cache()
def get_s3(region: str | None = None):
    return boto3.client("s3", region_name=region or get_settings().aws_region)


@lru_cache()
def get_sns(region: str | None = None):
    return boto3.client("sns", region_name=region or get_settings().aws_region)


@lru_cache()
def get_cloudwatch(region: str | None = None):
    return boto3.client("cloudwatch", region_name=region or get_settings().aws_region)


@lru_cache()
def get_cloudwatch_logs(region: str | None = None):
    return boto3.client("logs", region_name=region or get_settings().aws_region)


@lru_cache()
def get_ec2(region: str | None = None):
    return boto3.client("ec2", region_name=region or get_settings().aws_region)
