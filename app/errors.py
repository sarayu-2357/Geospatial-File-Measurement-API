"""Custom exceptions. Each carries the HTTP status code the API will return."""


class GeoAPIError(Exception):
    status_code = 400

    def __init__(self, message: str, file_id: str | None = None):
        
        super().__init__(message)
        self.message = message
        self.file_id = file_id   # set when a FAILED record was saved, so the client can look it up


class UnsupportedFormatError(GeoAPIError):
    status_code = 415   # Unsupported Media Type


class FileTooLargeError(GeoAPIError):
    status_code = 413   # Payload Too Large


class InvalidFileError(GeoAPIError):
    status_code = 422   # Unprocessable: file arrived fine but its content is bad


class MissingCRSError(GeoAPIError):
    status_code = 422


class NotFoundError(GeoAPIError):
    status_code = 404


class ConflictError(GeoAPIError):
    status_code = 409   # request is valid but the resource isn't in the right state