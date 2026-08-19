# Feature Specification: Complete Contest-Ready WP13 System

**Feature Branch**: `team/tv5-ui-evaluation-release`

**Feature Identifier**: `001-contest-ready-wp13`

**Created**: 2026-08-17

**Status**: Revised for E4 implementation; final live acceptance remains gated

**Input**: One contest-ready WP13 operator product covering KIS, VQA/Q&A, TRAKE, original-video inspection, submission preparation, evaluation, fixture/live operation, failure handling, and deployment handoff.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Find and inspect KIS moments (Priority: P0)

As a contest operator, I can enter a textual KIS query, review as many as 100 ranked candidates, inspect each candidate against the original video and its evidence, and deliberately add promising candidates to the submission basket.

**Why this priority**: KIS is a primary contest workflow and depends on fast, identity-safe inspection under time pressure.

**Independent Test**: Use deterministic KIS fixture data, submit a query, inspect the ranked candidates and original-video location, step through approved neighboring frames, and add candidates to the basket without using live retrieval services.

**Acceptance Scenarios**:

1. **Given** a valid KIS query and an available runtime, **When** the operator searches, **Then** the product displays no more than 100 candidates with visible rank, canonical `video_id`, original `frame_id`, canonical timestamp, and available evidence/provenance.
2. **Given** a displayed candidate, **When** the operator opens it, **Then** the original raw video is shown at a location consistent with that candidate's canonical timestamp and frame identity.
3. **Given** an inspected candidate, **When** the operator adds it to the basket, **Then** the basket retains its canonical identity and a visible submission rank.
4. **Given** an empty or failed KIS response, **When** the search completes, **Then** the product shows an explicit empty, degraded, or error state and does not fabricate a candidate.

---

### User Story 2 - Answer VQA with mandatory human confirmation (Priority: P0)

As a contest operator, I can submit an event description and question, inspect candidate evidence and original frames, review an optional answer suggestion, enter or edit the answer, and explicitly confirm it before it becomes eligible for submission.

**Why this priority**: VQA correctness depends on both grounded evidence and human control; unsafe automatic answers can consume a contest submission opportunity.

**Independent Test**: Use deterministic VQA fixtures containing evidence, no evidence, and a weak suggestion; verify that evidence can be inspected, answers can be edited, and no answer enters the basket without explicit confirmation.

**Acceptance Scenarios**:

1. **Given** a VQA result with evidence, **When** the operator reviews it, **Then** the product displays the candidate identity, evidence, suggestion status, confidence when available, and a separately editable answer field.
2. **Given** any machine-provided suggestion, **When** it first appears, **Then** it is not selected or confirmed for submission automatically.
3. **Given** an operator-edited answer, **When** the operator explicitly confirms it, **Then** that exact approved text becomes eligible for basket selection.
4. **Given** empty evidence, **When** VQA results are displayed, **Then** the product does not present a confident automatic answer and requires manual inspection and entry.
5. **Given** a weak or unavailable answer engine, **When** candidate retrieval succeeds, **Then** evidence inspection and manual answer entry remain usable.

---

### User Story 3 - Build an ordered TRAKE prediction (Priority: P0)

As a contest operator, I can provide an ordered event list, inspect the retrieved video hypothesis and one candidate frame for every event, adjust selections, lock accepted events, and add only a complete order-preserving hypothesis to the basket.

**Why this priority**: Incorrect event count or semantic order invalidates the intended TRAKE prediction and cannot be repaired during serialization.

**Independent Test**: Use a deterministic four-event fixture, inspect each event frame, lock and unlock selections, attempt invalid deletion/reordering, and verify that only a complete four-frame ordered hypothesis can enter the basket.

**Acceptance Scenarios**:

1. **Given** an ordered list of N events, **When** alignment succeeds, **Then** the product displays the selected video and exactly N event positions in the same semantic order.
2. **Given** an event position, **When** the operator inspects or changes its frame, **Then** the position remains associated with its original event and canonical video identity.
3. **Given** locked event selections, **When** another operation would replace them, **Then** the product preserves the locks until the operator explicitly unlocks them.
4. **Given** missing, duplicated, extra, or semantically reordered event positions, **When** the operator attempts basket selection, **Then** the product rejects the hypothesis and identifies the violation.
5. **Given** no valid alignment, **When** processing ends, **Then** the product shows an explicit no-alignment state and creates no submission prediction.

---

### User Story 4 - Inspect canonical original video and exact frames (Priority: P0)

As a contest operator, I can play the existing local raw video read-only, seek to the candidate's canonical time, inspect the canonical frame, and step through approved neighboring original frames without creating a competing frame mapping.

**Why this priority**: Original-video identity is a contest-correctness invariant shared by all three tasks.

**Independent Test**: Open a known canonical candidate, compare the displayed identity and timestamp with its source record, step backward and forward through approved exact-frame results, and verify that no raw video is modified.

**Acceptance Scenarios**:

1. **Given** a canonical `video_id`, **When** playback is requested, **Then** the product serves the corresponding existing raw video read-only and does not substitute a proxy identity.
2. **Given** a canonical candidate timestamp and frame, **When** inspection opens, **Then** playback and frame inspection remain consistent with the upstream canonical mapping and decoder timing.
3. **Given** a request to step or refine a frame, **When** the shared exact-frame capability is available, **Then** the product uses its canonical results, including degraded/manual-only status and audit information when supplied.
4. **Given** that exact-frame capability is unavailable, **When** the operator requests stepping or refinement, **Then** the product clearly disables or degrades that action and never derives a new frame ID from nominal FPS, playback position, a proxy, or a UI index.

