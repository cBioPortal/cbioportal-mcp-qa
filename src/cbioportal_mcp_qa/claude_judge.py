"""The judge on the local Claude Code subscription (`claude -p`) instead of Bedrock.

Same prompt, rubric and grade fields as the Bedrock judge, with the claude-code runner's safeguards: billing
variables removed, the billing guard run before the first call (and the session's apiKeySource checked after
each), user settings left out, an empty working directory, and no tools at all (no built-ins, no MCP servers,
no claude.ai connectors). Claude Code can't set the temperature, so its grades vary more than Bedrock's
temperature-0 ones; each grade records the judge as `claude-code:<model>` so `compare` keeps them apart.
"""

import json
import os
import subprocess
import tempfile
import threading

from .claude_code import (
    USAGE_LIMIT,
    api_billing_error,
    api_key_source,
    bills_per_token,
    check_billing,
    session_env,
    setting_sources_args,
)
from .config import MODELS, _model_family
from .grade import JUDGE_SCHEMA, BaseJudge, JudgeOutputError, JudgeStopped, parse_verdict
from .persist import write_private_json
from .redact import redact

JUDGE_ID_PREFIX = "claude-code:"
# Claude Code's own system prompt (tools, coding style) would be part of the grading context otherwise.
JUDGE_SYSTEM_PROMPT = "You are a grader. Reply with the verdict the JSON schema describes, nothing else."
ATTEMPTS = 2  # an invalid verdict is retried once, then the answer stays ungraded


def claude_code_model(model: str) -> str:
    """A Claude Code model id from a model key (`sonnet-4.6`), a Bedrock id (`us.anthropic.claude-sonnet-4-6`)
    or a Claude Code id (`claude-sonnet-4-6`): by default the same model as the Bedrock judge."""
    if model in MODELS:
        known = MODELS[model]
        if known.claude_code_id:
            return known.claude_code_id
        if not known.bedrock_id:
            raise ValueError(f"{model} isn't a single model")
        model = known.bedrock_id
    return _model_family(model)


def judge_args(model: str, mcp_config_path: str, isolate_settings: bool = True) -> list[str]:
    """`claude -p` with the prompt on stdin, no tools and no MCP servers, and the verdict as structured output."""
    return [
        "claude",
        "-p",
        "--model",
        model,
        "--system-prompt",
        JUDGE_SYSTEM_PROMPT,
        "--tools",
        "",
        "--strict-mcp-config",
        "--mcp-config",
        mcp_config_path,
        "--json-schema",
        json.dumps(JUDGE_SCHEMA),
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
        *setting_sources_args(isolate_settings),
    ]


def judge_env(base, allow_api_billing: bool) -> tuple[dict, list[str]]:
    """The runner's session environment, with the claude.ai connectors off too."""
    env, stripped = session_env(base, allow_api_billing)
    return env | {"ENABLE_CLAUDEAI_MCP_SERVERS": "false"}, stripped


# What --json-schema adds to the session to return the verdict; it does nothing else.
STRUCTURED_OUTPUT_TOOL = "StructuredOutput"


def session_tools(events: list[dict]) -> list[str]:
    """Tools (built-in or MCP) the session had besides the structured-output one, from its init event."""
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
    return sorted(t for t in init.get("tools") or [] if t != STRUCTURED_OUTPUT_TOOL)


class ClaudeCodeJudge(BaseJudge):
    def __init__(
        self,
        model: str,
        allow_api_billing: bool = False,
        isolate_settings: bool = True,
        trust_org_policy: bool = False,
        timeout_s: float = 300.0,
    ):
        self.claude_model = claude_code_model(model)
        self.model = JUDGE_ID_PREFIX + self.claude_model
        self.allow_api_billing = allow_api_billing
        self.isolate_settings = isolate_settings
        self.timeout_s = timeout_s
        self.env, self.stripped_env = judge_env(os.environ, allow_api_billing)
        # Refuses per-token billing (and unchecked org policies) before any grading call.
        self.auth = check_billing(self.env, isolate_settings, allow_api_billing, trust_org_policy)
        self._workdir = tempfile.TemporaryDirectory(prefix="mcp-qa-judge-")
        self.mcp_config_path = os.path.join(self._workdir.name, "no-mcp.json")
        write_private_json(self.mcp_config_path, {"mcpServers": {}})
        self.stopped: str | None = None
        self._lock = threading.Lock()

    def close(self) -> None:
        self._workdir.cleanup()

    def _stop(self, reason: str) -> JudgeStopped:
        with self._lock:
            self.stopped = self.stopped or reason
        return JudgeStopped(self.stopped)

    def verdict(self, prompt: str) -> tuple[dict, int, int]:
        problem = ""
        for _ in range(ATTEMPTS):
            if self.stopped:
                raise JudgeStopped(self.stopped)
            try:
                return self._call(prompt)
            except JudgeOutputError as exc:
                problem = str(exc)
        raise JudgeOutputError(f"{problem} (after {ATTEMPTS} attempts)")

    def _call(self, prompt: str) -> tuple[dict, int, int]:
        try:
            out = subprocess.run(
                judge_args(self.claude_model, self.mcp_config_path, self.isolate_settings),
                input=prompt,
                cwd=self._workdir.name,  # empty: no project CLAUDE.md
                env=self.env,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            raise JudgeOutputError(f"timed out after {self.timeout_s:.0f}s") from exc
        lines = out.stdout.splitlines()
        if not self.allow_api_billing and bills_per_token(source := api_key_source(lines)):
            raise self._stop(api_billing_error(source))
        events = []
        for line in lines:
            if line.strip().startswith("{"):
                try:
                    events.append(json.loads(line))
                except ValueError:
                    pass
        if tools := session_tools(events):
            raise self._stop(f"the judge session had tools {tools}; it must have none")
        result = next((e for e in reversed(events) if e.get("type") == "result"), None)
        if result is None or result.get("is_error"):
            error = redact(str((result or {}).get("result") or (result or {}).get("subtype") or "no result"))
            stderr = redact(out.stderr or "")
            if USAGE_LIMIT.search(error) or USAGE_LIMIT.search(stderr):
                raise self._stop(f"Claude subscription limit: {error[:300]}")
            raise JudgeOutputError(f"claude failed: {error[:300]} (exit {out.returncode}: {stderr[-300:]})")
        verdict = result.get("structured_output")
        verdict = parse_verdict(verdict if verdict is not None else (result.get("result") or ""))
        usage = result.get("usage") or {}
        input_tokens = sum(
            usage.get(k) or 0
            for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
        )
        return verdict, input_tokens, usage.get("output_tokens") or 0
