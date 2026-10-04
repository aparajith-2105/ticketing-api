from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str,
                 details: list | None = None, headers: dict | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []
        self.headers = headers


def _body(code: str, message: str, details: list | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or []}}


def register_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError):
        return JSONResponse(_body(exc.code, exc.message, exc.details),
                            status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e["loc"][1:]) or str(e["loc"][0]),
                    "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(_body("VALIDATION_ERROR", "Request validation failed", details),
                            status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
        return JSONResponse(_body(codes.get(exc.status_code, f"HTTP_{exc.status_code}"),
                                  str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        return JSONResponse(_body("INTERNAL_ERROR", "Something went wrong"), status_code=500)