# Faculty Attendance Management System — Prototype

Multimodal attendance verification (face / face+plate / face+plate+ID) built
incrementally. This README currently covers **Phases 0–4**.

## Project layout so far

```
Attendance_Management_System/
  backend/
    app/
      main.py                 # FastAPI entrypoint
      core/config.py          # all settings/thresholds, env-driven
      db/database.py          # SQLAlchemy engine/session
      db/models.py            # persons, face_embeddings, vehicles, id_cards,
                               #   recognition_events, attendance_events
      services/face_service.py# InsightFace load-once + pgvector recognition
      api/routes/persons.py   # GET /api/persons, /api/persons/{id}
      api/routes/verify.py    # POST /api/verify/face
      schemas/                # pydantic request/response models
    migrations/                # Alembic
    requirements.txt
  frontend/
    index.html, css/style.css, js/app.js   # Verify page (face-only for now)
  ml/
    face_recognition/
      enrollment.py            # builds embeddings from Image_Train
      recognize.py             # CLI: recognize one image
      evaluate.py               # accuracy/confusion matrix on Image_Test
  scripts/
    seed_demo_database.py     # imports demo persons/vehicles/id_cards
    clear_demo_database.py    # wipes demo data
  datasets/                    # <-- put your dataset here (see below)
  results/                     # evaluation CSVs land here
  .env.example
```

## 1. Put your dataset in place

Copy your existing dataset folders so the structure looks like this
(matches what you already have):

```
datasets/
  face_dataset/
    Image_Train/<NAME>/<NAME>_1.jpeg ... _14.jpeg
    Image_Test/<NAME>/
        <NAME>_15.jpeg ... _20.jpeg
        car_image_<NAME>.jpg
        car_number_<NAME>.txt
        id_<NAME>.txt
  number_plate_dataset/
    train/images/... , train/labels.csv
    test/images/...  , test/labels.csv
```

(The `number_plate_dataset` isn't used until the ANPR phase — you don't need
it yet for Phases 0–4.)

## 2. Set up a Neon Postgres database

1. Create a free project at https://neon.tech
2. Copy the connection string it gives you (looks like
   `postgresql://user:pass@ep-xxxx.neon.tech/dbname?sslmode=require`)
3. Connect to it once (Neon's SQL editor, or `psql`) and run:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
   This enables pgvector, used for face embedding similarity search.

## 3. Configure environment variables

```bash
cd Attendance_Management_System
cp .env.example .env
```
Edit `.env` and set `DATABASE_URL` to your Neon connection string. The
dataset paths in `.env.example` already match the layout above — leave them
as-is unless you moved things.

## 4. Install dependencies

```bash
cd backend
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

This installs FastAPI/SQLAlchemy/Alembic **and** InsightFace/onnxruntime/
opencv (needed from Phase 3 onward). InsightFace will auto-download its
`buffalo_l` model weights (~350MB) the first time it runs — that happens
locally on your machine, not during `pip install`.

## 5. Create the database tables

Two options:

**Quick (dev-only):** the seed script (next step) auto-creates tables the
first time it runs via `Base.metadata.create_all()`.

**Proper (recommended once things stabilize):**
```bash
cd backend
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

## 6. Seed the demo database

From the **project root** (not `backend/`):

```bash
python scripts/seed_demo_database.py --dry-run   # preview, no writes
python scripts/seed_demo_database.py             # actually writes
```

Expected output (10-person dataset example):
```
Discovered 10 demo people in .../Image_Train: ['ABHAY', 'Aditi', ...]
  [OK] person DEMO001 -> ABHAY (id=1)
  [OK] vehicle AP39KA3617 -> ABHAY
  [OK] id_card DEMO001 -> ABHAY
  ...
--- Summary ---
Persons:  created=10 skipped=0
Vehicles: created=10 skipped=0
ID cards: created=10 skipped=0
```

To start over later (e.g. before loading real faculty data):
```bash
python scripts/clear_demo_database.py
```

## 7. Enroll faces (builds embeddings from Image_Train)

```bash
python ml/face_recognition/enrollment.py
```

Expected output per person:
```
ABHAY (person_id=1): 14 training images
  [OK] Enrolled: ABHAY_1.jpeg (det_score=0.998)
  ...
--- Enrollment summary ---
Images processed: 140
Embeddings stored: 140
No-face-detected images: 0
```

If `No-face-detected images` is high, check image quality/cropping — this
number is reported honestly, not hidden.

## 8. Evaluate face recognition (Image_Test)

```bash
python ml/face_recognition/evaluate.py
```

This writes `results/face_results.csv` and prints overall accuracy,
per-person accuracy, and a confusion matrix. **Whatever number comes out is
the real number** — if accuracy is low we'll diagnose it (bad crops, wrong
model pack, thresholds) rather than assume the pipeline is fine.

