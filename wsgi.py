"""WSGI entry point: ``gunicorn wsgi:app`` in production, ``python wsgi.py`` locally."""

import os

from app import create_app
from app.config import DevelopmentConfig

app = create_app(DevelopmentConfig if os.getenv("FLASK_ENV") == "development" else None)

if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("PORT", "5000")))