---

### User Story 5 - Manage a rank-safe submission basket (Priority: P0)

As a contest operator, I can review, rank, remove, and validate predictions for each query while seeing task-specific readiness problems before export.

**Why this priority**: The basket is the control point between retrieval results and irreversible contest submission files.

**Independent Test**: Populate baskets for all three task types, exercise the 100-prediction boundary, and verify that visible basket order exactly matches export order.

**Acceptance Scenarios**:

1. **Given** predictions for multiple queries, **When** the basket is opened, **Then** entries are grouped by query and task with visible rank and canonical identity.
2. **Given** a basket with 100 predictions for a query, **When** a 101st is added, **Then** the addition is rejected without changing the existing 100.
3. **Given** basket edits, **When** a prediction is removed or deliberately reordered, **Then** the visible ranks are deterministic and exported in exactly that order; no hidden sorting occurs.
4. **Given** an unconfirmed VQA answer or incomplete TRAKE prediction, **When** basket readiness is evaluated, **Then** the affected query remains not ready.

---

### User Story 6 - Export one correct CSV per query (Priority: P0)

As a contest operator, I can export each ready query to a plain-text competition CSV whose records preserve the basket's visible ordering and approved content.

**Why this priority**: A correct UI without correct files cannot produce a valid contest submission.

**Independent Test**: Export golden KIS, Q&A, and TRAKE baskets and compare the bytes and parsed records with their expected headerless UTF-8 fixtures.

**Acceptance Scenarios**:

1. **Given** a ready KIS basket, **When** it is exported, **Then** every record has exactly `<video_id>,<frame_id>` in visible rank order.
2. **Given** a ready Q&A basket, **When** it is exported, **Then** every record has exactly `<video_id>,<frame_id>,<answer>` and preserves the operator-approved answer text.
3. **Given** a ready TRAKE basket with N events, **When** it is exported, **Then** every record has exactly `<video_id>,<frame_id_1>,...,<frame_id_N>` in semantic event order.
4. **Given** an answer containing commas, quotes, line breaks, Vietnamese text, English text, or leading/trailing whitespace, **When** it is exported, **Then** standard CSV quoting/escaping preserves the approved text on round-trip parsing.
5. **Given** any query export, **When** the file is inspected, **Then** it is UTF-8, contains no header row, contains at most 100 records, uses video identifiers without `.mp4`, and uses integer original-frame IDs.

---

### User Story 7 - Fail closed before submission (Priority: P0)

As a contest operator, I can validate selected predictions, exported files, and the final package and receive a complete actionable error report before anything is marked ready.

**Why this priority**: Malformed submissions can consume limited attempts and constitute a contest-blocking failure.

**Independent Test**: Run the validator against valid golden fixtures and intentionally malformed files/packages covering every required failure class.

**Acceptance Scenarios**:

1. **Given** any validation error, **When** validation completes, **Then** the submission is marked not ready and cannot be packaged as ready.
2. **Given** several independent errors, **When** validation completes, **Then** all safely detectable errors are reported together with query/file context.
3. **Given** an unknown task suffix, missing query file, wrong filename, wrong schema, header, invalid encoding/CSV, more than 100 records, `.mp4` video ID, non-integer frame ID, unconfirmed VQA answer, over-limit VQA answer, or invalid TRAKE count/order, **When** validation runs, **Then** it rejects the affected submission.
4. **Given** an identity that cannot be verified against the available canonical registry, **When** final validation runs, **Then** it fails closed rather than assuming the identity is valid.

---

### User Story 8 - Package the submission ZIP (Priority: P0)

As a contest operator, I can create a ZIP containing the required top-level `submission/` directory and exactly the validated per-query CSV files, then inspect its readiness report before manually uploading it.

**Why this priority**: Directory layout and filenames are provisional operational requirements that directly affect submission acceptance.

**Independent Test**: Package the deterministic golden query set, inspect the archive tree, and verify rejection of root-level CSVs, missing/wrong files, malformed files, and unexpected spreadsheet files.

**Acceptance Scenarios**:

1. **Given** all expected query CSVs pass validation, **When** packaging is requested, **Then** the ZIP contains them under a top-level `submission/` directory with the expected query-derived filenames.
2. **Given** a missing, invalid, unexpected, or wrongly named output, **When** packaging is requested, **Then** no package is marked ready.
3. **Given** a successfully created ZIP, **When** final validation reopens it, **Then** archive structure and every contained CSV pass the same fail-closed rules.
4. **Given** a ready package, **When** the workflow finishes, **Then** the operator receives the local artifact and validation report but no automated Codabench upload occurs.

---

### User Story 9 - Simulate official metrics (Priority: P0)

As an evaluator, I can load predictions and ground truth, calculate task R-Score, R@1, R@5, R@20, R@50, R@100, and Final Score, and inspect per-query results.

**Why this priority**: Metric simulation is required for trustworthy local evaluation but is secondary to producing a valid contest submission.

**Independent Test**: Evaluate organizer-derived golden examples for KIS, VQA, TRAKE, and Final Score and compare exact expected results.

**Acceptance Scenarios**:

