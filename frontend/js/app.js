// Point this at your running backend
const API_BASE = "http://127.0.0.1:8000/api";

// ---------------------------------------------------------------------------
// Client-side Page Router
// ---------------------------------------------------------------------------
const pages = ["dashboard", "verify", "enroll", "persons", "vehicles", "recognition", "attendance", "status"];
let activeWebcamStream = null;
let activeEnrollWebcamStream = null;

function showPage(name) {
  // Stop webcam streams when leaving relevant pages to save power/camera
  if (name !== "verify") stopWebcam();
  if (name !== "enroll") stopEnrollWebcam();

  pages.forEach((p) => {
    const el = document.getElementById(`page-${p}`);
    if (el) el.classList.toggle("active", p === name);
  });

  document.querySelectorAll(".nav-link").forEach((link) => {
    link.classList.toggle("active", link.dataset.page === name);
  });

  const loader = pageLoaders[name];
  if (loader) loader();
}

document.getElementById("navLinks").addEventListener("click", (e) => {
  const link = e.target.closest(".nav-link");
  if (!link) return;
  e.preventDefault();
  showPage(link.dataset.page);
});

const btnGotoEnroll = document.getElementById("btnGotoEnroll");
if (btnGotoEnroll) {
  btnGotoEnroll.addEventListener("click", () => showPage("enroll"));
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
async function apiGet(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`GET ${path} failed (${res.status})`);
  return res.json();
}

function fmtDate(iso) {
  if (!iso) return "-";
  return new Date(iso).toLocaleString();
}

function renderTable(container, columns, rows, emptyMessage) {
  if (!rows || rows.length === 0) {
    container.innerHTML = `<p class="muted" style="padding: 16px;">${emptyMessage}</p>`;
    return;
  }
  const thead = `<tr>${columns.map((c) => `<th>${c.label}</th>`).join("")}</tr>`;
  const tbody = rows
    .map((row) => `<tr>${columns.map((c) => `<td>${c.render ? c.render(row) : (row[c.key] ?? "-")}</td>`).join("")}</tr>`)
    .join("");
  container.innerHTML = `<table><thead>${thead}</thead><tbody>${tbody}</tbody></table>`;
}

function statusPill(decision) {
  return `<span class="status-pill ${decision}"><span class="pulse-dot" style="width:6px;height:6px;"></span>${decision}</span>`;
}

// ---------------------------------------------------------------------------
// 1. Dashboard & Analytics (Chart.js)
// ---------------------------------------------------------------------------
let methodsChartInstance = null;
let arrivalChartInstance = null;

async function loadDashboard() {
  const recentEl = document.getElementById("dashboardRecent");
  recentEl.innerHTML = `<p class="muted" style="padding: 16px;">Loading attendance records...</p>`;

  try {
    const [stats, status, attendance] = await Promise.all([
      apiGet("/attendance/stats").catch(() => null),
      apiGet("/status").catch(() => null),
      apiGet("/attendance").catch(() => []),
    ]);

    // Top KPIs
    const enrolled = stats ? stats.total_enrolled : (status ? status.counts.persons : 0);
    const presentToday = stats ? stats.unique_present_today : 0;
    const rateToday = stats ? stats.attendance_rate_pct : 0;
    const vehicles = status ? status.counts.vehicles : 0;

    document.getElementById("statEnrolled").textContent = enrolled;
    document.getElementById("statPresentToday").textContent = presentToday;
    document.getElementById("statRateToday").textContent = `${rateToday}%`;
    document.getElementById("statVehicles").textContent = vehicles;

    // Charts rendering with Chart.js
    renderDashboardCharts(stats);

    // Recent table
    renderTable(
      recentEl,
      [
        { label: "Timestamp", render: (r) => fmtDate(r.timestamp) },
        { label: "Person ID", key: "person_id" },
        { label: "Event", key: "event_type" },
        { label: "Verification Method", render: (r) => `<span class="badge-sm">${r.verification_method}</span>` },
        { label: "Confidence", render: (r) => (r.confidence != null ? `${(r.confidence * 100).toFixed(1)}%` : "-") },
      ],
      attendance.slice(0, 8),
      "No attendance recorded yet — run a verification on the Kiosk page."
    );
  } catch (err) {
    recentEl.innerHTML = `<p class="muted" style="padding: 16px;">Could not load dashboard: ${err.message}. Is the backend running?</p>`;
  }
}

document.getElementById("refreshDashboardBtn").addEventListener("click", () => {
  loadDashboard();
});

function renderDashboardCharts(stats) {
  const methodsCanvas = document.getElementById("methodsChart");
  const arrivalCanvas = document.getElementById("arrivalChart");
  if (!methodsCanvas || !arrivalCanvas || !window.Chart) return;

  // 1. Methods Chart
  const methodData = stats && stats.method_breakdown ? stats.method_breakdown : { "FACE": 5, "FACE+PLATE": 8, "FACE+PLATE+ID": 2 };
  const methodLabels = Object.keys(methodData);
  const methodValues = Object.values(methodData);

  if (methodsChartInstance) methodsChartInstance.destroy();
  methodsChartInstance = new Chart(methodsCanvas, {
    type: "doughnut",
    data: {
      labels: methodLabels.length ? methodLabels : ["None"],
      datasets: [{
        data: methodValues.length ? methodValues : [1],
        backgroundColor: ["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6"],
        borderWidth: 0,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "bottom", labels: { color: "#94a3b8", font: { family: "Inter", size: 11 } } },
      },
      cutout: "70%",
    }
  });

  // 2. Arrival Chart
  const arrivalData = stats && stats.arrival_breakdown ? stats.arrival_breakdown : { "WALKING": 4, "CAR": 9, "BIKE": 2 };
  const arrivalLabels = Object.keys(arrivalData);
  const arrivalValues = Object.values(arrivalData);

  if (arrivalChartInstance) arrivalChartInstance.destroy();
  arrivalChartInstance = new Chart(arrivalCanvas, {
    type: "doughnut",
    data: {
      labels: arrivalLabels.length ? arrivalLabels : ["None"],
      datasets: [{
        data: arrivalValues.length ? arrivalValues : [1],
        backgroundColor: ["#6366f1", "#ec4899", "#14b8a6", "#eab308"],
        borderWidth: 0,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "bottom", labels: { color: "#94a3b8", font: { family: "Inter", size: 11 } } },
      },
      cutout: "70%",
    }
  });
}

