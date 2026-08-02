"""Running operations in the background, for callers that cannot block."""

from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

from ..observability.correlation import correlate

LOGGER = logging.getLogger(__name__)

DEFAULT_WORKERS = 4


class Dispatcher:
    """A thread pool for work whose result the caller collects later.

    A panel calls, gets an operation id back, and polls. The alternative is a
    websocket request blocking for the length of a deploy.

    **PARAMETERS:**
        `max_workers` (int): How many operations may run at once. Defaults to ``4``.  <br>
        `actor` (str): Recorded on the audit events the work emits. Defaults to ``"-"``.  <br>
    """

    def __init__(self, max_workers: int = DEFAULT_WORKERS, actor: str = "-") -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="fleetctl-op")
        self._actor = actor
        self._running: dict[str, Future[None]] = {}

    def submit(self, op_id: str, work: Callable[[], Any]) -> str:
        """Run `work` in the background under `op_id`.

        Correlation is bound inside the worker, not at the call site: context
        variables do not cross a thread boundary, and losing them here would
        leave every backgrounded operation's logs unattributable.

        **PARAMETERS:**
            `op_id` (str): The operation this work reports through.  <br>
            `work` (Callable[[], Any]): The work. Any return value is discarded -- the operation record is the result.  <br>

        **RETURNS:**
            `str`: `op_id`, so a caller can return it straight to its user.  <br>
        """

        def _run() -> None:
            with correlate(op_id=op_id, actor=self._actor):
                try:
                    work()
                except Exception:  # noqa: BLE001 - the operation record already holds the failure
                    LOGGER.exception("Backgrounded operation %s failed", op_id)
                finally:
                    self._running.pop(op_id, None)

        self._running[op_id] = self._pool.submit(_run)
        return op_id

    @property
    def busy(self) -> int:
        """RETURNS: int: How many operations are in flight."""
        return len(self._running)

    def wait(self, timeout: float | None = None) -> None:
        """Block until every in-flight operation finishes. For tests and shutdown."""
        for future in list(self._running.values()):
            future.result(timeout)

    def shutdown(self, *, wait: bool = False) -> None:
        """Stop accepting work.

        Running operations are not cancelled: a deploy killed mid-transfer
        leaves a device worse off than one allowed to finish.

        **PARAMETERS:**
            `wait` (bool): Whether to block until in-flight work finishes. Defaults to ``False``.  <br>
        """
        self._pool.shutdown(wait=wait, cancel_futures=True)
