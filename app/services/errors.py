"""Exceptions that map directly onto JSON error responses.

Services raise these; the app-level error handler turns them into
``{"error": message, ...extra}`` with the right status code, so routes
never build error responses by hand.
"""


class ApiError(Exception):
    status_code = 400

    def __init__(self, message: str, status_code: int | None = None, **extra: object) -> None:
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.extra = extra

    def to_dict(self) -> dict:
        return {"error": self.message, **self.extra}


class NotFoundError(ApiError):
    status_code = 404


class ConflictError(ApiError):
    status_code = 409
