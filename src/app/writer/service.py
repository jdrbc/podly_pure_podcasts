import logging
import threading
import time

from app.ipc import get_queue, make_server_manager
from app.logger import setup_logger
from app.writer.protocol import WriteCommandType

from .executor import CommandExecutor

logger = setup_logger("writer", "src/instance/logs/app.log", level=logging.INFO)


def run_writer_service() -> None:
    from app import create_writer_app

    logger.info("Starting Writer Service...")

    # 1. Start the IPC Server
    manager = make_server_manager()
    server = manager.get_server()

    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    logger.info("IPC Server started on port 50001")

    # 2. Get the queue
    queue = get_queue()

    # 3. Initialize App and Executor
    app = create_writer_app()
    executor = CommandExecutor(app)

    logger.info("Writer Loop starting...")

    # 4. Writer Loop
    while True:
        try:
            cmd = queue.get()

            # Check if this is a polling command (dequeue_job)
            is_polling = (
                getattr(cmd, "type", None) == WriteCommandType.ACTION
                and isinstance(getattr(cmd, "data", None), dict)
                and cmd.data.get("action") == "dequeue_job"
            )

            if not is_polling:
                logger.info(
                    "[WRITER] Received command: id=%s type=%s model=%s has_reply=%s",
                    getattr(cmd, "id", None),
                    getattr(cmd, "type", None),
                    getattr(cmd, "model", None),
                    bool(getattr(cmd, "reply_queue", None)),
                )

            result = executor.process_command(cmd)

            # Only log finished/reply if not polling or if polling actually did something
            if not is_polling or (result and result.data):
                logger.info(
                    "[WRITER] Finished command: id=%s success=%s error=%s",
                    getattr(result, "command_id", None),
                    getattr(result, "success", None),
                    getattr(result, "error", None),
                )

            if cmd.reply_queue:
                if not is_polling or (result and result.data):
                    logger.info(
                        "[WRITER] Sending reply for command id=%s",
                        getattr(cmd, "id", None),
                    )
                cmd.reply_queue.put(result)

        except Exception as e:
            logger.error("Error in writer loop: %s", e, exc_info=True)
            time.sleep(1)
