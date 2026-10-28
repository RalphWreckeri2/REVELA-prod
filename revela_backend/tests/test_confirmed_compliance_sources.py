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
    assert compliance_report.get_inspection_verified_compliant()["total"] == 0
    result, error = registry.confirm_pin_compliance(30, "OFFICE-030", 2,
        registry_review_token=review["reviewToken"], confirm_establishment=True)
    assert error is None and result["alreadyConfirmed"]
    assert len(db.rows("SELECT * FROM enforcement_events")) == 1


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


def test_green_without_confirmation_event_is_unclassified(db):
    seed(db)
    db.db.execute("""INSERT INTO official_registry
        (businessID,businessName,barangayID,applicationStatus,confirmedLogID)
        VALUES ('OFFICE-030','FIELD SHOP',1,'Active',30)""")
    db.db.execute("UPDATE geospatial_logs SET businessID='OFFICE-030',flagColor='Green'")
    db.commit()
    assert snapshot(db) == []
