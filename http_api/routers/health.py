"""Liveness probe endpoint for orchestrator health checks."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health():
    """Health check."""
    return {"status": "ok"}
