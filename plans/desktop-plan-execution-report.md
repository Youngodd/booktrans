# Execution Report: Desktop app plan

Plan: `docs/DESKTOP_PLAN.md`. Date: 2026-10-18.

## Summary
Partial. M1 (desktop mode in `web/`) is built and tested. M0, M2, M3, M4 are not done: they need a
Windows machine or runner, the shell decision that M0 produces, and a signing certificate.

## Step results
| Step | Status | Notes |
| --- | --- | --- |
| M0 spike | Not done | Needs Windows; this is macOS. |
| M1 desktop mode, cancel hook, key endpoint | Done | `booktrans/web/app.py`, `jobs.py`, `pipeline.py`, `booktrans/desktop/` |
| M1 per-provider estimate | Not done | Only the Anthropic cost per page is measured; spend guard not started. |
| M2 shell, credential store, UI screens | Not done | Depends on M0. |
| M3 CI installer and smoke test | Not done | Needs Windows runner. |
| M4 signing, update channel | Not done | Needs certificate decision. |

## Deviations
- Sidecar uses a thread executor, not a process pool (avoids frozen multiprocessing; jobs run one at a time).
- Cancel is a flag file checked in the progress callback.

## Test results
- `.venv/bin/python -m pytest -q`: 101 passed (3 runs). Baseline was 92; 9 new in `tests/test_desktop.py`.
- One earlier full run failed `test_web.py::test_provider_is_checked_and_passed_to_the_backend`; it passed alone
  and in 6 repeated runs with and without my changes. It asserts on a list the worker thread fills, so it is
  a pre-existing race. Not fixed.
- Ran `python -m booktrans.desktop`: printed the ready line; `/api/config` gave 401 without the token and 200 with it.
- Not run: a real translation against a provider, Windows, PyInstaller.

## Audit findings
- The ready line is printed just before uvicorn starts listening, so a shell must retry the first connection.
- `/` is served without the token (only `/api/*` is protected).
- No key is written to disk or returned by any endpoint (tested). Key storage in the OS credential store is M2.
- Hosted behaviour: `api_key` is now optional in the request models, so a hosted request that omits it gets 400 instead of 422.

## Definition of done
The plan defines none beyond per-milestone testability. M1: existing tests pass (met), desktop tests added (met).

## Follow-ups
Do M0 on a Windows machine; measure Qwen/DeepSeek cost; decide on a signing certificate and the open questions in the plan.
