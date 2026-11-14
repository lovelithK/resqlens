from __future__ import annotations


class AppError(Exception):
    """Error that maps directly to an HTTP response."""

    def __init__(self, status: int, code: str, message: str, details: dict | list | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def conflict(message: str, code: str = "CONFLICT", details=None) -> AppError:
    return AppError(409, code, message, details)


def invalid(message: str, code: str = "VALIDATION_ERROR", details=None) -> AppError:
    return AppError(422, code, message, details)


def forbidden(message: str = "You do not have access to this resource") -> AppError:
    return AppError(403, "FORBIDDEN", message)
