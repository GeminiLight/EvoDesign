"""ASGI entrypoint for EvoDiagram API."""

from app.application import create_app
from app.config import get_settings


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
