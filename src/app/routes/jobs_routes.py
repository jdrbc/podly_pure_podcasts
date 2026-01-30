import logging

import flask
from flask import Blueprint, current_app, request
from flask.typing import ResponseReturnValue

from app.auth.guards import require_admin
from app.extensions import db
from app.jobs_manager import get_jobs_manager
from app.jobs_manager_run_service import build_run_status_snapshot
from app.post_cleanup import cleanup_processed_posts, count_cleanup_candidates
from app.runtime_config import config as runtime_config

logger = logging.getLogger("global_logger")


jobs_bp = Blueprint("jobs", __name__)


@jobs_bp.route("/api/jobs/active", methods=["GET"])
def api_list_active_jobs() -> ResponseReturnValue:
    try:
        limit = int(request.args.get("limit", "100"))
    except ValueError:
        limit = 100
    result = get_jobs_manager().list_active_jobs(limit=limit)
    return flask.jsonify(result)


@jobs_bp.route("/api/jobs/all", methods=["GET"])
def api_list_all_jobs() -> ResponseReturnValue:
    try:
        limit = int(request.args.get("limit", "100"))
    except ValueError:
        limit = 100
    result = get_jobs_manager().list_all_jobs_detailed(limit=limit)
    return flask.jsonify(result)


@jobs_bp.route("/api/job-manager/status", methods=["GET"])
def api_job_manager_status() -> ResponseReturnValue:
    run_snapshot = build_run_status_snapshot(db.session)
    return flask.jsonify({"run": run_snapshot})


@jobs_bp.route("/api/jobs/<string:job_id>/cancel", methods=["POST"])
def api_cancel_job(job_id: str) -> ResponseReturnValue:
    try:
        result = get_jobs_manager().cancel_job(job_id)
        status_code = (
            200
            if result.get("status") == "cancelled"
            else (404 if result.get("error_code") == "NOT_FOUND" else 400)
        )

        db.session.expire_all()

        return flask.jsonify(result), status_code
    except Exception as e:
        logger.error(f"Failed to cancel job {job_id}: {e}")
        return (
            flask.jsonify(
                {
                    "status": "error",
                    "error_code": "CANCEL_FAILED",
                    "message": f"Failed to cancel job: {str(e)}",
                }
            ),
            500,
        )


@jobs_bp.route("/api/jobs/cleanup/preview", methods=["GET"])
def api_cleanup_preview() -> ResponseReturnValue:
    _, error_response = require_admin("preview cleanup candidates")
    if error_response:
        return error_response

    # Allow override via query param for testing
    retention_override = request.args.get("retention_days", type=int)
    retention = (
        retention_override
        if retention_override is not None
        else getattr(runtime_config, "post_cleanup_retention_days", None)
    )
    count, cutoff = count_cleanup_candidates(retention)
    return flask.jsonify(
        {
            "count": count,
            "retention_days": retention,
            "cutoff_utc": cutoff.isoformat() if cutoff else None,
        }
    )


@jobs_bp.route("/api/jobs/cleanup/run", methods=["POST"])
def api_run_cleanup() -> ResponseReturnValue:
    _, error_response = require_admin("run cleanup job")
    if error_response:
        return error_response

    # Allow override via query param for testing
    retention_override = request.args.get("retention_days", type=int)
    retention = (
        retention_override
        if retention_override is not None
        else getattr(runtime_config, "post_cleanup_retention_days", None)
    )

    # In developer mode, allow retention_days=0 for testing
    # In production, require retention_days > 0
    developer_mode = current_app.config.get("developer_mode", False)

    if retention is None or (retention <= 0 and not developer_mode):
        return flask.jsonify(
            {
                "status": "disabled",
                "message": "Cleanup is disabled because retention_days <= 0.",
            }
        )

    try:
        removed = cleanup_processed_posts(retention)
        remaining, cutoff = count_cleanup_candidates(retention)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Manual cleanup failed: %s", exc, exc_info=True)
        return (
            flask.jsonify(
                {
                    "status": "error",
                    "message": "Cleanup job failed. Check server logs for details.",
                }
            ),
            500,
        )

    return flask.jsonify(
        {
            "status": "ok",
            "removed_posts": removed,
            "remaining_candidates": remaining,
            "retention_days": retention,
            "cutoff_utc": cutoff.isoformat() if cutoff else None,
        }
    )
