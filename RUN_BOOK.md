# AIC 2026 WP13 Operational Runbook

This runbook is the operational manual for Team SS009.Q24's WP13 (UI, Evaluation, Submission & Deployment) system for the AI Challenge HCM 2026. It documents current operational commands, physical component paths, workflow instructions, fallback mechanisms, exact-frame resolution rules, and target handoff boundaries.

---

## 1. System Architecture

The AIC 2026 multimodal retrieval platform consists of seven cooperating work packages:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        WP13 Operator Cockpit                           │
│                     (Vite / React 18, Port 5173)                       │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HTTP JSON API
┌───────────────────────────────────▼────────────────────────────────────┐
│                    TV4 Orchestrator / API Gateway                      │
│                      (FastAPI / Uvicorn, Port 8200)                    │
├─────────────────┬──────────────────┬─────────────────┬─────────────────┤
│  WP07 Router    │  WP10 Fusion     │   WP11 VQA      │  WP12 TRAKE     │
│  & Dispatch     │  & RRF Rerank    │   Evidence/VLM  │  Monotonic DP   │
└────────┬────────┴────────┬─────────┴────────┬────────┴────────┬────────┘
         │                 │                  │                 │
┌────────▼────────┐┌───────▼────────┐┌────────▼────────┐┌───────▼────────┐
│   TV1 Service   ││  WP04 Service  ││   WP03 Visual   ││   WP09 Exact   │
│   (Port 8000)   ││  (Port 8100)   ││   Retrieval     ││   Frame Decode │
│ Corpus Manifest ││ OCR, ASR, Obj, ││ (CLI Subprocess)││ (In-Process    │
│ Frames Parquet  ││ Metadata Evid. ││ 4 FAISS Indexes ││ PyAV/Cert Anch)│
└─────────────────┘└────────────────┘└─────────────────┘└────────────────┘
```

### Process vs Module Classification:
- **HTTP Standalone Servers**:
  - **TV1**: Standalone FastAPI service (`wp06_api_server.py`) on port `8000`.
  - **WP04**: Standalone FastAPI service (`backend.app.main:app`) on port `8100`.
  - **TV4**: Standalone FastAPI service (`tv4.api:app`) on port `8200`.
  - **WP13**: Standalone Vite dev server on port `5173`.
- **In-Process / Subprocess Modules**:
  - **WP03 (Visual Retrieval)**: WP03 is not an HTTP server. TV4 invokes WP03 through `TV2VisualClient` / the WP03 CLI subprocess; batch search is implemented in `wp03.search.search_visual_batch`.
  - **WP08 (Feedback State Machine)**: Integrated in-process via `tv4.adapters.wp08_adapter.Wp08FeedbackAdapter`.
  - **WP09 (Exact Frame Decoder)**: **NOT** an HTTP server. TV4 invokes WP09 in-process via `ExactFrameResolver`, `wp09.service`, and PyAV consecutive decoder.

---

## 2. Canonical Paths

| Component | Canonical Location | Description |
|---|---|---|
| **TV1 Runtime** | `D:\aic226\tv1` | Raw videos, run manifest, frames parquet |
| **WP04 Runtime** | `D:\aic226\tv1tv3\TV1_TV3_WP04` | Modality records, OCR/ASR/Object evidence |
| **WP03 Runtime** | `D:\aic226\tv2_1\WP03` | Visual search module & FAISS index artifacts |
| **WP09 Runtime** | `D:\aic226\tv2_1\WP09` | Exact-frame resolution, certification & decoder |
| **TV4 Runtime** | `D:\aic226\tv4` | Deployed orchestrator runtime environment |
| **Git Repository** | `D:\aic226\tv5` | Primary Git workspace (`team/tv5-ui-evaluation-release`) |
| **Tracked TV4** | `D:\aic226\tv5\tv4` | Tracked source code for TV4 backend |
| **WP13 Frontend** | `D:\aic226\tv5\tv5` | WP13 React cockpit & client application |

---

## 3. Network Ports

| Service | Port | Protocol | Binding |
|---|---|---|---|
| TV1 API Server | `8000` | HTTP/1.1 | `127.0.0.1:8000` |
| WP04 Evidence Server | `8100` | HTTP/1.1 | `127.0.0.1:8100` |
| TV4 Orchestrator | `8200` | HTTP/1.1 | `127.0.0.1:8200` |
| WP13 Cockpit Frontend | `5173` | HTTP/1.1 | `localhost:5173` |

---

## 4. Listener and PID Inspection

To inspect active listening ports and identify owning processes without guessing:

```powershell
# List all AIC-relevant listening ports (8000, 8100, 8200, 5173)
Get-NetTCPConnection -LocalPort 8000, 8100, 8200, 5173 -State Listen -ErrorAction SilentlyContinue | Select-Object LocalAddress, LocalPort, OwningProcess

