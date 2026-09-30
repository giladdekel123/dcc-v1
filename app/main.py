from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.routes import router
from app.config import WEB_DIR
from app.db import close_pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    close_pool()


def create_app() -> FastAPI:
    app = FastAPI(title="DCC V1", version=__version__, lifespan=lifespan)
    app.include_router(router)
    # Mounted last so /api routes take precedence over static files.
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
