"""Shared local vLLM-backed clients and persistent service management."""

from .client import LocalVLLMClient
from .service import VLLMServiceError, VLLMServiceManager, VLLMServiceStatus

__all__ = ["LocalVLLMClient", "VLLMServiceError", "VLLMServiceManager", "VLLMServiceStatus"]
