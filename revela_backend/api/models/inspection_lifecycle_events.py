def get_latest_inspection_cycle_id(cursor, report_id):
    cursor.execute("""
        SELECT COALESCE(cycleID, eventID) AS cycle_id
        FROM inspection_lifecycle_events
        WHERE reportID = %s AND eventType IN ('dispatched', 'reassigned')
        ORDER BY eventID DESC
        LIMIT 1
    """, (report_id,))
    row = cursor.fetchone()
    return row["cycle_id"] if row else None


def log_inspection_event(
    cursor,
    report_id,
    target_log_id,
    event_type,
    actor_user_id=None,
    assigned_to_user_id=None,
    flag_color_at_event=None,
    inspection_result=None,
    remarks=None,
    cycle_id=None,
):
    cursor.execute("""
        INSERT INTO inspection_lifecycle_events
            (reportID, targetLogID, cycleID, eventType, actorUserID,
             assignedToUserID, flagColorAtEvent, inspectionResult, remarks)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        report_id,
        target_log_id,
        cycle_id,
        event_type,
        actor_user_id,
        assigned_to_user_id,
        flag_color_at_event,
        inspection_result,
        remarks,
    ))
    return cursor.lastrowid
