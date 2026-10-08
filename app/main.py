from contextlib import asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.database import init_db
    from app.services.jobs import recover_stale_jobs

    init_db()
    recover_stale_jobs()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Bulk Certificate Generator", lifespan=lifespan)

    from app.routers import jobs as jobs_router

    app.include_router(jobs_router.router, prefix="/api/v1", tags=["jobs"])

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/v1/health")
    def health_v1():
        return {"status": "ok"}

    return app


app = create_app()
