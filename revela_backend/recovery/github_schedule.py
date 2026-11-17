"""Control the repository's scheduled backup workflow through the GitHub API."""
import os
import re
from urllib.parse import quote

import requests


def _configuration():
    token = os.getenv("DB_BACKUP_GITHUB_TOKEN", "").strip()
    repository = os.getenv(
        "DB_BACKUP_GITHUB_REPOSITORY", "RalphWreckeri2/REVELA-prod"
    ).strip()
    workflow = os.getenv(
        "DB_BACKUP_GITHUB_WORKFLOW", "database-backup-trigger.yml"
    ).strip()
    if (not token
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+\.ya?ml", workflow, re.IGNORECASE)):
        return None
    return token, repository, workflow


def configured():
    return _configuration() is not None


def set_enabled(enabled):
    if type(enabled) is not bool:
        raise ValueError("invalid_github_workflow_state")
    configuration = _configuration()
    if not configuration:
        raise RuntimeError("github_backup_workflow_control_not_configured")
    token, repository, workflow = configuration
    owner, name = repository.split("/", 1)
    action = "enable" if enabled else "disable"
    url = (
        f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(name, safe='')}"
        f"/actions/workflows/{quote(workflow, safe='')}/{action}"
    )
    response = requests.put(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=(5, 15),
        allow_redirects=False,
    )
    if response.status_code != 204:
        raise RuntimeError("github_backup_workflow_update_failed")
