"""
In-process pub/sub for admin notification SSE (single Flask process).
For multiple workers, add Redis pub/sub or poll DB only.
"""

import queue
import threading
from typing import Any, Dict, List, Tuple

_lock = threading.Lock()
_subscribers: List[Tuple[str, queue.Queue]] = []  # (user_id_str, Queue)


def subscribe(user_id: str) -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=100)
    with _lock:
        _subscribers.append((user_id, q))
    return q


def unsubscribe(user_id: str, q: queue.Queue) -> None:
    with _lock:
        _subscribers[:] = [p for p in _subscribers if not (p[0] == user_id and p[1] is q)]


def publish_to_admins(event: Dict[str, Any]) -> None:
    """Push a JSON-serializable event to every connected admin stream."""
    with _lock:
        for _, q in _subscribers:
            try:
                q.put_nowait(event)
            except queue.Full:
                try:
                    q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    q.put_nowait(event)
                except queue.Full:
                    pass
