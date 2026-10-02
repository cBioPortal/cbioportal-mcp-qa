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
  test; or through the local Claude Code subscription with `--judge-runner claude-code`) checks the answer against the reference answer, expected links and the `notes` rubric, using the
  criterion for the question's track (below). It also records whether the answer *declined*, so the report
  can separate precision (right when it answers) from coverage (how often it answers). The judge also sees the
  answer's tool calls (inputs and truncated results; guide text left out), so statistics the agent actually
  computed aren't marked as invented. Older claude-code runs are graded from their transcripts.
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

### Secrets in published results

`results/` is published with GitHub Pages, so everything the benchmark writes there goes through one
redaction boundary (`persist.py`). run.json, summary.json, the HTML and Markdown reports, compare outputs,
transcripts and the recorded agent prompt are deep-scrubbed on the way out:

- **Known values first**: every secret the benchmark loads or can see is masked wherever it appears, also
  URL-encoded, JSON-escaped, backslash-escaped or HTML-escaped. That covers the LibreChat and Langfuse keys, the
  cBioAgent Mongo password read from its k8s secret, and every environment variable whose name contains PASS,
  PWD, SECRET, TOKEN, KEY, AUTH or CREDENTIAL. It also covers the password of any URI in the environment, both
  as written and percent-decoded. Values under 6 characters are ignored.
- **Structure**: the value of any key named like a credential (`password`, `*_token`, `apiKey`,
  `Authorization`, `Cookie`, ...) is masked whole, and a list of strings is also read as a command line.
- **Patterns** for anything else: URI userinfo, bearer tokens, key=value secrets, password flags of database
  clients and `--password`-style flags. They mask to the end of the line, or of the text when the quoting after
  them can't be trusted.
- Failed commands are recorded as `<executable> exited with status N` and the redacted tail of their output,
  never with their arguments.

**Screenshots are not redacted**: they are pixels. The `shots/` of a run only hold the public cBioPortal pages
that navigation answers linked to. Pass `--no-screenshots` to `run` or `render` to keep the page text without
them.

## Setup

```bash
uv sync
cp .env.example .env   # then fill it in
```

- `LIBRECHAT_API_KEY`: create under **Settings → Agent API Keys** on beta.chat.cbioportal.org. Beta and prod
  share a database, so the key works on both. Runs are billed to that account's token balance.
