# E4 Implementation Quickstart

This is a future implementation/run guide. It contains no preprocessing steps and must never be used to rebuild WP03/WP04 artifacts.

## Common preflight

1. Work on `team/tv5-ui-evaluation-release`; verify tracked source before runtime copies.
2. Configure TV4 source/runtime, WP09 source/runtime, WP08, TV1/TV3 APIs, authoritative read-only raw-media root/registry, WP13 mutable-state root and artifact roots through environment/config. Do not hard-code `D:\aic226` in portable code.
3. Run the read-only readiness command. Interpret `READY`, `PARTIAL`, `MISSING`, `INCOMPATIBLE`; never repair/preprocess from it.
4. Start services in dependency order: required upstream runtime(s) -> TV4 -> WP13. Probe component health; process startup alone is insufficient.

## Fixture mode

Use deterministic KIS/Feedback/VQA/TRAKE/evidence/exact-neighbor/degraded fixtures and metric/submission goldens. Label all UI/report output `FIXTURE`; fixture readiness is not live readiness. Exercise basket, shortcuts, CSV/ZIP, CLI fallback, telemetry and backup/restore without full corpus or GPU.

## Current partial live mode

Point TV4 at the current WP03 smoke artifact and current WP08 where supported. Expect WP03 `PARTIAL` and WP04 branches `MISSING`; keep these visible. Run all applicable current-artifact tests, including known canonical anchors, representative original-video exact-frame TDD, safe media ranges and degraded VQA/evidence. Never describe this mode as final live contest-ready.

## Final live mode

After corrected WP03 and WP04 handover:

1. Mount/read artifacts read-only and rerun schema/digest/index-map/coverage/linkage/provenance validation.
2. Reject incompatible handover; do not repair it.
3. Freeze accepted artifact roots, digests, model/run/config and media registry.
4. Rerun Visual/OCR/ASR/Object/Metadata, routing/RRF, KIS/Feedback/VQA/TRAKE, exact-frame, submission/evaluation, full E2E and health.
5. Complete three consecutive P0-clean mock competitions, target-machine fresh start, backup/restore and non-owner handoff before final release.

## Exact-frame enablement gate

Keep neighbor submission disabled until anchor/global-ID, immediate prev/current/next, repeated stepping, boundaries, VFR/seek/back-seek, duplicate/missing/non-monotonic PTS, cross-anchor and stale-provenance tests pass. Raw PTS/FPS/keyframe/proxy/UI/browser/seek-local identity is forbidden. Unproved neighbors remain nonselectable.

## Submission operation

Use UI or CLI to revalidate basket, write headerless CSV, build `submission/` ZIP, reopen/revalidate and manually inspect. Use an API fallback only when explicitly approved/configured. No automated test or WP13 command uploads to Codabench.

## Recovery

Restore only WP13-owned mutable state and config lock, re-probe dependencies and revalidate drafts/packages. Upstream artifact mounts remain read-only and are not copied into backup. Any changed handover/config invalidates prior ready status.
