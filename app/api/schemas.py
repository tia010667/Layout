"""Pydantic request/response models for the API."""

from pydantic import BaseModel, Field
from typing import Optional


class ConfigStatusResponse(BaseModel):
    configured: bool
    provider: str
    model: str
    base_url: str = ""


class UploadResponse(BaseModel):
    job_id: str
    template_filename: str
    content_filename: str


class ProcessRequest(BaseModel):
    job_id: str


class ProcessResponse(BaseModel):
    job_id: str
    status: str = "started"


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    retry_count: int = 0
    error: Optional[str] = None
    template_filename: str = ""
    content_filename: str = ""
    coverage_rate: Optional[float] = None
    error_count: Optional[int] = None
    warning_count: Optional[int] = None


class ErrorResponse(BaseModel):
    detail: str
    job_id: Optional[str] = None
