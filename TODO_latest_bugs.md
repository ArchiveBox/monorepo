# TODO Latest Bugs

Date: 2026-06-02
Context: correctness/perf smoke against `archivebox/data` using `archivebox v0.9.34rc35/rc36`, real SQLite data dir, supervised server/runner/sonic, real URLs, API token auth, and screenshot helper.

## Confirmed Major Bugs

1. `archivebox search` is unusable on the large real data dir.
   - `timeout 45 ../../.venv/bin/archivebox search --json example` produced no output and timed out after 45s.
   - `timeout 45 ../../.venv/bin/archivebox list --search content --limit 5 example` also produced no output and timed out after 45s.
   - This reproduced while sonic was running under the normal supervised stack, so this is not just "sonic was not started".
   - Earlier `archivebox search example` also produced no output after more than 100s.

3. Short-lived CLI `add --index-only` takes over the live server stack.
   - While `archivebox server 127.0.0.1:9292` was running, `archivebox add --depth=0 --index-only --tag smoke-real-url https://example.com/?archivebox-smoke-20260601195219` became the newer ArchiveBox process and took over `orchestrator, server, sonic`.
   - The foreground server stopped supervisord, then recreated daphne/sonic/runner after the CLI process exited.
   - it's supposed to take over the orchestrator and sonic, but not the server

4. API pagination on large tables spends seconds doing total counts for tiny pages.
   - Authenticated `/api/v1/core/archiveresults?limit=1` repeatedly took about 2.3-3.1s to return 1 row.
   - `/api/v1/core/archiveresults?limit=3` repeatedly took about 2.4-2.6s.
   - The response includes `count: 6371957`, so the slow piece is likely global counting over 6.37M rows.
   - By comparison `/api/v1/core/snapshots?limit=1` was about 0.42s and `/api/v1/core/tags?limit=3` was about 0.02s.

5. `bin/fuzz_test.sh` cannot run from a source checkout despite setting `DATA_DIR`.
   - The harness `cd`s to the repo root and runs `DATA_DIR=... archivebox ...`.
   - Both fuzz jobs failed immediately with `[!] Cannot run from source dir, cd to a data folder first`.
   - Directly running `../../.venv/bin/archivebox version` from `archivebox/data` succeeds, so this is harness path behavior, not a basic CLI failure.

6. `/api/v1/crawls/crawls` times out even with tiny pagination.
   - Authenticated `GET /api/v1/crawls/crawls?limit=1`, `?limit=2`, and `?offset=0&limit=1` each timed out after 30s with 0 bytes received.
   - Fetching a single known Crawl by ID worked in about 0.1s, so this is specific to the collection endpoint.

10. ArchiveBox self-archive protection is not enforced by `archivebox add --index-only`.
    - These commands all exited 0 and created queued Crawls:
      - `archivebox add --depth=0 --index-only http://archivebox.localhost:9292/admin/`
      - `archivebox add --depth=0 --index-only http://web.archivebox.localhost:9292/`
      - `archivebox add --depth=0 --index-only http://api.archivebox.localhost:9292/api/v1/docs`
      - `archivebox add --depth=0 --index-only http://snap-2fb8e923c58c.archivebox.localhost:9292/index.html`
    - SQLite confirmed 4 queued self-archive Crawls from this run.
    - The DB also already had 2 older sealed self-archive Crawls, so this is not just a newly introduced test artifact.

12. `archivebox list --limit=0` is unsafe on the large data dir.
    - It ran for 30s, hit `django.db.utils.OperationalError: too many SQL variables`, then the timeout killed it with exit 124.
    - The traceback shows prefetching related rows for too many Snapshots.


16. `archivebox search --status unarchived` returns archived/sealed snapshots.
    - `archivebox search --json --status unarchived example` returned many Snapshots with `status: "sealed"` and `is_archived: true`.
    - `--status indexed` and `--status archived` timed out after 30s in the same run.

17. Normal API/runner activity can hit SQLite lock retries.
    - During the API CLI search/update tests, `worker_daphne.log` showed repeated `SQLite database is locked ... retrying in 5s` messages.
    - The logged query was `UPDATE core_snapshot`, with DB holders listed as daphne and `archivebox run --daemon`.
    - This matches the user-facing concern that short SQLite writes should not be producing lock stalls in normal server+runner operation.

18. Supervised shutdown/reload can leave supervisor in error states.
    - The wrapped fuzz run started `archivebox server --reload --debug 127.0.0.1:8755` and interrupted `archivebox update`.
    - `supervisord.log` shows `PermissionError: [Errno 1] Operation not permitted` while killing `worker_runner` / `worker_supervisord_parent_watchdog`.
    - It also shows `AssertionError: ... UNKNOWN not in RUNNING`.
    - No ArchiveBox processes were left running after the fuzz run, but the supervisor shutdown path is not clean.

19. Debug reload server starts/stops worker_runner repeatedly.
    - The fuzz server log shows `worker_runner` initially configured stopped, then started as pid 73476, stopped by SIGTERM, and started again as pid 73514 within seconds.
    - This happened during normal `server --reload --debug` startup before the fuzz harness stopped it.
    - It increases takeover/reload churn and may interact with the supervisor shutdown errors above.

## Drift / Cleanup Notes

1. `archivebox config` still shows legacy runtime path values like `SNAP_DIR = ""` and `CRAWL_DIR = ""`.
   - This may be acceptable if they are ignored by runtime scoping, but it is still visible in user-facing config output.

2. Public list previews mostly render blank placeholder boxes even for sealed snapshots with output files.
   - Screenshot: `archivebox/tmp/screens/public-web-9292.png`.
   - Not yet confirmed whether this is expected lazy loading, missing thumbnails, or a UI/data mismatch.

3. `archivebox status` took about 24s on the real 1M snapshot / 14GB index data dir.
   - This may be acceptable for a full status scan, but it is worth tracking separately from hot-path snapshot execution.

4. `/api/docs` and `/api/schema` fall through to snapshot-style 404 pages; canonical docs are at `/api/v1/docs` and schema is at `/api/v1/openapi.json`.
   - This is probably route polish, not a runtime blocker.

5. `HEAD /api/v1/core/snapshots` returns 405 even though GET is allowed.
   - Low priority, but it is surprising for a GET endpoint.

## Perf Note

The event bus itself is not the cause of the ArchiveResult latency. Existing measurements showed abxbus around 0.2ms/event, while the remaining heavy block was dominated by ArchiveResult persistence and Django/DB work.