1. **Given** a KIS prediction with the correct video and a frame inside the accepted interval, **When** scored, **Then** R-Score is 1; wrong video or out-of-interval frame produces 0.
2. **Given** a VQA prediction, **When** scored, **Then** correctness requires correct video, an in-interval frame, and authoritative semantic answer agreement; exact-string matching alone is not substituted for semantic agreement.
3. **Given** a four-event TRAKE prediction with correct video and three accepted event frames, **When** scored, **Then** R-Score is 0.75.
4. **Given** ranked predictions, **When** R@k is calculated, **Then** each value is the maximum R-Score among the first k records for k in 1, 5, 20, 50, and 100.
5. **Given** R@1=0.5 and R@5=R@20=R@50=R@100=0.8, **When** Final Score is calculated, **Then** it is 0.74.

---

### User Story 10 - Operate deterministically in fixture or live mode (Priority: P0)

As an operator or tester, I can start WP13 in fixture or live mode using configuration, immediately see the active mode and health, and use the same operator workflows in either mode.

**Why this priority**: Fixture mode enables reliable development and recovery without requiring every upstream service; live mode is required for contest use.

**Independent Test**: Repeat identical fixture queries across restarts and verify equivalent results, then switch configuration to live mode without changing competition semantics or UI workflow.

**Acceptance Scenarios**:

1. **Given** fixture mode, **When** the same request is repeated from the same fixture version, **Then** response content and ordering are deterministic.
2. **Given** either runtime mode, **When** the product is opened, **Then** the active mode and health/degraded state are visible to the operator.
3. **Given** a runtime-mode switch, **When** configuration is changed and the product restarts, **Then** task contracts, validation rules, and submission semantics remain unchanged.
4. **Given** fixture data, **When** it is used for tests or demonstrations, **Then** it does not redefine canonical TV4, frame, metric, or submission contracts.

---

### User Story 11 - Recover from degraded or failed dependencies (Priority: P0)

As a contest operator, I receive clear failure status and safe fallback actions when retrieval, evidence, exact-frame, media, or submission dependencies are degraded.

**Why this priority**: Competition operation must continue safely through partial failures without inventing results or corrupting submissions.

**Independent Test**: Simulate each dependency class as unavailable and verify visible status, preserved operator work, allowed fallback, and blocked unsafe actions.

**Acceptance Scenarios**:

1. **Given** live TV4 is unhealthy, **When** an operation depends on it, **Then** the product shows the upstream failure and does not present stale or fabricated results as current.
2. **Given** evidence or the answer engine is unavailable, **When** VQA candidates remain available, **Then** the operator can inspect available original frames and manually enter an answer, while confirmation remains mandatory.
3. **Given** exact-frame stepping is unavailable, **When** an already canonical coarse candidate exists, **Then** that identity is preserved and stepping/refinement is disabled or marked degraded rather than approximated.
4. **Given** an interruption or restart, **When** the operator follows recovery instructions, **Then** previously exported artifacts remain untouched and submission readiness must be revalidated before use.

---

### User Story 12 - Deploy and hand off contest operation (Priority: P0)

As the receiving operator, I can start WP13 on the TV4 target machine, configure connections to existing TV1-TV4 services and read-only raw media, verify health, follow recovery procedures, and create a validated package without owner-only knowledge.

**Why this priority**: The system is not contest-ready until another operator can run and recover it on the target machine.

**Independent Test**: A non-owner follows the runbook on the target machine through fixture startup, live configuration, health verification, raw-video inspection, golden submission generation, and a documented recovery exercise.

**Acceptance Scenarios**:

1. **Given** the documented prerequisites and configuration, **When** a receiving operator follows the runbook, **Then** WP13 starts reproducibly and reports its runtime mode and dependency health.
2. **Given** existing TV1-TV4 services, **When** live configuration is applied, **Then** WP13 connects through configuration without rebuilding or repackaging upstream systems.
3. **Given** the raw-video location, **When** configured for WP13, **Then** access is read-only and canonical identity is retained.
4. **Given** a documented failure scenario, **When** backup/recovery instructions are followed, **Then** the operator restores usable operation or a clearly identified fallback path.
5. **Given** the handoff package, **When** a non-owner performs the readiness checklist, **Then** fixture, live smoke, validation, packaging, and recovery evidence are available for review.

---

### User Story 13 - Refine results with reference-frame feedback (Priority: P0)

As a contest operator, I can select a canonical reference frame, add feedback text while retaining the original query, inspect a separate refined result set and session history, and reset to the untouched original results without changing my basket.

**Why this priority**: The Final Pipeline requires the feedback workflow and integration seam. The workflow is P0; any advanced composed-feedback model remains optional until its benchmark and stability gate passes.

**Independent Test**: With deterministic WP08-compatible fixtures, start from KIS results, select a canonical reference frame, refine twice, inspect history, reset, and prove that original results and basket state are unchanged.

**Acceptance Scenarios**:

1. The request retains original query, canonical reference-frame identity, feedback text, session/revision, and immutable original-result snapshot.
2. Refined results are stored separately, independently validate canonical identity, and never mutate the basket automatically.
3. Reset/back-to-original restores the original result view without deleting history or basket entries.
4. Unavailable WP08 produces a visible degraded state while original search remains usable.
5. Absence or benchmark failure of an advanced feedback model does not fail unrelated P0 release gates.