// ---------------------------------------------------------------------------
// 2. Verify Attendance (Webcam & Upload Kiosk)
// ---------------------------------------------------------------------------
let selectedArrival = "AUTO";
let selectedEventType = "AUTO";
let selectedFaceFile = null;
let selectedVehicleFile = null;
let lastCapturedBlob = null;

const arrivalPills = document.querySelectorAll("#arrivalPills .pill");
const eventTypePills = document.querySelectorAll("#eventTypePills .pill");
const vehicleField = document.getElementById("vehicleField");
const idCardField = document.getElementById("idCardField");
const idCardInput = document.getElementById("idCardInput");
const submitIdBtn = document.getElementById("submitIdBtn");

if (eventTypePills) {
  eventTypePills.forEach((pill) => {
    pill.addEventListener("click", () => {
      eventTypePills.forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");
      selectedEventType = pill.dataset.event;
    });
  });
}


const btnModeWebcam = document.getElementById("btnModeWebcam");
const btnModeUpload = document.getElementById("btnModeUpload");
const webcamContainer = document.getElementById("webcamContainer");
const uploadContainer = document.getElementById("uploadContainer");
const startCamBtn = document.getElementById("startCamBtn");
const snapVerifyBtn = document.getElementById("snapVerifyBtn");
const webcamVideo = document.getElementById("webcamVideo");
const captureCanvas = document.getElementById("captureCanvas");
const kioskStatus = document.getElementById("kioskStatus");

// Mode Switcher
btnModeWebcam.addEventListener("click", () => {
  btnModeWebcam.classList.add("active");
  btnModeUpload.classList.remove("active");
  webcamContainer.hidden = false;
  uploadContainer.hidden = true;
});

btnModeUpload.addEventListener("click", () => {
  btnModeUpload.classList.add("active");
  btnModeWebcam.classList.remove("active");
  uploadContainer.hidden = false;
  webcamContainer.hidden = true;
  stopWebcam();
});

// Webcam Controls
startCamBtn.addEventListener("click", async () => {
  if (activeWebcamStream) {
    stopWebcam();
    return;
  }
  try {
    startCamBtn.textContent = "⌛ Connecting...";
    activeWebcamStream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "user" },
      audio: false,
    });
    webcamVideo.srcObject = activeWebcamStream;
    startCamBtn.textContent = "⏹️ Stop Camera";
    snapVerifyBtn.disabled = false;
    kioskStatus.innerHTML = `<span class="status-badge live"><span class="pulse-dot"></span> Camera Active</span>`;
  } catch (err) {
    alert(`Could not start webcam: ${err.message}. Please check browser camera permissions.`);
    startCamBtn.textContent = "▶️ Start Camera";
    snapVerifyBtn.disabled = true;
  }
});

function stopWebcam() {
  if (activeWebcamStream) {
    activeWebcamStream.getTracks().forEach((t) => t.stop());
    activeWebcamStream = null;
  }
  if (webcamVideo) webcamVideo.srcObject = null;
  if (startCamBtn) startCamBtn.textContent = "▶️ Start Camera";
  if (snapVerifyBtn) snapVerifyBtn.disabled = true;
  if (kioskStatus) kioskStatus.innerHTML = `<span class="status-badge ready">Ready to Scan</span>`;
}

// Snapshot & Verify from Webcam
snapVerifyBtn.addEventListener("click", () => {
  if (!activeWebcamStream) return;
  captureCanvas.width = webcamVideo.videoWidth || 640;
  captureCanvas.height = webcamVideo.videoHeight || 480;
  const ctx = captureCanvas.getContext("2d");
  // Mirror un-inversion
  ctx.translate(captureCanvas.width, 0);
  ctx.scale(-1, 1);
  ctx.drawImage(webcamVideo, 0, 0, captureCanvas.width, captureCanvas.height);

  captureCanvas.toBlob(async (blob) => {
    if (!blob) return;
    lastCapturedBlob = blob;
    const file = new File([blob], "webcam_face.jpg", { type: "image/jpeg" });
    executeVerification(file, selectedVehicleFile, idCardInput.value.trim());
  }, "image/jpeg", 0.95);
});

// Arrival Pills
function updateVehicleFieldVisibility() {
  if (vehicleField) {
    vehicleField.style.display = selectedArrival === "WALKING" ? "none" : "block";
  }
}

arrivalPills.forEach((pill) => {
  pill.addEventListener("click", () => {
    arrivalPills.forEach((p) => p.classList.remove("active"));
    pill.classList.add("active");
    selectedArrival = pill.dataset.arrival;
    updateVehicleFieldVisibility();
  });
});
updateVehicleFieldVisibility();

// File Upload Wiring
function wireUpload(inputId, previewId, textId, onSelect) {
  const input = document.getElementById(inputId);
  const preview = document.getElementById(previewId);
  const text = document.getElementById(textId);
  if (!input) return;
  input.addEventListener("change", () => {
    const file = input.files[0];
    if (!file) return;
    onSelect(file);
    const reader = new FileReader();
    reader.onload = (e) => {
      preview.src = e.target.result;
      preview.hidden = false;
      text.hidden = true;
    };
    reader.readAsDataURL(file);
  });
}

wireUpload("faceInput", "facePreview", "faceUploadText", (f) => (selectedFaceFile = f));
wireUpload("vehicleInput", "vehiclePreview", "vehicleUploadText", (f) => (selectedVehicleFile = f));

// Verify Upload Button
const verifyBtn = document.getElementById("verifyBtn");
if (verifyBtn) {
  verifyBtn.addEventListener("click", () => {
    if (!selectedFaceFile) {
      alert("Please upload or capture a face image first.");
      return;
    }
    executeVerification(selectedFaceFile, selectedVehicleFile, idCardInput.value.trim());
  });
}

