class AppError(Exception):
    def __init__(self, message: str, error_code: str, details: dict | None = None, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        self.status_code = status_code


class AuthenticationError(AppError):
    def __init__(self, message: str = "Authentication required", details: dict | None = None) -> None:
        super().__init__(message=message, error_code="authentication_error", details=details, status_code=401)


class AuthorizationError(AppError):
    def __init__(self, message: str = "Forbidden", details: dict | None = None) -> None:
        super().__init__(message=message, error_code="authorization_error", details=details, status_code=403)


class ResourceNotFoundError(AppError):
    def __init__(self, message: str = "Resource not found", details: dict | None = None) -> None:
        super().__init__(message=message, error_code="not_found", details=details, status_code=404)
