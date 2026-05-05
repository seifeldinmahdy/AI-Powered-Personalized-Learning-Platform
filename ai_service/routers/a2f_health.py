"""
Audio2Face Health Router — simple connectivity check for the A2F NIM gRPC endpoint.
"""

import os
import logging
import grpc
from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/a2f",
    tags=["Audio2Face"],
)

A2F_GRPC_HOST = os.getenv("A2F_GRPC_HOST", "localhost")
A2F_GRPC_PORT = int(os.getenv("A2F_GRPC_PORT", "52000"))


@router.get("/health")
async def a2f_health():
    """Check if the Audio2Face-3D NIM gRPC endpoint is reachable."""
    target = f"{A2F_GRPC_HOST}:{A2F_GRPC_PORT}"
    try:
        channel = grpc.insecure_channel(target)
        # Wait up to 2 seconds for channel to become ready
        grpc.channel_ready_future(channel).result(timeout=2)
        channel.close()
        return {
            "status": "connected",
            "connected": True,
            "host": A2F_GRPC_HOST,
            "port": A2F_GRPC_PORT,
        }
    except grpc.FutureTimeoutError:
        return {
            "status": "unavailable",
            "connected": False,
            "host": A2F_GRPC_HOST,
            "port": A2F_GRPC_PORT,
            "error": "Connection timed out (2s)",
        }
    except Exception as e:
        return {
            "status": "error",
            "connected": False,
            "host": A2F_GRPC_HOST,
            "port": A2F_GRPC_PORT,
            "error": str(e),
        }
