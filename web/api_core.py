"""Shared FastSME FastAPI primitives vendored into each product repository."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, create_model
from starlette.responses import JSONResponse


class ErrorDetail(BaseModel):
    """Machine-readable API error."""

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    """Consistent error response envelope."""

    error: ErrorDetail


class PaginationMeta(BaseModel):
    """Offset pagination metadata."""

    total: int
    limit: int
    offset: int


class HealthResponse(BaseModel):
    """API health response."""

    status: str
    product: str
    version: str
    writes_enabled: bool


@dataclass(frozen=True)
class Resource:
    """A public API resource backed by an allow-listed table."""

    slug: str
    table: str
    title: str
    description: str
    write_fields: tuple[str, ...] = ()
    search_fields: tuple[str, ...] = ()
    primary_key: str | None = None


class SQLiteBackend:
    """Small read/write adapter with strict identifier allow-lists."""

    def __init__(
        self,
        path: str | Path,
        resources: tuple[Resource, ...],
        initialize: Callable[[], None] | None = None,
    ) -> None:
        self.path = str(path)
        self.resources = {resource.slug: resource for resource in resources}
        if initialize:
            initialize()
        self.ensure_tenant_columns()

    def ensure_tenant_columns(self) -> None:
        """Add a compatibility tenant discriminator without changing product models."""
        with self.connection() as connection:
            for resource in self.resources.values():
                columns = {
                    row["name"] for row in connection.execute(
                        f'PRAGMA table_info("{resource.table}")'
                    ).fetchall()
                }
                if "_fastoffice_org_id" not in columns:
                    connection.execute(
                        f'ALTER TABLE "{resource.table}" ADD COLUMN "_fastoffice_org_id" '
                        "TEXT NOT NULL DEFAULT 'standalone'"
                    )
            connection.commit()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def columns(self, resource: Resource) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                f'PRAGMA table_info("{resource.table}")'
            ).fetchall()
        if not rows:
            raise RuntimeError(
                f"API resource {resource.slug!r} references missing table "
                f"{resource.table!r}"
            )
        return [dict(row) for row in rows if row["name"] != "_fastoffice_org_id"]

    def primary_key(self, resource: Resource) -> str:
        if resource.primary_key:
            return resource.primary_key
        columns = self.columns(resource)
        primary = next((column["name"] for column in columns if column["pk"]), None)
        return primary or columns[0]["name"]

    def list(
        self,
        resource: Resource,
        *,
        limit: int,
        offset: int,
        query: str | None,
        organisation_id: str = "standalone",
    ) -> tuple[list[dict[str, Any]], int]:
        where = ' WHERE "_fastoffice_org_id"=?'
        params: list[Any] = [organisation_id]
        if query and resource.search_fields:
            clauses = [f'CAST("{field}" AS TEXT) LIKE ?' for field in resource.search_fields]
            where += " AND (" + " OR ".join(clauses) + ")"
            params.extend([f"%{query}%"] * len(clauses))
        with self.connection() as connection:
            total = connection.execute(
                f'SELECT COUNT(*) FROM "{resource.table}"{where}', params
            ).fetchone()[0]
            rows = connection.execute(
                f'SELECT * FROM "{resource.table}"{where} '
                f'ORDER BY "{self.primary_key(resource)}" LIMIT ? OFFSET ?',
                (*params, limit, offset),
            ).fetchall()
        return [_serialise_row(row) for row in rows], total

    def get(self, resource: Resource, item_id: str, organisation_id: str = "standalone") -> dict[str, Any] | None:
        primary_key = self.primary_key(resource)
        with self.connection() as connection:
            row = connection.execute(
                f'SELECT * FROM "{resource.table}" WHERE "{primary_key}"=? AND "_fastoffice_org_id"=?',
                (item_id, organisation_id),
            ).fetchone()
        return _serialise_row(row) if row else None

    def create(self, resource: Resource, values: dict[str, Any], organisation_id: str = "standalone") -> dict[str, Any]:
        allowed = set(resource.write_fields)
        clean = {key: value for key, value in values.items() if key in allowed and value is not None}
        if not clean:
            raise ValueError("At least one writable field is required")
        columns = {column["name"]: column for column in self.columns(resource)}
        primary_key = self.primary_key(resource)
        if (
            primary_key not in clean
            and "TEXT" in (columns[primary_key]["type"] or "").upper()
        ):
            clean[primary_key] = uuid.uuid4().hex
        timestamp = datetime.now(UTC).isoformat()
        for field in ("created", "created_at", "updated_at"):
            column = columns.get(field)
            if (
                column
                and field not in clean
                and column["notnull"]
                and column["dflt_value"] is None
            ):
                clean[field] = timestamp
        fields = tuple(clean)
        clean["_fastoffice_org_id"] = organisation_id
        fields = tuple(clean)
        placeholders = ",".join("?" for _ in fields)
        quoted = ",".join(f'"{field}"' for field in fields)
        with self.connection() as connection:
            cursor = connection.execute(
                f'INSERT INTO "{resource.table}" ({quoted}) VALUES ({placeholders})',
                tuple(clean[field] for field in fields),
            )
            connection.commit()
            item_id = cursor.lastrowid
        created = self.get(resource, str(item_id), organisation_id)
        return created or clean


def _serialise_row(row: sqlite3.Row) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in row.keys():
        value = row[key]
        if isinstance(value, bytes):
            value = value.hex()
        result[key] = value
    return result


def _python_type(sql_type: str) -> type[Any]:
    normalized = (sql_type or "").upper()
    if "INT" in normalized:
        return int
    if any(token in normalized for token in ("REAL", "FLOA", "DOUB", "NUM", "DEC")):
        return float
    if "BLOB" in normalized:
        return str
    return str


def _models_for(
    backend: SQLiteBackend,
    resource: Resource,
) -> tuple[type[BaseModel], type[BaseModel], type[BaseModel] | None]:
    fields: dict[str, tuple[Any, Any]] = {}
    columns = backend.columns(resource)
    for column in columns:
        value_type = _python_type(column["type"])
        nullable = not column["notnull"] or bool(column["pk"])
        fields[column["name"]] = (
            value_type | None if nullable else value_type,
            None if nullable else ...,
        )
    item_model = create_model(
        f"{resource.title.replace(' ', '')}Resource",
        __config__=ConfigDict(extra="ignore"),
        **fields,
    )
    list_model = create_model(
        f"{resource.title.replace(' ', '')}Collection",
        data=(list[item_model], ...),
        meta=(PaginationMeta, ...),
    )
    create_fields: dict[str, tuple[Any, Any]] = {}
    by_name = {column["name"]: column for column in columns}
    for field in resource.write_fields:
        column = by_name[field]
        value_type = _python_type(column["type"])
        required = bool(column["notnull"]) and column["dflt_value"] is None
        create_fields[field] = (value_type if required else value_type | None, ... if required else None)
    create_model_type = (
        create_model(
            f"{resource.title.replace(' ', '')}Create",
            __config__=ConfigDict(extra="forbid"),
            **create_fields,
        )
        if create_fields
        else None
    )
    return item_model, list_model, create_model_type


bearer = HTTPBearer(
    auto_error=False,
    scheme_name="FastSME API token",
    description=(
        "Selected writes require `Authorization: Bearer <token>`. "
        "Reads are public. Set FASTSME_API_TOKEN to enable writes."
    ),
)


@dataclass(frozen=True)
class Principal:
    organisation_id: str
    role: str
    subject: str


def _suite_principal(token: str, audience: str) -> Principal | None:
    secret = os.getenv("FASTOFFICE_SSO_SECRET", "")
    if not secret:
        return None
    try:
        encoded, supplied = token.split(".", 1)
        expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, supplied):
            return None
        body = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if body.get("aud") != audience or body.get("exp", 0) < int(datetime.now(UTC).timestamp()):
            return None
        return Principal(str(body["org_id"]), str(body.get("role", "member")), str(body["sub"]))
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def api_principal(audience: str):
    def dependency(credentials: HTTPAuthorizationCredentials | None = Security(bearer)) -> Principal:
        supplied = credentials.credentials if credentials else ""
        suite = _suite_principal(supplied, audience)
        if suite:
            return suite
        configured = os.getenv("FASTSME_API_TOKEN", "")
        if configured and secrets.compare_digest(configured, supplied):
            return Principal("standalone", "admin", "service")
        if os.getenv("FASTSME_PUBLIC_API_READS", "true").lower() in {"1", "true", "yes"} and not supplied:
            return Principal("standalone", "viewer", "public")
        raise HTTPException(status_code=401, detail={"code": "invalid_token", "message": "A tenant-scoped bearer token is required.", "details": {}})
    return dependency


def require_write_token(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer),  # noqa: B008
) -> None:
    """Require an explicitly configured bearer token for mutations."""

    configured = os.getenv("FASTSME_API_TOKEN", "")
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "writes_disabled",
                "message": "API writes are disabled until FASTSME_API_TOKEN is configured.",
                "details": {},
            },
        )
    supplied = credentials.credentials if credentials else ""
    if not secrets.compare_digest(configured, supplied):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "invalid_token",
                "message": "A valid bearer token is required for this operation.",
                "details": {},
            },
            headers={"WWW-Authenticate": "Bearer"},
        )


def create_sqlite_api(
    *,
    product: str,
    version: str,
    description: str,
    base_url: str,
    backend: SQLiteBackend,
    resources: tuple[Resource, ...],
) -> FastAPI:
    """Create the product API and register its typed resource routes."""

    api = FastAPI(
        title=f"{product} API",
        version=version,
        description=(
            f"{description}\n\n"
            "**Access model:** reads are public. Selected writes are implemented but "
            "disabled unless the deployment configures `FASTSME_API_TOKEN`; write "
            "clients then send it as a bearer token."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        servers=[{"url": f"{base_url.rstrip('/')}/api", "description": "Production"}],
        contact={"name": "FastSME", "url": "https://fastsme.com"},
        license_info={"name": "MIT"},
    )
    api.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "HEAD", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "Authorization"],
    )

    @api.exception_handler(HTTPException)
    async def api_http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, dict) else {
            "code": "http_error",
            "message": str(exc.detail),
            "details": {},
        }
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": detail},
            headers=exc.headers,
        )

    @api.get("/", tags=["System"])
    def api_index() -> dict[str, Any]:
        return {
            "name": f"{product} API",
            "version": version,
            "documentation": f"{base_url.rstrip('/')}/developers",
            "swagger": f"{base_url.rstrip('/')}/api/docs",
            "openapi": f"{base_url.rstrip('/')}/api/openapi.json",
        }

    @api.get("/v1/health", response_model=HealthResponse, tags=["System"])
    def api_health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            product=product,
            version=version,
            writes_enabled=bool(os.getenv("FASTSME_API_TOKEN")),
        )

    def register(resource: Resource) -> None:
        item_model, list_model, create_model_type = _models_for(backend, resource)
        audience = product.lower().removeprefix("fast")
        principal_dependency = api_principal(audience)

        @api.get(
            f"/v1/{resource.slug}",
            response_model=list_model,
            tags=[resource.title],
            summary=f"List {resource.title.lower()}",
            description=resource.description,
            operation_id=f"list_{resource.slug.replace('-', '_')}",
        )
        def list_items(
            limit: int = Query(default=50, ge=1, le=200),
            offset: int = Query(default=0, ge=0),
            q: str | None = Query(default=None, description="Case-insensitive text search"),
            principal: Principal = Depends(principal_dependency),
        ) -> dict[str, Any]:
            rows, total = backend.list(
                resource, limit=limit, offset=offset, query=q, organisation_id=principal.organisation_id
            )
            return {
                "data": rows,
                "meta": {"total": total, "limit": limit, "offset": offset},
            }

        @api.get(
            f"/v1/{resource.slug}/{{item_id}}",
            response_model=item_model,
            responses={404: {"model": ErrorEnvelope}},
            tags=[resource.title],
            summary=f"Get one {resource.title.lower()} record",
            operation_id=f"get_{resource.slug.replace('-', '_')}",
        )
        def get_item(item_id: str, principal: Principal = Depends(principal_dependency)) -> dict[str, Any]:
            row = backend.get(resource, item_id, principal.organisation_id)
            if row is None:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "not_found",
                        "message": f"{resource.title} record not found.",
                        "details": {"id": item_id},
                    },
                )
            return row

        if create_model_type is not None:

            def create_item(payload, principal=Depends(principal_dependency)):
                if principal.role not in {"owner", "admin", "member"}:
                    raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "This role cannot create records.", "details": {}})
                try:
                    return backend.create(
                        resource,
                        payload.model_dump(exclude_none=True),
                        principal.organisation_id,
                    )
                except (sqlite3.IntegrityError, sqlite3.OperationalError, ValueError) as exc:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": "invalid_write",
                            "message": "The record could not be created.",
                            "details": {"reason": str(exc)},
                        },
                    ) from exc

            create_item.__annotations__ = {
                "payload": create_model_type,
                "principal": Principal,
                "return": dict[str, Any],
            }
            api.post(
                f"/v1/{resource.slug}",
                response_model=item_model,
                status_code=201,
                responses={
                    401: {"model": ErrorEnvelope},
                    422: {"model": ErrorEnvelope},
                    503: {"model": ErrorEnvelope},
                },
                dependencies=[],
                tags=[resource.title],
                summary=f"Create a {resource.title.lower()} record",
                description=(
                    "Implemented for token-authenticated integrations. Production "
                    "writes remain disabled until FASTSME_API_TOKEN is configured."
                ),
                operation_id=f"create_{resource.slug.replace('-', '_')}",
            )(create_item)

    for configured_resource in resources:
        register(configured_resource)

    return api


def write_swagger(api: FastAPI, destination: str | Path) -> None:
    """Write a deterministic, committed OpenAPI snapshot."""

    path = Path(destination)
    path.write_text(json.dumps(api.openapi(), indent=2, sort_keys=True) + "\n")
