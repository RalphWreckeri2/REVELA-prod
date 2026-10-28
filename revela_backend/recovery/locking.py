"""Cross-thread/process fence shared by snapshot capture and evidence writes.

Use one persistent volume and one backend replica. The operating system releases
the lock on process death; stale lock *files* are harmless and must not be deleted.
"""
import os
import threading
import time
from contextlib import contextmanager
from functools import wraps

from flask import jsonify

from recovery.settings import enabled, state_directory

_threads = {"evidence": threading.RLock(), "job": threading.Lock()}


class LockBusy(RuntimeError):
    pass


@contextmanager
def lock(name, directory=None, timeout=10):
    thread_lock = _threads[name]
    if not thread_lock.acquire(timeout=timeout):
        raise LockBusy("backup_busy")
    handle = None
    acquired = False
    try:
        directory = directory or state_directory()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        handle = open(directory / f"{name}.lock", "a+b")
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise LockBusy("backup_busy") from None
                time.sleep(0.05)
        yield
    finally:
        if handle:
            if acquired:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
        thread_lock.release()


def evidence_write(fn):
    @wraps(fn)
    def guarded(*args, **kwargs):
        if not enabled():
            return fn(*args, **kwargs)
        try:
            with lock("evidence"):
                return fn(*args, **kwargs)
        except LockBusy:
            response = jsonify({"error": "A recovery snapshot is being captured. Retry shortly.",
                                "code": "backup_busy"})
            response.headers["Retry-After"] = "30"
            return response, 503
    return guarded