### Edge Cases

- A query returns zero candidates, fewer candidates than requested, duplicate candidates, or ranks with gaps.
- TV4 returns malformed, unknown-version, or partially populated data; optional evidence may be absent, but canonical identity fields may not be invented.
- The canonical raw video is missing, unreadable, or its identity does not match the candidate.
- Playback seek lands between decoded frames or the media uses variable frame rate; canonical inspection must remain governed by decoder PTS/time-base and shared mapping.
- The shared exact-frame service returns `partial`, `manual_only`, or unavailable; the product must preserve its status and coarse fallback without fabricating refinement.
- A VQA suggestion is blank, confidence is absent, evidence is empty, the answer is exactly 100 characters, or it exceeds 100 characters.
- A Q&A answer contains commas, double quotes, embedded line breaks, Vietnamese Unicode, English text, or leading/trailing whitespace.
- A TRAKE event list is empty, contains fewer than two events, has missing selections, uses multiple videos, duplicates an event position, or violates semantic/temporal order.
- Basket operations reach 0, 100, or 101 predictions; concurrent or repeated actions must not create hidden duplicates or reorder records silently.
- Query filenames have unsupported or ambiguous task suffixes.
- A ZIP contains traversal-like names, root-level CSVs, missing query CSVs, duplicate filenames, malformed CSVs, or unexpected spreadsheet files.
- Ground truth is incomplete or cannot provide an authoritative VQA semantic-match verdict; the metric simulator must report the evaluation as incomplete rather than substituting exact-string semantics.
- The system restarts during export or packaging; incomplete output must never be reported as ready.
- Repeated frame stepping reaches first/last-frame boundaries, duplicate/missing/non-monotonic PTS, stale provenance, or a seek-backward re-identification mismatch; unresolved identity is nonselectable.
- Feedback refinement fails, returns a candidate outside the session snapshot, or returns a noncanonical candidate; original results and basket remain intact.

## Requirements *(mandatory)*

### Functional Requirements

#### Product and authority boundary

- **FR-001**: The product MUST provide one integrated operator experience for KIS, VQA/Q&A, TRAKE, original-video inspection, evaluation, submission preparation, and runtime health.
- **FR-002**: The product MUST consume existing upstream behavior through the approved TV4 application boundary wherever that behavior exists.
- **FR-003**: The WP13 application MUST NOT duplicate upstream retrieval, multimodal fusion, event alignment, preprocessing, or exact-frame logic; it MUST consume the CLOSED/ACCEPTED E4-1 WP09/TV4 exact-frame foundation and MUST NOT create a competing WP13 mapper.
- **FR-004**: The product MUST treat original video as the final media source of truth and canonical upstream `video_id`, original `frame_id`, timestamp, and mapping provenance as authoritative.
- **FR-005**: The product MUST NOT derive a submission frame from keyframe sequence, proxy identity, UI index, decoder iteration index, nominal FPS, or unapproved local calculation.

#### KIS

- **FR-006**: The product MUST accept a textual KIS query and display up to 100 ranked results.
- **FR-007**: Each KIS result MUST expose rank, canonical identity, canonical timestamp, and available score/evidence/provenance sufficient for operator inspection.
- **FR-008**: The operator MUST be able to inspect and deliberately select KIS results for the query basket.

#### VQA/Q&A

- **FR-009**: The product MUST accept an event description and question and display candidate original-frame evidence.
- **FR-010**: The product MAY display an upstream answer suggestion only when the suggestion and its evidence state are clearly distinguished from operator approval.
- **FR-011**: No VQA suggestion MUST be automatically selected, confirmed, or added to a submission basket.
- **FR-012**: The operator MUST explicitly confirm or edit every VQA answer before its prediction becomes submission-eligible.
- **FR-013**: Empty evidence MUST never yield a confident automatic answer; the product MUST expose a manual-review state.
- **FR-014**: Evidence inspection and manual answer entry MUST remain available when the answer engine is weak, unavailable, or abstains, provided candidate identity/media remain available.
- **FR-015**: The product MUST preserve the operator-approved answer exactly through basket storage and CSV serialization, including leading/trailing whitespace and Unicode text.
- **FR-016**: Under the provisional submission contract, answers of 100 characters MUST be accepted and answers longer than 100 characters MUST be rejected before readiness.

#### TRAKE

- **FR-017**: The product MUST accept and preserve an ordered semantic event list.
- **FR-018**: Each TRAKE prediction MUST contain one canonical original-frame selection for every requested event, all belonging to one video.
- **FR-019**: Event locks MUST prevent accidental replacement until explicitly unlocked.
- **FR-020**: The product MUST reject missing, extra, duplicated, or semantically reordered event selections.
- **FR-021**: The product MUST retain event-position association when an operator changes a frame and MUST make count/order validity visible before basket selection.

#### Original-video inspection

- **FR-022**: The product MUST provide read-only browser playback of the existing local raw video corresponding to a canonical video identity.
- **FR-023**: Playback, displayed timestamps, still-frame inspection, and selected original-frame identity MUST remain mutually consistent with approved upstream mapping and decoder timing.
- **FR-024**: Neighbor inspection, frame stepping, and refinement MUST reuse the approved shared exact-frame capability, including its status, mapping guarantee, and audit evidence where available.
- **FR-025**: When shared exact-frame capability is unavailable, the product MUST visibly degrade or disable dependent actions without fabricating a frame; an already canonical upstream candidate may be retained unchanged.
- **FR-026**: The product MUST NOT modify, copy as a replacement source, transcode as a new identity, or submit identity from the local raw-video corpus.