# Inspect process command line for a specific PID (e.g., PID 1234)
Get-CimInstance Win32_Process -Filter "ProcessId = 1234" | Select-Object ProcessId, CommandLine

# Terminate ONLY confirmed stale AIC process after verifying CommandLine
Stop-Process -Id 1234 -Force
```

> [!WARNING]
> Never blindly terminate processes without inspecting `CommandLine` to avoid disrupting OS or background development tasks.

---

## 5. Startup Order

Services **must** be started in the following dependency order:

1. **TV1** (Port 8000) — Provides corpus video and frames metadata.
2. **WP04** (Port 8100) — Provides OCR/ASR/Object/Metadata evidence APIs.
3. **TV4** (Port 8200) — Provides KIS/VQA/TRAKE orchestration, exact frames, and proxy media.
4. **WP13** (Port 5173) — Web cockpit connecting to TV4.

---

## 6. TV1 Startup

Start TV1 metadata API server using the physically proven command (do not run preprocessing):

```powershell
cd D:\aic226\tv1
.\.venv\Scripts\python.exe wp06_api_server.py `
    --run_dir data\runs\run_v1_batch1 `
    --port 8000
```

Verify TV1 health:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/health"
```

---

## 7. WP04 Startup (Current Development Run vs Future Handover)

For current local development, start the existing WP04 service:

```powershell
cd D:\aic226\tv1tv3\TV1_TV3_WP04
$env:AIC_RUN_ID = "tv1-tv3-dev-v1"
$env:AIC_CONFIG = "configs\default.yaml"
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app `
    --host 127.0.0.1 `
    --port 8100
```

> [!IMPORTANT]
> The current development WP04 run returns HTTP 200 with a degraded status. This development run is explicitly distinguished from the future corrected/frozen full-corpus WP04 run to be supplied and accepted under task T057. Current WP04 is **not** claimed as fully `READY`.

Verify WP04 health:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8100/health"
```

---

## 8. TV4 Startup

### Live Mode:
```powershell
cd D:\aic226\tv4
$env:TV4_CONFIG = "configs/default.yaml"
$env:TV4_EXACT_CERTIFICATION_PATH = "D:\aic226\tv2_1\WP09\configs\certifications\run_v1_batch1.json"
Remove-Item env:TV4_FIXTURE_MODE -ErrorAction SilentlyContinue
& "D:\aic226\tv4\.venv\Scripts\python.exe" -m uvicorn tv4.api:app --host 127.0.0.1 --port 8200
```

### Deterministic Fixture Mode (No GPU or upstream services required):
```powershell
cd D:\aic226\tv4
$env:TV4_FIXTURE_MODE = "1"
& "D:\aic226\tv4\.venv\Scripts\python.exe" -m uvicorn tv4.api:app --host 127.0.0.1 --port 8200
```

---

## 9. Frontend (WP13) Startup

```powershell
cd D:\aic226\tv5\tv5
npm run dev
```

The browser UI will be available at `http://localhost:5173`.

> [!TIP]
> If Vite reports port `5173` is in use and falls back to `5174`, inspect the owning PID using `Get-NetTCPConnection -LocalPort 5173` and terminate the stale Vite process before restarting.

