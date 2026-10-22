"""One consistent error envelope for every endpoint:

{"error": {"code": "validation_error", "message": "...", "details": {...}}}
"""

from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None  # unhandled -> Django 500 (logged / Sentry)

    data = response.data
    code = getattr(exc, "default_code", "error")
    if isinstance(data, dict) and set(data) == {"detail"}:
        message, details = str(data["detail"]), None
    else:
        message, details = "Request failed validation." if response.status_code == 400 else "Error.", data
    response.data = {"error": {"code": code, "message": message, "details": details}}
    return response