#### Basket, CSV, validation, and packaging

- **FR-027**: The product MUST maintain a separate ordered basket for each query and MUST limit each basket to at most 100 predictions.
- **FR-028**: Visible basket rank MUST be the exported record order; add, remove, or deliberate reorder actions MUST NOT cause hidden sorting.
- **FR-029**: Basket entries MUST retain canonical source identity and task-specific readiness state.
- **FR-030**: The product MUST export one CSV corresponding to each input query, using the task suffix mapping `-kis.txt` to `-kis.csv`, `-qa.txt` to `-qa.csv`, and `-trake.txt` to `-trake.csv` under the provisional operational contract.
- **FR-031**: KIS CSV records MUST contain exactly `<video_id>,<frame_id>`.
- **FR-032**: Q&A CSV records MUST contain exactly `<video_id>,<frame_id>,<answer>`.
- **FR-033**: TRAKE CSV records MUST contain exactly `<video_id>,<frame_id_1>,...,<frame_id_N>` with N matching the query's ordered events.
- **FR-034**: Every CSV MUST be UTF-8, comma-delimited, headerless, plain text, and contain no more than 100 prediction records.
- **FR-035**: CSV serialization MUST use standards-compliant quoting/escaping and MUST round-trip Q&A answers containing commas, quotes, line breaks, Unicode, and surrounding whitespace without semantic rewriting.
- **FR-036**: Exported video identifiers MUST exclude `.mp4`, and all exported frame identifiers MUST be integers representing canonical original-video frames.
- **FR-037**: The product MUST provide a deterministic pre-submit validator that checks basket state, query/file correspondence, task schema, record limit and rank order, CSV validity, canonical identity, VQA confirmation/length/preservation, and TRAKE count/order.
- **FR-038**: Validation MUST fail closed: any detected error or inability to complete a required identity/contract check MUST prevent ready status.
- **FR-039**: Validation MUST report all safely detectable errors with actionable query/file context before the submission is marked ready.
- **FR-040**: The product MUST package only validated query CSVs under a top-level `submission/` directory inside a ZIP.
- **FR-041**: The final validator MUST reopen and validate the ZIP structure and contained CSV records before assigning ready status.
- **FR-042**: The product MUST NOT upload submissions to Codabench automatically; upload remains an explicit human action.

#### Official metric simulation

- **FR-043**: The metric simulator MUST implement the official AIC 2026 KIS, VQA, and TRAKE R-Score semantics without replacement by provisional AIC 2025 wording.
- **FR-044**: For k in 1, 5, 20, 50, and 100, R@k MUST equal the maximum R-Score in the first k ranked predictions, and Final Score MUST equal their arithmetic mean.
- **FR-045**: VQA simulation MUST require authoritative semantic-answer agreement and MUST NOT silently substitute exact-string equality when semantic agreement is unavailable.
- **FR-046**: The simulator MUST expose per-query/task results and MUST reproduce the organizer-derived golden examples defined in acceptance scenarios.

#### Runtime, degraded behavior, and handoff

- **FR-047**: The product MUST support configurable deterministic fixture mode and configurable live mode without changing task or submission semantics.
- **FR-048**: The active mode, WP13 health, TV4 health, and material degraded/error conditions MUST be visible to the operator.
- **FR-049**: Fixture data MUST remain small, deterministic, independent of the full corpus, and contract-conformant without becoming contract authority.
- **FR-050**: Recoverable operator state and previously completed exports MUST be protected from dependency failures and restarts; readiness MUST be revalidated after recovery before submission use.
- **FR-051**: A command-line or equivalent non-UI fallback MUST permit validation and submission-package preparation when the interactive UI is unavailable.
- **FR-052**: WP13-owned deployment MUST start reproducibly and connect to existing TV1-TV4 services through configuration rather than rebuilding or repackaging the full upstream system.
- **FR-053**: Deployment configuration MUST identify runtime mode, upstream service locations, read-only raw-media location, stable run/index/config identifiers when frozen, and health expectations without embedding secrets.
- **FR-054**: The operator runbook MUST cover prerequisites, fixture/live startup, health checks, raw-media verification, submission preparation, shutdown, backup/recovery, fallback, and target-machine readiness checks.
- **FR-055**: Contest readiness MUST require a target-machine handoff exercise, a successful fresh-start verification, backup/recovery verification, and operation by a person other than the primary owner.
- **FR-056**: Contest readiness MUST require at least three consecutive mock competition runs with no known P0 error.
- **FR-057**: If official AIC 2026 submission guidance becomes available, the product's provisional packaging and answer-length rules MUST be reviewed before any subsequent ready package is produced.

#### Complete pipeline-facing capabilities and feedback