// Execute Verification API Call
const resultPanel = document.getElementById("resultPanel");

async function executeVerification(faceFile, vehicleFile, idCardText) {
  if (verifyBtn) { verifyBtn.disabled = true; verifyBtn.textContent = "Verifying Biometrics..."; }
  if (snapVerifyBtn) { snapVerifyBtn.disabled = true; snapVerifyBtn.textContent = "Analyzing..."; }
  resultPanel.hidden = true;

  try {
    const formData = new FormData();
    formData.append("arrival_type", selectedArrival);
    formData.append("event_type", selectedEventType);
    formData.append("face_image", faceFile);
    if (vehicleFile) formData.append("vehicle_image", vehicleFile);
    if (idCardText) formData.append("id_card_text", idCardText);

    const res = await fetch(`${API_BASE}/verify`, { method: "POST", body: formData });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `Server error (${res.status})`);
    }

    const data = await res.json();
    renderVerificationResult(data);
  } catch (err) {
    alert(`Verification failed: ${err.message}`);
  } finally {
    if (verifyBtn) { verifyBtn.disabled = false; verifyBtn.textContent = "Verify Attendance (Uploaded Files)"; }
    if (snapVerifyBtn) { snapVerifyBtn.disabled = false; snapVerifyBtn.textContent = "📸 Capture & Verify Now"; }
  }
}

