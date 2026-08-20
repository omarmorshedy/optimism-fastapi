# Issue #71 Todo: Remove public access to API routes

GitHub issue: https://github.com/DoESLiverpool/optimism/issues/71

## Status

Implementation complete in separate worktree `/home/doesliverpool-0/dev/optimism-issue-71` on branch `issue-71-api-proxy` from `origin/develop`. Docker/manual verification requested by user.

## Chosen issue

**#71: Remove public access to API routes**

I picked this as the top-priority issue because it is a security/deployment architecture issue. The API currently exposes routes publicly, but the website only appears to need browser-side access to the calendar endpoint. Other website/API interactions are already server-side, so public API access can be reduced by proxying calendar requests through the website.

## Issue outline

Issue #71 asks for:

1. Create a proxy endpoint in the website project for the calendar endpoint.
2. Replace client-side calls to use this endpoint.
3. Do not expose port `3001` in the API container.

Expected result: the browser talks only to the website app, while the website app talks privately to the API container over Docker/container networking.

## Current findings

- `website/templates/select-a-time.html` currently makes a browser-side request to:

  ```js
  axios.get("{{apiUrl}}/calendar/...")
  ```

- `{{apiUrl}}` is passed from `settings.apiUrlClientSide` in `website/routes/select-a-time.js`.

- `website/settings.js` currently defines both:

  ```js
  apiUrl: process.env.OPTIMISM_API_URL || 'http://optimism_api:3001/api',
  apiUrlClientSide: process.env.OPTIMISM_API_CLIENT_SIDE_URL || 'http://localhost:3001/api'
  ```

- `docker-compose.yml` currently publishes the API port on localhost:

  ```yaml
  api:
    ports:
      - 127.0.0.1:3001:3001
  ```

- The website service already links to the API service, so server-side calls from website to API via `http://optimism_api:3001/api` should continue to work.

- `api/routes/calendar.js` already implements the API calendar endpoint:

  ```txt
  GET /api/calendar/:startDate/:endDate/:resourceId
  ```

- `website/app.js` is where website routes are registered.

## Proposed implementation plan

Use a separate git worktree, likely from `origin/develop` because the README says most development happens on `develop`:

```bash
git worktree add ../optimism-issue-71 -b issue-71-api-proxy origin/develop
```

Then:

1. Add a website route, probably `website/routes/calendar.js`, exposing:

   ```txt
   GET /api/calendar/:startDate/:endDate/:resourceId
   ```

2. In that route, use `axios` to call the private API using server-side `settings.apiUrl`:

   ```txt
   http://optimism_api:3001/api/calendar/...
   ```

3. Register the route in `website/app.js`.

4. Update `website/templates/select-a-time.html` so the browser calls the website-relative route:

   ```js
   axios.get('/api/calendar/...')
   ```

   instead of calling `http://localhost:3001/api/calendar/...`.

5. Update `website/routes/select-a-time.js` so it no longer passes `settings.apiUrlClientSide` to the template if it is no longer needed.

6. Remove or stop using `OPTIMISM_API_CLIENT_SIDE_URL` in Docker/config if safe.

7. Update `docker-compose.yml` so the API service is not publicly published with `ports:`. Preferred option pending confirmation:

   ```yaml
   expose:
     - "3001"
   ```

   Alternative: remove `ports:` entirely.

8. Search for remaining browser/client-side references to `localhost:3001`, `OPTIMISM_API_CLIENT_SIDE_URL`, and `apiUrlClientSide`.

9. Run tests/lint where practical.

10. Summarise changes and prepare commit/PR notes.

## Questions for user before implementation

- [x] Should the worktree branch from `origin/develop` or `origin/master`? Decision: use `origin/develop`.
- [x] Should `apiUrlClientSide` be fully removed, or left temporarily for backwards compatibility? Decision: stop using it, but do not fully remove it yet.
- [x] Should Docker Compose use `expose: ["3001"]`, or simply remove the API `ports:` block? Decision: use `expose`.
- [x] Should README/config documentation be updated to explain that the API is internal-only? Decision: yes, update README/config documentation.

## Step-by-step todo

- [x] Create separate git worktree for issue #71 from `origin/develop`.
- [x] Confirm branch/worktree state is clean except for planned new `todo.md`.
- [x] Add website calendar proxy route.
- [x] Register calendar proxy route in `website/app.js`.
- [x] Change browser calendar fetch URL to use website-relative `/api/calendar/...`.
- [x] Remove now-unneeded client-side API URL usage from the select-time route/template path.
- [x] Update Docker Compose to stop publishing the API port.
- [x] Search for remaining browser/client-side references to `localhost:3001` or `apiUrlClientSide`.
- [x] Run relevant tests/lint.
- [x] Update this file with implementation notes and final status.
- [x] Run Docker stack with UI exposed on localhost and local network.
- [x] Provide manual test steps for the proxied calendar functionality.
- [x] Summarise changes for the user. (Delivered in session report: proxy route, select-time template/route changes, docker-compose `expose`, README update, and Docker verification results.)

