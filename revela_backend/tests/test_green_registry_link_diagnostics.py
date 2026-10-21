"""Read-only deployment/schema diagnostics cannot confirm or edit any business."""
from email.message import Message
from io import BytesIO
import json
from unittest.mock import MagicMock, patch

import pytest

from scripts.check_green_registry_link_deployment import check_deployment, NoRedirects
from scripts import check_green_registry_link_schema as schema


ORIGIN = "https://www.revelasys.site"


def response(status, headers=None, body=b""):
    stream = BytesIO(body)
    stream.code = status
    stream.headers = Message()
    for name, value in (headers or {}).items():
        stream.headers[name] = value
    return stream


def deployment_responses(review_status=204):
    headers = {"Access-Control-Allow-Origin": ORIGIN,
               "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
               "Access-Control-Allow-Headers": "authorization, content-type"}
    return [response(review_status, headers), response(204, headers), response(401, headers)]


def test_deployment_check_only_sends_preflights_and_unauthenticated_get():
    opener = MagicMock()
    opener.open.side_effect = deployment_responses()
    result = check_deployment("https://api.revelasys.site", ORIGIN, 7, "A-0401018-00078", opener=opener)
    assert result["passed"]
    requests = [call.args[0] for call in opener.open.call_args_list]
    assert [request.get_method() for request in requests] == ["OPTIONS", "OPTIONS", "GET"]
    assert requests[0].get_header("Access-control-request-headers") == "authorization"
    assert requests[1].get_header("Access-control-request-headers") == "authorization,content-type"
    for request in requests:
        assert request.data is None
        assert not request.has_header("Authorization")


@pytest.mark.parametrize("status", [301, 307, 308, 401, 403, 404, 500, 502])
def test_cors_headers_alone_do_not_make_a_failed_preflight_pass(status):
    opener = MagicMock()
    opener.open.side_effect = deployment_responses(status)
    result = check_deployment("https://api.revelasys.site", ORIGIN, opener=opener)
    assert not result["passed"]
    assert result["checks"][0]["status"] == status


def test_deployment_probe_does_not_follow_redirects():
    assert NoRedirects().redirect_request(None, None, 302, "Found", None, "https://other.example") is None


def metadata_connection(*, missing=None, read_only=True):
    connection = MagicMock()
    cursor = connection.cursor.return_value
    cursor.fetchone.return_value = {"schema_name": "isolated_schema", "read_only": int(read_only)}
    columns = [
        {"TABLE_NAME": "official_registry", "COLUMN_NAME": "confirmedLogID", "COLUMN_TYPE": "int", "IS_NULLABLE": "YES"},
        *({"TABLE_NAME": "enforcement_state", "COLUMN_NAME": name} for name in ("warningLevel", "blackLocked", "blackDispatchUnlocked")),
    ]
    indexes = [{"INDEX_NAME": "uq_registry_confirmed_pin", "COLUMN_NAME": "confirmedLogID"}]
    foreign_keys = [{"REFERENCED_TABLE_NAME": "geospatial_logs", "REFERENCED_COLUMN_NAME": "logID",
                     "DELETE_RULE": "RESTRICT", "UPDATE_RULE": "RESTRICT"}]
    cursor.fetchall.side_effect = [
        columns if missing != "columns" else [],
        indexes if missing != "unique" else [],
        foreign_keys if missing != "foreign_key" else [],
    ]
    return connection


def test_schema_check_reads_only_session_and_information_schema_metadata():
    connection = metadata_connection()
    result = schema.inspect_schema(connection)
    assert result["status"] == "ready"
    for call in connection.cursor.return_value.execute.call_args_list:
        sql = call.args[0].strip()
        assert sql.startswith("SELECT ")
        assert "information_schema." in sql or "@@session.transaction_read_only" in sql
    connection.commit.assert_not_called()


@pytest.mark.parametrize("missing", ["columns", "unique", "foreign_key"])
def test_schema_check_does_not_claim_a_partial_migration_is_ready(missing):
    assert schema.inspect_schema(metadata_connection(missing=missing))["status"] == "migration_required"


def test_schema_check_refuses_a_writable_session_before_inspecting_schema():
    connection = metadata_connection(read_only=False)
    with pytest.raises(RuntimeError, match="READ ONLY"):
        schema.inspect_schema(connection)
    assert connection.cursor.return_value.execute.call_count == 1


def test_schema_cli_requests_a_read_only_connection_and_always_rolls_back(capsys):
    connection = metadata_connection()
    with patch("sys.argv", ["check_green_registry_link_schema.py"]), patch("MySQLdb.connect", return_value=connection) as connect:
        assert schema.main() == 0
    assert connect.call_args.kwargs["init_command"] == "SET SESSION TRANSACTION READ ONLY"
    assert json.loads(capsys.readouterr().out)["status"] == "ready"
    connection.commit.assert_not_called()
    connection.rollback.assert_called_once()
    connection.close.assert_called_once()


def test_schema_connection_errors_do_not_echo_credentials_or_connection_details(capsys):
    from MySQLdb import OperationalError

    with patch("sys.argv", ["check_green_registry_link_schema.py"]), patch("MySQLdb.connect", side_effect=OperationalError(2002, "isolated-private-host-and-password")):
        assert schema.main() == 2
    output = capsys.readouterr().out
    assert "isolated-private" not in output
    assert json.loads(output)["mysql_error_code"] == 2002
