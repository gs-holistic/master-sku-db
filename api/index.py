"""Vercel entry point. Vercel's Python runtime serves the WSGI `app`; vercel.json sends every path here.
See docs/HUB_API.md."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from msku.hub_api import app  # noqa: E402,F401