// Render Result Card
function renderVerificationResult(data) {
  resultPanel.hidden = false;
  const isVerified = data.decision === "VERIFIED";
  const needsId = data.requires_additional_verification;
  const isExit = data.event_type === "EXIT";
  const panelClass = isVerified ? "verified" : needsId ? "needs-id" : "rejected";

  resultPanel.className = `result-panel ${panelClass}`;

  // Toggle ID card field if additional verification is requested
  if (needsId) {
    idCardField.hidden = false;
    idCardInput.focus();
  } else {
    idCardField.hidden = true;
  }

  const verdictIcon = isVerified ? (isExit ? "🚪" : "✅") : needsId ? "⚠️" : "❌";
  const verdictText = isVerified
    ? (data.attendance_recorded ? (isExit ? "EXIT RECORDED — CHECK-OUT VERIFIED" : "ENTRY RECORDED — CHECK-IN VERIFIED") : "VERIFIED")
    : needsId
    ? "ADDITIONAL VERIFICATION REQUIRED (SCAN ID)"
    : "VERIFICATION REJECTED";

  const durationBanner = (isVerified && isExit && data.campus_duration)
    ? `
      <div style="background: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.35); padding: 10px 16px; border-radius: 8px; margin: 12px 0; display:flex; justify-content:space-between; align-items:center;">
        <span style="display:flex;align-items:center;gap:8px;font-weight:600;color:#fbbf24;font-size:14px;">
          ⏱️ Total Campus Dwell Duration:
        </span>
        <span class="badge-duration" style="font-size:14px;padding:4px 10px;">${data.campus_duration}</span>
      </div>
    `
    : "";

  resultPanel.innerHTML = `
    <div class="verdict-banner">
      <div class="verdict-title">
        <span>${verdictIcon}</span>
        <span>${verdictText}</span>
      </div>
      <div>
        <span class="status-pill ${data.decision}">${data.decision}</span>
      </div>
    </div>

    ${durationBanner}

    <div class="evidence-grid">
      <!-- Person Match -->
      <div class="evidence-card">
        <h4>Identified Personnel</h4>
        <div class="result-row"><span class="label">Name:</span><strong>${data.person_name || "Unidentified"}</strong></div>
        <div class="result-row"><span class="label">Employee ID:</span><span>${data.employee_id || "-"}</span></div>
        <div class="result-row"><span class="label">Direction:</span><span class="badge ${isExit ? 'badge-exit' : 'badge-entry'}">${data.event_type || 'ENTRY'}</span></div>
        <div class="result-row"><span class="label">Overall Confidence:</span><span>${(data.final_confidence * 100).toFixed(1)}%</span></div>
        <div class="result-row"><span class="label">Method:</span><span class="badge-sm">${data.verification_method}</span></div>
      </div>

      <!-- Face Signal -->
      <div class="evidence-card">
        <h4>Face Biometrics</h4>
        <div class="result-row"><span class="label">Matched Person:</span><span>${data.face ? (data.face.person_name || "No Match") : "No Face"}</span></div>
        <div class="result-row"><span class="label">Similarity:</span><span>${data.face ? (data.face.similarity * 100).toFixed(1) + "%" : "0.0%"}</span></div>
        <div class="result-row"><span class="label">Confidence:</span><span class="badge ${data.face ? data.face.confidence_label : "LOW"}">${data.face ? data.face.confidence_label : "NONE"}</span></div>
      </div>

      <!-- Vehicle / ANPR Signal -->
      <div class="evidence-card">
        <h4>Vehicle & ANPR</h4>
        <div class="result-row"><span class="label">Arrival Mode:</span><span>${data.arrival.arrival_type} (${data.arrival.source})</span></div>
        <div class="result-row"><span class="label">Detected Plate:</span><span>${data.plate ? (data.plate.plate_number || "Unrecognized") : "None"}</span></div>
        <div class="result-row"><span class="label">Plate Owner:</span><span>${data.plate ? (data.plate.person_name || "No DB Match") : "-"}</span></div>
      </div>
    </div>

    <div class="result-row" style="border-top: 1px solid var(--border); padding-top: 12px; margin-top: 10px;">
      <span class="label">Decision Reasoning:</span>
      <span class="muted">${data.reason}</span>
    </div>
  `;


  // Auto-scroll to result
  resultPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// Re-submit with ID Card
if (submitIdBtn) {
  submitIdBtn.addEventListener("click", () => {
    const idVal = idCardInput.value.trim();
    if (!idVal) {
      alert("Please enter faculty ID card text.");
      return;
    }
    const faceFile = selectedFaceFile || (lastCapturedBlob ? new File([lastCapturedBlob], "webcam_face.jpg", { type: "image/jpeg" }) : null);
    if (!faceFile) {
      alert("Please capture or upload face image first.");
      return;
    }
    executeVerification(faceFile, selectedVehicleFile, idVal);
  });
}

// ---------------------------------------------------------------------------
// 3. Faculty Enrollment (NEW FEATURE)
// ---------------------------------------------------------------------------
let enrollPhotoBlob = null;
let selectedEnrollPhotoFile = null;

const enrollForm = document.getElementById("enrollForm");
const enrollPhotoInput = document.getElementById("enrollPhotoInput");
const enrollPreview = document.getElementById("enrollPreview");
const enrollUploadText = document.getElementById("enrollUploadText");
const enrollResult = document.getElementById("enrollResult");
const submitEnrollBtn = document.getElementById("submitEnrollBtn");

const btnEnrollPhotoUpload = document.getElementById("btnEnrollPhotoUpload");
const btnEnrollPhotoCam = document.getElementById("btnEnrollPhotoCam");
const enrollUploadArea = document.getElementById("enrollUploadArea");
const enrollCameraArea = document.getElementById("enrollCameraArea");
const startEnrollCamBtn = document.getElementById("startEnrollCamBtn");
const snapEnrollCamBtn = document.getElementById("snapEnrollCamBtn");
const enrollWebcamVideo = document.getElementById("enrollWebcamVideo");

let selectedEnrollVehicleType = "CAR";
const enrollVehicleTypePills = document.querySelectorAll("#enrollVehicleTypePills .pill");
enrollVehicleTypePills.forEach((p) => {
  p.addEventListener("click", () => {
    enrollVehicleTypePills.forEach((el) => el.classList.remove("active"));
    p.classList.add("active");
    selectedEnrollVehicleType = p.dataset.vtype;
  });
});

// Photo Mode toggle
btnEnrollPhotoUpload.addEventListener("click", () => {
  btnEnrollPhotoUpload.classList.add("active");
  btnEnrollPhotoCam.classList.remove("active");
  enrollUploadArea.hidden = false;
  enrollCameraArea.hidden = true;
  stopEnrollWebcam();
});

btnEnrollPhotoCam.addEventListener("click", () => {
  btnEnrollPhotoCam.classList.add("active");
  btnEnrollPhotoUpload.classList.remove("active");
  enrollCameraArea.hidden = false;
  enrollUploadArea.hidden = true;
});

// Enroll Webcam Controls
startEnrollCamBtn.addEventListener("click", async () => {
  if (activeEnrollWebcamStream) {
    stopEnrollWebcam();
    return;
  }
  try {
    startEnrollCamBtn.textContent = "Connecting...";
    activeEnrollWebcamStream = await navigator.mediaDevices.getUserMedia({
      video: { width: 640, height: 480, facingMode: "user" },
      audio: false,
    });
    enrollWebcamVideo.srcObject = activeEnrollWebcamStream;
    startEnrollCamBtn.textContent = "Stop Camera";
    snapEnrollCamBtn.disabled = false;
  } catch (err) {
    alert(`Could not start enrollment camera: ${err.message}`);
    startEnrollCamBtn.textContent = "Start Camera";
  }
});

function stopEnrollWebcam() {
  if (activeEnrollWebcamStream) {
    activeEnrollWebcamStream.getTracks().forEach((t) => t.stop());
    activeEnrollWebcamStream = null;
  }
  if (enrollWebcamVideo) enrollWebcamVideo.srcObject = null;
  if (startEnrollCamBtn) startEnrollCamBtn.textContent = "Start Camera";
  if (snapEnrollCamBtn) snapEnrollCamBtn.disabled = true;
}

snapEnrollCamBtn.addEventListener("click", () => {
  if (!activeEnrollWebcamStream) return;
  const canvas = document.createElement("canvas");
  canvas.width = enrollWebcamVideo.videoWidth || 640;
  canvas.height = enrollWebcamVideo.videoHeight || 480;
  const ctx = canvas.getContext("2d");
  ctx.translate(canvas.width, 0);
  ctx.scale(-1, 1);
  ctx.drawImage(enrollWebcamVideo, 0, 0, canvas.width, canvas.height);

  canvas.toBlob((blob) => {
    if (!blob) return;
    enrollPhotoBlob = blob;
    selectedEnrollPhotoFile = new File([blob], "enrolled_face.jpg", { type: "image/jpeg" });
    enrollPreview.src = URL.createObjectURL(blob);
    enrollPreview.hidden = false;
    enrollUploadText.hidden = true;
    // Switch to upload preview to see snapped photo
    btnEnrollPhotoUpload.click();
  }, "image/jpeg", 0.95);
});

// File input handler for enroll
if (enrollPhotoInput) {
  enrollPhotoInput.addEventListener("change", () => {
    const f = enrollPhotoInput.files[0];
    if (!f) return;
    selectedEnrollPhotoFile = f;
    const reader = new FileReader();
    reader.onload = (e) => {
      enrollPreview.src = e.target.result;
      enrollPreview.hidden = false;
      enrollUploadText.hidden = true;
    };
    reader.readAsDataURL(f);
  });
}

// Enroll Form Submission
if (enrollForm) {
  enrollForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = document.getElementById("enrollName").value.trim();
    const empId = document.getElementById("enrollEmpId").value.trim();
    const dept = document.getElementById("enrollDept").value;
    const plate = document.getElementById("enrollPlate").value.trim();

    if (!selectedEnrollPhotoFile) {
      alert("Please provide a faculty face photo (upload or snap via webcam).");
      return;
    }

    submitEnrollBtn.disabled = true;
    submitEnrollBtn.textContent = "Processing 512D ArcFace Embedding...";
    enrollResult.hidden = true;

    try {
      const formData = new FormData();
      formData.append("name", name);
      formData.append("employee_id", empId);
      formData.append("department", dept);
      if (plate) {
        formData.append("plate_number", plate);
        formData.append("vehicle_type", selectedEnrollVehicleType);
      }
      formData.append("id_card_number", empId);
      formData.append("face_image", selectedEnrollPhotoFile);

      const res = await fetch(`${API_BASE}/persons/enroll`, { method: "POST", body: formData });
      const resultData = await res.json();

      if (!res.ok) {
        throw new Error(resultData.detail || "Enrollment failed.");
      }

      enrollResult.className = "result-message success";
      enrollResult.hidden = false;
      enrollResult.innerHTML = `
        <strong>🎉 Successfully Enrolled: ${resultData.person.name} (${resultData.person.employee_id})!</strong>
        <p style="margin: 4px 0 0; font-size: 13px;">
          512D ArcFace embedding stored in pgvector.
          ${resultData.plate_number ? `Vehicle plate <code>${resultData.plate_number}</code> mapped.` : "No vehicle registered."}
          You can now verify this faculty immediately on the Verify Attendance page!
        </p>
      `;

      // Reset form
      enrollForm.reset();
      selectedEnrollPhotoFile = null;
      enrollPreview.hidden = true;
      enrollUploadText.hidden = false;
    } catch (err) {
      enrollResult.className = "result-message error";
      enrollResult.hidden = false;
      enrollResult.innerHTML = `<strong>Enrollment Error:</strong> ${err.message}`;
    } finally {
      submitEnrollBtn.disabled = false;
      submitEnrollBtn.textContent = "🚀 Complete Faculty Enrollment";
    }
  });
}