## Implementation notes

- Created worktree `/home/doesliverpool-0/dev/optimism-issue-71`.
- Created branch `issue-71-api-proxy` tracking `origin/develop`.
- Copied this `todo.md` into the worktree so it is part of the implementation branch.
- Added `website/routes/calendar.js` as a website-side proxy for `GET /api/calendar/:startDate/:endDate/:resourceId`.
- Registered the proxy route in `website/app.js`.
- Updated `website/templates/select-a-time.html` to call `/api/calendar/...` on the website instead of `{{apiUrl}}/calendar/...`.
- Updated `website/routes/select-a-time.js` so the template no longer receives `settings.apiUrlClientSide`.
- Changed the API service in `docker-compose.yml` from publishing `127.0.0.1:3001:3001` to internal `expose: ["3001"]`.
- Removed `OPTIMISM_API_CLIENT_SIDE_URL` build args from `docker-compose.yml`; the setting remains in code for compatibility but is no longer used by the select-time browser flow.
- Search result: remaining `apiUrlClientSide`/`OPTIMISM_API_CLIENT_SIDE_URL` references are only in `website/settings.js` and `website/Dockerfile` for compatibility, not in browser route/template usage.
- Ran `npm install` to install dependencies. It completed with Node engine warnings for older jsdoc/eslint dependencies and reported existing audit vulnerabilities; no dependency files are being committed from this.
- Ran `npx eslint website/routes/calendar.js website/routes/select-a-time.js website/app.js`; passed with no output.
- Ran targeted calendar API test: `npm run test-just-api -- api/test/integration/calendar.js`; passed, 6 tests.
- Ran `npm run test-just-api`; completed with 0 tests because this script does not recurse into integration tests.
- Tried full `npm run test-api`; it timed out after both 120s and 300s without test output. This appears unrelated to this website/proxy change and should be noted for follow-up.
- User asked to run the changes in Docker, expose the UI on localhost and the local network, and provide manual test steps.
- Created local secret files for Docker testing: `email_user`, `email_pass`, `admin_user`, `admin_pass`; these are ignored by git.
- Created temporary override file `/tmp/optimism-local-network.yml` with `website.ports: !override ["0.0.0.0:3000:3000"]` so the website is reachable on localhost and the LAN.
- Initial Docker run was blocked by permissions, but the user added `doesliverpool-0` to the `docker` group. The existing shell did not pick up the new group, so Docker commands were run via `sg docker -c '...'`.
- Docker stack built and started successfully with `docker compose -f docker-compose.yml -f /tmp/optimism-local-network.yml up -d --build`.
- Containers running: `optimism_db`, `optimism_api`, `optimism_website`.
- Website is published on `0.0.0.0:3000->3000/tcp`; API is internal-only and shown as `3001/tcp` with no host binding.
- Ran production migrations in Docker: `docker compose ... exec -T api npx knex migrate:latest --env production`; 2 migrations run.
- Ran production seed data in Docker: `docker compose ... exec -T api npx knex seed:run --env production`; 5 seed files run.
- Verified `http://localhost:3000/` returns HTTP 200.
- Verified `http://localhost:3000/select-a-resource` returns HTTP 200.
- Verified `http://localhost:3000/select-a-time?resource=1` returns HTTP 200 and rendered JavaScript calls `/api/calendar/...` with no `localhost:3001` or `{{apiUrl}}` in the page.
- Verified website proxy `http://localhost:3000/api/calendar/2026-08-05/2026-08-12/1` returns HTTP 200 with calendar JSON.
- Verified direct host access to API `http://localhost:3001/api/resources` fails to connect, as expected.
- Verified local-network URLs respond with HTTP 200 from this host: `http://10.0.31.0:3000/` and Tailscale `http://100.100.10.40:3000/`.
- Updated `README.md` to document that the Docker API service is internal-only and browser-facing requests should go through the website.

## Related follow-up (FastAPI rewrite planning)

This `todo.md` tracks issue #71 only. The planning work for the FastAPI replacement (in the main repo, on `master`) is documented in [summary.md](summary.md), [EVALUATION.md](EVALUATION.md), [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md), [PLAN_REVIEW.md](PLAN_REVIEW.md), [API_SPEC.md](API_SPEC.md), and [docs/arc42/](docs/arc42/). Reflections on this issue's steps:

- The issue-71 proxy is the **interim** security fix for the Node system and stays as-is until cutover. The rewrite removes the website↔API HTTP split entirely (decision #8, API_SPEC.md §1.1: API internal-only in the same process), so the proxy route, `apiUrlClientSide`, and the `expose: 3001` port distinction all disappear by design in the new system.
- The calendar endpoint keeps the legacy JSON shape in the new contract (API_SPEC.md §3.3/§6), so the `select-a-time` flow ports almost unchanged.
- The worktree copy of this file (`/home/doesliverpool-0/dev/optimism-issue-71/todo.md`, branch `issue-71-api-proxy`) should be kept in sync with this one if further edits are made before the PR is finalised.
