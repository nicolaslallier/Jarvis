import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class _State:
    last_run_at: datetime | None = None
    last_status: str = "starting"  # "starting" | "ok" | "error"
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, status: str) -> None:
        with self._lock:
            self.last_run_at = datetime.now(timezone.utc)
            self.last_status = status


state = _State()
