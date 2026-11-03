"""Both confirmation paths share one canonical current-business classification."""
from unittest.mock import patch

import pytest

from api.flags import compliance_report
from api.flags.compliance import current_confirmation_rows, confirmation_summary
from api.inspections import service as inspections
from api.registry import service as registry
from test_map_compliance import FeatureDB


@pytest.fixture
def db():
    database = FeatureDB()
    with (patch.object(compliance_report, "mysql", database),
          patch.object(inspections, "mysql", database),
          patch.object(registry, "mysql", database),
          patch("api.notifications.hub.publish_to_admins")):
        yield database
    database.close()


def seed(db, *, source="detection", report=False, status="Submitted", result="Green"):
    db.db.execute("""INSERT INTO geospatial_logs
        (logID,barangayID,detectedName,latitude,longitude,flagColor,source)
        VALUES (30,1,'FIELD SHOP',13.9667,121.1167,'Yellow',?)""", (source,))
    if report:
        db.db.execute("""INSERT INTO inspection_reports
            (reportID,targetID,targetType,userID,verificationStatus,inspectionResult)
            VALUES (31,30,'geospatial_log',9,?,?)""", (status, result))
    db.commit()


def snapshot(db):
    cursor = db.cursor()
    try:
        return current_confirmation_rows(cursor, ladder=True)
    finally:
        cursor.close()


def office_confirm(db):
    review, error = registry.preview_pin_compliance(30, "OFFICE-030")
    assert error is None
    result, error = registry.confirm_pin_compliance(30, "OFFICE-030", 2,
        registry_review_token=review["reviewToken"], confirm_establishment=True)
    assert error is None, error
    return result


@pytest.mark.parametrize("source", ["detection", "manual"])
def test_submitted_green_is_not_verified_and_verification_includes_linked_origin(db, source):
    seed(db, source=source, report=True)
    assert snapshot(db) == []
    review, error = inspections.preview_green_registry_link(31, "OFFICE-030")
    assert error is None
    result, error = inspections.verify_inspection(31, 2, business_id="OFFICE-030",
        registry_review_token=review["reviewToken"], confirm_establishment=True)
    assert error is None, error
    rows = snapshot(db)
    assert confirmation_summary(rows)["inspection_verified"] == 1
    assert len(rows) == 1 and rows[0]["businessID"] == "OFFICE-030"
    report = compliance_report.get_inspection_verified_compliant()
    assert report["total"] == 1
    assert report["data"][0]["originSource"] == source
    assert db.rows("SELECT source FROM geospatial_logs") == [{"source": source}]
    result, error = inspections.verify_inspection(31, 2, business_id="OFFICE-030",
        registry_review_token=review["reviewToken"], confirm_establishment=True)
    assert error is None and result["alreadyVerified"]
    assert len(snapshot(db)) == 1


def test_office_event_counts_without_report_and_retry_does_not_duplicate(db):
    seed(db)
    review, error = registry.preview_pin_compliance(30, "OFFICE-030")
    assert error is None
    office_confirm(db)
    rows = snapshot(db)
    assert confirmation_summary(rows) == {"office_confirmed": 1, "inspection_verified": 0,
        "total_confirmed": 1, "count_unit": "distinct confirmed registry businesses"}
    assert db.rows("SELECT * FROM inspection_reports") == []
    report_snapshot = compliance_report.get_inspection_verified_compliant()
    assert report_snapshot["total"] == 0
    assert report_snapshot["adminConfirmedTotal"] == 1
    assert report_snapshot["adminConfirmedData"][0]["businessID"] == "OFFICE-030"
    assert report_snapshot["adminConfirmedData"][0]["verificationMethod"] == "DIRECT_ADMIN_CONFIRMATION"
    assert report_snapshot["adminConfirmedData"][0]["confirmedBy"] == "Admin"
    assert report_snapshot["adminConfirmedData"][0]["confirmedByUserID"] == 2
    assert report_snapshot["adminConfirmedData"][0]["verifiedOn"]
    result, error = registry.confirm_pin_compliance(30, "OFFICE-030", 2,
        registry_review_token=review["reviewToken"], confirm_establishment=True)
    assert error is None and result["alreadyConfirmed"]
    assert len(db.rows("SELECT * FROM enforcement_events")) == 1


