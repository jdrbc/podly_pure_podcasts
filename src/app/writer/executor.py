import logging
from typing import Any, Callable, Dict

from flask import Flask

from app import models
from app.extensions import db
from app.writer import actions as writer_actions
from app.writer.model_ops import execute_model_command
from app.writer.protocol import WriteCommand, WriteCommandType, WriteResult

logger = logging.getLogger("writer")


class CommandExecutor:
    def __init__(self, app: Flask):
        self.app = app
        self.models = self._discover_models()
        self.actions: Dict[str, Any] = {}  # Registry for custom actions
        self._register_default_actions()

    def _register_default_actions(self) -> None:
        self.register_action(
            "ensure_active_run", writer_actions.ensure_active_run_action
        )
        self.register_action("dequeue_job", writer_actions.dequeue_job_action)
        self.register_action(
            "cleanup_stale_jobs", writer_actions.cleanup_stale_jobs_action
        )
        self.register_action("clear_all_jobs", writer_actions.clear_all_jobs_action)
        self.register_action(
            "cleanup_missing_audio_paths",
            writer_actions.cleanup_missing_audio_paths_action,
        )
        self.register_action("create_job", writer_actions.create_job_action)
        self.register_action(
            "cancel_existing_jobs", writer_actions.cancel_existing_jobs_action
        )
        self.register_action(
            "update_job_status", writer_actions.update_job_status_action
        )
        self.register_action("mark_cancelled", writer_actions.mark_cancelled_action)
        self.register_action(
            "reassign_pending_jobs", writer_actions.reassign_pending_jobs_action
        )
        self.register_action("refresh_feed", writer_actions.refresh_feed_action)
        self.register_action("add_feed", writer_actions.add_feed_action)
        self.register_action(
            "clear_post_processing_data",
            writer_actions.clear_post_processing_data_action,
        )
        self.register_action(
            "cleanup_processed_post", writer_actions.cleanup_processed_post_action
        )
        self.register_action(
            "increment_download_count", writer_actions.increment_download_count_action
        )
        self.register_action(
            "set_user_billing_fields", writer_actions.set_user_billing_fields_action
        )
        self.register_action(
            "set_user_billing_by_customer_id",
            writer_actions.set_user_billing_by_customer_id_action,
        )
        self.register_action(
            "ensure_user_feed_membership",
            writer_actions.ensure_user_feed_membership_action,
        )
        self.register_action(
            "remove_user_feed_membership",
            writer_actions.remove_user_feed_membership_action,
        )
        self.register_action(
            "whitelist_latest_post_for_feed",
            writer_actions.whitelist_latest_post_for_feed_action,
        )
        self.register_action(
            "toggle_whitelist_all_for_feed",
            writer_actions.toggle_whitelist_all_for_feed_action,
        )
        self.register_action(
            "create_dev_test_feed", writer_actions.create_dev_test_feed_action
        )
        self.register_action(
            "delete_feed_cascade", writer_actions.delete_feed_cascade_action
        )
        self.register_action(
            "update_discord_settings", writer_actions.update_discord_settings_action
        )
        self.register_action(
            "update_combined_config", writer_actions.update_combined_config_action
        )
        self.register_action(
            "create_feed_access_token", writer_actions.create_feed_access_token_action
        )
        self.register_action(
            "touch_feed_access_token", writer_actions.touch_feed_access_token_action
        )
        self.register_action("create_user", writer_actions.create_user_action)
        self.register_action(
            "update_user_password", writer_actions.update_user_password_action
        )
        self.register_action("delete_user", writer_actions.delete_user_action)
        self.register_action("set_user_role", writer_actions.set_user_role_action)
        self.register_action(
            "set_manual_feed_allowance", writer_actions.set_manual_feed_allowance_action
        )
        self.register_action(
            "upsert_discord_user", writer_actions.upsert_discord_user_action
        )

        self.register_action(
            "upsert_model_call", writer_actions.upsert_model_call_action
        )
        self.register_action(
            "upsert_whisper_model_call", writer_actions.upsert_whisper_model_call_action
        )
        self.register_action(
            "replace_transcription", writer_actions.replace_transcription_action
        )
        self.register_action(
            "mark_model_call_failed", writer_actions.mark_model_call_failed_action
        )
        self.register_action(
            "insert_identifications", writer_actions.insert_identifications_action
        )
        self.register_action(
            "replace_identifications", writer_actions.replace_identifications_action
        )
        self.register_action(
            "update_user_last_active", writer_actions.update_user_last_active_action
        )

    def _discover_models(self) -> Dict[str, Any]:
        """Discover all SQLAlchemy models in app.models"""
        model_map = {}
        for name, obj in vars(models).items():
            if isinstance(obj, type) and issubclass(obj, db.Model) and obj != db.Model:
                model_map[name] = obj
        return model_map

    def register_action(self, name: str, func: Callable[[Dict[str, Any]], Any]) -> None:
        self.actions[name] = func

    def process_command(self, cmd: WriteCommand) -> WriteResult:
        with self.app.app_context():
            try:
                logger.info(
                    "[WRITER] Processing command: id=%s type=%s model=%s",
                    cmd.id,
                    cmd.type,
                    cmd.model,
                )
                if cmd.type == WriteCommandType.TRANSACTION:
                    result = self._handle_transaction(cmd)
                    if result.success:
                        logger.debug(
                            "[WRITER] Committing TRANSACTION command id=%s", cmd.id
                        )
                        db.session.commit()
                    else:
                        logger.debug(
                            "[WRITER] Rolling back TRANSACTION command id=%s", cmd.id
                        )
                        db.session.rollback()
                    return result

                # Single operation
                result = self._execute_single_command(cmd)
                if result.success:
                    # Suppress commit log for empty dequeue_job actions (polling)
                    is_polling_noop = (
                        cmd.type == WriteCommandType.ACTION
                        and cmd.data.get("action") == "dequeue_job"
                        and not result.data
                    )

                    if not is_polling_noop:
                        logger.info("[WRITER] Committing single command id=%s", cmd.id)
                    db.session.commit()
                else:
                    logger.info("[WRITER] Rolling back single command id=%s", cmd.id)
                    db.session.rollback()
                return result

            except Exception as e:
                logger.error(
                    "[WRITER] Error processing command id=%s: %s",
                    cmd.id,
                    e,
                    exc_info=True,
                )
                db.session.rollback()
                return WriteResult(cmd.id, False, error=str(e))

    def _execute_single_command(self, cmd: WriteCommand) -> WriteResult:
        if cmd.type == WriteCommandType.ACTION:
            return self._handle_action(cmd)

        if not cmd.model or cmd.model not in self.models:
            return WriteResult(cmd.id, False, error=f"Unknown model: {cmd.model}")

        model_cls = self.models[cmd.model]
        if cmd.type in (
            WriteCommandType.CREATE,
            WriteCommandType.UPDATE,
            WriteCommandType.DELETE,
        ):
            return execute_model_command(
                cmd=cmd, model_cls=model_cls, db_session=db.session
            )

        return WriteResult(cmd.id, False, error="Unknown command type")

    def _handle_transaction(self, cmd: WriteCommand) -> WriteResult:
        sub_commands_data = cmd.data.get("commands", [])
        results = []

        try:
            for sub_cmd_data in sub_commands_data:
                if isinstance(sub_cmd_data, dict):
                    sub_cmd = WriteCommand(
                        id=sub_cmd_data.get("id", "sub"),
                        type=WriteCommandType(sub_cmd_data.get("type")),
                        model=sub_cmd_data.get("model"),
                        data=sub_cmd_data.get("data", {}),
                    )
                else:
                    sub_cmd = sub_cmd_data

                res = self._execute_single_command(sub_cmd)
                if not res.success:
                    # Let process_command handle rollback
                    return WriteResult(
                        cmd.id,
                        False,
                        error=f"Transaction failed at {sub_cmd.id}: {res.error}",
                    )
                results.append(res)

            # Let process_command handle commit
            return WriteResult(
                cmd.id,
                True,
                data={
                    "results": [
                        {
                            "command_id": r.command_id,
                            "success": r.success,
                            "data": r.data,
                            "error": r.error,
                        }
                        for r in results
                    ]
                },
            )

        except Exception as e:
            # Let process_command handle rollback
            return WriteResult(cmd.id, False, error=str(e))

    def _handle_action(self, cmd: WriteCommand) -> WriteResult:
        action_name = cmd.data.get("action")
        if action_name not in self.actions:
            return WriteResult(cmd.id, False, error=f"Unknown action: {action_name}")

        func = self.actions[action_name]
        try:
            result = func(cmd.data.get("params", {}))
            # Commit is handled by process_command
            return WriteResult(cmd.id, True, data=result)
        except Exception as e:
            # Rollback is handled by process_command
            raise e
