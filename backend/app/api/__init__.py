"""API blueprint registration."""

from __future__ import annotations

from flask import Flask

from app.api.admin_events import bp as admin_events_bp
from app.api.admin_policies import bp as admin_policies_bp
from app.api.auth import bp as auth_bp
from app.api.files import bp as files_bp
from app.api.folders import bp as folders_bp
from app.api.health import bp as health_bp
from app.api.notifications import bp as notifications_bp
from app.api.public_share_links import bp as public_share_links_bp
from app.api.share_links import bp as share_links_bp
from app.api.shares import bp as shares_bp
from app.api.tags import bp as tags_bp
from app.api.tier_overrides import admin_bp as tier_overrides_admin_bp
from app.api.tier_overrides import user_bp as tier_overrides_user_bp
from app.api.trash import bp as trash_bp


def register_blueprints(app: Flask) -> None:
    """Register all blueprints on the app."""
    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(folders_bp)
    app.register_blueprint(shares_bp)
    app.register_blueprint(share_links_bp)
    app.register_blueprint(public_share_links_bp)
    app.register_blueprint(trash_bp)
    app.register_blueprint(tags_bp)
    app.register_blueprint(tier_overrides_user_bp)
    app.register_blueprint(tier_overrides_admin_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(admin_events_bp)
    app.register_blueprint(admin_policies_bp)
