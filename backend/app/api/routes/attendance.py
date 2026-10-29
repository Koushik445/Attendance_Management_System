import csv
import io
from datetime import datetime, date, timezone
from fastapi import APIRouter, Depends, Response, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Date

from app.db.database import get_db
from app.db.models import AttendanceEvent, RecognitionEvent, Person, AttendanceEventType
from app.schemas.attendance import AttendanceEventOut, RecognitionEventOut

router = APIRouter(tags=["attendance"])


@router.get("/attendance", response_model=list[AttendanceEventOut])
def list_attendance(
    date_str: str | None = Query(None, description="Date filter YYYY-MM-DD"),
    db: Session = Depends(get_db)
):
    query = db.query(AttendanceEvent).join(Person, AttendanceEvent.person_id == Person.id, isouter=True)
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            query = query.filter(cast(AttendanceEvent.timestamp, Date) == target_date)
        except ValueError:
            pass

    events = query.order_by(AttendanceEvent.timestamp.desc()).all()
    results = []
    for ev in events:
        results.append(AttendanceEventOut(
            id=ev.id,
            person_id=ev.person_id,
            person_name=ev.person.name if ev.person else "Unknown",
            employee_id=ev.person.employee_id if ev.person else None,
            department=ev.person.department if ev.person else None,
            event_type=ev.event_type.value if hasattr(ev.event_type, "value") else str(ev.event_type),
            timestamp=ev.timestamp,
            verification_method=ev.verification_method,
            confidence=ev.confidence,
            recognition_event_id=ev.recognition_event_id,
        ))
    return results


@router.get("/recognition-events", response_model=list[RecognitionEventOut])
def list_recognition_events(
    limit: int = Query(15, ge=1, le=100, description="Max recent events to return"),
    db: Session = Depends(get_db)
):
    """Returns the most recent recognition audit events (default top 15)."""
    return db.query(RecognitionEvent).order_by(RecognitionEvent.timestamp.desc()).limit(limit).all()


@router.get("/attendance/calendar-summary")
def calendar_summary(
    month_str: str | None = Query(None, description="Month filter YYYY-MM"),
    db: Session = Depends(get_db)
):
    """Aggregates attendance counts per day for month-view calendar indicators."""
    now = datetime.now()
    if not month_str:
        month_str = now.strftime("%Y-%m")

    events = db.query(AttendanceEvent).all()
    days_summary: dict[str, dict] = {}

    for ev in events:
        if not ev.timestamp:
            continue
        d_str = ev.timestamp.strftime("%Y-%m-%d")
        if not d_str.startswith(month_str):
            continue
        if d_str not in days_summary:
            days_summary[d_str] = {"persons": set(), "events_count": 0}
        days_summary[d_str]["persons"].add(ev.person_id)
        days_summary[d_str]["events_count"] += 1

    formatted_days = {
        k: {
            "present_count": len(v["persons"]),
            "event_count": v["events_count"]
        }
        for k, v in days_summary.items()
    }

    return {
        "month": month_str,
        "active_days": formatted_days,
    }


