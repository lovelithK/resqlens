"""Small routing layer on top of Starlette: authentication, per-request
transaction, Pydantic validation and uniform JSON error handling."""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

import jwt
from pydantic import BaseModel, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..database import Database
from ..domain.models import DomainError
from ..errors import AppError
from ..repositories import NotFound
from ..security import decode_token
from ..services.context import ServiceContext

log = logging.getLogger("resqlens")


class RequestContext:
    def __init__(self, request: Request, svc: ServiceContext, body: Any, token_claims: dict | None):
        self.request = request
        self.svc = svc
        self.body = body
        self.claims = token_claims

    @property
    def params(self) -> dict:
        return self.request.path_params

    @property
    def query(self):
        return self.request.query_params

    def int_param(self, name: str) -> int:
        return int(self.request.path_params[name])


class Api:
    def __init__(self, db_getter: Callable[[], Database], settings_getter: Callable):
        self.routes: list[Route] = []
        self.meta: list[dict] = []          # used to generate the OpenAPI document (/docs)
        self._db = db_getter
        self._settings = settings_getter

    def route(self, path: str, methods: list[str], auth: bool = True, schema: type[BaseModel] | None = None,
              query: list[str] | None = None):
        def decorator(fn: Callable[[RequestContext], Any]):
            self.meta.append({"path": path, "methods": methods, "auth": auth, "schema": schema,
                              "query": query or [], "fn": fn})
            async def endpoint(request: Request) -> Response:
                try:
                    body = None
                    if schema is not None:
                        raw = await request.body()
                        try:
                            data = json.loads(raw or b"{}")
                        except json.JSONDecodeError:
                            raise AppError(400, "INVALID_JSON", "Request body is not valid JSON")
                        body = schema.model_validate(data)
                    with self._db().transaction() as conn:
                        svc = ServiceContext(conn)
                        claims = None
                        if auth:
                            claims = self._authenticate(request, svc)
                        result = fn(RequestContext(request, svc, body, claims))
                    if isinstance(result, Response):
                        return result
                    if result is None:
                        return Response(status_code=204)
                    status = 201 if request.method == "POST" and getattr(fn, "_created", False) else 200
                    return JSONResponse(result, status_code=status)
                except ValidationError as e:
                    errors = [{"field": ".".join(str(x) for x in err["loc"]), "message": err["msg"]}
                              for err in e.errors()]
                    return _error(422, "VALIDATION_ERROR", errors[0]["message"] if errors else "Invalid input", errors)
                except AppError as e:
                    return _error(e.status, e.code, e.message, e.details)
                except NotFound as e:
                    return _error(404, "NOT_FOUND", f"{e.what} not found")
                except DomainError as e:
                    return _error(422, e.code, e.message, e.details)
                except Exception:  # pragma: no cover - safety net
                    log.exception("Unhandled error on %s %s", request.method, request.url.path)
                    return _error(500, "INTERNAL_ERROR", "An unexpected error occurred")

            self.routes.append(Route(path, endpoint, methods=methods))
            return fn
        return decorator

    def _authenticate(self, request: Request, svc: ServiceContext) -> dict:
        header = request.headers.get("authorization", "")
        token = header[7:] if header.lower().startswith("bearer ") else None
        if not token:
            raise AppError(401, "UNAUTHENTICATED", "Authentication required")
        try:
            claims = decode_token(token, self._settings().secret_key)
        except jwt.ExpiredSignatureError:
            raise AppError(401, "TOKEN_EXPIRED", "Session expired – please sign in again")
        except jwt.PyJWTError:
            raise AppError(401, "INVALID_TOKEN", "Invalid authentication token")
        if not svc.users.session_exists(claims["jti"]):
            raise AppError(401, "SESSION_REVOKED", "Session has ended – please sign in again")
        user = svc.users.get(int(claims["sub"]))
        if not user:
            raise AppError(401, "INVALID_TOKEN", "User no longer exists")
        svc.user = user
        return claims


def created(fn):
    fn._created = True
    return fn


def _error(status: int, code: str, message: str, details=None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "details": details}}, status_code=status)