- **FR-058**: KIS MUST retain continuous ranking, diversity/video aggregation, exact-frame correction, optional feedback, dense-only fallback, and query/run/model/config/latency logging.
- **FR-059**: The feedback workflow MUST preserve the original query, canonical selected reference frame, raw feedback text, session history where supported, separate original/refined snapshots, reset/back-to-original, and no silent basket mutation.
- **FR-060**: Every feedback-refined candidate MUST independently pass canonical-identity validation before selection; unavailable WP08 MUST be visible and advanced feedback models MUST remain benchmark-gated rather than global P0 blockers.
- **FR-061**: VQA MUST support proposal/confidence, verifier boundary, OCR for text questions, ASR for speech questions, object/multi-frame evidence where applicable, exact-neighbor correction, at most the approved controlled retry, manual fallback, edit and confirm; normalization occurs only before approval and export MUST preserve the approved answer byte-for-byte.
- **FR-062**: TRAKE MUST support ordered parsing, video/event coverage scoring, diverse hypotheses where upstream supports them, exact-frame fine alignment, timeline, lock/unlock, manual correction and pre-basket validation; semantic event order is authoritative and numerical frame sorting MUST NOT redefine it.
- **FR-063**: Visual retrieval integration MUST preserve text-to-frame and supported image/reference-frame-to-frame retrieval, FAISS deterministic mapping, approved model adapters, model/index/mapping provenance, dedup, diversity, aggregation and top-k behavior without redesigning for the current smoke artifact.
- **FR-064**: OCR, ASR, Object and Metadata MUST remain distinct visible retrieval/evidence branches with their upstream fields and provenance; Object is a soft constraint/boost by default and unavailable branches produce explicit degraded state.
- **FR-065**: Routing/fusion MUST preserve task/query parsing, modality priorities, filters, ordered events, rule fallback, low-confidence multi-route behavior, independent raw ranks/scores/evidence, and RRF as the mandatory baseline; incompatible raw scores MUST NOT be directly combined.
- **FR-066**: Evidence presentation MUST support selected original frames/adaptive local sampling, OCR text and bbox/polygon, ASR transcript/timing/context, object labels/bboxes/crops, retrieval/source references, `preprocess_run_id`, model versions and run/config provenance without flattening away source identity.
- **FR-067**: The operator UI MUST provide KIS/VQA/TRAKE modes, top-100 grid, original-timestamp player, exact neighbors and repeated stepping, OCR overlays, ASR context, object evidence, provenance, feedback, VQA proposal/confidence/edit/confirm, TRAKE timeline/lock/unlock/reorder validation, basket and documented keyboard shortcuts.

#### Accepted exact-frame foundation and P0 correctness invariants

- **FR-068**: The CLOSED/ACCEPTED E4-1 production exact-frame foundation through WP09/TV4 MUST be consumed as the canonical backend for anchor identity, immediately previous/current/next ORIGINAL decoded frames, repeated signed cumulative stepping and first/last boundaries; WP13 work is UI/state integration and regression protection, not resolver reconstruction.
- **FR-069**: Exact-frame correctness invariants MUST preserve decoder PTS/time-base handling, seek and seek-backward re-identification, duplicate/missing/non-monotonic PTS handling, cross-anchor consistency, stale/wrong preprocess provenance rejection, and correct VFR handling whenever VFR media or test coverage is available. The absence of a live VFR sample in the accepted E4-1 certification is a documented non-blocking residual; it MUST NOT reopen WP09 or become a current P0 implementation gate, and canonical identity/selectability MUST continue to fail closed under FR-070 and FR-071.
- **FR-070**: Raw PTS, nominal-FPS arithmetic, keyframe sequence, proxy/UI ordinal, browser playback time and seek-local decoded ordinal MUST never become submission `frame_id`; any unprovable identity MUST fail closed.
- **FR-071**: A newly inspected neighboring frame MUST be nonselectable until canonical identity validation passes; display-only stepping cannot satisfy final P0 acceptance.
- **FR-072**: Original-video transport MUST use a configured authoritative registry/root, path containment and byte-range/seek-safe read-only delivery; playback-derived identity is forbidden.

#### Readiness, evaluation and release

- **FR-073**: A read-only handover/readiness validator MUST classify each dependency with the scoped vocabulary `READY`, `PARTIAL`, `HANDOVER PENDING`, `CODE GAP`, `INCOMPATIBLE` or `ACTUALLY MISSING`, emit CLI/UI/runbook diagnostics, and never preprocess or repair artifacts. Known pending owner delivery MUST NOT be relabeled `ACTUALLY MISSING`, and a missing TV4 endpoint MUST NOT erase an existing upstream capability.
- **FR-074**: WP03 validation MUST cover manifest/run/model/config/index/mapping digests, index-map/vector consistency, unique-video and selected-frame coverage, canonical mapping and compatible `preprocess_run_id`, deriving expected counts from authoritative registries where practical.
- **FR-075**: WP04 validation MUST independently cover OCR, ASR, Object and Metadata existence, schema, coverage, canonical/timing linkage, evidence fields, model/run provenance and retrieval-index availability.
- **FR-076**: Evaluation MUST include official R-Score/R@k/Final Score plus Video Hit@K, Frame Interval Hit@K, valid VQA accuracy/E2E, TRAKE video/event alignment, latency p50/p95, time-to-first-correct, submission error rate, and ingestion/reporting of validated upstream preprocessing throughput/storage metrics without rerunning preprocessing.
- **FR-077**: WP13 MUST support the Benchmark -> Ablation -> Error Analysis -> Mock Competition -> Iterate reporting/orchestration loop while leaving upstream preprocessing ownership upstream and distinguishing metric implementation readiness from official-dataset evaluation readiness.
- **FR-078**: Deployment MUST include WP13 Docker Compose, dependency probes, read-only upstream mounts, stable manifest consumption, config lock, WP13-owned mutable-state persistence, backup/restore, fresh/target-machine runbook, CLI fallback and an approved API fallback if available; actual upload remains human-controlled.
- **FR-079**: Final G4-equivalent release requires accepted corrected handovers, regression-protected WP13 consumption of the accepted exact-frame proof, live health/coverage/integration/E2E, submission/evaluation checks, three consecutive P0-clean mocks, target-machine acceptance, recovery, cross-review and non-owner operation.
- **FR-080**: WP13 MUST NOT run WP03/WP04 preprocessing, regenerate upstream artifacts/indexes/mappings, create a persistent full-corpus frame-index replacement, or rewrite stable artifacts; bounded runtime exact-frame decoding/cache is allowed only when provenance-safe.

