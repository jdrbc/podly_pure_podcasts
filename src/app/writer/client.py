import os
import uuid
from queue import Empty
from typing import Any, Callable, Dict, Optional, cast

from flask import current_app

from app.ipc import make_client_manager
from app.writer.model_ops import execute_model_command
from app.writer.protocol import WriteCommand, WriteCommandType, WriteResult


class WriterClient:
    def __init__(self) -> None:
        self.manager: Any = None
        self.queue: Any = None

    def connect(self) -> None:
        if not self.manager:
            self.manager = make_client_manager()
            self.queue = self.manager.get_command_queue()  # pylint: disable=no-member

    def _should_use_local_fallback(self) -> bool:
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return True
        if os.environ.get("PODLY_WRITER_LOCAL_FALLBACK") == "1":
            return True
        try:
            return bool(getattr(current_app, "testing", False))
        except Exception:  # pylint: disable=broad-except
            return False

    def _local_execute(self, cmd: WriteCommand) -> WriteResult:
        # Import locally to avoid cyclic dependencies
        from app import models  # pylint: disable=import-outside-toplevel
        from app.extensions import db  # pylint: disable=import-outside-toplevel

        model_map: Dict[str, Any] = {}
        for name, obj in vars(models).items():
            if isinstance(obj, type) and issubclass(obj, db.Model) and obj != db.Model:
                model_map[name] = obj

        try:
            if cmd.type == WriteCommandType.TRANSACTION:
                return self._local_execute_transaction(cmd, model_map)

            result = self._local_execute_single(cmd, model_map)
            if result.success:
                db.session.commit()
            else:
                db.session.rollback()
            return result
        except Exception as exc:  # pylint: disable=broad-except
            db.session.rollback()
            return WriteResult(cmd.id, False, error=str(exc))

    def _local_execute_single(
        self, cmd: WriteCommand, model_map: Dict[str, Any]
    ) -> WriteResult:
        if cmd.type == WriteCommandType.ACTION:
            return self._local_execute_action(cmd)
        return self._local_execute_model(cmd, model_map)

    def _local_execute_transaction(
        self, cmd: WriteCommand, model_map: Dict[str, Any]
    ) -> WriteResult:
        # Import locally to avoid cyclic dependencies
        from app.extensions import db  # pylint: disable=import-outside-toplevel

        results = []
        for sub_cmd_data in cmd.data.get("commands", []):
            if isinstance(sub_cmd_data, dict):
                sub_cmd = WriteCommand(
                    id=sub_cmd_data.get("id", "sub"),
                    type=WriteCommandType(sub_cmd_data.get("type")),
                    model=sub_cmd_data.get("model"),
                    data=sub_cmd_data.get("data", {}),
                )
            else:
                sub_cmd = sub_cmd_data

            res = self._local_execute_single(sub_cmd, model_map)
            if not res.success:
                db.session.rollback()
                return WriteResult(
                    cmd.id,
                    False,
                    error=f"Transaction failed at {sub_cmd.id}: {res.error}",
                )
            results.append(res)

        db.session.commit()
        return WriteResult(cmd.id, True, data={"results": [r.data for r in results]})

    def _local_execute_action(self, cmd: WriteCommand) -> WriteResult:
        # Import locally to avoid cyclic dependencies
        # pylint: disable=import-outside-toplevel
        from app.writer import actions as writer_actions

        action_name = cmd.data.get("action")
        func_name = f"{action_name}_action" if action_name else None
        func_obj = getattr(writer_actions, func_name, None) if func_name else None
        if func_obj is None or not callable(func_obj):
            return WriteResult(cmd.id, False, error=f"Unknown action: {action_name}")

        func = cast(Callable[[Dict[str, Any]], Any], func_obj)
        result = func(cmd.data.get("params", {}))  # pylint: disable=not-callable
        return WriteResult(
            cmd.id,
            True,
            data=result if isinstance(result, dict) else {"result": result},
        )

    def _local_execute_model(
        self, cmd: WriteCommand, model_map: Dict[str, Any]
    ) -> WriteResult:
        # Import locally to avoid cyclic dependencies
        from app.extensions import db  # pylint: disable=import-outside-toplevel

        if not cmd.model or cmd.model not in model_map:
            return WriteResult(cmd.id, False, error=f"Unknown model: {cmd.model}")

        model_cls = model_map[cmd.model]
        return execute_model_command(
            cmd=cmd, model_cls=model_cls, db_session=db.session
        )

    def submit(
        self, cmd: WriteCommand, wait: bool = False, timeout: int = 10
    ) -> Optional[WriteResult]:
        if not self.queue:
            try:
                self.connect()
            except Exception:  # pylint: disable=broad-except
                if self._should_use_local_fallback():
                    result = self._local_execute(cmd)
                    return result if wait else None
                raise

        if wait:
            if not self.manager:
                raise RuntimeError("Manager not connected")
            # Create a temporary queue for the reply
            reply_q = self.manager.Queue()  # pylint: disable=no-member
            cmd.reply_queue = reply_q

        if self.queue:
            self.queue.put(cmd)

        if wait:
            try:
                return reply_q.get(timeout=timeout)  # type: ignore
            except Empty as exc:
                raise TimeoutError("Writer service did not respond") from exc
        return None

    def create(
        self, model: str, data: Dict[str, Any], wait: bool = True
    ) -> Optional[WriteResult]:
        cmd = WriteCommand(
            id=str(uuid.uuid4()), type=WriteCommandType.CREATE, model=model, data=data
        )
        return self.submit(cmd, wait=wait)

    def update(
        self, model: str, pk: Any, data: Dict[str, Any], wait: bool = True
    ) -> Optional[WriteResult]:
        data["id"] = pk
        cmd = WriteCommand(
            id=str(uuid.uuid4()), type=WriteCommandType.UPDATE, model=model, data=data
        )
        return self.submit(cmd, wait=wait)

    def delete(self, model: str, pk: Any, wait: bool = True) -> Optional[WriteResult]:
        cmd = WriteCommand(
            id=str(uuid.uuid4()),
            type=WriteCommandType.DELETE,
            model=model,
            data={"id": pk},
        )
        return self.submit(cmd, wait=wait)

    def action(
        self, action_name: str, params: Dict[str, Any], wait: bool = True
    ) -> Optional[WriteResult]:
        cmd = WriteCommand(
            id=str(uuid.uuid4()),
            type=WriteCommandType.ACTION,
            model=None,
            data={"action": action_name, "params": params},
        )
        return self.submit(cmd, wait=wait)


# Singleton instance
writer_client = WriterClient()
