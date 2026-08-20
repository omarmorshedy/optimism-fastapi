# Optimism — FastAPI Replacement (implementation repo)

Fresh git repository for the FastAPI/SQLAlchemy rewrite of [DoES Liverpool](https://doesliverpool.com)'s
resource-booking system ("Optimism"). This repo is intentionally **separate** from the legacy
codebase; it contains everything the implementation agent needs as **read-only reference**.

## Layout

| Path | What it is |
|---|---|
| `docs/planning/` | The planning/reference markdown files (copies): `API_SPEC.md`, `IMPLEMENTATION_PLAN.md`, `EVALUATION.md`, `PLAN_REVIEW.md`, `summary.md`, `todo.md`, and `arc42/` (12-chapter architecture docs). **Start here.** |
| `legacy/` | The original Node/Express codebase as a **git submodule**, pinned to commit `e5eef9c` (`master`). Read it for behaviour reference; never edit it. |
| `app/`, `tests/` | (to be created) The FastAPI implementation per `docs/planning/IMPLEMENTATION_PLAN.md`. |

## For the coding agent

1. **The authoritative API contract is `docs/planning/API_SPEC.md`** — the middle ground
   between the legacy API and the approved improvements. Implement exactly that. The
   legacy→v1 endpoint mapping is in its §2.3; the improvements-applied parity matrix in §10.
2. **The delivery order is `docs/planning/IMPLEMENTATION_PLAN.md`** — test-first baseline,
   quality gates, ordered checklist. Do not start coding until the §11 default decisions in
   `API_SPEC.md` are confirmed with the product owner.
3. **`docs/planning/PLAN_REVIEW.md`** records the review of the plan and the open decisions.
4. **`legacy/`** contains the original `api/`, `website/`, migrations, seeds and tests — use
   it as the behavioural reference when translating legacy tests (its API integration tests
   live in `legacy/api/test/`).

## Maintenance

- These planning docs are **copies**. The working originals live untracked in
  `/home/doesliverpool-0/dev/optimism` (intentionally not committed there). This repo is the
  durable, git-protected copy — refresh with `cp` from that directory when they change.
- Bump the legacy reference: `git -C legacy fetch && git -C legacy checkout <commit>` then
  commit the pointer update. Submodule URL: https://github.com/DoESLiverpool/optimism.git
  (upstream: https://github.com/DoESLiverpool/optimism — `develop` is the active branch).
- The legacy `issue-71` API-proxy work lives on branch `issue-71-api-proxy` in the
  `optimism-issue-71` worktree (not merged to `master` at pin time).