Quick single-image sanity check any time:
```bash
python ml/face_recognition/recognize.py datasets/face_dataset/Image_Test/ABHAY/ABHAY_15.jpeg
```

## 9. Run the backend API

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Visit http://127.0.0.1:8000/health → `{"status":"ok",...}`
Visit http://127.0.0.1:8000/docs → interactive Swagger UI, try
`GET /api/persons` and `POST /api/verify/face` (upload a test image) there
directly if you want to check the API before touching the UI.

## 10. Run the frontend

The frontend is static HTML/CSS/JS — no build step. Simplest option:

```bash
cd frontend
python -m http.server 5500
```
Then open http://127.0.0.1:5500 in your browser. Make sure the backend
(`uvicorn`, step 9) is running at the same time — `js/app.js` calls
`http://127.0.0.1:8000/api`.

Upload one of the `Image_Test/<NAME>/<NAME>_15..20.jpeg` files and click
**Verify Face**. You should see the predicted identity, similarity score,
and a HIGH/MEDIUM/LOW confidence badge.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `pydantic_core.ValidationError: DATABASE_URL field required` | `.env` missing or not at project root — re-check step 3 |
| `sqlalchemy.exc.ProgrammingError: type "vector" does not exist` | Run `CREATE EXTENSION IF NOT EXISTS vector;` on your Neon DB (step 2) |
| `ModuleNotFoundError: No module named 'app'` | Run scripts from the **project root**, not from inside `scripts/` or `ml/` |
| Enrollment reports many `No face detected` | Check the images actually open/are valid JPEGs; try a lower-res or better-lit sample first |
| CORS error in browser console | Add your frontend's origin (e.g. `http://127.0.0.1:5500`) to `CORS_ORIGINS` in `.env` and restart uvicorn |
| InsightFace model download hangs/fails | Needs outbound internet access on first run only; retry, or check firewall/proxy |
| `uvicorn` starts but `/api/verify/face` 500s the first time | Check the server log — `insightface`/`onnxruntime` install issue is the most common cause; re-run `pip install -r requirements.txt` |

## What's NOT built yet (upcoming phases)

- YOLO-based arrival-type detection (WALKING / CAR / BIKE)
- Number-plate detection + OCR (ANPR) + its evaluation script
- ID-card OCR-text verification module
- The route-aware fusion/decision engine
- Combined `/api/verify` endpoint, recognition/attendance history, full
  dashboard UI
- End-to-end automated test-case script

---

# Phases 5–10 — Full System

Everything below extends the Phase 0–4 setup above. Re-run `pip install -r
requirements.txt` first (new ML dependencies were added).

## 11. Install the remaining ML dependencies

```bash
cd backend
pip install -r requirements.txt   # now also installs ultralytics + easyocr
```

- **YOLO (arrival detection)**: `ultralytics` auto-downloads `yolov8n.pt`
  (COCO-pretrained, ~6MB) the first time it's used - no manual download
  needed for arrival routing.
- **EasyOCR**: downloads its English text-recognition weights (~50-100MB)
  the first time `get_ocr_reader()` runs.
