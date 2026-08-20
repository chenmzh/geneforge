"""Domain exceptions mapped to HTTP responses by the app error handlers."""
from __future__ import annotations

from typing import Any


class GeneForgeError(Exception):
    status_code = 400
    code = "error"

    def __init__(self, message: str, *, detail: Any | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail
        if code:
            self.code = code

    def to_payload(self) -> dict:
        payload = {"code": self.code, "message": self.message}
        if self.detail is not None:
            payload["detail"] = self.detail
        return payload


class NotFoundError(GeneForgeError):
    status_code = 404
    code = "not_found"


class PermissionDeniedError(GeneForgeError):
    status_code = 403
    code = "permission_denied"


class AuthenticationError(GeneForgeError):
    status_code = 401
    code = "unauthenticated"


class ValidationError(GeneForgeError):
    status_code = 422
    code = "validation_error"


class ConflictError(GeneForgeError):
    status_code = 409
    code = "conflict"


class PayloadTooLargeError(GeneForgeError):
    status_code = 413
    code = "payload_too_large"


class ExternalServiceError(GeneForgeError):
    status_code = 502
    code = "external_service_error"
