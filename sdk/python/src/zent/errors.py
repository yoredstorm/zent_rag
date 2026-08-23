from __future__ import annotations


class APIError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code


class AuthenticationError(APIError):
    """401 — API key inválida o ausente."""


class PermissionDeniedError(APIError):
    """403 — falta un scope o permiso."""


class RateLimitError(APIError):
    """429 — rate limit o cuota."""
