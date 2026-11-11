"""ASGI entry point: ``uvicorn forliosa.main:app``."""

from forliosa.api.app import create_app

app = create_app()
