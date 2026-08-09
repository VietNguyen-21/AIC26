# WP08 — Interactive Composed Feedback

WP08 refines a fixed WP03 candidate pool from an original query, a selected rendered frame, and feedback text. It never changes the candidate universe during a session.

## Required integration

1. Construct `Wp03FeedbackRuntime(artifact_root, four_encoders, pool_size=500)`.
2. Inject its `pool_provider`, `ranker`, and `renderer` methods into `FeedbackSessions`.
3. Use `Beit3TokenCounter` with the exact `beit3.spm` file used by WP03.

`pool_provider` returns a `SessionPool`: its serializable raw C0 ordering, per-model
embedding references, candidate media metadata, and pinned configuration provenance
are persisted in SQLite. The runtime can restore that snapshot after a process restart
and still rerank the same C0 without issuing a new full-corpus search.

The runtime must receive an approved `StableFeedbackConfig` containing the exact
four model keys plus `benchmark_run_id` and `approved_at_utc`; this is the gate
that allows composed/BGE feedback to be exposed as stable. An experiment that
has not passed benchmark must not construct this runtime.

## Session guarantees

- At most five active feedback events; each has 1–300 raw characters.
- The token counter must be the production BEiT-3 tokenizer and must reject templates above 64 tokens.
- SQLite uses fixed 24-hour TTL, optimistic revision CAS, artifact-run lookup, and idempotent confirmations.
- Refine/Undo failure leaves the old state untouched. Confirm does not increment ranking revision.
- `start_session`, `refine`, `undo`, `reset`, and `get_session` return `SessionView`.
  Its candidates contain only `display_rank`, identity, and media references; raw
  C0/RRF ranks stay in the persisted audit snapshot.

TV5 owns the HTTP/UI adapter. It must supply `expected_revision`, permit selection only from the rendered list, and call `active_artifact_runs()` before cleaning old WP03 artifacts.

`wp08.wp03_adapter.Wp03ArtifactVectorResolver` and
`FourModelFeedbackRanker` implement the per-model fusion and late RRF. The
usual wiring is `Wp03FeedbackRuntime.pool_provider`, `.ranker`, and `.renderer`.
TV5 must send the current `expected_revision`, select only an ID returned by the
latest `SessionView`, map `RevisionConflict` to a refresh, and display
`SessionExpired`, `FeedbackValidationError`, and `ModelRankingFailed` as errors.

For evaluation, TV5 or the labelled harness calls
`FeedbackSessions.record_correct(session_id, candidate_id, expected_revision)`
only after it has externally determined that the frame is correct. The first call
per session is immutable and returns `FirstCorrect`, including `elapsed_ms` and
the `no_feedback`/`with_feedback` cohort. Call `feedback_metrics()` to obtain the
raw elapsed-time samples for each cohort; evaluation code computes its chosen
time-to-first-correct aggregate from those samples.
