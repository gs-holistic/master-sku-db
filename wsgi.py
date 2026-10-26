"""Entry point for a WSGI host, e.g. `gunicorn wsgi:app`. See docs/HUB_API.md."""
from msku.hub_api import app  # noqa: F401
