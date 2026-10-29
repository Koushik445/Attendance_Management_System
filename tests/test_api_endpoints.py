import os
import sys
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath("backend"))
from app.main import app

client = TestClient(app)


def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"


def test_list_persons():
    res = client.get("/api/persons")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_attendance_stats():
    res = client.get("/api/attendance/stats")
    assert res.status_code == 200
    data = res.json()
    assert "total_enrolled" in data
    assert "attendance_rate_pct" in data


def test_export_csv():
    res = client.get("/api/attendance/export")
    assert res.status_code == 200
    assert "text/csv" in res.headers.get("content-type", "")
    assert "Event ID" in res.text


if __name__ == "__main__":
    test_health()
    print("test_health: PASSED")
    test_list_persons()
    print("test_list_persons: PASSED")
    test_attendance_stats()
    print("test_attendance_stats: PASSED")
    test_export_csv()
    print("test_export_csv: PASSED")
    print("\nALL API TESTS PASSED!")
