# Implementation-Readiness Checklist: Complete Contest-Ready WP13

`[x]` means planning evidence is present and E4 can begin; it does not mean code or final live acceptance is complete.

## E3 planning gate

- [x] CHK001 Spec describes the complete Final-Pipeline target rather than current artifact limits.
- [x] CHK002 Plan separates implementation gate and final live acceptance gate.
- [x] CHK003 Dependency classes for Claim 1/2/3 are explicit and not mixed.
- [x] CHK004 Tasks are concrete, dependency-aware, test-first, owned and identify final-live dependencies separately.
- [x] CHK005 Every FR-001-FR-080 maps to an implementation task and test/acceptance path.
- [x] CHK006 No task runs WP03/WP04 preprocessing or builds a persistent replacement corpus mapping.
- [x] CHK007 Current source defects were rechecked; raw PTS, false mapping guarantee, missing neighbor/media/health/evidence/Feedback seams and incompatible exporter remain scheduled.
- [x] CHK008 Existing WP08 original-query/history/reference behavior is reused; no unsupported behavior is invented.

## Exact-frame P0 gate

- [x] CHK009 Resolver tests precede implementation and cover all specified identity/PTS/seek/provenance risks.
- [x] CHK010 Immediate previous/current/next original frames, repeated stepping and boundaries are explicit.
- [x] CHK011 Newly inspected frames are nonselectable until proof; unresolved results fail closed.
- [x] CHK012 Raw PTS/FPS/keyframe/proxy/UI/browser/seek-local identity is prohibited end-to-end.
- [x] CHK013 Tracked-first WP09/TV4 changes and reviewed runtime synchronization are separate tasks.
- [x] CHK014 Safe configured original-media transport has security/range/read-only tests.

## Workflow and contract gate

- [x] CHK015 KIS, Feedback, VQA and TRAKE have independent fixture/current/live slices.
- [x] CHK016 Visual/OCR/ASR/Object/Metadata/RRF/evidence/provenance/degradation are represented in contracts and tasks.
- [x] CHK017 VQA empty/weak evidence, retry, manual fallback, approval and exact export text have tests.
- [x] CHK018 TRAKE semantic count/order, locks/correction, exact frames and export have tests.
- [x] CHK019 Feedback reset/history/no-basket-mutation/canonical revalidation and optional advanced model have tests.
- [x] CHK020 Keyboard shortcuts cannot bypass canonical, approval or order guards.
- [x] CHK021 Basket, headerless CSV, ZIP, CLI and conditional API fallback fail closed.

## Evaluation and operations gate

- [x] CHK022 Official goldens and internal metrics are test-first; missing VQA adjudication returns incomplete.
- [x] CHK023 Upstream preprocessing reports are ingested read-only; metric tasks do not own preprocessing.
- [x] CHK024 Readiness validator reports `READY|PARTIAL|MISSING|INCOMPATIBLE` without repair.
- [x] CHK025 Fixture/current partial/final live quickstart contains service order, health and handover revalidation.
- [x] CHK026 Compose/config lock/read-only mounts/mutable persistence/backup/restore/runbook are planned and tested.
- [x] CHK027 Corrected WP03 and WP04 acceptance gates are read-only and precede full live E2E.
- [x] CHK028 Three P0-clean mocks, target-machine recovery, cross-review and non-owner handoff precede final freeze.

## Readiness verdict

- [x] E4 implementation can begin immediately.
- [ ] Final live contest readiness (intentionally pending Claim 1/2 handovers, implementation, exact-frame proof and final gates).
