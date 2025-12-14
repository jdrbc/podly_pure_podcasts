from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class WriteCommandType(Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    # Critical for integrity: Execute multiple operations in one commit
    TRANSACTION = "transaction"
    # For complex logic that needs to run inside the writer (e.g. "deduct_credits_and_start_job")
    ACTION = "action"


@dataclass
class WriteCommand:
    id: str
    type: WriteCommandType
    model: Optional[str]
    data: Dict[str, Any]
    # The queue to send the result back to (managed by the client)
    reply_queue: Any = None


@dataclass
class WriteResult:
    command_id: str
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
