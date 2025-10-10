import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, Awaitable, Callable, Optional, TypeVar

T = TypeVar("T")


class AsyncToThreadRunner:
    """Run blocking callables in a background thread with bounded concurrency."""

    def __init__(self, max_concurrency: int = 8):
        self._coordinator = ConcurrencyCoordinator(max_concurrency=max_concurrency)

    async def run(
        self,
        func: Callable[..., T],
        *args,
        key: Optional[str] = None,
        **kwargs,
    ) -> T:
        async with self._coordinator.guard(key):
            return await asyncio.to_thread(func, *args, **kwargs)


class ConcurrencyCoordinator:
    """Coordinate access to shared resources and cap global concurrency.

    This helper provides two layers of protection:
    - A global semaphore keeps the number of in-flight heavy operations bounded.
    - Per-key asyncio.Lock instances guarantee exclusive access per logical resource
      (e.g. Notion page ID or Slack thread).
    """

    def __init__(self, max_concurrency: int = 8):
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be greater than zero")
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def _get_lock(self, key: str) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock

    @asynccontextmanager
    async def guard(self, key: Optional[str] = None) -> AsyncIterator[None]:
        """Context manager that acquires the global semaphore and optional per-key lock."""
        async with self._semaphore:
            if not key:
                yield
                return

            lock = await self._get_lock(key)
            await lock.acquire()
            try:
                yield
            finally:
                lock.release()

    async def run(self, func: Callable[..., Awaitable[T]], *args, key: Optional[str] = None, **kwargs) -> T:
        """Execute an awaitable under the concurrency guard."""
        async with self.guard(key):
            return await func(*args, **kwargs)
