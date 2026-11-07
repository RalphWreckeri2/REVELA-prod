from unittest.mock import MagicMock, patch

from api.notifications import service


def test_inspection_submitted_notification_links_to_report_details():
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        {"fullName": "Inspector"},
        {"detectedName": "DALI EVERYDAY GROCERY"},
    ]
    cursor.fetchall.return_value = [{"userID": 2, "email": None}]

    with (
        patch.object(service, "_ensure_tables"),
        patch.object(service, "mysql") as mysql,
        patch.object(service, "hub") as hub,
        patch.object(service, "get_email_inspection_alerts", return_value=False),
        patch.object(service.logger, "warning"),
    ):
        mysql.connection.cursor.return_value = cursor
        service.notify_inspection_submitted(
            report_id=31,
            log_id=52,
            inspector_user_id=9,
            inspection_result="Orange",
            has_evidence_photo=True,
        )

    insert_call = next(
        call for call in cursor.execute.call_args_list
        if "INSERT INTO revela_notifications" in call.args[0]
    )
    assert insert_call.args[1][-1] == "/inspections?reportID=31&openReport=1"
    hub.publish_to_admins.assert_called_once()
    assert hub.publish_to_admins.call_args.args[0]["link"] == insert_call.args[1][-1]


def test_inspection_assigned_notification_links_to_report_details():
    cursor = MagicMock()
    cursor.fetchone.return_value = {"detectedName": "DALI EVERYDAY GROCERY"}

    with (
        patch.object(service, "_ensure_tables"),
        patch.object(service, "mysql") as mysql,
        patch.object(service, "send_inspection_dispatch_push"),
    ):
        mysql.connection.cursor.return_value = cursor
        service.notify_inspection_assigned(31, 52, 9)

    insert_call = next(
        call for call in cursor.execute.call_args_list
        if "INSERT INTO revela_notifications" in call.args[0]
    )
    assert insert_call.args[1][-1] == "/inspections?reportID=31&openReport=1"


def test_yellow_flag_notification_links_to_specific_map_flag():
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        {"fullName": "Inspector"},
        {"barangayName": "Barangay II"},
    ]
    cursor.fetchall.return_value = [{"userID": 2}]

    with (
        patch.object(service, "_ensure_tables"),
        patch.object(service, "mysql") as mysql,
        patch.object(service, "hub") as hub,
    ):
        mysql.connection.cursor.return_value = cursor
        service.notify_yellow_flag_reported(633, "BigBeew", 2, 9)

    insert_call = next(
        call for call in cursor.execute.call_args_list
        if "INSERT INTO revela_notifications" in call.args[0]
    )
    assert insert_call.args[1][-1] == "/map?flag=633"
    assert hub.publish_to_admins.call_args.args[0]["link"] == "/map?flag=633"


def test_password_reset_notification_links_to_specific_user():
    cursor = MagicMock()
    cursor.fetchall.return_value = [{"userID": 2}]

    with (
        patch.object(service, "_ensure_tables"),
        patch.object(service, "mysql") as mysql,
        patch.object(service, "hub") as hub,
    ):
        mysql.connection.cursor.return_value = cursor
        service.notify_password_reset_request("Inspector", 9)

    insert_call = next(
        call for call in cursor.execute.call_args_list
        if "INSERT INTO revela_notifications" in call.args[0]
    )
    assert insert_call.args[1][-1] == "/users?userID=9&openReset=1"
    event = hub.publish_to_admins.call_args.args[0]
    assert event["userID"] == 9
    assert event["link"] == "/users?userID=9&openReset=1"