// ---------------------------------------------------------------------------
// 4. Persons & Vehicles Directory
// ---------------------------------------------------------------------------
let allPersonsCache = [];
let allVehiclesCache = [];

async function loadPersons() {
  const el = document.getElementById("personsTable");
  el.innerHTML = `<p class="muted" style="padding: 16px;">Loading directory...</p>`;
  try {
    allPersonsCache = await apiGet("/persons");
    renderPersonsTable(allPersonsCache);
  } catch (err) {
    el.innerHTML = `<p class="muted" style="padding: 16px;">Could not load persons: ${err.message}</p>`;
  }
}

function renderPersonsTable(data) {
  const el = document.getElementById("personsTable");
  renderTable(el, [
    { label: "ID", key: "id" },
    { label: "Employee ID", render: (r) => `<strong>${r.employee_id}</strong>` },
    { label: "Faculty Name", render: (r) => `<span style="font-weight:600;">${r.name}</span>` },
    { label: "Department", render: (r) => r.department || "-" },
    { label: "Status", render: (r) => `<span class="badge ${r.status === 'ACTIVE' ? 'HIGH' : 'LOW'}">${r.status}</span>` },
    { label: "Vehicle", render: (r) => (r.vehicles && r.vehicles.length) ? `<code>${r.vehicles[0].plate_number}</code>` : `<span class="muted">None</span>` },
    { label: "Registered", render: (r) => fmtDate(r.created_at) },
    {
      label: "Action",
      render: (r) => `
        <div style="display:flex;gap:6px;">
          <button class="btn-secondary" style="padding:4px 10px;font-size:12px;" onclick="openEditPersonModal(${r.id})">✏️ Edit</button>
          <button class="btn-danger" style="padding:4px 10px;font-size:12px;" onclick="deletePerson(${r.id})">🗑️ Delete</button>
        </div>
      `,
    },
  ], data, "No persons registered yet. Enroll someone using the Enroll Faculty page!");
}

async function deletePerson(id) {
  if (!confirm(`Delete Person #${id} and all associated embeddings, vehicles, and ID cards?`)) return;
  try {
    const res = await fetch(`${API_BASE}/persons/${id}`, { method: "DELETE" });
    if (res.ok) {
      loadPersons();
    } else {
      alert("Failed to delete person.");
    }
  } catch (err) {
    alert(err.message);
  }
}

// ---------------------------------------------------------------------------
// Edit Faculty Modal Logic
// ---------------------------------------------------------------------------
const editPersonModal = document.getElementById("editPersonModal");
const editPersonForm = document.getElementById("editPersonForm");
const closeEditModalBtn = document.getElementById("closeEditModalBtn");
const cancelEditBtn = document.getElementById("cancelEditBtn");
const saveEditBtn = document.getElementById("saveEditBtn");
const editResult = document.getElementById("editResult");
const editPhotoInput = document.getElementById("editPhotoInput");
const editPhotoPreview = document.getElementById("editPhotoPreview");
const editPhotoPrompt = document.getElementById("editPhotoPrompt");
const editVehicleTypePills = document.querySelectorAll("#editVehicleTypePills .pill");
let selectedEditVehicleType = "CAR";
let selectedEditPhotoFile = null;

if (editVehicleTypePills) {
  editVehicleTypePills.forEach((pill) => {
    pill.addEventListener("click", () => {
      editVehicleTypePills.forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");
      selectedEditVehicleType = pill.dataset.vtype;
    });
  });
}

if (closeEditModalBtn) closeEditModalBtn.addEventListener("click", closeEditPersonModal);
if (cancelEditBtn) cancelEditBtn.addEventListener("click", closeEditPersonModal);

if (editPersonModal) {
  editPersonModal.addEventListener("click", (e) => {
    if (e.target === editPersonModal) closeEditPersonModal();
  });
}

if (editPhotoInput) {
  editPhotoInput.addEventListener("change", () => {
    const f = editPhotoInput.files[0];
    if (!f) return;
    selectedEditPhotoFile = f;
    const reader = new FileReader();
    reader.onload = (e) => {
      editPhotoPreview.src = e.target.result;
      editPhotoPreview.hidden = false;
      editPhotoPrompt.hidden = true;
    };
    reader.readAsDataURL(f);
  });
}

