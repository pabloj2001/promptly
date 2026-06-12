"""FastAPI app: CORS, router registration, consistent error envelope (02)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .routers import (
    docs,
    executions,
    internal,
    metadata,
    operations,
    permissions,
    projects,
    tasks,
)
from .storage import StorageError


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # In-flight runs die with the server; flip them to failed so users can retry.
    from .deps import get_execution

    get_execution().mark_orphans_failed()
    yield


def create_app() -> FastAPI:
    # Relocate the interactive docs so they don't collide with our /docs router.
    app = FastAPI(
        title="Promptly API",
        version="0.1.0",
        docs_url="/api-docs",
        redoc_url="/api-redoc",
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def envelope(code: str, message: str, status: int) -> JSONResponse:
        return JSONResponse(
            status_code=status, content={"error": {"code": code, "message": message}}
        )

    @app.exception_handler(StorageError)
    async def _storage_error(_: Request, exc: StorageError):
        return envelope(exc.code, exc.message, exc.status)

    @app.exception_handler(NotImplementedError)
    async def _not_implemented(_: Request, exc: NotImplementedError):
        return envelope("not_implemented", str(exc) or "not implemented", 501)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        return envelope("http_error", str(exc.detail), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        return envelope("validation", str(exc.errors()), 422)

    app.include_router(projects.router)
    app.include_router(docs.router)
    app.include_router(tasks.router)
    app.include_router(metadata.router)
    app.include_router(executions.router)
    app.include_router(operations.router)
    app.include_router(permissions.router)
    app.include_router(internal.router)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
