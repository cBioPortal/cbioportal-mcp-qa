"""Read a deployed agent's system prompt (its instructions in the cBioAgent MongoDB) via kubectl.

The benchmark never keeps its own copy of the prompt: the Claude Code runner fetches it from the live
agent at the start of every run, and run.json records only its hash.
"""

import base64
import hashlib
import json

from .redact import add_secret, describe_error, run_command

MONGO_SECRET = "cbioagent-mongodb-creds"
MONGO_SECRET_KEY = "mongodb-passwords"


def _kubectl(args: list[str], context: str | None) -> str:
    cmd = ["kubectl", *(["--context", context] if context else []), *args]
    return run_command(cmd, timeout=120)


def fetch_agent_prompt(agent_id: str, context: str | None = None) -> dict:
    """The agent's `instructions`, model, handoff destinations (`edges`) and when the agent was last updated."""
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
        "edges: (a.edges || []).flatMap((e) => [].concat(e.to))} : null))"
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
            "updated_at": agent.get("updated_at"),
            "edges": edges,
        }
        todo += edges
    return out
