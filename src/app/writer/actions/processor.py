from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Identification, ModelCall, TranscriptSegment


def upsert_model_call_action(params: Dict[str, Any]) -> Dict[str, Any]:
    post_id = params.get("post_id")
    model_name = params.get("model_name")
    first_seq = params.get("first_segment_sequence_num")
    last_seq = params.get("last_segment_sequence_num")
    prompt = params.get("prompt")

    if post_id is None or model_name is None or first_seq is None or last_seq is None:
        raise ValueError(
            "post_id, model_name, first_segment_sequence_num, last_segment_sequence_num are required"
        )
    if not isinstance(prompt, str) or not prompt:
        raise ValueError("prompt is required")

    def _query() -> ModelCall | None:
        return (
            db.session.query(ModelCall)
            .filter_by(
                post_id=int(post_id),
                model_name=str(model_name),
                first_segment_sequence_num=int(first_seq),
                last_segment_sequence_num=int(last_seq),
            )
            .order_by(ModelCall.timestamp.desc())
            .first()
        )

    model_call = _query()
    if model_call is None:
        model_call = ModelCall(
            post_id=int(post_id),
            first_segment_sequence_num=int(first_seq),
            last_segment_sequence_num=int(last_seq),
            model_name=str(model_name),
            prompt=str(prompt),
            status="pending",
            timestamp=datetime.utcnow(),
            retry_attempts=0,
            error_message=None,
            response=None,
        )
        db.session.add(model_call)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            model_call = _query()
            if model_call is None:
                raise

    # Match prior behavior: reset only when pending/failed_retries.
    if model_call.status in ["pending", "failed_retries"]:
        model_call.status = "pending"
        model_call.prompt = str(prompt)
        model_call.retry_attempts = 0
        model_call.error_message = None
        model_call.response = None

    db.session.flush()
    return {"model_call_id": int(model_call.id)}


def upsert_whisper_model_call_action(params: Dict[str, Any]) -> Dict[str, Any]:
    post_id = params.get("post_id")
    model_name = params.get("model_name")
    first_seq = params.get("first_segment_sequence_num", 0)
    last_seq = params.get("last_segment_sequence_num", -1)
    prompt = params.get("prompt") or "Whisper transcription job"

    if post_id is None or model_name is None:
        raise ValueError("post_id and model_name are required")

    reset_fields: Dict[str, Any] = params.get("reset_fields") or {
        "status": "pending",
        "prompt": "Whisper transcription job",
        "retry_attempts": 0,
        "error_message": None,
        "response": None,
    }

    def _query() -> ModelCall | None:
        return (
            db.session.query(ModelCall)
            .filter_by(
                post_id=int(post_id),
                model_name=str(model_name),
                first_segment_sequence_num=int(first_seq),
                last_segment_sequence_num=int(last_seq),
            )
            .order_by(ModelCall.timestamp.desc())
            .first()
        )

    model_call = _query()
    if model_call is None:
        model_call = ModelCall(
            post_id=int(post_id),
            model_name=str(model_name),
            first_segment_sequence_num=int(first_seq),
            last_segment_sequence_num=int(last_seq),
            prompt=str(prompt),
            status=str(reset_fields.get("status") or "pending"),
            retry_attempts=int(reset_fields.get("retry_attempts") or 0),
            error_message=reset_fields.get("error_message"),
            response=reset_fields.get("response"),
            timestamp=datetime.utcnow(),
        )
        db.session.add(model_call)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            model_call = _query()
            if model_call is None:
                raise

    for k, v in reset_fields.items():
        if hasattr(model_call, k):
            setattr(model_call, k, v)

    db.session.flush()
    return {"model_call_id": int(model_call.id)}