function openEditPersonModal(id) {
  const person = allPersonsCache.find((p) => p.id === id);
  if (!person) {
    alert("Person not found.");
    return;
  }

  document.getElementById("editPersonId").value = person.id;
  document.getElementById("editName").value = person.name || "";
  document.getElementById("editEmpId").value = person.employee_id || "";
  document.getElementById("editDept").value = person.department || "Computer Science & Engineering";
  document.getElementById("editStatus").value = person.status || "ACTIVE";

  const v = person.vehicles && person.vehicles.length ? person.vehicles[0] : null;
  document.getElementById("editPlate").value = v ? v.plate_number : "";
  selectedEditVehicleType = v && v.vehicle_type ? v.vehicle_type.toUpperCase() : (v ? "CAR" : "NONE");
  if (editVehicleTypePills) {
    editVehicleTypePills.forEach((pill) => {
      pill.classList.toggle("active", pill.dataset.vtype === selectedEditVehicleType);
    });
  }

  selectedEditPhotoFile = null;
  if (editPhotoInput) editPhotoInput.value = "";
  if (editPhotoPreview) { editPhotoPreview.src = ""; editPhotoPreview.hidden = true; }
  if (editPhotoPrompt) editPhotoPrompt.hidden = false;
  if (editResult) { editResult.hidden = true; editResult.textContent = ""; }

  editPersonModal.hidden = false;
}

function closeEditPersonModal() {
  if (editPersonModal) editPersonModal.hidden = true;
  selectedEditPhotoFile = null;
}

if (editPersonForm) {
  editPersonForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const id = document.getElementById("editPersonId").value;
    const name = document.getElementById("editName").value.trim();
    const empId = document.getElementById("editEmpId").value.trim();
    const dept = document.getElementById("editDept").value;
    const status = document.getElementById("editStatus").value;
    const plate = document.getElementById("editPlate").value.trim();

    saveEditBtn.disabled = true;
    saveEditBtn.textContent = "Saving changes...";
    editResult.hidden = true;

    try {
      const formData = new FormData();
      formData.append("name", name);
      formData.append("employee_id", empId);
      formData.append("department", dept);
      formData.append("status", status);
      formData.append("plate_number", plate);
      formData.append("vehicle_type", selectedEditVehicleType === "NONE" ? "CAR" : selectedEditVehicleType);
      formData.append("id_card_number", empId);
      if (selectedEditPhotoFile) {
        formData.append("face_image", selectedEditPhotoFile);
      }

      const res = await fetch(`${API_BASE}/persons/${id}`, { method: "PUT", body: formData });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Update failed.");
      }

      editResult.className = "result-message success";
      editResult.hidden = false;
      editResult.innerHTML = `<strong>✅ ${data.message}</strong>`;

      await loadPersons();
      setTimeout(() => {
        closeEditPersonModal();
      }, 700);
    } catch (err) {
      editResult.className = "result-message error";
      editResult.hidden = false;
      editResult.innerHTML = `<strong>Error:</strong> ${err.message}`;
    } finally {
      saveEditBtn.disabled = false;
      saveEditBtn.textContent = "💾 Save Changes";
    }
  });
}

window.openEditPersonModal = openEditPersonModal;
window.closeEditPersonModal = closeEditPersonModal;
window.deletePerson = deletePerson;


// Live Search Persons
const searchPersonsInput = document.getElementById("searchPersonsInput");
if (searchPersonsInput) {
  searchPersonsInput.addEventListener("input", (e) => {
    const q = e.target.value.toLowerCase().trim();
    if (!q) {
      renderPersonsTable(allPersonsCache);
      return;
    }
    const filtered = allPersonsCache.filter(
      (p) => p.name.toLowerCase().includes(q) || p.employee_id.toLowerCase().includes(q) || (p.department && p.department.toLowerCase().includes(q))
    );
    renderPersonsTable(filtered);
  });
}

async function loadVehicles() {
  const el = document.getElementById("vehiclesTable");
  el.innerHTML = `<p class="muted" style="padding: 16px;">Loading vehicles...</p>`;
  try {
    allVehiclesCache = await apiGet("/vehicles");
    renderVehiclesTable(allVehiclesCache);
  } catch (err) {
    el.innerHTML = `<p class="muted" style="padding: 16px;">Could not load vehicles: ${err.message}</p>`;
  }
}

function renderVehiclesTable(data) {
  const el = document.getElementById("vehiclesTable");
  renderTable(el, [
    { label: "ID", key: "id" },
    { label: "Person ID", key: "person_id" },
    { label: "Plate Number", render: (r) => `<code style="font-size:13px;font-weight:700;color:#38bdf8;">${r.plate_number}</code>` },
    { label: "Type", render: (r) => r.vehicle_type || "CAR" },
    { label: "Status", render: (r) => `<span class="badge HIGH">${r.status}</span>` },
  ], data, "No vehicles registered yet.");
}

// Live Search Vehicles
const searchVehiclesInput = document.getElementById("searchVehiclesInput");
if (searchVehiclesInput) {
  searchVehiclesInput.addEventListener("input", (e) => {
    const q = e.target.value.toUpperCase().trim();
    if (!q) {
      renderVehiclesTable(allVehiclesCache);
      return;
    }
    const filtered = allVehiclesCache.filter(
      (v) => v.plate_number.includes(q) || String(v.person_id).includes(q)
    );
    renderVehiclesTable(filtered);
  });
}

// ---------------------------------------------------------------------------
// 5. Recognition (Latest 15) & Calendar Attendance History
// ---------------------------------------------------------------------------
async function loadRecognitionHistory() {
  const el = document.getElementById("recognitionTable");
  el.innerHTML = `<p class="muted" style="padding: 16px;">Loading latest 15 recognition events...</p>`;
  try {
    const events = await apiGet("/recognition-events?limit=15");
    renderTable(el, [
      { label: "Timestamp", render: (r) => fmtDate(r.timestamp) },
      { label: "Arrival", render: (r) => `<span class="badge-sm">${r.arrival_type}</span>` },
      { label: "Face Score", render: (r) => (r.face_similarity != null ? `${(r.face_similarity * 100).toFixed(1)}%` : "-") },
      { label: "Plate", render: (r) => r.plate_number || "-" },
      { label: "Person ID", render: (r) => r.final_person_id ?? "-" },
      { label: "Confidence", render: (r) => (r.final_confidence != null ? `${(r.final_confidence * 100).toFixed(1)}%` : "-") },
      { label: "Method", render: (r) => r.verification_method || "-" },
      { label: "Decision", render: (r) => statusPill(r.decision) },
    ], events, "No recognition events recorded yet.");
  } catch (err) {
    el.innerHTML = `<p class="muted" style="padding: 16px;">Could not load recognition history: ${err.message}</p>`;
  }
}

