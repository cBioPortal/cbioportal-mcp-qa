# cBioPortalChat benchmark

Benchmarks the deployed cBioPortalChat agent by asking it every question in
[`input/questions.yaml`](input/questions.yaml) through LibreChat's Agents API, then grading the answers.
Because it calls the real deployment, a run measures what users get: the same system prompt, MCP tools
(cbioportal-database, cbioportal-navigator), prompt caching and model.

**[Results](https://cbioportal.github.io/cbioportal-mcp-qa/results/)** — one HTML report per run, published with GitHub Pages.
**[Test sets](https://cbioportal.github.io/cbioportal-mcp-qa/results/test-sets.html)** — what each questions file covers, with every question, its reference and rubric.

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

## Cheap runs with Claude Code (`--runner claude-code`)

For iterating on prompts, guides and views, `--runner claude-code` answers each question with headless
Claude Code (`claude -p`) instead of the deployed agent:

- **System prompt:** the deployed agent's instructions, read from the cBioAgent MongoDB via `kubectl` at the
  start of the run (`--target beta` → the beta agent). Only its hash is stored in `run.json`.
- **Tools:** only the two MCP servers (the database MCP and the navigator); Claude Code's built-in
  tools are disabled and extended thinking is off, matching the deployment.
- **Models:** the same Haiku 4.5 / Sonnet 5.
- **Cost:** runs on the Claude subscription of the Claude home it's started with, so point
  `CLAUDE_CONFIG_DIR` at the Claude home you want billed (default `~/.claude`). Only the judge bills Bedrock.
  If the subscription's usage limit is hit (or the connector's login expires), the run stops asking, skips
  grading, and prints the `--resume` command to continue once the limit resets.

With a port-forward, dropped connections show up as tool errors such as `ECONNRESET` that the deployed agent
wouldn't have hit — prefer the connector. The prompt the run tested is saved as `results/<run>/agent-prompt.md`
(a record; runs always read the live agent) and named in the report header with the agent, its hash and when
the agent was last updated. Each answer's transcript (tool calls with their SQL
and results, then the answer) is saved under `results/<run>/transcripts/` and linked from the report, in
place of the Langfuse trace link. Costs in claude-code reports are list-price equivalents; nothing is billed
per token.

Scores are close to, not identical with, the deployed agent (different harness: no LibreChat recursion limit
or eager tool execution). Compare claude-code runs with each other; confirm on beta with the Agents API
runner before changing prod. Reports and the results index label the runner.

The MCP servers are the deployed ones, with nothing to configure in the usual case:

- **Navigator:** its public endpoint `https://mcp.cbioportal.org/navigator/mcp` (no login needed).
- **Database:** its public endpoint `https://mcp.cbioportal.org/db/mcp` needs an OAuth login, so the runner
  uses your claude.ai connector for it — found by that URL in `claude mcp list`, whatever you named it — and
  hides every other claude.ai connector from the model. Add the connector in claude.ai once.

```bash
uv run cbioportal-mcp-qa run --runner claude-code --questions 1-20
uv run cbioportal-mcp-qa ask "what is the median age in os target gdc" --runner claude-code
```

Optional: `DATABASE_MCP_URL` points the runner at a database MCP by URL instead — e.g. a locally built,
unmerged cbioportal-mcp branch (below) or a `kubectl port-forward svc/cbioagent-clickhouse-mcp 18080:80`
(`http://localhost:18080/db/mcp`) if you don't have the connector. `CLAUDE_AI_DATABASE_CONNECTOR` names a
connector explicitly.

With a port-forward, dropped connections show up as tool errors such as `ECONNRESET` that the deployed agent
wouldn't have hit — prefer the connector. The prompt the run tested is saved as `results/<run>/agent-prompt.md`
(a record; runs always read the live agent) and named in the report header with the agent, its hash and when
the agent was last updated. Each answer's transcript (tool calls with their SQL
and results, then the answer) is saved under `results/<run>/transcripts/` and linked from the report, in
place of the Langfuse trace link. Costs in claude-code reports are list-price equivalents; nothing is billed
per token.

