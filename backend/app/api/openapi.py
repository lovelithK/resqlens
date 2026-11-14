"""OpenAPI 3.1 document generated from the registered routes and their
Pydantic request schemas, plus an interactive Swagger UI at ``/docs``."""
from __future__ import annotations

import re

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from .routing import Api

TAGS = [
    ("Authentication", "Registration, login, logout and profile"),
    ("System", "Health check, catalog, dashboard and activity feed"),
    ("Projects", "Projects, architecture, validation, layout, undo, import/export"),
    ("Components", "Components, dependencies and functionalities"),
    ("Scenarios", "Saved failure scenarios"),
    ("Simulation", "Simulation lifecycle and timeline"),
    ("Analysis", "Impact, root cause, SPOF, diagnosis, what-if, resilience, comparison"),
    ("Recovery", "Recovery plans and step-wise execution"),
    ("Reports", "JSON/PDF reports and CSV exports"),
]


def _tag(path: str) -> str:
    p = path.lower()
    if p.startswith("/api/auth"):
        return "Authentication"
    if any(k in p for k in ("report", "export")):
        return "Reports"
    if "recovery" in p:
        return "Recovery"
    if any(k in p for k in ("impact", "root-cause", "single-points", "diagnose", "what-if", "resilience", "compare")):
        return "Analysis"
    if "scenario" in p:
        return "Scenarios"
    if any(k in p for k in ("component", "dependenc", "functionalit")):
        return "Components"
    if p.startswith("/api/simulations"):
        return "Simulation"
    if p.startswith("/api/projects"):
        return "Projects"
    return "System"


def build_openapi(api: Api, title: str = "ResQLens API", version: str = "1.0.0") -> dict:
    paths: dict = {}
    schemas: dict = {
        "Error": {"type": "object", "properties": {"error": {"type": "object", "properties": {
            "code": {"type": "string"}, "message": {"type": "string"}, "details": {}}}}},
    }
    for m in api.meta:
        oa_path = re.sub(r"\{(\w+):\w+\}", r"{\1}", m["path"])
        params = [{"name": n, "in": "path", "required": True, "schema": {"type": "integer"}}
                  for n in re.findall(r"\{(\w+):int\}", m["path"])]
        params += [{"name": q, "in": "query", "required": False, "schema": {"type": "string"}} for q in m["query"]]
        fn = m["fn"]
        summary = (fn.__doc__ or "").strip().split("\n")[0] or fn.__name__.replace("_", " ").capitalize()
        for method in m["methods"]:
            op: dict = {
                "tags": [_tag(m["path"])],
                "summary": summary,
                "operationId": f"{fn.__name__}_{method.lower()}",
                "parameters": params,
                "responses": {
                    "200": {"description": "Success", "content": {"application/json": {"schema": {}}}},
                    "4XX": {"description": "Error", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                },
            }
            if getattr(fn, "_created", False):
                op["responses"]["201"] = op["responses"].pop("200")
            if m["auth"]:
                op["security"] = [{"bearerAuth": []}]
            else:
                op["security"] = []
            schema = m["schema"]
            if schema is not None:
                js = schema.model_json_schema(ref_template="#/components/schemas/{model}")
                for name, sub in js.pop("$defs", {}).items():
                    schemas[name] = sub
                schemas[schema.__name__] = js
                op["requestBody"] = {"required": True, "content": {"application/json": {
                    "schema": {"$ref": f"#/components/schemas/{schema.__name__}"}}}}
            paths.setdefault(oa_path, {})[method.lower()] = op
    return {
        "openapi": "3.1.0",
        "info": {"title": title, "version": version,
                 "description": "REST API of ResQLens – deterministic failure simulation, impact and root-cause "
                                "analysis, recovery planning and resilience scoring. Click **Authorize** and paste "
                                "the `token` returned by `POST /api/auth/login`."},
        "tags": [{"name": n, "description": d} for n, d in TAGS],
        "paths": paths,
        "components": {"schemas": schemas,
                       "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}},
    }


SWAGGER_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>ResQLens API docs</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
</head><body><div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
window.ui = SwaggerUIBundle({ url: '/openapi.json', dom_id: '#swagger-ui', persistAuthorization: true,
  docExpansion: 'none', defaultModelsExpandDepth: 0 });
</script>
<noscript>Open <a href="/openapi.json">/openapi.json</a> for the raw OpenAPI document.</noscript>
</body></html>"""


def openapi_routes(api: Api) -> list[Route]:
    cache: dict = {}

    async def spec(request: Request):
        if "doc" not in cache:
            cache["doc"] = build_openapi(api)
        return JSONResponse(cache["doc"])

    async def docs(request: Request):
        return HTMLResponse(SWAGGER_HTML)

    return [Route("/openapi.json", spec, methods=["GET"]), Route("/docs", docs, methods=["GET"])]
