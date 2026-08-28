# Job Search Agent · Reachout v2

A local-first, human-in-the-loop job-search pipeline for one candidate:

> discover jobs → evaluate within a search Campaign → prepare the right next action →
> let the candidate review and submit manually → track outcomes and learn from feedback.

This repository is the canonical home of the project. It combines the original orchestration
specs with the working BOSS/LinkedIn application, a versioned SQLite domain model, and a
regression eval suite.

## Current shape

The system does **not** force different job markets into one recall policy. It shares the job and
application lifecycle while keeping each search direction bounded:

| Campaign | Discovery | Evaluation policy | Prepared outcome |
|---|---|---|---|
| `cn-2027-ai-product` | BOSS Zhipin | China campus rules + `cn-match-v2` | Candidate opens the job and uses the fixed greeting configured in BOSS |
| `global-2027-ai-product` | LinkedIn; company career sites next | New Grad, seniority and Sponsorship rules + `global-match-v1` | Tailored resume and English outreach for manual submission |

`jobs` stores the canonical job. `job_campaign_matches` stores why that job belongs to a
Campaign, which policy evaluated it, and its Campaign-local assessment. Scores from different
Campaigns are never treated as directly comparable.

## Safety boundary

- Sending messages and submitting applications are always human actions.
- The Agent tool registry structurally rejects tools with external side effects.
- A generated claim must be traceable to the candidate's approved evidence archive.
- Unknown send/submit state is never retried automatically.
- No anti-detection escalation, high-frequency scraping, or unattended mass outreach.

## Repository map

```text
.
├── app/                    # Working local-first Python/Tauri application
├── evals/                  # Independent L0-L3 regression harness and golden sets
├── docs/                   # Architecture, technical plan, and Agent evolution roadmap
├── skills/                 # Evidence capture, resume tailoring, and apply workflow specs
├── integrations/           # Candidate source adapters not yet wired into the main app
├── legacy/v1-prompts/      # Original prompt-only orchestration, retained as history
├── HANDOFF.md              # Current operational state and next work
└── AGENTS.md               # Rules for code assistants working in this repository
```

The `app/` and `evals/` histories were imported with Git subtree without squashing, so their
development history remains inspectable. The original v1 overview is preserved at
[`legacy/v1-overview.md`](legacy/v1-overview.md).

The active GitHub Actions workflow is `.github/workflows/ci.yml` at the repository root. The
workflow retained under `app/.github/` belongs to the imported upstream app history and is not
loaded by GitHub from this monorepo layout.

## Verification

```bash
cd app
uv run pytest -q                    # 315 passed

cd ../evals
python3 run_evals.py                # L0 4/4 + L1 20/20 = 24/24 offline
python3 run_evals.py --regression   # compare real-DB distributions; never overwrites baseline

# Paid L2: uses the production prompt builder and parser from app/
set -a && . ../app/.env && set +a
../app/.venv/bin/python run_evals.py --l2
```

Current L2 baseline on `claude-sonnet-4-6`: China Campaign 7/7 and Global Campaign 4/4.
Use `--case G02` to rerun only a failed case when the endpoint returns a transient network error.

## Working locally

```bash
cd app
uv sync
uv run boss-zhipin-daily --per-route 5 --limit 60
uv run linkedin-job-daily --per-route 3 --limit 30
uv run reachout-plan
```

The daily commands capture and classify jobs; they never send messages or submit applications.
Read [`HANDOFF.md`](HANDOFF.md) before changing code, especially before touching migrations or a
real browser profile.

## Evaluation discipline

Every product-layer change has a matching eval obligation:

| Change | Required eval update |
|---|---|
| Source platform or Campaign routing | L0 Campaign contract |
| Deterministic recall/filter rule | L1 golden + real-DB regression explanation |
| Match prompt, parser, or hard gate | Campaign-specific L2 case |
| Resume/outreach generation | L3 case and factuality rubric before implementation |
| Application states or feedback semantics | E2E metric definition and history compatibility |

Golden labels are expected behavior, not output fixtures. They are not changed merely to make a
regression green. Production match prompts live only in `app/src/boss_zhipin/models/match_scoring.py`;
the eval harness imports them directly.

## Roadmap

The next milestone is a Campaign-aware review desk:

1. backfill existing jobs into explicit Campaigns on a database copy;
2. filter and sort review queues within each Campaign;
3. change the BOSS action from per-job draft approval to “worth contacting / skip / open job”;
4. connect the overseas evidence archive and tailored-material workflow;
5. upgrade the deterministic daily planner to Campaign-aware state before evaluating an LLM planner.

The architecture rationale and acceptance criteria live in
[`docs/goal-一条龙系统蓝图.md`](docs/goal-一条龙系统蓝图.md).

## Upstream and attribution

The BOSS browser foundation descends from
[`longsizhuo/BossZhiPin_Job_Search`](https://github.com/longsizhuo/BossZhiPin_Job_Search)
and retains its original license and history under `app/`. Reachout's Campaign model, review
workflow, application tracking, Agent tools, and eval system are maintained here as the personal
job-search system.