// Calendar & Day View State
let calCurrentDate = new Date(); // controls displayed month
let calSelectedDateStr = new Date().toISOString().split("T")[0]; // YYYY-MM-DD
let calSummaryCache = {};
let dailyAttendanceCache = [];

const monthNames = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"
];

async function loadAttendanceHistory() {
  initCalendarEventListeners();
  const dateInput = document.getElementById("calendarDateInput");
  if (dateInput) dateInput.value = calSelectedDateStr;

  await fetchCalendarMonthSummary();
  renderCalendarDaysGrid();
  await loadDailyAttendance(calSelectedDateStr);
}

let calListenersAttached = false;
function initCalendarEventListeners() {
  if (calListenersAttached) return;
  calListenersAttached = true;

  const prevBtn = document.getElementById("calPrevMonthBtn");
  const nextBtn = document.getElementById("calNextMonthBtn");
  const todayBtn = document.getElementById("btnTodayAttendance");
  const dateInput = document.getElementById("calendarDateInput");
  const searchInput = document.getElementById("searchDayAttendanceInput");

  if (prevBtn) {
    prevBtn.addEventListener("click", async () => {
      calCurrentDate.setMonth(calCurrentDate.getMonth() - 1);
      await fetchCalendarMonthSummary();
      renderCalendarDaysGrid();
    });
  }

  if (nextBtn) {
    nextBtn.addEventListener("click", async () => {
      calCurrentDate.setMonth(calCurrentDate.getMonth() + 1);
      await fetchCalendarMonthSummary();
      renderCalendarDaysGrid();
    });
  }

  if (todayBtn) {
    todayBtn.addEventListener("click", async () => {
      const today = new Date();
      calCurrentDate = new Date(today);
      calSelectedDateStr = today.toISOString().split("T")[0];
      if (dateInput) dateInput.value = calSelectedDateStr;
      await fetchCalendarMonthSummary();
      renderCalendarDaysGrid();
      await loadDailyAttendance(calSelectedDateStr);
    });
  }

  if (dateInput) {
    dateInput.addEventListener("change", async (e) => {
      if (!e.target.value) return;
      calSelectedDateStr = e.target.value;
      calCurrentDate = new Date(calSelectedDateStr + "T00:00:00");
      await fetchCalendarMonthSummary();
      renderCalendarDaysGrid();
      await loadDailyAttendance(calSelectedDateStr);
    });
  }

  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      const q = e.target.value.toLowerCase().trim();
      if (!q) {
        renderDailyAttendanceTable(dailyAttendanceCache);
        return;
      }
      const filtered = dailyAttendanceCache.filter(
        (r) => r.name.toLowerCase().includes(q) || r.employee_id.toLowerCase().includes(q) || (r.department && r.department.toLowerCase().includes(q))
      );
      renderDailyAttendanceTable(filtered);
    });
  }
}

async function fetchCalendarMonthSummary() {
  const year = calCurrentDate.getFullYear();
  const month = String(calCurrentDate.getMonth() + 1).padStart(2, "0");
  const monthKey = `${year}-${month}`;

  const titleEl = document.getElementById("calendarMonthTitle");
  if (titleEl) titleEl.textContent = `${monthNames[calCurrentDate.getMonth()]} ${year}`;

  try {
    const data = await apiGet(`/attendance/calendar-summary?month_str=${monthKey}`);
    calSummaryCache = data.active_days || {};
  } catch (err) {
    calSummaryCache = {};
  }
}

function renderCalendarDaysGrid() {
  const grid = document.getElementById("calendarDaysGrid");
  if (!grid) return;
  grid.innerHTML = "";

  const year = calCurrentDate.getFullYear();
  const month = calCurrentDate.getMonth();

  const firstDayObj = new Date(year, month, 1);
  let startDay = firstDayObj.getDay();
  // Adjust Monday-first (0 = Mon, 6 = Sun)
  startDay = (startDay === 0) ? 6 : startDay - 1;

  const totalDays = new Date(year, month + 1, 0).getDate();
  const todayStr = new Date().toISOString().split("T")[0];

  // Empty leading cells
  for (let i = 0; i < startDay; i++) {
    const cell = document.createElement("div");
    cell.className = "cal-day-cell empty";
    grid.appendChild(cell);
  }

  // Day cells
  for (let day = 1; day <= totalDays; day++) {
    const dayStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const cell = document.createElement("div");
    cell.className = "cal-day-cell";
    if (dayStr === todayStr) cell.classList.add("today");
    if (dayStr === calSelectedDateStr) cell.classList.add("selected");

    const dayActivity = calSummaryCache[dayStr];
    if (dayActivity && dayActivity.present_count > 0) {
      cell.classList.add("has-attendance");
    }

    cell.innerHTML = `
      <span class="cal-day-num">${day}</span>
      ${dayActivity && dayActivity.present_count > 0
        ? `<span class="cal-day-badge">👥 ${dayActivity.present_count}</span>`
        : `<span></span>`
      }
    `;

    cell.addEventListener("click", async () => {
      calSelectedDateStr = dayStr;
      const dateInput = document.getElementById("calendarDateInput");
      if (dateInput) dateInput.value = calSelectedDateStr;
      renderCalendarDaysGrid();
      await loadDailyAttendance(calSelectedDateStr);
    });

    grid.appendChild(cell);
  }
}