- **Plate detector**: there is *no* generic pretrained plate detector
  bundled with `ultralytics`/OpenCV, and — since you don't have any
  annotated plate images — fine-tuning your own is off the table for now.
  Good news: **you don't need annotations at all.** An already-trained
  YOLOv8 license-plate detector is freely available and installs with one
  command:

  ```bash
  pip install huggingface_hub
  python scripts/download_plate_model.py
  ```

  This downloads `best.pt` from the public
  [`Koushim/yolov8-license-plate-detection`](https://huggingface.co/Koushim/yolov8-license-plate-detection)
  model (YOLOv8n, single `license_plate` class, MIT licensed, 19k+
  downloads on Hugging Face) and saves it to
  `PLATE_DETECTOR_MODEL_PATH` (default `models/plate_detector.pt`).
  `anpr_service.py` automatically prefers it over the Haar-cascade fallback
  as soon as the file exists there — no code changes needed. If you'd
  rather use a different pretrained checkpoint, just download its `.pt`
  file yourself and place it at the same path.

  Until you run this script, the system uses the Haar-cascade fallback
  (bundled with OpenCV, no download needed) so the pipeline still runs
  end-to-end — just with weaker detection accuracy, which `evaluate.py`
  will report honestly.

## 12. Arrival-type detection (Phase 5)

```bash
python ml/arrival/arrival_router.py path/to/scene_image.jpg
```
Expected output: a JSON blob with `arrival_type`, `detected_objects`
(person/car/motorcycle/bicycle boxes + confidences), `confidence`, and a
plain-English `reason`.

This uses a scene image containing a person (optionally near a vehicle).
The demo dataset's face images are close-ups without a vehicle in frame -
for a realistic test, use `car_image_<NAME>.jpg` from `Image_Test` (it may
or may not contain a visible person depending on the source photo) or any
photo you have of a person near a car/bike.

## 13. ANPR — plate detection + OCR (Phase 6)

Quick single-image checks:
```bash
python ml/anpr/detect_plate.py datasets/face_dataset/Image_Test/ABHAY/car_image_ABHAY.jpg
python ml/anpr/ocr.py datasets/face_dataset/Image_Test/ABHAY/car_image_ABHAY.jpg
```

Full evaluation against `Number Plate dataset/test`:
```bash
python ml/anpr/evaluate.py
python ml/anpr/evaluate.py --limit 50    # quick smoke test on 50 images first
```
Writes `results/anpr_results.csv` (per-image) and `results/anpr_summary.json`
(aggregate — read by the System Status page). Reports detection success
rate, exact-match accuracy, character-level accuracy, and character error
rate **honestly** — a low score with the Haar fallback is an expected,
correctly-reported result, not a bug.

## 14. ID card verification (Phase 7)

No script to run — it's a pure DB-lookup function
(`app/services/id_card_service.py`) exercised through the API
(`POST /api/verify/id-card`) or the combined `/api/verify` endpoint. Text
is normalized (uppercase, alphanumeric-only) before comparison, so
`"DEMO001"`, `"demo-001"`, and the dataset's `id_<NAME>.txt` contents all
match consistently.

## 15. Fusion / decision engine (Phase 8)

`fusion/decision_engine.py` is a pure function — no image/DB/ML imports —
that implements the route-specific policy table from the spec (minimum
necessary evidence, conflict → ID request or manual review, never
auto-verify on conflicting evidence). `backend/app/services/fusion_service.py`
is the thin adapter that feeds it your configured thresholds from `.env`.

Test it directly (no server/DB/dataset needed):
```bash
python tests/test_demo_scenarios.py
```
Expected output: a table of all 10 demo scenarios from the spec (WALKING+
good face, CAR+conflicting evidence, ALL THREE CONFLICT, etc.) each showing
PASS/FAIL, the decision, the verification method actually used, and why —
ending in `10/10 scenarios matched expected decision + verification method.`

## 16. The full backend + frontend (Phase 9)

Restart the backend (it now loads 3 models at startup — face, YOLO, OCR —
so the first `uvicorn` start will take longer and each will print its own
`[startup]` line, or a `[startup][WARN]` if that dependency isn't installed
yet without blocking the others):
```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Restart/refresh the frontend (`cd frontend && python -m http.server 5500`,
open http://127.0.0.1:5500). You now have all 7 pages:

- **Dashboard** — live counts + recent attendance
- **Verify Attendance** — pick arrival type (or Auto Detect), upload
  face/vehicle images, submit; if the system asks for it, enter ID Card OCR
  text and submit again. Full evidence panel with Face / Plate / ID Card /
  Final Decision, matching the spec's mock exactly, including live
  "ENTRY RECORDED" confirmation.
- **Persons / Vehicles** — read-only tables from the DB
- **Recognition History** — every verification attempt ever made, with
  decision badges
- **Attendance History** — every recorded ENTRY/EXIT
- **System Status** — which models are loaded, which plate detector is
  active, the latest face/ANPR evaluation numbers, and **Seed Demo Data /
  Clear Demo Data** buttons (same logic as the CLI scripts, now in the UI)

## 17. Try the full demo workflow end-to-end

1. System Status page → **Seed Demo Data** (or `python scripts/seed_demo_database.py`)
2. `python ml/face_recognition/enrollment.py`
3. Verify Attendance page → Arrival = **Car** → upload an `Image_Test/<NAME>/<NAME>_15..20.jpeg`
   as the face image and `car_image_<NAME>.jpg` as the vehicle image → Verify
4. If confidence is high enough: **VERIFIED**, method `FACE+PLATE`, attendance
   ENTRY recorded — check the Attendance History page.
5. If it asks for additional verification: open `id_<NAME>.txt` from that
   person's `Image_Test` folder, paste its contents into the ID Card field,
   click Verify Attendance again → method becomes `FACE+PLATE+ID`.

## Troubleshooting (Phases 5–10)

| Symptom | Likely cause / fix |
|---|---|
| ANPR accuracy very low / `detector_used: haar_fallback` everywhere | Expected without a real plate-detector model — see step 11. Report it honestly; don't hide it. |
| `/api/verify` 400 "vehicle_image is required" | You selected/auto-detected CAR or BIKE but didn't upload a vehicle image |
| Arrival Auto Detect always says WALKING | The uploaded image may not contain a clearly visible vehicle near the person, or YOLO confidence is low on that specific photo — try a clearer scene image, or manually select Car/Bike as the debug fallback (built into the UI, per spec) |
| System Status page: "Not evaluated yet" | Run `ml/face_recognition/evaluate.py` and/or `ml/anpr/evaluate.py` at least once — their summary JSON files feed this page |
| `POST /api/admin/clear-demo` returns `{"ok": false, ...}` | You must call it with `?confirm=true` (the UI button already does this with a confirm dialog) |
| First `/api/verify` call after server start is slow | Models load lazily on first use per modality if they weren't preloaded successfully at startup — check server logs for `[startup][WARN]` lines |
| Fusion test script fails | `fusion/decision_engine.py` is pure Python with no external deps — a failure here means the policy logic itself needs a look, not an environment issue |

## Final project structure

```
Attendance_Management_System/
  backend/app/
    main.py, core/config.py
    db/{database.py, models.py}
    services/
      face_service.py       arrival_service.py     anpr_service.py
      id_card_service.py    fusion_service.py       admin_service.py
    api/routes/
      persons.py  verify.py  vehicles.py  attendance.py  admin.py  status.py
    schemas/
  frontend/            (7-page single-file app: index.html + css/ + js/)
  ml/
    face_recognition/  {enrollment,recognize,evaluate}.py
    anpr/              {detect_plate,ocr,evaluate}.py
    arrival/           arrival_router.py (CLI wrapper)
  fusion/decision_engine.py     (pure policy logic, no ML/DB imports)
  scripts/           seed_demo_database.py, clear_demo_database.py
  tests/             test_demo_scenarios.py
  results/           face_results.csv, face_summary.json,
                      anpr_results.csv, anpr_summary.json
  datasets/          <- your dataset goes here
```

