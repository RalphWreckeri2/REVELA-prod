import pytest

from recovery import github_schedule


def test_github_schedule_config_requires_token_and_valid_repository(monkeypatch):
    monkeypatch.delenv("DB_BACKUP_GITHUB_TOKEN", raising=False)
    assert not github_schedule.configured()
    monkeypatch.setenv("DB_BACKUP_GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("DB_BACKUP_GITHUB_REPOSITORY", "invalid/repository/shape")
    assert not github_schedule.configured()
    monkeypatch.setenv("DB_BACKUP_GITHUB_REPOSITORY", "owner/repo")
    assert github_schedule.configured()


@pytest.mark.parametrize(("enabled", "action"), [(False, "disable"), (True, "enable")])
def test_github_workflow_state_uses_authenticated_actions_api(monkeypatch, enabled, action):
    monkeypatch.setenv("DB_BACKUP_GITHUB_TOKEN", "synthetic-token")
    monkeypatch.setenv("DB_BACKUP_GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("DB_BACKUP_GITHUB_WORKFLOW", "backup.yml")
    calls = []

    class Response:
        status_code = 204

    monkeypatch.setattr(
        github_schedule.requests, "put",
        lambda *args, **kwargs: calls.append((args, kwargs)) or Response(),
    )
    github_schedule.set_enabled(enabled)

    args, kwargs = calls[0]
    assert args == (
        f"https://api.github.com/repos/owner/repo/actions/workflows/backup.yml/{action}",
    )
    assert kwargs["headers"]["Authorization"] == "Bearer synthetic-token"
    assert kwargs["timeout"] == (5, 15)
    assert kwargs["allow_redirects"] is False


def test_github_workflow_api_failure_is_reported_without_response_body(monkeypatch):
    monkeypatch.setenv("DB_BACKUP_GITHUB_TOKEN", "synthetic-token")
    monkeypatch.setenv("DB_BACKUP_GITHUB_REPOSITORY", "owner/repo")

    class Response:
        status_code = 403
        text = "secret provider response"

    monkeypatch.setattr(github_schedule.requests, "put", lambda *_args, **_kwargs: Response())
    with pytest.raises(RuntimeError, match="github_backup_workflow_update_failed"):
        github_schedule.set_enabled(False)


def test_github_workflow_api_requires_boolean(monkeypatch):
    monkeypatch.setenv("DB_BACKUP_GITHUB_TOKEN", "synthetic-token")
    with pytest.raises(ValueError, match="invalid_github_workflow_state"):
        github_schedule.set_enabled("false")
