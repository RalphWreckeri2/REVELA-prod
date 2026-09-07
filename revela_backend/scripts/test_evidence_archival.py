"""
Unit and integration test for REVELA Evidence Storage & Archival.
Tests:
1. Directory scanning and size calculation in get_evidence_storage_stats
2. Extraction of active photo paths with _extract_photo_filenames
3. Creation of zip archive with manifest.csv and renamed image evidence
4. Safe deletion of physical files and DB photoPath reference updates
"""

import os
import sys
import json
import tempfile
import zipfile
import csv
import io
from datetime import datetime, timedelta
from unittest.mock import MagicMock

# Add revela_backend to path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_dir)

import api.inspections.service as service


def test_extract_photo_filenames():
    print("Testing _extract_photo_filenames...")

    # Case 1: None / empty
    assert service._extract_photo_filenames(None) == []
    assert service._extract_photo_filenames("") == []

    # Case 2: Single string URL
    single = "/api/inspections/public-evidence/test1.jpg"
    assert service._extract_photo_filenames(single) == [single]

    # Case 3: JSON array string
    arr = json.dumps(["/api/inspections/public-evidence/a.jpg", "/api/inspections/public-evidence/b.jpg"])
    assert service._extract_photo_filenames(arr) == [
        "/api/inspections/public-evidence/a.jpg",
        "/api/inspections/public-evidence/b.jpg",
    ]

    # Case 4: Already archived string
    archived_single = "archived://test1.jpg"
    assert service._extract_photo_filenames(archived_single) == []

    # Case 5: Mixed JSON array (one active, one archived)
    mixed = json.dumps(["/api/inspections/public-evidence/active.jpg", "archived://old.jpg"])
    assert service._extract_photo_filenames(mixed) == ["/api/inspections/public-evidence/active.jpg"]

    print("[OK] _extract_photo_filenames passed all cases!")


