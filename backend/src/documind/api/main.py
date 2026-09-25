"""ASGI entry point: ``uvicorn documind.api.main:app``."""

from documind.api.app import create_app

app = create_app()
