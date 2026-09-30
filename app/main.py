from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.routes import router
from app.config import WEB_DIR


def create_app() -> FastAPI:
    app = FastAPI(title="DCC V1", version=__version__)
    app.include_router(router)
    # Mounted last so /api routes take precedence over static files.
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
