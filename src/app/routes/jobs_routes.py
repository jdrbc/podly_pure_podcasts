import logging

import flask
from flask import Blueprint, request
from flask.typing import ResponseReturnValue

from app.extensions import db
from app.jobs_manager import get_jobs_manager
from app.jobs_manager_run_service import (
    get_active_run,
    recalculate_run_counts,
    serialize_run,
)

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
    run = get_active_run(db.session)
    if run:
        recalculate_run_counts(db.session)

    # Persist any aggregate updates performed above
    db.session.commit()

    return flask.jsonify({"run": serialize_run(run) if run else None})


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
