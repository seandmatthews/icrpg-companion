# 49 — app shell polish: readable no-build page, awaited shutdown, token coercion

**Status:** proposed
**Priority:** P3
**Area:** `server/app.py` (routes, lifespan, hello_gm)
**Found by:** 2026-10-06 full adversarial review

## Problem

1. **`/` and `/join` return a bare 500 before the client build
   exists.** The `/join` route registers unconditionally and
   constructs `FileResponse(index_html)` per request
   (`app.py:163-167`); the `StaticFiles` mount is conditional on
   `CLIENT_DIST` existing *at startup only* (`app.py:169-170`).
   Running the server before `npm run build` — the documented
   first-run trap — gives the GM a blank "Internal Server Error" at
   the console URL and a 404 at `/`, with no "build the client"
   hint; building while running doesn't mount until restart.
2. **The watcher task is cancelled but never awaited.**
   `task.cancel()` with no `await`/suppress (`app.py:60-64`) produces
   "Task was destroyed but it is pending" noise on Windows Ctrl+C and
   is exactly the seam where a future shutdown-flush step (final
   snapshot, conn close notices) would silently not run.
3. **`hello_gm` stores `device_token` uncoerced** (`app.py:106`, vs
   the player path's `str(... or "")`): harmless today (verified —
   GM conns are skipped in `refresh_seats` and the token is only
   compared), a latent `TypeError` if future code formats/hashes it.

## Proposal

- When `dist/index.html` is missing: `/` and `/join` return a small
  readable page ("client not built — run npm ci && npm run build"),
  and boot logs a clear warning; keep the mount-conditional but also
  note that a rebuild needs a restart (or re-check per request —
  cheap either way).
- `task.cancel(); with contextlib.suppress(asyncio.CancelledError):
  await task`.
- `conn.device_token = str(msg.get("device_token") or "")`.

## Acceptance criteria

- [ ] `tests/test_ws_flow.py::test_index_without_build_is_readable` —
      boot with `CLIENT_DIST` monkeypatched to an empty dir; `GET /`
      and `GET /join` return 200 with the build-hint text (not 500);
      `/api/bootstrap` and `/ws` still work.
- [ ] `tests/test_ws_flow.py::test_shutdown_has_no_destroyed_task_noise`
      — run a full boot/act/shutdown cycle capturing stderr; assert no
      "Task was destroyed" / "pending task" lines (uvicorn shutdown
      already happens in the fixture — this just pins the await).
- [ ] `tests/test_ws_flow.py::test_gm_hello_with_junk_token` —
      `hello_gm {gm_key: <valid>, device_token: {"x": 1}}` → hello
      succeeds with a string token stored (no latent TypeError on the
      first future consumer; today this only pins the coercion).