---

## 10. Health Checks and Diagnostics

Check TV4 overall health:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8200/health"
```

Expected live output:
```json
{
  "status": "ok",
  "mode": "live",
  "preprocess_run_id": "run_v1_batch1"
}
```

Expected fixture output:
```json
{
  "status": "ok",
  "mode": "fixture"
}
```

If TV4 reports `"status": "degraded"`, inspect the returned `"error"` message.

---

## 11. WP03 Visual Retrieval Artifacts

Canonical full-run visual artifact root:
```
D:\aic226\tv2_1\WP03\artifacts\full-run-1
```
Contains:
- 4 visual model indexes: `beit3.faiss`, `bge_vl.faiss`, `metaclip2.faiss`, `perception.faiss`
- 4 manifests: `manifests/*.json`
- Vector count: `106,380` vectors per model index
- Preprocess run ID: `run_v1_batch1`

> [!CAUTION]
> **NEVER** rebuild, regenerate, or preprocess WP03 artifacts during competition or runtime operation. Treat existing artifacts as frozen state.

---

## 12. KIS (Known-Item Search) Workflow

1. **Enter Query**: Operator inputs textual description in Vietnamese or English.
2. **Execute Search**: Press `Ctrl+Enter` or click "Search Candidates".
3. **Review Top 100**: Grid displays up to 100 continuously ranked candidates with ranks, scores, model provenance, and thumbnails.
4. **Inspect Candidate**: Click candidate card to open Inspection Workspace (raw video player and keyframe preview).
5. **Consecutive Stepping**: Use `ArrowLeft` / `ArrowRight` to step through exact certified neighboring frames via WP09's consecutive ORIGINAL-frame resolution service.
6. **Note on Basket Integration**: Frontend cross-workflow unified basket entry for KIS remains pending under task T039.

---

## 13. Feedback Workflow

1. **Select Reference Frame**: Click "Set Reference" on any candidate card.
2. **Add Feedback Text**: Type refinement guidance (e.g. "at sunset", "closer shot").
3. **Refine Search**: Click "Refine Candidates". TV4 dispatches session revision to WP08 state machine.
4. **History & Undo**: Operators can view past revision snapshots and click "Undo" or "Reset to Original".
5. **Guard**: Maximum 5 active refinements per query session.
6. **Basket Isolation**: Refining search results **never** alters or overwrites existing basket items.

---

## 14. VQA (Video Question Answering) Workflow

1. **Enter Question**: Input event description and specific question in the Retrieval workspace.
2. **Inspect Evidence**: Review OCR detections, ASR transcripts, and Object bounding boxes in the Multimodal Evidence Pack via `EvidenceInspector`.
3. **Advisory Proposal**: View machine proposal and confidence score in `VqaAnswerPanel`. Machine suggestions are **advisory only**.
4. **Mandatory Human Confirmation**: Operator edits the answer and clicks "Approve Answer". Unapproved answers cannot enter the submission basket.
5. **Add to Basket**: Once approved, the answer can be added to the basket (records `video_id`, `frame_id`, `approved_answer`).

---

## 15. TRAKE (Track Event Sequence) Workflow

1. **Ordered Event List**: Input N events separated by semicolons (e.g. `event1; event2; event3`).
2. **Monotonic DP Alignment**: TV4 computes optimal monotonic frame sequence within a single video hypothesis.
3. **Inspect Event Slots**: Exactly N ordered event slots appear in `TrakeTimeline`.
4. **Lock Selections**: Operators can lock verified event slots while adjusting others.
5. **Exact Neighbor Correction**: Adjust individual event frame selections using exact frame stepping.
6. **Complete Chain Validation**: Only a complete, order-preserving, single-video N-event chain can enter the basket.

---

## 16. Exact-Frame Invariants and Identity Rules

- **Resolution Mechanism**: Canonical frames are resolved through WP09's proven consecutive ORIGINAL-frame service by combining:
  1. `certified_root_anchor` (from certification registry)
  2. `persistent anchor_offset` (accumulated verified steps)
  3. `transient cumulative signed step` (active slider/key offset)
- **Identity Invariant**: Submission `frame_id` is always a real integer original frame from the raw video.
- **Forbidden Practices**: **NEVER** calculate frame IDs using:
  - Nominal FPS arithmetic (`time_seconds * fps`)
  - PTS arithmetic without time-base validation
  - Browser HTML5 playback time
  - UI ordinal index
- **Fail-Closed Policy**:
  - If a neighboring frame is uncertified or proof validation fails, TV4 returns `HTTP 409` or `submission_selectable = false`.

---

## 17. Evidence Modalities and Provenance

- **OCR**: Bounding boxes `[x1, y1, x2, y2]` normalized (0..1), raw text, normalized text, model provenance.
- **ASR**: Segment timestamps (`start_ms`, `end_ms`), language, transcript, word-level confidence tokens.
- **Objects**: Bounding box coordinates, label, confidence, crop references.
- **Metadata**: Structured catalog values and source provenance.
- **Degraded Branches**: Empty or unavailable modalities display an explicit `Empty` tag without fabricating data.

---

## 18. Keyboard Shortcuts Guide

### Implemented & Fully Operational Shortcuts:
| Action | Key Combination | Focus Safe | Location |
|---|---|---|---|
| Toggle Keyboard Shortcuts Guide | `?` (or Header `?` Button) | Yes | Global (All Workspaces) |
| Step Backward (-1 frame) | `ArrowLeft` | Yes | Inspection Workspace |
| Step Forward (+1 frame) | `ArrowRight` | Yes | Inspection Workspace |
| Reset to Anchor (offset 0) | `Home` / `0` | Yes | Inspection Workspace |
| Toggle Video Playback | `Space` | Yes | Media Player |
| Submit KIS Query | `Ctrl+Enter` / `Cmd+Enter` | No | Retrieval Workspace |
| Close Modals / Reset View | `Escape` | Yes | Global |

---

## 19. Submission Basket & 1-Click Export Operational Guide

- **Capacity Invariant**: Maximum 100 predictions per query.
- **Unified Cross-Workflow Basket**:
  - **KIS**: Click `[ + Basket ]` on any candidate card in the retrieval matrix or `[ + Basket ]` in the inspection transport rail.
  - **VQA**: Inspect evidence -> edit answer draft -> click `[ Approve Answer ]` -> click `[ Add to Basket ]`.
  - **TRAKE**: Input event sequence -> verify monotonic alignment -> lock all event slots -> click `[ Add TRAKE to Basket ]`.
- **1-Click Web Export**:
  - Open `Evidence / Submission` tab in header.
  - Review basket items and count (`N / 100`).
  - Click **`[ 📥 Export CSV ]`** to download standard RFC 4180 competition CSV instantly.
  - Click **`[ Clear All ]`** to reset the active basket.
- **Evaluation & Telemetry Inspector**:
  - Open `Evaluation / Stats` tab in header.
  - View live metric calculations (KIS Hit@k, VQA agreement, TRAKE alignment, Final Score = 0.74).
  - View ingested corpus statistics (873 videos, 106,380 vectors, active run ID).
  - Click **`[ 📥 Download Telemetry (JSONL) ]`** to export recorded operator action logs.

---

## 20. Submission File Formats & Competition Authority

> [!IMPORTANT]
> **No approved automatic competition-upload API endpoint is implemented. CLI/UI preparation stops at validated local artifacts; actual upload is human-controlled.**
> CSV/ZIP operational mechanics derived from provisional prior guidance must be re-reviewed against the official AIC 2026 submission guide before final competition use.

Per-query CSV files must be headerless, UTF-8 encoded:

- **KIS**:
  ```csv
  <video_id>,<frame_id>
  ```
  *Example:*
  ```csv
  L01_V001,1050
  L01_V002,2340
  ```

- **VQA / Q&A**:
  ```csv
  <video_id>,<frame_id>,<approved_answer>
  ```
  *Example:*
  ```csv
  L01_V001,1050,cốc màu đỏ
  ```

- **TRAKE**:
  ```csv
  <video_id>,<frame_id_1>,<frame_id_2>,...,<frame_id_N>
  ```
  *Example:*
  ```csv
  L01_V001,1050,1125,1200,1280
  ```

*Video IDs must NEVER contain `.mp4`. Frame IDs must be non-negative integers.*

---

## 21. CLI Tool Usage (Fallback Execution)

Always set working directory and PYTHONPATH before running CLI tools:

```powershell
cd D:\aic226\tv5
$env:PYTHONPATH = "D:\aic226\tv5;D:\aic226\tv5\tv5"

# Validate a single query CSV
& "D:\aic226\tv1tv3\TV1_TV3_WP04\.venv\Scripts\python.exe" -m tv5.submission validate-csv D:\aic226\tv5\outputs\query_1.csv --task-type KIS

# Package a directory of CSVs into a submission ZIP
& "D:\aic226\tv1tv3\TV1_TV3_WP04\.venv\Scripts\python.exe" -m tv5.submission package D:\aic226\tv5\outputs\csvs D:\aic226\tv5\outputs\submission.zip

# Validate an existing submission ZIP package
& "D:\aic226\tv1tv3\TV1_TV3_WP04\.venv\Scripts\python.exe" -m tv5.submission validate-package D:\aic226\tv5\outputs\submission.zip
```

---

## 22. Operational Telemetry Status

- **Implementation**: Telemetry recorder, event definitions, and secret redaction library exist in `tv5/telemetry/` and are unit-tested.
- **Integration Status**: Automatic runtime workflow emission is **NOT** yet wired into live FastAPI or React paths (classified as `T025: IMPLEMENTED LIBRARY / INTEGRATION PENDING`).
- **Operator Note**: `telemetry.jsonl` will not populate automatically during UI usage until T025 wiring is completed.

---

## 23. Evaluation & Metric Engine Status

- **Implementation**: Competition scoring formulas (KIS binary hit, VQA semantic agreement requirement, TRAKE R-Score, R@k, Final Score = 0.74 golden) and report models exist in `tv5/evaluation/metrics.py` and `reports.py`.
- **Preprocessing Ingestion**: Read-only manifest parser exists in `tv5/evaluation/preprocessing_reports.py`.
- **Integration Status**: UI/CLI operator adapter exposure remains pending under `T046` and `T048`.

---

## 24. Backup and Restore Procedures

Set working directory and PYTHONPATH before running backup scripts:

```powershell
cd D:\aic226\tv5
$env:PYTHONPATH = "D:\aic226\tv5;D:\aic226\tv5\tv5"
```

### Create State Backup:
```python
from pathlib import Path
from tv5.backup import create_backup

manifest = create_backup(
    state_dir=Path("D:/aic226/tv5/state"),
    output_zip=Path("D:/aic226/tv5/backups/wp13_backup.zip")
)
print(f"Backup created with SHA-256: {manifest.archive_sha256}")
```

### Restore State:
```python
from pathlib import Path
from tv5.backup import restore_backup

ok, manifest, errors = restore_backup(
    zip_path=Path("D:/aic226/tv5/backups/wp13_backup.zip"),
    target_dir=Path("D:/aic226/tv5/state")
)
print(f"Restore success: {ok}, readiness invalidated: {manifest.readiness_invalidated}")
```

*Note: Restoring a backup automatically invalidates readiness status until revalidated.*

---

## 25. Controlled Shutdown

Stop services in reverse dependency order:
1. Stop WP13 Vite dev server (`Ctrl+C`).
2. Stop TV4 Uvicorn process (`Ctrl+C`).
3. Stop WP04 Uvicorn process (`Ctrl+C`).
4. Stop TV1 server (`Ctrl+C`).

Verify ports 8000, 8100, 8200, 5173 are no longer in `Listen` state:
```powershell
Get-NetTCPConnection -LocalPort 8000, 8100, 8200, 5173 -State Listen -ErrorAction SilentlyContinue
```

---

## 26. Troubleshooting and Recovery Matrix

| Symptom | Root Cause | Recovery Action |
|---|---|---|
| Port 5173 occupied, Vite starts on 5174 | Stale Vite process running | Run `Get-NetTCPConnection -LocalPort 5173` and kill PID, then restart `npm run dev` |
| TV4 returns HTTP 503 / Degraded | TV1 or WP04 not running, or wrong config | Verify TV1 (8000) and WP04 (8100) are up; verify `TV4_CONFIG=configs/default.yaml` |
| Exact neighbor returns HTTP 409 | Candidate uncertified or decode proof failed | Fail closed: keep coarse anchor; do not bypass proof validation |
| WP04 Evidence is empty / degraded | Development run or no evidence detected | System operates in degraded mode; manual VQA answer entry remains functional |
| Submission validation fails on `.mp4` | Video ID has file extension or invalid format | Use the authoritative canonical video_id supplied by the upstream candidate/registry. Do not derive submission identity by manually stripping or transforming filenames. |
| Interrupted backup write | Write interrupted midway | Backup uses atomic write to temporary file; corrupt partial file unlinked automatically |

---

## 27. Target-Machine Handoff Checklist & Task Graph Alignment

### Implemented & Unit-Tested Assets on Current Machine:
- [x] Accepted core KIS/Feedback/VQA/TRAKE operator UI plus Media Inspector and Evidence rendering.
- [x] 124 passing Vitest unit/integration tests
- [x] 75 passing Python contract/unit/integration tests
- [x] 69 passing TV4 backend tests
- [x] RFC 4180 CSV serializer, fail-closed validator, top-level `submission/` ZIP packager, CLI tool (`tv5/submission/`)
- [x] Evaluation metric calculation engine (`tv5/evaluation/metrics.py`, `reports.py`)
- [x] Preprocessing report parser (`tv5/evaluation/preprocessing_reports.py`)
- [x] Telemetry recorder library (`tv5/telemetry/`)
- [x] Docker Compose definitions & config lock (`tv5/deployment/`)
- [x] Backup manager with restore revalidation (`tv5/backup/manager.py`)
- [x] Pre-handover validation of WP03 `full-run-1` (4 models, 106,380 vectors each)

### Pending Integrations & Handoff Items (Do Not Overclaim as Accepted):
- [ ] **T025**: Wire operational telemetry emission into runtime FastAPI and React workflows.
- [ ] **T036**: Complete automated test coverage for mode/grid/lock/basket shortcuts.
- [ ] **T037**: Mount `KeyboardHelpModal` into root `App.tsx` view.
- [ ] **T038**: Complete frontend cross-workflow shared basket guard tests.
- [ ] **T039**: Unify frontend KIS basket entry into the shared submission basket.
- [ ] **T040–T044 Acceptance**: Formal task acceptance pending T038/T039 prerequisites.
- [ ] **T046**: Implement operator UI/CLI adapter for evaluation metrics.
- [ ] **T048**: Implement operator UI/CLI display for preprocessing reports.
- [ ] **T050**: Execute live search for current 3-video WP03 KIS/Feedback where supported against running backend.
- [ ] **T052**: Perform runtime Docker container startup and daemon health check.
- [ ] **T054 Acceptance**: Formal task acceptance pending T052 runtime startup.
- [ ] **T055**: Conduct non-owner human operator dry-run of `RUN_BOOK.md`.
- [ ] **T056 Handover**: Receive formal external Claim-1 handover artifact.
- [ ] **T057 Handover**: Receive, read-only validate, and freeze the external Claim-2 full-corpus WP04 modality delivery.
- [ ] **T058–T061 Final Live Acceptance**: Execute live E2E, 3-mock competitions, and target release freeze on target GPU host.