- `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`: for tool-call stats (optional; runs work without).
- AWS credentials for the judge: `AWS_PROFILE` with Bedrock access (e.g. `cdsi-imagine-490004633549`). Not
  needed with `--judge-runner claude-code` ([below](#grading-with-claude-code---judge-runner-claude-code)).

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

# Continue an interrupted run (re-asks only missing or failed answers). It keeps the run's --questions,
# --questions-file, --no-grade, judge, concurrency, rendering and --wait-on-limit unless you give them again;
# the --claude-code-* opt-ins must be given again.
uv run cbioportal-mcp-qa run --resume 20260923-1800

# Re-attach traces (Langfuse ingestion can lag), regrade, or re-render
uv run cbioportal-mcp-qa traces 20260923-1800
uv run cbioportal-mcp-qa grade 20260923-1800 --regrade

# After fixing references in input/questions.yaml, regrade an existing run against them (only the expected
# answer, links, notes and track are refreshed; the judge still sees the question text and history that were asked)
uv run cbioportal-mcp-qa grade 20260923-1800 --refresh-questions
uv run cbioportal-mcp-qa report 20260923-1800
```

### Targets

| `--target` | Agent | `--models` | Request |
|---|---|---|---|
| `beta` | unified beta agent `agent_OHVSJI9Gd6gwsDnFSL-Xl` | `haiku`, `sonnet` | with the `cBioPortalChatBeta` / `cBioPortalChatBetaSonnet` spec |
| `beta-router` | handoff router `agent_cbiobeta_router` | `router` | no spec: the router and its specialists run their own models |
| `beta-unified` | unified beta agent | `unified` | no spec: the agent's own model |
| `prod` | prod agent `agent_9ZXhcwLIsROBQX0u4JS5F` | `haiku`, `sonnet` | with the prod specs |

Once beta's `cBioPortalChatBeta` spec points at the router, `--target beta` returns 400 (the spec no longer
selects a model for the unified agent) and `beta-unified` is the single-agent baseline. `router` and `unified`
stand for whatever models the agents call, so their answers are priced per LLM call from the Langfuse trace.
Each trace records every LLM call (model, agent, start/end, tokens, cost), the handoffs (`lc_transfer_to_*`),
the agent that answered (`routed_to`), and tool rounds; `summary.json` has the routing distribution, p90
latency, LLM calls and tool rounds per answer. `run.json` records the target agent and every agent it hands
off to (prompt hash, model, last update) and the LibreChat and MCP image tags, where kubectl can read them.

### Comparing runs

```bash
# B against baseline A, per question and per category, repeats pooled (A's model must be named if it ran several)
uv run cbioportal-mcp-qa compare 20260923-1919 20260927-1200 --model-a haiku
```

Writes `results/compare/<A>-<model>_vs_<B>-<model>/compare.{html,md,json}` and prints the markdown: the
headline metrics below, the same by category and track (with precision, recall, p90, share under 10s and LLM
calls per answer), and every question with its outcome per repeat, pass variance and latency spread,
regressions first. Only questions both runs asked are compared. Runs recorded before per-call traces show
"–" for tool rounds, handoffs and routing.

**Comparable runs only.** `compare` refuses, and says why, when the runs used a different judge model (or
either run mixes judge models) or questions file, or when a question's text, conversation history, track,
`expected_answer`, `expected_links` or `notes` differ between the runs (or between one run's repeats) — their
pass/fail would measure different things. Each grade records the judge model that made it and a snapshot of
the question it was graded against, and `compare` checks those; grades from before per-answer judges fall back
to the run's `judge_model`. Regrade the older run against the current references (`grade <run>
--refresh-questions`) and compare again, or pass `--allow-mismatch` to compare anyway: the affected questions
are then marked ⚠ and a warning is printed.

`--refresh-questions` never changes the question text or history, since the answer was to what was asked. So
even after regrading 20260923-1919, the 9 questions reworded since then still differ from runs that asked the
new wording and can only be compared with `--allow-mismatch`. For a clean beta comparison, record a fresh
3-repeat baseline (`run --target beta-unified --repeats 3`) on the current questions file rather than relying on
the regraded 09-23 run.

**Every turn is counted.** A turn is one question × repeat. Each side reports its *expected* turns (questions ×
the run's `repeats`), *completed* (HTTP 200), *failed* (an HTTP error or timeout), *missing* (never recorded,
e.g. an interrupted run), *ungraded* (completed, has a reference, no grade yet) and *no reference* turns, in
the headline, per category and per question; an incomplete side gets a warning. *Eligible* turns are the
graded, failed and missing turns of questions with a reference: a failed or missing turn counts as not passed.
Ungraded turns are left out until graded.

| Metric | Definition |
|---|---|
| **Recall** | passes / eligible turns — the headline score; failed and missing turns count against it |
| **Precision** | passes / attempted answers (pass + fail; declines are not attempts) |
| **Attempt rate** | attempted answers / eligible turns (declines, failures and missing turns are not attempts); recall = precision × attempt rate |
| Pass rate | passes / graded answers — the per-run report's definition, which leaves failed turns out; shown for continuity |
| Latency | median and p90 over completed turns, and again over completed + failed turns with each failure at its elapsed time |
| Under 10s | completed turns under 10s, over completed turns and over completed + failed turns (a failure is never fast) |

The per-run report's **coverage** is different from the attempt rate: it is the share of *graded answers* that
weren't declines, so failed requests don't lower it. **p90** everywhere (reports, `summary.json`, compare) is
the upper nearest-rank value, `sorted(values)[⌊0.9·n⌋]` (clamped to the last value): with 10 or fewer values
it is the maximum, so small samples err high.

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
  `CLAUDE_CONFIG_DIR` at the Claude home you want billed (default `~/.claude`). Only the judge bills Bedrock,
  and with `--judge-runner claude-code` it doesn't either.
  If the subscription's usage limit is hit (`You've hit your limit`, `hit your session / weekly limit`,
  `usage limit reached`), or the connector's login expires, the run stops asking, skips
  grading, and prints the `--resume` command to continue once the limit resets.

### Stopping on the usage limit, and `--wait-on-limit`

A stop (the usage limit, per-token billing, a plugin, an expired connector login) ends the batch at once:

- answers already in flight finish and are saved as usual (an ordinary failure among them too);
- no queued answer starts a `claude` session, and none gets a record in `run.json`;
- a reply that is itself a stop isn't recorded either, judged by its own content: the limit reply
  (`You've hit your session limit`), and a reply in flight that hit a different stop (say a plugin) after it.
  The first stop is the reason given; any others are listed after it.

So `run.json` has no junk failures, and `run --resume <run>` asks exactly the answers that are missing or failed.
The printed command keeps every option the run was started with that isn't a default (`--questions`,
`--no-grade`, `--questions-file`, judge options, `--concurrency`, `--wait-on-limit`, the `--claude-code-*`
opt-ins, …). `--resume` also restores the run's own options from `run.json` (`options`), except the
`--claude-code-*` and `--judge-allow-managed-customizations` opt-ins: those guards must be given again.