async function loadDailyAttendance(dateStr) {
  const titleEl = document.getElementById("dayRecordsTitle");
  const subEl = document.getElementById("dayRecordsSub");
  const tableEl = document.getElementById("dayAttendanceTable");
  const exportBtn = document.getElementById("btnExportDayCsv");

  if (exportBtn) {
    exportBtn.href = `${API_BASE}/attendance/export?date_str=${dateStr}`;
  }

  const dObj = new Date(dateStr + "T00:00:00");
  const formattedDayTitle = isNaN(dObj) ? dateStr : dObj.toLocaleDateString(undefined, { weekday: "long", year: "numeric", month: "long", day: "numeric" });
  if (titleEl) titleEl.textContent = `Daily Log: ${formattedDayTitle}`;
  if (subEl) subEl.textContent = `Attendance and campus dwell analysis for ${dateStr}`;

  tableEl.innerHTML = `<p class="muted" style="padding: 16px;">Loading records for ${dateStr}...</p>`;

  try {
    const data = await apiGet(`/attendance/daily?date_str=${dateStr}`);
    const summary = data.summary || {};
    dailyAttendanceCache = data.records || [];

    document.getElementById("dayStatPresent").textContent = summary.total_present || 0;
    document.getElementById("dayStatInCampus").textContent = summary.in_campus || 0;
    document.getElementById("dayStatCheckedOut").textContent = summary.checked_out || 0;
    document.getElementById("dayStatAvgDuration").textContent = summary.avg_campus_duration || "-";

    renderDailyAttendanceTable(dailyAttendanceCache);
  } catch (err) {
    tableEl.innerHTML = `<p class="muted" style="padding: 16px;">Error loading day records: ${err.message}</p>`;
  }
}

function renderDailyAttendanceTable(records) {
  const tableEl = document.getElementById("dayAttendanceTable");
  renderTable(tableEl, [
    { label: "Faculty Member", render: (r) => `<span style="font-weight:600;">${r.name}</span> <span class="muted" style="font-size:11px;">(${r.employee_id})</span>` },
    { label: "Department", render: (r) => r.department || "-" },
    { label: "First Check-In (Entry)", render: (r) => `<span class="badge-entry">${r.first_entry_time}</span>` },
    { label: "Last Check-Out (Exit)", render: (r) => r.last_exit_time === "In Campus" ? `<span class="badge HIGH">🟢 In Campus</span>` : `<span class="badge-exit">${r.last_exit_time}</span>` },
    { label: "Campus Duration", render: (r) => `<span class="badge-duration">${r.duration_text}</span>` },
    { label: "Status", render: (r) => r.status === "IN_CAMPUS" ? `<span class="badge HIGH">IN CAMPUS</span>` : `<span class="badge" style="background:rgba(59,130,246,0.15);color:#60a5fa;">CHECKED OUT</span>` },
    { label: "Methods Used", render: (r) => r.methods && r.methods.length ? r.methods.map(m => `<span class="badge-sm">${m}</span>`).join(" ") : "-" },
  ], records, `No attendance events recorded on ${calSelectedDateStr}. Use Verify Attendance to record an Entry!`);
}


// ---------------------------------------------------------------------------
// 6. System Status & Admin
// ---------------------------------------------------------------------------
async function loadStatus() {
  const el = document.getElementById("statusCard");
  el.innerHTML = `<p class="muted" style="padding: 16px;">Checking model health...</p>`;
  try {
    const s = await apiGet("/status");
    const evalBlock = (title, evalData, fields) => {
      if (!evalData) return `<div class="evidence-card" style="margin-top:12px;"><h4>${title}</h4><p class="muted">Not evaluated yet — run evaluate.py script.</p></div>`;
      return `
        <div class="evidence-card" style="margin-top:12px;">
          <h4>${title}</h4>
          ${fields.map(([label, key]) => `<div class="result-row"><span class="label">${label}:</span><strong>${evalData[key]}</strong></div>`).join("")}
        </div>
      `;
    };

    el.innerHTML = `
      <div class="result-row"><span class="label">Environment:</span><span>${s.environment}</span></div>
      <div class="result-row"><span class="label">Face Model (InsightFace ArcFace 512D):</span><span class="badge ${s.face_model_loaded ? "HIGH" : "LOW"}">${s.face_model_loaded ? "ACTIVE (Preloaded)" : "Idle"}</span></div>
      <div class="result-row"><span class="label">Arrival Detector (YOLOv8):</span><span class="badge ${s.arrival_model_loaded ? "HIGH" : "LOW"}">${s.arrival_model_loaded ? "ACTIVE (Preloaded)" : "Idle"}</span></div>
      <div class="result-row"><span class="label">License Plate Detector:</span><span class="badge-sm">${s.plate_detector_type.toUpperCase()}</span></div>
      ${evalBlock("Face Recognition Evaluation (Test Set)", s.face_evaluation, [["Accuracy", "accuracy"], ["Total Images", "total_images"], ["Correct Matches", "correct"]])}
      ${evalBlock("ANPR Evaluation (Indian Highway Test Set)", s.anpr_evaluation, [["Detection Rate", "detection_success_rate"], ["Exact Matches", "exact_match_accuracy"], ["Character Accuracy", "character_level_accuracy"], ["Total Images", "total_images"]])}
    `;
  } catch (err) {
    el.innerHTML = `<p class="muted" style="padding: 16px;">Could not load status: ${err.message}</p>`;
  }
}

document.getElementById("seedBtn").addEventListener("click", async () => {
  const out = document.getElementById("adminOutput");
  out.hidden = false;
  out.textContent = "Seeding demo dataset...";
  try {
    const res = await fetch(`${API_BASE}/admin/seed-demo`, { method: "POST" });
    out.textContent = JSON.stringify(await res.json(), null, 2);
    loadStatus();
  } catch (err) {
    out.textContent = `Error: ${err.message}`;
  }
});

document.getElementById("clearBtn").addEventListener("click", async () => {
  if (!confirm("WARNING: This permanently wipes all demo records, vehicle plates, and vector embeddings. Continue?")) return;
  const out = document.getElementById("adminOutput");
  out.hidden = false;
  out.textContent = "Wiping database...";
  try {
    const res = await fetch(`${API_BASE}/admin/clear-demo?confirm=true`, { method: "POST" });
    out.textContent = JSON.stringify(await res.json(), null, 2);
    loadStatus();
  } catch (err) {
    out.textContent = `Error: ${err.message}`;
  }
});

// Page Loader Mappings
const pageLoaders = {
  dashboard: loadDashboard,
  persons: loadPersons,
  vehicles: loadVehicles,
  recognition: loadRecognitionHistory,
  attendance: loadAttendanceHistory,
  status: loadStatus,
  verify: () => {},
  enroll: () => {},
};

// Start on Dashboard
showPage("dashboard");
