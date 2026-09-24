# cBioPortalChat benchmark

Benchmarks the deployed cBioPortalChat agent by asking it every question in
[`input/questions.yaml`](input/questions.yaml) through LibreChat's Agents API, then grading the answers.
Because it calls the real deployment, a run measures what users get: the same system prompt, MCP tools
(cbioportal-database, cbioportal-navigator), prompt caching and model.

**[Results](https://cbioportal.github.io/cbioportal-mcp-qa/results/)** — one HTML report per run, published with GitHub Pages.

## What a run records

For every question × model (× repeat):

- **Answer** from `POST /api/agents/v1/chat/completions`, with latency and token usage
  (input, cache read, cache write, output) → estimated cost at Anthropic list prices.
- **Execution trace** from Langfuse, matched by response id: number of LLM calls, every tool call, and
  tool errors (e.g. navigator schema errors).
- **Grade**, pass/fail: an LLM judge (default Sonnet 4.6 on Bedrock, deliberately not one of the models under
  test) checks the answer against the reference answer, expected links and the `notes` rubric, using the
  criterion for the question's track (below). It also records whether the answer *declined*, so the report
  can separate precision (right when it answers) from coverage (how often it answers).
- **Objective checks**: when the reference is a single number, whether the answer contains it (exact for
  counts, within rounding for decimals/percentages) — shown where it disagrees with the judge; and whether
  every study id in the answer's cBioPortal links exists (a hallucination signal).

Every question has a **track**, and the report shows pass rates per track and model:

| Track | Passes when |
|---|---|
| `data` | it states the fact in the reference (a count, frequency, list) |
| `navigation` | it gives a cBioPortal link to the right view: page, study, genes, filters |
| `analysis` | it uses the right cohort and method and doesn't invent statistics |
| `out_of_scope` | it clearly declines instead of making something up |

Questions without any reference are still asked and reported, but not graded.

## Setup

```bash
uv sync
cp .env.example .env   # then fill it in
```

- `LIBRECHAT_API_KEY`: create under **Settings → Agent API Keys** on beta.chat.cbioportal.org. Beta and prod
  share a database, so the key works on both. Runs are billed to that account's token balance.
- `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`: for tool-call stats (optional; runs work without).
- AWS credentials for the judge: `AWS_PROFILE` with Bedrock access (e.g. `cdsi-imagine-490004633549`).

Choosing the model per request requires cbioportal/librechat `v0.8.7-custom-v3` or later on the target, where
the Agents API accepts a `spec` (modelSpec name) alongside the agent id.

## Usage

```bash
# One question, to check the setup
uv run cbioportal-mcp-qa ask "How many studies are in cBioPortal?" --model haiku

# Full benchmark, Haiku vs Sonnet on beta
uv run cbioportal-mcp-qa run --models haiku,sonnet

# A subset, three repeats each to measure consistency
uv run cbioportal-mcp-qa run --questions 1-10 --repeats 3

# Continue an interrupted run (re-asks only missing or failed answers)
uv run cbioportal-mcp-qa run --resume 20260923-1800

# Re-attach traces (Langfuse ingestion can lag), regrade, or re-render
uv run cbioportal-mcp-qa traces 20260923-1800
uv run cbioportal-mcp-qa grade 20260923-1800 --regrade

# After fixing references in input/questions.yaml, regrade an existing run against them
uv run cbioportal-mcp-qa grade 20260923-1800 --refresh-questions
uv run cbioportal-mcp-qa report 20260923-1800
```

Output goes to `results/<run-id>/`: `run.json` (every answer, trace and grade), `report.html`, and
`summary.json`, plus `results/index.html` listing all runs. Commit the run directory to publish it.

Keep `--concurrency` low (default 2, at most ~3): the beta pod is small and shared with real users. A full run
(146 questions × Haiku + Sonnet) takes about 1.5 hours and ~35M LibreChat credits (~$35 at list prices).

## Adding questions

Append to `input/questions.yaml` with the next unused `id` (ids are stable; never renumber or reuse):

```yaml
- id: 147
  track: data
  type: Clinical Data
  study: msk_chord_2024
  question: How many patients in MSK-CHORD received immunotherapy?
  expected_answer: "4,721"          # or leave "" and give links / a rubric
  expected_links: []
  notes: |
    A correct answer must use the treatment table; must not count planned treatments.
  checked: 2026-09-23               # when the reference was last verified
  source: https://github.com/cBioPortal/cbioportal-mcp/issues/24
```

Questions from user-feedback issues set `source` to the issue URL and usually carry a rubric in `notes`.

## Development

```bash
uv run pytest
uv run ruff check src tests && uv run ruff format src tests
```

The benchmark tests the agent as deployed: its system prompt lives in the agent's instructions in the
cBioAgent MongoDB and the LibreChat config, not in this repo.
