import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ModalRecord:
    view_id: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    expires_at: float = field(default_factory=float)

    def is_expired(self) -> bool:
        return time.time() >= self.expires_at


class ModalRegistry:
    """Simple in-memory registry for Slack modals with TTL support."""

    def __init__(self, ttl_seconds: int = 900):
        self._ttl = ttl_seconds
        self._items: Dict[str, ModalRecord] = {}
        self._lock = asyncio.Lock()

    async def put(self, external_id: str, view_id: str, **metadata: Any) -> None:
        record = ModalRecord(
            view_id=view_id,
            metadata=metadata,
            expires_at=time.time() + self._ttl,
        )
        async with self._lock:
            self._items[external_id] = record

    async def get(self, external_id: str) -> Optional[ModalRecord]:
        async with self._lock:
            record = self._items.get(external_id)
            if not record:
                return None
            if record.is_expired():
                self._items.pop(external_id, None)
                return None
            return record

    async def delete(self, external_id: str) -> None:
        async with self._lock:
            self._items.pop(external_id, None)