@router.get("/attendance/daily")
def daily_attendance(
    date_str: str | None = Query(None, description="Target date YYYY-MM-DD"),
    db: Session = Depends(get_db)
):
    """Calculates daily attendance, campus durations, and in-campus status for a given day."""
    if not date_str:
        date_str = date.today().strftime("%Y-%m-%d")

    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        target_date = date.today()
        date_str = target_date.strftime("%Y-%m-%d")

    day_events = (
        db.query(AttendanceEvent)
        .join(Person, AttendanceEvent.person_id == Person.id, isouter=True)
        .filter(cast(AttendanceEvent.timestamp, Date) == target_date)
        .order_by(AttendanceEvent.timestamp.asc())
        .all()
    )

    # Group events by faculty
    faculty_map: dict[int, dict] = {}
    total_duration_all = 0
    checked_out_count = 0

    for ev in day_events:
        pid = ev.person_id
        p_name = ev.person.name if ev.person else f"Person #{pid}"
        emp_id = ev.person.employee_id if ev.person else "-"
        dept = ev.person.department if ev.person else "-"

        if pid not in faculty_map:
            faculty_map[pid] = {
                "person_id": pid,
                "name": p_name,
                "employee_id": emp_id,
                "department": dept,
                "first_entry": None,
                "last_exit": None,
                "methods": set(),
                "events": [],
                "duration_seconds": 0,
                "duration_text": "-",
                "status": "IN_CAMPUS",
            }

        rec = faculty_map[pid]
        ev_type = ev.event_type.value if hasattr(ev.event_type, "value") else str(ev.event_type)
        if ev.verification_method:
            rec["methods"].add(ev.verification_method)

        rec["events"].append({
            "id": ev.id,
            "type": ev_type,
            "time": ev.timestamp.strftime("%I:%M %p") if ev.timestamp else "-",
            "method": ev.verification_method,
            "confidence": round(ev.confidence or 0.0, 2),
        })

        if ev_type == "ENTRY":
            if rec["first_entry"] is None:
                rec["first_entry"] = ev.timestamp
            rec["status"] = "IN_CAMPUS"
        elif ev_type == "EXIT":
            rec["last_exit"] = ev.timestamp
            rec["status"] = "CHECKED_OUT"

    # Compute duration for each faculty
    now_utc = datetime.now(timezone.utc)
    for pid, rec in faculty_map.items():
        first_e = rec["first_entry"]
        last_x = rec["last_exit"]

        if first_e and last_x:
            diff_secs = max(0, int((last_x - first_e).total_seconds()))
            rec["duration_seconds"] = diff_secs
            hrs = diff_secs // 3600
            mins = (diff_secs % 3600) // 60
            rec["duration_text"] = f"{hrs}h {mins}m" if hrs > 0 else f"{mins}m"
            total_duration_all += diff_secs
            checked_out_count += 1
        elif first_e and rec["status"] == "IN_CAMPUS":
            # Still in campus: live elapsed duration
            fe = first_e
            if fe.tzinfo is None:
                fe = fe.replace(tzinfo=timezone.utc)
            diff_secs = max(0, int((now_utc - fe).total_seconds()))
            hrs = diff_secs // 3600
            mins = (diff_secs % 3600) // 60
            rec["duration_text"] = f"{hrs}h {mins}m (live)" if hrs > 0 else f"{mins}m (live)"
            rec["duration_seconds"] = diff_secs

        rec["methods"] = list(rec["methods"])
        rec["first_entry_time"] = first_e.strftime("%I:%M %p") if first_e else "-"
        rec["last_exit_time"] = last_x.strftime("%I:%M %p") if last_x else ("In Campus" if first_e else "-")

    faculty_list = list(faculty_map.values())
    in_campus_count = sum(1 for f in faculty_list if f["status"] == "IN_CAMPUS")

    avg_secs = (total_duration_all // checked_out_count) if checked_out_count > 0 else 0
    avg_hrs = avg_secs // 3600
    avg_mins = (avg_secs % 3600) // 60
    avg_duration_text = f"{avg_hrs}h {avg_mins}m" if avg_hrs > 0 else (f"{avg_mins}m" if avg_mins > 0 else "-")

    return {
        "date": date_str,
        "summary": {
            "total_present": len(faculty_list),
            "in_campus": in_campus_count,
            "checked_out": checked_out_count,
            "total_events": len(day_events),
            "avg_campus_duration": avg_duration_text,
        },
        "records": faculty_list,
    }


@router.get("/attendance/stats")
def attendance_stats(db: Session = Depends(get_db)):
    total_persons = db.query(func.count(Person.id)).scalar() or 0
    total_attendance = db.query(func.count(AttendanceEvent.id)).scalar() or 0

    today_start = datetime.combine(date.today(), datetime.min.time())
    today_events = db.query(AttendanceEvent).filter(AttendanceEvent.timestamp >= today_start).all()
    today_count = len(today_events)
    unique_present_today = len(set(e.person_id for e in today_events))

    method_counts = {}
    for e in db.query(AttendanceEvent.verification_method, func.count(AttendanceEvent.id)).group_by(AttendanceEvent.verification_method).all():
        method_counts[e[0]] = e[1]

    arrival_counts = {}
    for r in db.query(RecognitionEvent.arrival_type, func.count(RecognitionEvent.id)).group_by(RecognitionEvent.arrival_type).all():
        arrival_counts[str(r[0].value if hasattr(r[0], "value") else r[0])] = r[1]

    attendance_pct = round((unique_present_today / total_persons * 100) if total_persons > 0 else 0.0, 1)

    return {
        "total_enrolled": total_persons,
        "today_attendance": today_count,
        "unique_present_today": unique_present_today,
        "attendance_rate_pct": attendance_pct,
        "total_attendance_events": total_attendance,
        "method_breakdown": method_counts,
        "arrival_breakdown": arrival_counts,
    }


@router.get("/attendance/export")
def export_attendance_csv(
    date_str: str | None = Query(None, description="Optional date filter YYYY-MM-DD"),
    db: Session = Depends(get_db)
):
    query = (
        db.query(AttendanceEvent, Person)
        .outerjoin(Person, AttendanceEvent.person_id == Person.id)
    )
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            query = query.filter(cast(AttendanceEvent.timestamp, Date) == target_date)
        except ValueError:
            pass

    events = query.order_by(AttendanceEvent.timestamp.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Event ID", "Timestamp", "Person ID", "Employee ID",
        "Faculty Name", "Department", "Event Type",
        "Verification Method", "Confidence Score"
    ])

    for ev, person in events:
        writer.writerow([
            ev.id,
            ev.timestamp.strftime("%Y-%m-%d %H:%M:%S") if ev.timestamp else "",
            ev.person_id,
            person.employee_id if person else "",
            person.name if person else "Unknown",
            person.department if person else "",
            ev.event_type.value if hasattr(ev.event_type, "value") else str(ev.event_type),
            ev.verification_method,
            f"{ev.confidence:.3f}" if ev.confidence is not None else "",
        ])

    csv_data = output.getvalue()
    date_suffix = date_str or datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"attendance_export_{date_suffix}.csv"
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