### Dependency and acceptance classification

| Claim | Classification | Current state | Implementation effect | Final live effect |
|---|---|---|---|---|
| Claim 1: WP03 | EXTERNAL ARTIFACT DEPENDENCY | `smoke-run-1`: 3/873 videos and 892/106,380 selected frames/vectors | Use for supported current integration; do not preprocess; continue unrelated work | Corrected corpus-complete handover must pass read-only validation and freeze |
| Claim 2: WP04 | EXTERNAL ARTIFACT HANDOVER DEPENDENCY plus TV4/WP13 CODE GAP | Producer source, modality contracts, evidence APIs and reusable Range/original-frame semantics exist; corrected OCR/ASR/Object/Metadata artifacts/indexes/evidence are `HANDOVER PENDING` | Build contracts/adapters/UI/degraded paths now; do not repair or run the producer unless explicitly reassigned | Corrected modality handover must pass branch-specific read-only validation; TV4 rich-evidence integration still requires its own evidence |
| Claim 3: exact-frame | CLOSED / ACCEPTED BACKEND FOUNDATION | E4-1 delivered the production resolver, canonical identity, TV4 neighbor integration, certified anchors, signed cumulative stepping, ORIGINAL-frame neighbors/boundaries, proof rejection, live non-sample acceptance and automated regressions | Consume through TV4; implement WP13 inspector/state/basket integration and protect the accepted behavior with regressions | No backend reconstruction or repeat sync; residual defense-in-depth hardening is optional and non-blocking |

The **Implementation Gate** passes when contracts, tests and all independently executable WP13-owned work are ready to begin/continue against fixtures and current artifacts, external gaps are explicit, and no forbidden preprocessing is planned. The **Final Live Acceptance Gate** additionally requires corrected WP03/WP04 acceptance, regression-protected consumption of the accepted exact-frame foundation, frozen artifacts/config, full live integration/E2E, submission/evaluation, mock, deployment and operational handoff. Pending Claim 1/2 handovers do not block implementation-now work.

### Key Entities

- **Query**: A contest request with unique identity, task type, source filename, text/question, and ordered events where applicable.
- **Canonical Candidate**: A ranked upstream result containing canonical video/frame/time identity, evidence/provenance, score/confidence, and runtime version context.
- **Evidence Set**: Available original-frame, OCR, ASR, object, neighboring-frame, and provenance material used for operator judgment; absence is explicit.
- **VQA Approval**: The operator-approved answer text, confirmation state, approving action, and associated canonical candidate/evidence state.
- **TRAKE Event Position**: One immutable semantic position in the ordered query, with event text, selected canonical frame, and lock/validity state.
- **Prediction**: One task-shaped contest answer with visible rank and canonical identity; a TRAKE prediction contains the complete ordered event-frame sequence.
- **Query Basket**: The ordered set of at most 100 predictions for one query plus readiness issues.
- **Validation Report**: Deterministic ready/not-ready result containing all detected errors and the rule/identity context checked.
- **Submission Package**: A ZIP containing top-level `submission/`, expected per-query CSVs, and evidence that final validation passed.
- **Ground Truth and Evaluation Result**: Accepted intervals, semantic answer verdicts, ranked predictions, per-query R-Scores, R@k values, and Final Score.
- **Runtime Status**: Fixture/live mode, WP13 and upstream health, degraded reasons, active configuration identity, and recovery guidance.
- **Feedback Session**: Immutable original query/results, canonical selected reference, raw feedback events/history, refined snapshots, revision and reset state.
- **Artifact Readiness**: Per-dependency classification, diagnostics, expected/observed coverage, digests, provenance and acceptance timestamp.
- **Operational Telemetry**: Query/run/model/config, dependency status, latency, correction actions, time-to-first-correct and submission-validation outcomes without secrets.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can complete each deterministic KIS, VQA, and TRAKE fixture journey from query entry through validated basket selection without consulting source code.
- **SC-002**: Across the golden submission suite, 100% of valid task records and packages are accepted and 100% of required invalid cases are rejected before ready status.
- **SC-003**: A query with exactly 100 predictions exports successfully, while a 101st prediction is rejected without corrupting or reordering the first 100.
- **SC-004**: Golden CSV round trips preserve 100% of operator-approved Q&A answer characters, including commas, quotes, line breaks, Unicode, and leading/trailing whitespace.
- **SC-005**: Golden identity checks show zero use of keyframe-sequence, proxy, UI, or nominal-FPS-derived frame IDs in exported predictions.
- **SC-006**: All empty-evidence VQA cases produce zero automatically confirmed or automatically selected answers, and all exported VQA answers have explicit human confirmation.
- **SC-007**: All accepted TRAKE records contain exactly N canonical frames for N requested events in semantic order; all count/order mutation fixtures are rejected.
- **SC-008**: Official golden metric examples produce exact expected values, including TRAKE 0.75 and Final Score 0.74.
- **SC-009**: Repeating fixture-mode workflows from the same fixture version produces identical result content, ordering, validation reports, and package contents apart from explicitly excluded packaging metadata.
- **SC-010**: Every material dependency failure exercised during readiness review produces a visible degraded/error state and zero fabricated candidates, frames, answers, or ready packages.
- **SC-011**: A receiving operator who is not the primary owner completes fresh startup, health verification, raw-video inspection, golden package creation, and one documented recovery exercise on the target machine.
- **SC-012**: At least three consecutive mock competition runs complete with no known P0 error before contest-ready release.