`run.json` records the questions the run means to ask (`planned_questions`, added to when a resume selects
more). Every resume asks the planned answers that are still missing as well as its own selection, so a narrower
`--questions` on one resume never strands them, and a run never ends successfully with planned answers missing.
The report counts a planned turn with no record as a failed request ("not asked"), and `compare` counts it as
missing, so a stopped run shows as incomplete exactly as it would with failure records. `compare` checks each
run against its own plan, so it warns about an incomplete run even when the missing questions are ones the
other run didn't ask (and so aren't scored). Runs from before `planned_questions` are reported from their
records, as before.

Grading works the same way (see
[Grading with Claude Code](#grading-with-claude-code---judge-runner-claude-code)): in-flight grades are saved,
nothing ungraded gets a `judge_error` from a limit, and no judge call starts once a stop is recorded (the stop
check and the launch are one locked step).

`run` and `grade` take `--wait-on-limit` to wait the usage limit out in the same process instead of stopping:

```bash
uv run cbioportal-mcp-qa run --runner claude-code --wait-on-limit --max-wait 300
uv run cbioportal-mcp-qa grade 20261002-0306 --judge-runner claude-code --wait-on-limit
```

- **When.** The reset time is read from the message: `resets 9:50pm (Pacific/Honolulu)`, `resets 3:40am (UTC)`,
  `resets 3pm` (no zone: the machine's local time). It is the next such time (tomorrow's if today's has
  passed), plus a minute. The wait is elapsed time, so it is right across a DST change; a time that happens
  twice (the fall-back hour) is taken as the later one. A message with no time of day (`resets Oct 3`, `resets Mon`), an unknown zone, or a
  time that passed less than an hour ago (the limit is about to clear) waits a fixed 15 minutes instead.
- **How long.** `--max-wait` (minutes, default 360) caps the waiting in all, across answering and grading; a
  wait that would go past it stops as without the flag, with the `--resume` command.
- It prints what it waits for and until when (`waiting 51 min, until 2026-10-01 21:51 HST`); Ctrl-C stops it,
  and `--resume` continues later. Only the usage limit is waited out: the other stops need you.

```bash
uv run cbioportal-mcp-qa run --runner claude-code --questions 1-20
uv run cbioportal-mcp-qa ask "what is the median age in os target gdc" --runner claude-code
```

The prompt the run tested is saved as `results/<run>/agent-prompt.md` (a record; runs always read the live
agent) and named in the report header with the agent, its hash and when the agent was last updated. Each
answer's transcript (tool calls with their SQL and results, then the answer) is saved under
`results/<run>/transcripts/` and linked from the report, in place of the Langfuse trace link. Costs in
claude-code reports are list-price equivalents; nothing is billed per token.

Scores are close to, not identical with, the deployed agent (different harness: no LibreChat recursion limit
or eager tool execution). Compare claude-code runs with each other; confirm on beta with the Agents API
runner before changing prod. Reports and the results index label the runner.

### Billing guard

In `claude -p`, anything below takes precedence over the subscription login, in this order
([authentication docs](https://code.claude.com/docs/en/authentication)): a cloud provider
(`CLAUDE_CODE_USE_BEDROCK` / `_VERTEX` / `_FOUNDRY` / ...), `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_API_KEY` ("in
non-interactive mode (`-p`), the key is always used when present"), an `apiKeyHelper`, then a named Anthropic
profile or federation credentials. The guard fails closed. By default the runner:

- removes `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_PROFILE`,
  `ANTHROPIC_FEDERATION_*`, `ANTHROPIC_IDENTITY_TOKEN*` and every `CLAUDE_CODE_USE_*` from the sessions'
  environment. `CLAUDE_CODE_OAUTH_TOKEN`, a subscription token, stays;
- before any model call (the connector probe included), reads every settings source the isolated sessions
  still load ([managed settings](https://code.claude.com/docs/en/managed-settings)):
  - `managed-settings.json` and `managed-settings.d/*.json` in `/Library/Application Support/ClaudeCode/` or
    `/etc/claude-code/`;
  - the macOS MDM profile (`/Library/Managed Preferences/[<user>/]com.anthropic.claudecode.plist`);
  - the server-managed settings cache `$CLAUDE_CONFIG_DIR/remote-settings.json`.

  It refuses to start if any of them sets an `apiKeyHelper`, a `policyHelper` (its output can't be checked),
  or one of those variables in `env`, or can't be read;
- refuses to start unless `claude auth status` confirms a subscription login. That means a claude.ai login or
  an OAuth token that reports its `subscriptionType`, with no `ANTHROPIC_AUTH_TOKEN` in any settings source.
  `auth status` reports a bearer token and a subscription token alike as `oauth_token`. It also reads the user
  settings the isolated sessions skip, so an `apiKeyHelper` or bearer token there refuses too;
- refuses to start on a plan that can receive **server-managed settings**: only Claude for Teams and
  Enterprise can ([server-managed settings](https://code.claude.com/docs/en/server-managed-settings)). A
  `claude -p` session fetches and applies its organization's policy without caching it, so an
  `ANTHROPIC_AUTH_TOKEN` or API key the policy sets can't be checked beforehand. Only `subscriptionType`
  `pro` and `max` start by default. Team, Enterprise, and an unrecognised or missing plan need
  `--claude-code-trust-org-policy` (or `CLAUDE_CODE_TRUST_ORG_POLICY=1`), which trusts the organization's
  Claude Code policy not to route sessions to per-token billing. **A login in an MSK claude.ai organization
  reports `team`, so it needs this flag** (`claude auth status` shows your plan as `subscriptionType`). It doesn't relax the other checks;
- as a backstop, stops the run if a session's `apiKeySource` names a key, token, helper or bearer. A bearer
  token reports `none` there, like the subscription, which is why the checks above run first.

`--claude-code-allow-api-billing` (or `CLAUDE_CODE_ALLOW_API_BILLING=1`) turns all of these checks off. `run.json`
records `claude_code.auth_mode` (`subscription`, or with the opt-in `api-key`, `cloud-provider`, `unconfirmed`),
`claude_code.account_type` (the plan), `trust_org_policy` and `allow_api_billing`, the `claude auth status`
method, provider and whether the login belongs to an organization (no email, org id or name), and the names of
the removed variables.

A `CLAUDE_CODE_OAUTH_TOKEN` whose `auth status` doesn't show a subscription type is refused; use `/login` or
the opt-ins.

### Settings isolation

Sessions run with `--setting-sources ""`: the Claude home's user settings (and project/local ones) aren't
loaded, so `effortLevel`, hooks, enabled plugins and an `apiKeyHelper` in `~/.claude/settings.json` stay out of
the benchmark. Managed settings still apply. The login and the claude.ai connectors aren't settings, so the
connector path keeps working; if the connector ever fails to load, the runner stops with an error rather
than answering without the database. `--claude-code-user-settings` loads the user settings again.

### Built-in plugins

`claude` 2.1.287 ships plugins inside the binary (`<name>@builtin` in a session's init event). They load in every
session, even with `--setting-sources ""` and `--safe-mode`, and they are not the claude.ai org-synced plugins
(`~/.claude/plugins/synced/` holds only a marketplace index). On a Pro login a `claude -p` session loads
`cc-plugin-agents-md` (loads `AGENTS.md` as project instructions), `cc-plugin-telemetry` (lets plugins log
analytics events) and `cc-plugin-plugin-authoring` (a skill on writing plugins). On a Team or Enterprise login,
or on a machine with managed settings, it also seats `cc-plugin-sec-default` outermost. That plugin keeps the
organization's hooks, prompt content and tool policy out of reach of user plugins and adds no policy of its own.
Only managed `prependPlugins` can unseat it. `--bare` would skip plugins but never reads the subscription login.

So both the runner and the claude-code judge:

- pass `--settings '{"enabledPlugins": {"<id>@builtin": false, ...}}'` for every built-in plugin, which turns
  all of them off except a seated `cc-plugin-sec-default`;
- run a **preflight** before the first model call (the connector probe included). This is a `claude -p` on a
  model that doesn't exist, so the session prints its init event and then fails with `model_not_found`
  without generating or billing anything. The preflight must prove that: its result has to be the
  `model_not_found` error for that model, with zero tokens, no model usage and `total_cost_usd` 0 (or absent).
  Anything else refuses to start. A plugin it still finds is added to `enabledPlugins: false` and checked
  again;
- **refuse to start** if a plugin still loads, unless `--claude-code-allow-plugins` is passed (recorded in
  `run.json` as `allow_plugins`, with `plugins` and `disabled_plugins`, under `claude_code` and
  `claude_code_judge`);
- record the plugins each session loaded: `trace.plugins` on every answer and `judge_plugins` on every grade.
  A grade made without a judge session (empty answer, no reference) has `judge_plugins: null` and a
  `judge_plugins_note` saying so. A session that loads a plugin the preflight didn't find stops the
  run, the connector probe or the grading. So does an answering or judging session that doesn't report its
  plugins (no init event, or one without a plugin list), even with `--claude-code-allow-plugins`. A stopped
  run prints the `run --resume` command; the answer it stopped on, and any not yet asked, aren't recorded,
  so resume asks them.

### Grading with Claude Code (`--judge-runner claude-code`)

`run` and `grade` take `--judge-runner claude-code` to grade on the local Claude subscription instead of
Bedrock, so a benchmark costs no Bedrock credit. To grade an existing run (e.g. one collected with
`--no-grade`) locally:

```bash
uv run cbioportal-mcp-qa grade <run-id> --judge-runner claude-code --claude-code-trust-org-policy
```

(`--claude-code-trust-org-policy` is needed on a Team/Enterprise login, e.g. an MSK claude.ai organization; a
Pro or Max login doesn't need it.) `--concurrency N` grades N answers in parallel (default 1); `run` takes
`--judge-concurrency`. `--judge-model` picks the judge for either runner: a model key (`sonnet-4.6`), a Bedrock
id or a Claude Code id. By default the claude-code judge is the Bedrock judge's model (`JUDGE_MODEL`, Sonnet
4.6) through Claude Code, i.e. `claude-sonnet-4-6`.

- **Same prompt and grade.** Each answer goes to `claude -p` with the Bedrock judge's prompt and rubric on
  stdin, the same JSON schema as structured output (`--json-schema`), and produces the same grade fields.
- **No tools.** Built-in tools are off (`--tools ""`), and so are MCP servers: `--strict-mcp-config` with an
  empty config, and `ENABLE_CLAUDEAI_MCP_SERVERS=false` for the claude.ai connectors. Skills are off
  (`--disable-slash-commands`), as are auto memory (`CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`) and the hooks of every
  settings source a session can override (`--settings '{"disableAllHooks": true, "autoMemoryEnabled": false}'`).
- **Same billing safeguards as the runner** ([above](#billing-guard)): billing variables are removed, the
  billing guard and plan check run before the first grading call, and a session whose `apiKeySource` names a
  key or token stops grading. `--claude-code-trust-org-policy` and `--claude-code-allow-api-billing` work as
  for the runner. User settings are **never** loaded (`--setting-sources ""`): `--claude-code-user-settings`
  only applies to the runner (`grade` doesn't take it). It runs in an empty temp directory.
- **Managed customizations refuse the judge.** Managed (policy) settings still apply with
  `--setting-sources ""`, and a session can't turn them off: managed hooks (a `SessionStart` hook can add
  context, an agent hook can run tools that aren't in the session's tool list) run even with
  `disableAllHooks` set outside managed settings; a managed `CLAUDE.md` can't be excluded; managed plugins and
  MCP servers load. `--bare` would skip them, but bare mode never reads the subscription login. So before the
  first call, the judge reads every managed source the runner's billing guard reads:
  - the managed settings files and drop-ins (`managed-settings.json`, `managed-settings.d/*.json` in
    `/Library/Application Support/ClaudeCode/` or `/etc/claude-code/`);
  - the MDM profile (`/Library/Managed Preferences/[<user>/]com.anthropic.claudecode.plist`);
  - the cached server-managed settings (`$CLAUDE_CONFIG_DIR/remote-settings.json`);
  - the managed `CLAUDE.md`, `managed-mcp.json` and `.claude/` in those directories.

  It refuses to grade if any of them sets `hooks` or `allowManagedHooksOnly`, unless managed settings set
  `disableAllHooks: true`. It also refuses on `claudeMd`, `enabledPlugins`, `mcpServers`, `agent` or
  `outputStyle`, on any of those managed files, and on a file it can't read. `--judge-allow-managed-customizations`
  grades anyway: it prints what the sessions inherit and records it under `claude_code_judge` in `run.json`,
  with the judge's auth mode, plan and opt-ins. As a backstop, grading stops if a session's stream shows a hook
  running (`hook_started` / `hook_response`), an MCP server, or any tool besides `StructuredOutput`. Plugins
  are handled as described in [Built-in plugins](#built-in-plugins).
  **Residual risk:** as for the runner, server-managed settings that a Team or Enterprise organization delivers
  when a `claude -p` session starts aren't cached, so they can't be read beforehand. `--claude-code-trust-org-policy`
  trusts that policy not to add hooks or instructions to the judge, as it trusts it not to bill per token; the
  stream backstop catches hooks that run at session start, plugins and servers, but not a remotely delivered
  `claudeMd`.
- **Failures.** A reply that isn't valid JSON or doesn't match the schema is retried once; if it fails again
  the answer is left ungraded (`judge_error` in `run.json` says why) and the next `grade` tries it again. The
  subscription's usage limit stops grading on the call that hit it, with no retry. It is recognized by the same
  pattern the runner uses: `You've hit your limit`, `hit your session / weekly / 5-hour / … limit`,
  `usage limit reached`, or a rate limit that names its reset. Grades so far are saved, the report is written,
  and the `grade` command to resume once the limit resets is printed. That command keeps the run as you named it
  (id or path) and the judge options you used (`--judge-model`, `--concurrency`, `--claude-code-trust-org-policy`,
  `--claude-code-allow-api-billing`, `--judge-allow-managed-customizations`, `--claude-code-allow-plugins`). With
  `--wait-on-limit` it waits for the reset instead and carries on
  ([above](#stopping-on-the-usage-limit-and---wait-on-limit)).
- **Judge identity.** Each grade records its judge as `claude-code:<model>` (e.g.
  `claude-code:claude-sonnet-4-6`), so `compare` refuses to mix them with Bedrock grades (`us.anthropic.…`),
  and a run graded by both shows up as mixed. Judge cost isn't estimated: nothing is billed per token.

**Less deterministic than Bedrock.** Claude Code can't set the temperature, so the claude-code judge can't
grade at temperature 0 like the Bedrock judge, and regrading the same answer can flip a borderline verdict.
Grade the before and after runs of a comparison with the same judge (both `claude-code:<model>`, or both
Bedrock), and expect a little more noise than with Bedrock. Claude Code grades are **not comparable** with
the Bedrock-graded 09-23 run (20260923-1919) or any other Bedrock-graded run; regrade that run with
`--judge-runner claude-code --regrade` if you need it as a baseline.

### MCP servers, and benchmarking beta

- **Navigator:** its public endpoint `https://mcp.cbioportal.org/navigator/mcp` (`NAVIGATOR_MCP_URL`; no login
  needed). Beta and prod share the navigator deployment.
- **Database:** by default, the claude.ai connector for its public endpoint `https://mcp.cbioportal.org/db/mcp`
  (`DATABASE_CONNECTOR_URL`), which needs an OAuth login only the connector holds. The runner finds the
  connector by that URL in `claude mcp list`, whatever you named it (or `CLAUDE_AI_DATABASE_CONNECTOR` names
  it), and hides every other claude.ai connector from the model. Add the connector in claude.ai once.

That public endpoint is **prod's** database MCP (`cbioagent-clickhouse-mcp`, `cbioportal/mcp:latest`). Beta
runs its own, `cbioagent-clickhouse-mcp-beta` (`cbioportal/mcp:beta` on beta's ClickHouse buffers; see
knowledgesystems-k8s-deployment#658, which was still open at the time of writing), with no public endpoint.
So with a `beta*` target and no `DATABASE_MCP_URL`, answers come from prod's MCP: the runner prints a
warning and records `database_mcp_env: prod` in `run.json`. `--require-beta-mcp` makes that an error. To
benchmark beta, point `DATABASE_MCP_URL` at beta's MCP:

```bash
# Service and path from k8s-deployment#658 (to be confirmed once it's merged and synced)
kubectl port-forward svc/cbioagent-clickhouse-mcp-beta 18081:80 &
export DATABASE_MCP_URL=http://localhost:18081/db/mcp DATABASE_MCP_ENV=beta
uv run cbioportal-mcp-qa run --runner claude-code --target beta --require-beta-mcp --questions 1-20
```

A port-forward's URL doesn't say what's behind it, so declare it with `DATABASE_MCP_ENV` (`beta`, `prod` or
`local`); otherwise it's recorded as `unknown` and `--require-beta-mcp` refuses it. A declaration that
contradicts the URL's host (e.g. `DATABASE_MCP_ENV=beta` with the connector or `mcp.cbioportal.org`, or with
prod's service name) is recorded as `conflict`: that prints a warning on any target and fails
`--require-beta-mcp`. With a port-forward,
dropped connections show up as tool errors such as `ECONNRESET` that the deployed agent wouldn't have hit.
Prod's service works the same way (`svc/cbioagent-clickhouse-mcp`). `run.json`'s `versions` records the
deployments it read for the target (`versions.deployments`) and their image tags and digests.

To test an unmerged cbioportal-mcp branch, or the `cbioportal/mcp:beta` image, run it locally and point
`DATABASE_MCP_URL` at it (`DATABASE_MCP_ENV=beta` for the beta image): `docker run --rm -p 18080:8000
--env-file <clickhouse.env> -e CLICKHOUSE_MCP_SERVER_TRANSPORT=http -e CLICKHOUSE_MCP_BIND_HOST=0.0.0.0 -e
CLICKHOUSE_MCP_BIND_PORT=8000 <image>` (URL `http://localhost:18080/mcp`). For the same data as beta, its
env file must name beta's ClickHouse database (`kubectl get configmap clickhouse-mcp-active-beta -o
jsonpath='{.data.CLICKHOUSE_DATABASE}'`).

### Server instructions

Beta's LibreChat puts the database MCP's `instructions` (from its initialize response) into the agent's
system prompt after the agent's own (`serverInstructions: true`, k8s-deployment#654). Claude Code already
sends every MCP server's `instructions`, with `--system-prompt` too: as a "MCP Server Instructions"
system-reminder at the start of the first user turn, after the system prompt. This was checked against the
request Claude Code 2.1.283 sends, captured by a local stand-in for the API. That's the same order, so the
runner doesn't add them again. For a database MCP reached by URL, `run.json`'s `claude_code.prompt` records
hashes of the agent instructions, the server instructions and both joined in LibreChat's order (`combined`).
Through the connector, the server instructions can't be read without its OAuth login, so only the agent
instructions are hashed.

Every run also records versions (both runners): cBioPortal portal / DB schema / gene table versions from
`https://www.cbioportal.org/api/info`, and the cbioportal-mcp and navigator server versions (with a hash of
the server's instructions) and image digests.

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

### Subset questions

`input/questions-subset.yaml` (ids 2001+) asks for statistics over a *subset* of a study: a clinical subgroup
(sample type, sex, smoking, stage, MSI, HR/HER2, OncoTree code), a pooled set of studies, or a mutation-defined
group. The main set leans on per-study statistics, which precomputed tables and per-study tools answer directly;
these questions measure whether the agent writes the right SQL instead, and doesn't answer with the
whole-study number. Like the multi-turn set, it is its own test set with its own pass rates:

```bash
uv run cbioportal-mcp-qa run --runner claude-code --questions-file input/questions-subset.yaml
```

Each question's `sql` field names the query in `input/subset-sql/` that computed its reference, with the
database and date (see [its README](input/subset-sql/README.md)).

## Development

```bash
uv run pytest
uv run ruff check src tests && uv run ruff format src tests
```

The benchmark tests the agent as deployed: its system prompt lives in the agent's instructions in the
cBioAgent MongoDB and the LibreChat config, not in this repo.
