import logging
from datetime import datetime
from typing import Any, Dict

from app.extensions import db
from app.jobs_manager_run_service import get_or_create_singleton_run
from app.models import DiscordSettings

logger = logging.getLogger("writer")


def ensure_active_run_action(params: Dict[str, Any]) -> Dict[str, Any]:
    trigger = params.get("trigger", "system")
    context = params.get("context")

    logger.info(
        "[WRITER] ensure_active_run_action: trigger=%s context_keys=%s",
        trigger,
        list(context.keys()) if isinstance(context, dict) else None,
    )

    run = get_or_create_singleton_run(db.session, trigger, context)
    db.session.flush()  # Ensure ID is available

    logger.info(
        "[WRITER] ensure_active_run_action: obtained run_id=%s status=%s",
        getattr(run, "id", None),
        getattr(run, "status", None),
    )

    return {"run_id": run.id}


def update_discord_settings_action(params: Dict[str, Any]) -> Dict[str, Any]:
    settings = db.session.get(DiscordSettings, 1)
    if settings is None:
        settings = DiscordSettings(id=1)
        db.session.add(settings)

    for field in (
        "client_id",
        "client_secret",
        "redirect_uri",
        "guild_ids",
        "allow_registration",
    ):
        if field in params:
            setattr(settings, field, params.get(field))

    settings.updated_at = datetime.utcnow()
    db.session.flush()
    return {"updated": True}


def update_combined_config_action(params: Dict[str, Any]) -> Dict[str, Any]:
    payload = params.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dictionary")

    from app.config_store import (  # pylint: disable=import-outside-toplevel
        update_combined,
    )

    updated = update_combined(payload)
    if not isinstance(updated, dict):
        return {"updated": True}
    return updated
