"""Read a deployed agent's system prompt (its instructions in the cBioAgent MongoDB) via kubectl.

The benchmark never keeps its own copy of the prompt: the Claude Code runner fetches it from the live
agent at the start of every run, and run.json records only its hash.
"""

import base64
import hashlib
import json

import yaml

from .redact import add_secret, describe_error, run_command

MONGO_SECRET = "cbioagent-mongodb-creds"
MONGO_SECRET_KEY = "mongodb-passwords"


def _kubectl(args: list[str], context: str | None) -> str:
    cmd = ["kubectl", *(["--context", context] if context else []), *args]
    return run_command(cmd, timeout=120)


def fetch_agent_prompt(agent_id: str, context: str | None = None) -> dict:
    """The agent's `instructions`, model, `model_parameters`, handoff destinations (`edges`) and when the agent was
    last updated."""
    pods = _kubectl(["get", "pods", "-o", "name"], context).split()
    pod = next((p for p in pods if p.startswith("pod/cbioagent-mongodb-")), None)
    if pod is None:
        raise RuntimeError("no cbioagent-mongodb pod in the current kubectl context")
    encoded = _kubectl(
        ["get", "secret", MONGO_SECRET, "-o", f"jsonpath={{.data.{MONGO_SECRET_KEY}}}"], context
    )
    password = base64.b64decode(encoded).decode()
    # Masked wherever it could surface in results: the mongosh URI below carries it.
    for value in (encoded.strip(), password):
        add_secret(value)
    script = (
        f"const a = db.agents.findOne({{id: {json.dumps(agent_id)}}}); "
        "print(JSON.stringify(a ? {instructions: a.instructions, updated_at: a.updatedAt, model: a.model, "
        "model_parameters: a.model_parameters || {}, edges: (a.edges || []).flatMap((e) => [].concat(e.to))} "
        ": null))"
    )
    out = _kubectl(
        [
            "exec",
            pod.removeprefix("pod/"),
            "-c",
            "mongodb",
            "--",
            "mongosh",
            f"mongodb://cbioagent:{password}@localhost:27017/cBioAgent",
            "--quiet",
            "--eval",
            script,
        ],
        context,
    )
    agent = json.loads(out.strip().splitlines()[-1])
    if not agent or not agent.get("instructions"):
        raise RuntimeError(f"agent {agent_id} not found or has no instructions")
    return agent


# The LibreChat model parameters that set how much a model reasons (Anthropic thinking and its budget, an
# effort level, OpenAI's reasoning_effort). Only these are recorded.
EFFORT_PARAMETERS = ("thinking", "thinkingBudget", "effort", "reasoning_effort")


def effort_parameters(params) -> dict:
    return {k: params[k] for k in EFFORT_PARAMETERS if k in params} if isinstance(params, dict) else {}


def describe_effort(params: dict) -> str:
    """A label for effort parameters: the effort level and whether thinking is on (with its budget); "default"
    when none is set, so LibreChat's defaults apply."""
    parts = [str(v) for v in (params.get("effort"), params.get("reasoning_effort")) if v]
    if "thinking" in params:
        budget = params.get("thinkingBudget")
        parts.append(
            "thinking " + ("on" + (f", budget {budget}" if budget else "") if params["thinking"] else "off")
        )
    return ", ".join(parts) or "default"


def fetch_model_specs(deployment: str, context: str | None = None) -> dict:
    """The effort parameters of each modelSpec's preset in a LibreChat deployment's librechat.yaml (read in its
    container, at CONFIG_PATH or LibreChat's default path), by spec name. Nothing else of the file is kept."""
    out = _kubectl(
        ["exec", f"deploy/{deployment}", "--", "sh", "-c", 'cat "${CONFIG_PATH:-/app/librechat.yaml}"'],
        context,
    )
    try:
        config = yaml.safe_load(out) or {}
    except yaml.YAMLError:
        # Not the parser's message: it quotes the file, which can hold credentials.
        raise RuntimeError(f"{deployment}'s librechat.yaml did not parse") from None
    specs = ((config.get("modelSpecs") or {}).get("list")) or []
    return {
        s["name"]: effort_parameters(s.get("preset")) for s in specs if isinstance(s, dict) and s.get("name")
    }


def deployed_effort(agent_params: dict | None, spec: str | None, specs: dict | None) -> str | None:
    """The effort a deployed model answers with: the agent's effort parameters, overridden by its modelSpec's
    preset when the model is asked with a spec. None when either couldn't be read."""
    if agent_params is None:
        return None
    if spec is None:
        return describe_effort(agent_params)
    if not specs or spec not in specs:
        return None
    return describe_effort(agent_params | specs[spec])


def prompt_fingerprint(prompt: str) -> dict:
    return {"sha256": hashlib.sha256(prompt.encode()).hexdigest()[:12], "chars": len(prompt)}


def describe_agents(agent_id: str, context: str | None = None, fetch=fetch_agent_prompt) -> dict:
    """Prompt fingerprint, model and last update of an agent and every agent it hands off to, by id."""
    out: dict[str, dict] = {}
    todo = [agent_id]
    while todo:
        current = todo.pop(0)
        if current in out:
            continue
        try:
            agent = fetch(current, context)
        except Exception as exc:  # noqa: BLE001 - recorded, never fatal
            out[current] = {"error": describe_error(exc)}
            continue
        edges = [e for e in agent.get("edges") or [] if isinstance(e, str)]
        out[current] = prompt_fingerprint(agent["instructions"]) | {
            "model": agent.get("model"),
            "effort_parameters": effort_parameters(agent.get("model_parameters")),
            "updated_at": agent.get("updated_at"),
            "edges": edges,
        }
        todo += edges
    return out