def _normalize_segments_payload(
    segments: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        normalized.append(
            {
                "post_id": int(seg["post_id"]),
                "sequence_num": int(seg["sequence_num"]),
                "start_time": float(seg["start_time"]),
                "end_time": float(seg["end_time"]),
                "text": str(seg["text"]),
            }
        )
    return normalized


def replace_transcription_action(params: Dict[str, Any]) -> Dict[str, Any]:
    post_id = params.get("post_id")
    segments = params.get("segments")
    model_call_id = params.get("model_call_id")

    if post_id is None:
        raise ValueError("post_id is required")
    if not isinstance(segments, list):
        raise ValueError("segments must be a list")

    post_id_i = int(post_id)

    seg_ids = [
        row[0]
        for row in db.session.query(TranscriptSegment.id)
        .filter(TranscriptSegment.post_id == post_id_i)
        .all()
    ]
    if seg_ids:
        db.session.query(Identification).filter(
            Identification.transcript_segment_id.in_(seg_ids)
        ).delete(synchronize_session=False)

    db.session.query(TranscriptSegment).filter(
        TranscriptSegment.post_id == post_id_i
    ).delete(synchronize_session=False)

    payload = []
    for i, seg in enumerate(segments):
        if not isinstance(seg, dict):
            continue
        payload.append(
            {
                "post_id": post_id_i,
                "sequence_num": int(seg.get("sequence_num", i)),
                "start_time": float(seg["start_time"]),
                "end_time": float(seg["end_time"]),
                "text": str(seg["text"]),
            }
        )

    if payload:
        db.session.execute(sqlite_insert(TranscriptSegment).values(payload))

    if model_call_id is not None:
        mc = db.session.get(ModelCall, int(model_call_id))
        if mc is not None:
            mc.first_segment_sequence_num = 0
            mc.last_segment_sequence_num = len(payload) - 1
            mc.response = f"{len(payload)} segments transcribed."
            mc.status = "success"
            mc.error_message = None

    db.session.flush()
    return {"post_id": post_id_i, "segment_count": len(payload)}


def mark_model_call_failed_action(params: Dict[str, Any]) -> Dict[str, Any]:
    model_call_id = params.get("model_call_id")
    error_message = params.get("error_message")
    status = params.get("status", "failed_permanent")

    if model_call_id is None:
        raise ValueError("model_call_id is required")

    mc = db.session.get(ModelCall, int(model_call_id))
    if mc is None:
        return {"updated": False}

    mc.status = str(status)
    mc.error_message = str(error_message) if error_message is not None else None
    db.session.flush()
    return {"updated": True, "model_call_id": int(mc.id)}


def insert_identifications_action(params: Dict[str, Any]) -> Dict[str, Any]:
    identifications = params.get("identifications")
    if not isinstance(identifications, list):
        raise ValueError("identifications must be a list")

    values = []
    for ident in identifications:
        if not isinstance(ident, dict):
            continue
        values.append(
            {
                "transcript_segment_id": int(ident["transcript_segment_id"]),
                "model_call_id": int(ident["model_call_id"]),
                "label": str(ident.get("label") or "ad"),
                "confidence": ident.get("confidence"),
            }
        )

    if not values:
        return {"inserted": 0}

    stmt = sqlite_insert(Identification).values(values).prefix_with("OR IGNORE")
    result = db.session.execute(stmt)
    db.session.flush()
    return {"inserted": int(getattr(result, "rowcount", 0) or 0)}


def replace_identifications_action(params: Dict[str, Any]) -> Dict[str, Any]:
    delete_ids = params.get("delete_ids") or []
    new_identifications = params.get("new_identifications") or []

    if not isinstance(delete_ids, list) or not isinstance(new_identifications, list):
        raise ValueError("delete_ids and new_identifications must be lists")

    if delete_ids:
        db.session.query(Identification).filter(
            Identification.id.in_([int(i) for i in delete_ids])
        ).delete(synchronize_session=False)

    inserted = insert_identifications_action(
        {"identifications": new_identifications}
    ).get("inserted", 0)

    db.session.flush()
    return {"deleted": len(delete_ids), "inserted": int(inserted)}
