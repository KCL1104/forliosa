"""ASGI entry point: ``uvicorn forliosa.main:app``."""

from forliosa.api.app import create_app, warm_up_in_background

app = create_app()
warm_up_in_background()  # instrument master, latest closes, gc.freeze — before the first request needs them
