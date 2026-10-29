# Faculty Attendance Management System — Execution & User Guide

## 1. Start the Backend API (Terminal 1)
```powershell
cd d:\Attendance_Management_System\backend
.\venv\Scripts\activate
uvicorn app.main:app --reload --port 8000
```
* **Health Check:** http://127.0.0.1:8000/health
* **API Documentation (Swagger UI):** http://127.0.0.1:8000/docs

---

## 2. Start the Frontend Web UI (Terminal 2)
```powershell
cd d:\Attendance_Management_System\frontend
python -m http.server 5500
```
* **Dashboard & Kiosk UI:** http://127.0.0.1:5500

---

## 3. Managing Faculty & Candidates

### Enroll New Faculty
1. In the web UI, open the **Enroll Faculty** tab.
2. Enter **Full Name**, **Employee ID**, **Department**, and optional **Vehicle Plate**.
3. Upload a clear frontal photo or capture one with your webcam.
4. Click **Complete Faculty Enrollment** — the system automatically extracts and registers your 512D ArcFace facial embedding into PostgreSQL `pgvector`.

### Edit Registered Faculty
1. Open the **Faculty Directory** tab.
2. Find the candidate in the table and click the **✏️ Edit** button.
3. Update their Name, Employee ID, Department, Status (`ACTIVE`/`INACTIVE`), or Vehicle Plate.
4. *(Optional)* Upload a new face photo if you want to update their facial biometrics.
5. Click **💾 Save Changes**.

---

## 4. Attendance Verification Workflow (Check-In / Check-Out)

1. Navigate to **Verify Attendance**.
2. Select **Arrival Mode** (`Auto Detect`, `Walking`, `Car`, or `Bike`):
   * **Walking:** Only your face image/webcam snapshot is required.
   * **Car / Bike:** Requires face + vehicle plate image.
3. Select **Attendance Direction (Action Mode)**:
   * **🔄 Smart Auto:** Automatically checks in if not on campus, or checks out if already checked in today.
   * **🟢 Check-In (ENTRY):** Explicit check-in.
   * **🔴 Check-Out (EXIT):** Explicit check-out — the system automatically calculates and displays your **total dwell duration on campus**!
4. Click **Verify Attendance**.
   * If biometrics match: **ENTRY / EXIT RECORDED — VERIFIED**.
   * On Exit: Displays your total campus duration (e.g. `1h 47m`).
   * If a signal is ambiguous/conflicting: Prompts for Employee ID / ID Card text as an instant fallback.

---

## 5. Calendar & Daily Attendance Log

1. Open the **Attendance Log** tab.
2. Use the **Interactive Calendar Month Grid**:
   * Days with verified attendance show presence indicators (e.g. `👥 3`).
   * Click any date (or jump with the Date Picker) to view that day's attendance.
3. **Daily Summary Dashboard**:
   * View **Total Present**, **Currently In Campus**, **Checked Out**, and **Average Campus Duration**.
   * Table displays First Entry time, Last Exit time, Live Campus Duration, and status (`IN CAMPUS` or `CHECKED OUT`).
   * Download a dedicated day CSV report with **Export Day CSV**.

---

## 6. Recognition Audit Trail (Top 15 Recent)

* Open the **Recognition History** tab to view the 15 most recent biometric scans, detection scores, and fusion decisions.

