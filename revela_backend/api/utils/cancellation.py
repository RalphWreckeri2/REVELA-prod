from threading import Lock

_cancel_flags = {
    "registry_import": False,
    "run_detection": False
}
_cancel_lock = Lock()


def set_cancel(task_name: str, value: bool):
    """Set the cancellation status for a specific task."""
    with _cancel_lock:
        _cancel_flags[task_name] = value


def is_cancelled(task_name: str) -> bool:
    """Check if a specific task has been cancelled."""
    with _cancel_lock:
        return _cancel_flags.get(task_name, False)


def commit_unless_cancelled(task_name: str, commit):
    """Atomically commit unless cancellation was requested first."""
    with _cancel_lock:
        if _cancel_flags.get(task_name, False):
            return False
        commit()
        return True
