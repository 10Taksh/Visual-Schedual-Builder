from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from app import db
from app.bootstrap import bootstrap
from app.config import Config, config_from_env
from app.constants import (
    BREAK_DURATION_MINUTES,
    BREAK_THRESHOLD_MINUTES,
    DAYS_OF_WEEK,
    EMPLOYEE_COLOR_PALETTE,
    EMPLOYMENT_TYPES,
    MINIMUM_SHIFT_MINUTES,
    SLOT_MINUTES,
)
from app.services.errors import ApiError

# Static facts the browser needs; exposed as window.APP_META by base.html.
APP_META = {
    "days": DAYS_OF_WEEK,
    "employment_types": EMPLOYMENT_TYPES,
    "palette": EMPLOYEE_COLOR_PALETTE,
    "break_threshold_minutes": BREAK_THRESHOLD_MINUTES,
    "break_duration_minutes": BREAK_DURATION_MINUTES,
    "slot_minutes": SLOT_MINUTES,
    "minimum_shift_minutes": MINIMUM_SHIFT_MINUTES,
}


def create_app(config: type[Config] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config or config_from_env())

    engine = db.init_engine(app.config["DATABASE_URL"])
    bootstrap(engine)

    from app.routes.api import api
    from app.routes.pages import pages

    app.register_blueprint(pages)
    app.register_blueprint(api)

    @app.context_processor
    def inject_meta() -> dict:
        return {"app_meta": APP_META}

    @app.errorhandler(ApiError)
    def handle_api_error(error: ApiError):
        return jsonify(error.to_dict()), error.status_code

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        # API clients get JSON; page requests keep Werkzeug's default HTML pages.
        if request.path.startswith("/api/"):
            return jsonify(error=error.description), error.code
        return error

    return app