## Assumptions

- The official AIC 2026 Competition Specification remains authoritative for task and metric semantics.
- No additional official AIC 2026 submission guide is present in the authoritative workspace sources reviewed for this revision. AIC 2025 filename, CSV, answer-length, and ZIP mechanics are provisional operational requirements and require an organizer-source recheck before final submission operation.
- VQA is human-confirmed by default. Upstream suggestions are advisory regardless of `verified`, confidence, or manual-review fields.
- Existing TV4 KIS, VQA, TRAKE, fixture, and health contracts are implementation evidence; they do not override higher-authority requirements.
- Existing TV4 submission utilities are not contest-ready evidence for WP13 because their headers/extra fields and TRAKE JSON output conflict with the adopted submission contract.
- Existing local raw videos are available on the target machine and may be exposed read-only for browser playback.
- E4-1 production exact-frame resolver and WP09/TV4 integration are CLOSED/ACCEPTED. WP13 consumes the shared service, adds UI/state/basket integration, and does not derive identities itself. `VFR_NOT_LIVE_SAMPLED` and the bounded certification sample are accepted residual defense-in-depth risks, not current P0 blockers.
- WP09 tracked -> runtime synchronization is already complete: 34 tracked files verified identical, zero runtime missing and zero hash mismatch. E3.1 does not schedule another synchronization.
- Original MP4s, keyframes, thumbnails, mappings and reusable WP04 Range/original-frame semantics exist. The browser-safe TV4 media/image boundary and WP13 player/state are `CODE GAP`s, not evidence that original-video capability is unavailable.
- Current WP03/WP04 artifacts are temporary external state. Corrected artifacts will be accepted read-only and frozen later; target requirements do not shrink to current coverage.
- Deployment covers WP13-owned responsibilities and connects to separately operated TV1-TV4 services through configuration.
- Actual Codabench upload and any semantic VQA adjudication unavailable locally remain human/organizer-controlled activities.

## Dependencies

- Official AIC 2026 competition task and scoring semantics.
- Approved provisional submission mechanics derived from the AIC 2025 reference.
- TV4 task and health boundary for fixture/live operation.
- Existing canonical media/identity registry and the CLOSED/ACCEPTED E4-1 WP09/TV4 exact-frame capability.
- Existing local raw-video corpus mounted read-only on the target machine.
- Human operator for VQA confirmation, final package inspection, and Codabench upload.
- TV1 infrastructure support for target-machine deployment and runtime artifact freeze.
- Claim 1 corrected corpus-complete WP03 artifact handover (external artifact dependency; final-live only where relevant).
- Claim 2 corrected WP04 OCR/ASR/Object/Metadata artifact/index/evidence handover (known external `HANDOVER PENDING`; producer source/contracts already exist; final-live only where relevant).

## Explicitly Deferred Scope

- Advanced animation and non-essential visual polish.
- A persistent design system or broad component-library effort.
- Non-critical visual analytics dashboards beyond the required evaluation/telemetry reports.
- Framework migration, architecture redesign, or broad upstream refactoring.
- New preprocessing, regeneration of stable artifacts, or full-pipeline rebuild.
- New retrieval methods, model ensembles, advanced composed-feedback models, or replacement VQA models unless their benchmark gate approves them.
- Automated Codabench submission.
- Non-essential abstractions, generalized workflow engines, and unrelated cleanup.

## Authority and Conflict Notes

- Authority order is: official AIC 2026 competition PDF -> AIC2026 Final Pipeline -> AIC 2025 guide for provisional operational submission mechanics only -> current physical/runtime/source evidence -> these derived WP13 planning documents. Implementation limitations never override a higher-authority requirement.
- Official AIC 2026 semantic answer matching overrides the AIC 2025 reference's conflicting exact-string wording.
- The provisional submission contract requires headerless task-shaped CSV records, while current TV4 submission implementation writes headers and extra fields and emits TRAKE JSON. WP13 therefore owns an independent exporter/validator; targeted TV4 repairs remain in scope for media, evidence, health, VQA and WP08 integration, while accepted WP09 exact-frame behavior is consumed and regression-protected.
- Current TV4 fixture VQA fields may report a suggestion as verified, but human confirmation remains mandatory under the approved E1 decision.
- No unresolved human decision prevents independent review of this reconciliation. Code implementation has not started under E3.1. Final live acceptance remains explicitly pending on external Claim 1/2 handovers and evidence-based gates rather than being represented as already achieved.
