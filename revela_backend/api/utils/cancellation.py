_cancel_flags = {
    "registry_import": False,
    "run_detection": False
}

def set_cancel(task_name: str, value: bool):
    """Set the cancellation status for a specific task."""
    _cancel_flags[task_name] = value

def is_cancelled(task_name: str) -> bool:
    """Check if a specific task has been cancelled."""
    return _cancel_flags.get(task_name, False)
