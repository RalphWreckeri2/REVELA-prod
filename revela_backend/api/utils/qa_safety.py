"""Central runtime guards for local backend QA mode."""

import os
import threading

from flask import current_app, has_app_context


class QaSideEffectBlocked(RuntimeError):
    """An operation that could escape the local QA boundary was refused."""


def is_qa_mode():
    if has_app_context():
        return bool(current_app.config.get("REVELA_QA_MODE", False))
    return os.getenv("REVELA_QA_MODE", "").strip().lower() == "1"


def require_external_services_allowed(service):
    if is_qa_mode():
        raise QaSideEffectBlocked(
            f"{service} is disabled while REVELA_QA_MODE=1."
        )


def start_background_task(target, *args, name=None, **kwargs):
    """Start a background thread only outside isolated QA mode."""
    if is_qa_mode():
        return False
    thread = threading.Thread(
        target=target, args=args, kwargs=kwargs, name=name, daemon=True
    )
    thread.start()
    return True
