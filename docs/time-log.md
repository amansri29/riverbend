# Time log

Honest record of time spent, as the brief asks. Planning with an AI assistant counts.

| Date | Block | Hours |
|---|---|---|
| 2026-11-03 | Read brief, architecture discussion and decisions (queue, tenancy, follow-up, framework) | 1.5 |
| 2026-11-03 | Scaffold, catalog, samples, decisions file | 0.5 |
| 2026-11-03 | Schema + RLS, core modules, providers, API, worker, dispatchers, Compose | 1.5 |
| 2026-11-03 | Tests (78), cap-fix found by a test, native run through the Pub/Sub emulator, outage demo | 1.0 |
| 2026-11-03 | Terraform, Cloud Build, architecture note, not-built, GCP plan, README | 1.0 |
| 2026-11-05 | Gap check against the brief; note cut to two pages (rendered); slow-provider demo, which found the lingering `degraded` flag; README assumptions; Loom script | 1.0 |
| 2026-11-05 | Code-quality pass: docstrings on every public module, class and function; SQL moved out of the route into repositories; exception names per PEP 8; pydocstyle and naming rules enforced in ruff | 0.5 |
| 2026-11-05 | Azure provider on the v1 surface, model choice (gpt-5.6-luna), end-to-end checks, architecture diagram, timestamps in shop time | 1.0 |
| 2026-11-06 | Real 40-sample run (two passes: time-format fix, runner wait fix), date recovery from vague text, tutorial video pipeline and narration | 2.5 |

Running total: 10.5 h. Over the brief's eight by about two and a half, most of it the video and the second results pass; stated here rather than rounded down. Not done: the Compose path was written but verified only on the native stack (Docker Desktop would not start on the build machine).