def test_generate_zip_and_cleanup():
    print("Testing generate_evidence_archive_zip and cleanup_archived_evidence...")

    with tempfile.TemporaryDirectory() as temp_evidence_dir:
        # Create mock image files in temp_evidence_dir
        file1 = os.path.join(temp_evidence_dir, "photo_one.jpg")
        file2 = os.path.join(temp_evidence_dir, "photo_two.jpg")
        with open(file1, "wb") as f:
            f.write(b"MOCK_JPEG_IMAGE_DATA_1" * 1000)
        with open(file2, "wb") as f:
            f.write(b"MOCK_JPEG_IMAGE_DATA_2" * 2000)

        # Mock mysql cursor
        mock_mysql = MagicMock()
        mock_cursor = MagicMock()
        mock_mysql.connection.cursor.return_value = mock_cursor
        service.mysql = mock_mysql

        sample_reports = [
            {
                "reportID": 101,
                "targetID": 501,
                "inspectionResult": "Green",
                "verificationStatus": "Verified",
                "remarks": "Compliant establishment",
                "photoPath": json.dumps(["/api/inspections/public-evidence/photo_one.jpg"]),
                "irTimestamp": (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d %H:%M:%S"),
                "detectedName": "Lomi King Store",
                "barangayName": "Poblacion",
                "inspectorName": "Juan Dela Cruz",
            },
            {
                "reportID": 102,
                "targetID": 502,
                "inspectionResult": "Red",
                "verificationStatus": "Verified",
                "remarks": "Missing sanitary permit",
                "photoPath": json.dumps(["/api/inspections/public-evidence/photo_two.jpg"]),
                "irTimestamp": (datetime.now() - timedelta(days=250)).strftime("%Y-%m-%d %H:%M:%S"),
                "detectedName": "Mataas Cafe",
                "barangayName": "San Sebastian",
                "inspectorName": "Maria Santos",
            },
            {
                "reportID": 103,
                "targetID": 503,
                "inspectionResult": "Yellow",
                "verificationStatus": "Verified",
                "remarks": "Minor display issue, no photo required",
                "photoPath": None,  # No photo attached
                "irTimestamp": (datetime.now() - timedelta(days=210)).strftime("%Y-%m-%d %H:%M:%S"),
                "detectedName": "Mercadal Building",
                "barangayName": "Poblacion",
                "inspectorName": "Juan Dela Cruz",
            },
        ]

        # 1. Test get_evidence_storage_stats
        mock_cursor.fetchall.return_value = sample_reports
        stats, err = service.get_evidence_storage_stats(temp_evidence_dir)
        assert err is None
        assert stats["totalFilesOnDisk"] == 2
        assert stats["categories"]["older_180d"]["reportCount"] == 3
        assert stats["categories"]["older_180d"]["photoCount"] == 2
        print(f"[OK] get_evidence_storage_stats returned: {stats['totalDiskBytes']} bytes, {stats['totalFilesOnDisk']} files")

        # 2. Test generate_evidence_archive_zip
        mock_cursor.fetchall.return_value = sample_reports
        zip_res, zip_err = service.generate_evidence_archive_zip(temp_evidence_dir, "older_180d")
        assert zip_err is None
        zip_path, zip_filename, zip_stats = zip_res
        assert os.path.exists(zip_path)
        assert zip_filename.startswith("REVELA_Evidence_Archive_older_180d_")
        assert zip_stats["archivedPhotos"] == 2
        assert zip_stats["archivedReports"] == 3

        # Verify zip archive contents, html dossier, and manifest
        with zipfile.ZipFile(zip_path, "r") as zf:
            namelist = zf.namelist()
            assert "manifest.csv" in namelist
            assert "README_ARCHIVE.txt" in namelist
            assert "inspection_dossier.html" in namelist

            manifest_content = zf.read("manifest.csv").decode("utf-8-sig")
            reader = list(csv.reader(io.StringIO(manifest_content)))
            header = reader[0]
            assert header[0] == "Report ID"
            assert header[2] == "Business Name"
            assert len(reader) == 4 # Header + 3 report rows!
            assert reader[1][0] == "101"
            assert reader[1][2] == "Lomi King Store"
            assert reader[2][0] == "102"
            assert reader[2][2] == "Mataas Cafe"
            assert reader[3][0] == "103"
            assert reader[3][2] == "Mercadal Building"
            assert reader[3][16] == "No Photo Attached"

            dossier_content = zf.read("inspection_dossier.html").decode("utf-8")
            assert "Mataas Cafe" in dossier_content
            assert "Mercadal Building" in dossier_content
            assert "No Photo Attached" in dossier_content
            assert "Print / Save as PDF" in dossier_content

            # Check that physical evidence files are inside
            evidence_files = [n for n in namelist if n.startswith("evidence/")]
            assert len(evidence_files) == 2
            print(f"[OK] Zip verified successfully with 3 reports (including report without photo) and HTML dossier! Namelist: {namelist}")

        os.remove(zip_path)

        # 3. Test cleanup_archived_evidence
        cleanup_reports = [
            {
                "reportID": 101,
                "photoPath": json.dumps(["/api/inspections/public-evidence/photo_one.jpg"]),
                "irTimestamp": (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d %H:%M:%S"),
            },
            {
                "reportID": 102,
                "photoPath": json.dumps(["/api/inspections/public-evidence/photo_two.jpg"]),
                "irTimestamp": (datetime.now() - timedelta(days=250)).strftime("%Y-%m-%d %H:%M:%S"),
            },
            {
                "reportID": 103,
                "photoPath": None,
                "irTimestamp": (datetime.now() - timedelta(days=210)).strftime("%Y-%m-%d %H:%M:%S"),
            },
        ]
        mock_cursor.fetchall.return_value = cleanup_reports

        assert os.path.isfile(file1)
        assert os.path.isfile(file2)

        clean_res, clean_err = service.cleanup_archived_evidence(temp_evidence_dir, "older_180d")
        assert clean_err is None
        assert clean_res["deletedFiles"] == 2
        assert clean_res["updatedReports"] == 3

        # Verify physical files were deleted
        assert not os.path.isfile(file1)
        assert not os.path.isfile(file2)

        # Verify SQL UPDATE was executed
        update_calls = [call for call in mock_cursor.execute.call_args_list if "UPDATE inspection_reports" in str(call)]
        assert len(update_calls) == 3
        assert "archived://photo_one.jpg" in str(update_calls[0])
        assert "archived://photo_two.jpg" in str(update_calls[1])
        assert "archived://none" in str(update_calls[2])

        print(f"[OK] cleanup_archived_evidence successfully cleared disk and updated database records: {clean_res}")

    print("\nAll Evidence Archival & Cleanup backend tests passed successfully!")


if __name__ == "__main__":
    test_extract_photo_filenames()
    test_generate_zip_and_cleanup()
