from __future__ import annotations

from typing import Any

from app.writer.protocol import WriteCommand, WriteCommandType, WriteResult


def execute_model_command(
    *,
    cmd: WriteCommand,
    model_cls: Any,
    db_session: Any,
) -> WriteResult:
    if cmd.type == WriteCommandType.CREATE:
        obj = model_cls(**cmd.data)
        db_session.add(obj)
        db_session.flush()
        data = {"id": obj.id} if hasattr(obj, "id") else None
        return WriteResult(cmd.id, True, data=data)

    if cmd.type == WriteCommandType.UPDATE:
        pk = cmd.data.get("id")
        if not pk:
            return WriteResult(cmd.id, False, error="Missing 'id' in data for UPDATE")

        obj = db_session.get(model_cls, pk)
        if not obj:
            return WriteResult(
                cmd.id, False, error=f"Record not found: {cmd.model} {pk}"
            )

        for k, v in cmd.data.items():
            if k != "id" and hasattr(obj, k):
                setattr(obj, k, v)
        return WriteResult(cmd.id, True)

    if cmd.type == WriteCommandType.DELETE:
        pk = cmd.data.get("id")
        if not pk:
            return WriteResult(cmd.id, False, error="Missing 'id' in data for DELETE")

        obj = db_session.get(model_cls, pk)
        if obj:
            db_session.delete(obj)
        return WriteResult(cmd.id, True)

    return WriteResult(cmd.id, False, error="Unknown command type")
