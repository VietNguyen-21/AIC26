# WP13 Repository Instructions

## Repository Role

This repository is the official team repository containing WP13 work.

WP13 owns:

- UI
- Evaluation
- Submission
- Deployment
- Release
- Mock Competition support

Do not implement feature work directly on main.

Use the designated TV5 branch or a task-specific branch derived from it.

---

## Current Project Phase

WP13 begins from an existing upstream system.

Do not rebuild WP00-WP12 as part of normal WP13 development.

Reuse existing services, contracts, fixtures, data, preprocessing runs,
and indexes.

New production implementation should primarily focus on WP13 integration,
UI, evaluation, submission, deployment, and reliability.

---

## Specification First

Before substantial WP13 implementation on the TV5 host, consult the
canonical AIC 2026 competition and team architecture documentation.

Do not invent competition scoring, submission formats, frame identity,
or upstream contracts.

If canonical local references are unavailable on another machine,
do not guess missing competition requirements.

---

## Upstream Boundary

WP13 consumes behavior from WP10-WP12.

Prefer existing upstream contracts and adapters over reimplementing
retrieval logic.

For the current local integration environment, TV4 is the primary
application boundary.

Before building a replacement interface, inspect the existing:

- contracts;
- HTTP API;
- fixtures;
- submission utilities;
- tests.

---

## Original-frame Safety

Submission frame IDs must resolve to real frames in the original video.

Never substitute:

- keyframe sequence IDs;
- proxy frame IDs;
- UI-only frame indexes

for canonical original-video frame IDs.

---

## Development Discipline

For non-trivial changes:

1. inspect requirements and existing contracts;
2. inspect tests;
3. produce a plan;
4. define acceptance criteria;
5. add or identify tests;
6. implement a focused change;
7. run relevant tests;
8. review the diff;
9. perform manual UI verification when applicable.

Do not refactor unrelated working code merely for style.

---

## Testing

Prefer:

- unit tests for isolated logic;
- contract tests for upstream boundaries;
- integration tests for service interaction;
- end-to-end tests for KIS/VQA/TRAKE workflows;
- manual UI verification for interactive behavior.

Official metric logic must have regression tests based on organizer
examples.

Submission behavior must be validated against the official competition
specification.

---

## Git Safety

Before commit:

git status
git diff
git diff --staged

Do not commit:

- raw video;
- preprocessing artifacts;
- embeddings;
- FAISS indexes;
- credentials;
- secrets;
- local virtual environments;
- caches.

Never force-push unless explicitly approved.

---

## Completion Standard

Do not claim completion without verification evidence.

Report:

- changed files;
- tests;
- executed commands;
- results;
- manual verification;
- known limitations;
- unresolved specification or contract conflicts.
