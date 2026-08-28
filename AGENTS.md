# Repository instructions

Read `HANDOFF.md` before changing code. For files under `app/`, also read `app/CLAUDE.md`.

## Non-negotiable boundaries

- Never add automatic message sending, application submission, or automatic retry of an
  uncertain external action. The candidate performs those actions manually.
- Never add high-frequency scraping, concurrency for outreach, anti-detection escalation, or
  CAPTCHA bypasses.
- Never commit `.env`, browser profiles, local databases, vector stores, logs, resumes, tokens,
  or candidate-private evidence.
- Do not rewrite golden labels merely to make evals pass. Explain expected behavior changes.
- Do not add AI tools to commit `Co-Authored-By` trailers. Use Pacifica's configured authorship.

## Required verification

- App changes: `cd app && uv run pytest -q`.
- Campaign/filter changes: `cd evals && python3 run_evals.py` and
  `python3 run_evals.py --regression`.
- Prompt/parser changes: add the matching Campaign L2 case and run paid L2 only when authorized.
- Migration changes: test on a database copy. Do not initialize or migrate `app/data/reachout.db`
  as a side effect of a read-only command.

Production match-scoring prompts and parsers live in
`app/src/boss_zhipin/models/match_scoring.py`; evals import that implementation directly.