Scores are close to, not identical with, the deployed agent (different harness: no LibreChat recursion limit
or eager tool execution). Compare claude-code runs with each other; confirm on beta with the Agents API
runner before changing prod. Reports and the results index label the runner.

The MCP servers are the deployed ones:

- **Navigator:** the public endpoint `https://mcp.cbioportal.org/navigator/mcp` (default `NAVIGATOR_MCP_URL`).
- **Database:** its public endpoint needs an OAuth login, so either set `CLAUDE_AI_DATABASE_CONNECTOR` to the
  name of a claude.ai connector for it (as listed by `claude mcp list`, e.g. `claude.ai cBioPortal MCP`) —
  the runner then hides every other claude.ai connector from the model — or port-forward the in-cluster
  service and use `DATABASE_MCP_URL`. The connector avoids port-forward drops; both reach the same image and
  active database.

```bash
export CLAUDE_AI_DATABASE_CONNECTOR="claude.ai cBioPortal MCP"
uv run cbioportal-mcp-qa run --runner claude-code --questions 1-20
uv run cbioportal-mcp-qa ask "what is the median age in os target gdc" --runner claude-code

# or, without a connector:
kubectl port-forward svc/cbioagent-clickhouse-mcp 18080:80 &   # DATABASE_MCP_URL=http://localhost:18080/db/mcp
```

To test an unmerged cbioportal-mcp branch, run its image locally instead and point `DATABASE_MCP_URL` at it:
`docker run --rm -p 18080:8000 --env-file <clickhouse.env> -e CLICKHOUSE_MCP_SERVER_TRANSPORT=http
-e CLICKHOUSE_MCP_BIND_HOST=0.0.0.0 -e CLICKHOUSE_MCP_BIND_PORT=8000 <image>` (URL `http://localhost:18080/mcp`).

Every run also records versions (both runners): cBioPortal portal / DB schema / gene table versions from
`https://www.cbioportal.org/api/info`, and the cbioportal-mcp and navigator server versions and image digests.

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

Where things go:

- **`expected_answer`**: what a correct answer says — the facts, numbers or conclusion. A single bare number
  (e.g. `548`) is also checked automatically against the answer.
- **`notes`**: how to grade — `A correct answer must: …` / `Must not: …`. Facts the judge needs but the answer
  doesn't have to state (e.g. survival statistics the agent can't compute) go here too, labelled as context.
- **`expected_links`**: links that open the right view. Don't pin session-based group comparison links
  (`comparisonId=…`); they differ on every run.

Questions from user-feedback issues set `source` to the issue URL and usually carry a rubric in `notes`.
Add `technical: true` when the question asks for code, the schema, or how the agent works: answers are then
expected to be technical and are exempt from the "exposes internals" check.

### Multi-turn follow-ups

`input/questions-multiturn.yaml` is a separate set of follow-up questions modeled on real conversations in
Langfuse (paraphrased; `trace_id` names the conversation it's based on). Its pass rates are kept apart from
the main 146 questions so those stay comparable across runs:

```bash
uv run cbioportal-mcp-qa run --questions-file input/questions-multiturn.yaml
```

A question with `history` is the user's next message in that conversation; the earlier turns alternate
`user` / `assistant` and end with an assistant turn:

```yaml
- id: 1003
  question: And in lung squamous?
  history:
  - role: user
    content: What are the most common KRAS mutations in TCGA lung adenocarcinoma?
  - role: assistant
    content: In Lung Adenocarcinoma (TCGA, PanCancer Atlas), 168 of 566 profiled samples (29.7%) ...
```

The Agents API runner sends the history as prior messages. `claude -p` takes a single message, so the
claude-code runner quotes the history ahead of the new message. The judge sees the whole conversation.
Assistant turns are written by hand, not generated, and must be correct: the follow-up is graded, not them.

## Development

```bash
uv run pytest
uv run ruff check src tests && uv run ruff format src tests
```

The benchmark tests the agent as deployed: its system prompt lives in the agent's instructions in the
cBioAgent MongoDB and the LibreChat config, not in this repo.
