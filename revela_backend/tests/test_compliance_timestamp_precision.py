"""Isolated simulation of exported DATETIME(0) lifecycle and DATETIME(6) enforcement events.

No application database or clock is used. Fractional verification time is
deliberately lost in the legacy-row fixture, just as the exported column does.
"""
from unittest.mock import patch

import pytest

from api.flags.compliance import verified_green_at_sql
from api.inspections import service as inspections
from registry_sqlite import RegistryDB


@pytest.fixture
def db():
    database = RegistryDB()
    database.db.execute("""INSERT INTO official_registry
        (businessID,businessName,barangayID,applicationStatus,confirmedLogID)
        VALUES ('BPLO-1','FIELD SHOP',1,'Active',30)""")
    database.db.execute("""INSERT INTO geospatial_logs
        (logID,businessID,barangayID,detectedName,flagColor,latitude,longitude,source)
        VALUES (30,'BPLO-1',1,'FIELD SHOP','Green',13.9667,121.1167,'detection')""")
    database.db.execute("""INSERT INTO inspection_reports
        (reportID,targetID,targetType,userID,verificationStatus,inspectionResult)
        VALUES (31,30,'geospatial_log',9,'Verified','Green')""")
    database.db.execute("""INSERT INTO inspection_lifecycle_events
        (reportID,targetLogID,eventType,inspectionResult,actorUserID,eventTimestamp)
        VALUES (31,30,'verified','Green',2,'2026-10-25 12:00:00')""")
    database.db.execute("""INSERT INTO enforcement_state
        (subjectType,subjectID,warningLevel,blackLocked)
        VALUES ('business','BPLO-1',0,0)""")
    database.commit()
    with patch.object(inspections, "mysql", database), patch.object(inspections, "_ensure_gps_columns"):
        yield database
    database.close()


def verified_at(db):
    cursor = db.cursor()
    try:
        cursor.execute(f"SELECT {verified_green_at_sql('g', ladder=True)} AS verifiedGreenAt FROM geospatial_logs g WHERE g.logID = 30")
        return cursor.fetchone()["verifiedGreenAt"]
    finally:
        cursor.close()


def event(db, kind, time):
    db.db.execute("""INSERT INTO enforcement_events
        (subjectType,subjectID,eventType,actorUserID,createdAt)
        VALUES ('business','BPLO-1',?,2,?)""", (kind, time))
    db.commit()


def test_cleared_warning_earlier_same_second_does_not_erase_verified_green(db):
    event(db, 'warning_issued', '2026-10-25 12:00:00.100000')
    event(db, 'warning_cleared', '2026-10-25 12:00:00.200000')
    # After the precision migration, future writes retain the .800000 instant.
    db.db.execute("UPDATE inspection_lifecycle_events SET eventTimestamp='2026-10-25 12:00:00.800000'")
    db.commit()
    assert verified_at(db) is not None


def test_legacy_same_second_order_remains_unknown_and_fails_closed(db):
    event(db, 'warning_issued', '2026-10-25 12:00:00.100000')
    event(db, 'warning_cleared', '2026-10-25 12:00:00.200000')
    # The exported DATETIME(0) stored only 12:00:00. Expanding its column
    # cannot recover whether verification was before or after the warning.
    assert verified_at(db) is None


def test_genuinely_later_warning_invalidates_verified_green(db):
    db.db.execute("UPDATE inspection_lifecycle_events SET eventTimestamp='2026-10-25 12:00:00.800000'")
    db.commit()
    event(db, 'warning_issued', '2026-10-25 12:00:00.900000')
    assert verified_at(db) is None


def test_different_seconds_keep_their_order(db):
    event(db, 'warning_issued', '2026-10-25 11:59:59.900000')
    assert verified_at(db) is not None
    event(db, 'warning_issued', '2026-10-25 12:00:01.100000')
    assert verified_at(db) is None


def test_active_warning_still_blocks_green_verification(db):
    db.db.execute("UPDATE inspection_reports SET verificationStatus='Submitted' WHERE reportID=31")
    db.db.execute("UPDATE enforcement_state SET warningLevel=1 WHERE subjectID='BPLO-1'")
    db.commit()
    review, error = inspections.preview_green_registry_link(31, 'BPLO-1')
    assert error is None
    before = db.rows('SELECT * FROM inspection_reports')
    result, error = inspections.verify_inspection(31, 2, business_id='BPLO-1',
        registry_review_token=review['reviewToken'], confirm_establishment=True)
    assert result is None and error.conflict
    assert db.rows('SELECT * FROM inspection_reports') == before