def test_retry_repairs_missing_confirmation_event_without_duplicating_valid_event(db):
    seed(db)
    review, error = registry.preview_pin_compliance(30, "OFFICE-030")
    assert error is None
    office_confirm(db)
    db.db.execute("DELETE FROM enforcement_events")
    db.commit()

    result, error = registry.confirm_pin_compliance(30, "OFFICE-030", 2,
        registry_review_token=review["reviewToken"], confirm_establishment=True)

    assert error is None and result["alreadyConfirmed"]
    assert db.rows("""SELECT subjectID, eventType, actorUserID, reason
                      FROM enforcement_events""") == [{
        "subjectID": "OFFICE-030",
        "eventType": "compliance_confirmed",
        "actorUserID": 2,
        "reason": "Office confirmation: Business ID OFFICE-030 linked to existing registry record for original pin #30",
    }]
    assert compliance_report.get_inspection_verified_compliant()["adminConfirmedTotal"] == 1


def test_confirmation_event_failure_rolls_back_registry_link_and_green_status(db):
    seed(db)
    review, error = registry.preview_pin_compliance(30, "OFFICE-030")
    assert error is None
    db.db.execute("""CREATE TRIGGER fail_compliance_event
                     BEFORE INSERT ON enforcement_events
                     WHEN NEW.eventType = 'compliance_confirmed'
                     BEGIN SELECT RAISE(FAIL, 'event write failed'); END""")
    db.commit()

    result, error = registry.confirm_pin_compliance(30, "OFFICE-030", 2,
        registry_review_token=review["reviewToken"], confirm_establishment=True)

    assert result is None and "event write failed" in str(error)
    assert db.rows("SELECT businessID, flagColor FROM geospatial_logs WHERE logID=30") == [
        {"businessID": None, "flagColor": "Yellow"}]
    assert db.rows("SELECT * FROM official_registry WHERE businessID='OFFICE-030'") == []
    assert db.rows("SELECT * FROM enforcement_events") == []


def test_later_verified_inspection_reclassifies_office_without_double_count(db):
    seed(db)
    office_confirm(db)
    db.db.execute("""INSERT INTO inspection_reports
        (reportID,targetID,targetType,userID,verificationStatus,inspectionResult)
        VALUES (31,30,'geospatial_log',9,'Verified','Green')""")
    db.db.execute("""INSERT INTO inspection_lifecycle_events
        (reportID,targetLogID,eventType,inspectionResult,actorUserID,eventTimestamp)
        VALUES (31,30,'verified','Green',2,'2099-01-01 00:00:00.000001')""")
    db.commit()
    rows = snapshot(db)
    assert confirmation_summary(rows)["total_confirmed"] == 1
    assert confirmation_summary(rows)["inspection_verified"] == 1
    assert len(db.rows("SELECT * FROM enforcement_events")) == 1
    report = compliance_report.get_inspection_verified_compliant()
    assert report["total"] == 1
    assert report["adminConfirmedTotal"] == 0


def test_green_without_confirmation_event_is_unclassified(db):
    seed(db)
    db.db.execute("""INSERT INTO official_registry
        (businessID,businessName,barangayID,applicationStatus,confirmedLogID)
        VALUES ('OFFICE-030','FIELD SHOP',1,'Active',30)""")
    db.db.execute("UPDATE geospatial_logs SET businessID='OFFICE-030',flagColor='Green'")
    db.commit()
    assert snapshot(db) == []
    report = compliance_report.get_inspection_verified_compliant()
    assert report["total"] == 0
    assert report["adminConfirmedTotal"] == 0


def test_direct_confirmation_without_admin_actor_is_not_report_evidence(db):
    seed(db)
    office_confirm(db)
    db.db.execute("UPDATE enforcement_events SET actorUserID=NULL")
    db.commit()

    report = compliance_report.get_inspection_verified_compliant()

    assert report["adminConfirmedData"] == []
    assert report["adminConfirmedTotal"] == 0
