"""Read a deployed agent's system prompt (its instructions in the cBioAgent MongoDB) via kubectl.

The benchmark never keeps its own copy of the prompt: the Claude Code runner fetches it from the live
agent at the start of every run, and run.json records only its hash.
"""

import base64
import hashlib
import json
import subprocess

MONGO_SECRET = "cbioagent-mongodb-creds"
MONGO_SECRET_KEY = "mongodb-passwords"


def _kubectl(args: list[str], context: str | None) -> str:
    cmd = ["kubectl", *(["--context", context] if context else []), *args]
    return subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120).stdout


def fetch_agent_prompt(agent_id: str, context: str | None = None) -> str:
    pods = _kubectl(["get", "pods", "-o", "name"], context).split()
    pod = next((p for p in pods if p.startswith("pod/cbioagent-mongodb-")), None)
    if pod is None:
        raise RuntimeError("no cbioagent-mongodb pod in the current kubectl context")
    password = base64.b64decode(
        _kubectl(["get", "secret", MONGO_SECRET, "-o", f"jsonpath={{.data.{MONGO_SECRET_KEY}}}"], context)
    ).decode()
    script = f"const a = db.agents.findOne({{id: {json.dumps(agent_id)}}}); print(JSON.stringify(a ? a.instructions : null))"
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
    instructions = json.loads(out.strip().splitlines()[-1])
    if not instructions:
        raise RuntimeError(f"agent {agent_id} not found or has no instructions")
    return instructions


def prompt_fingerprint(prompt: str) -> dict:
    return {"sha256": hashlib.sha256(prompt.encode()).hexdigest()[:12], "chars": len(prompt)}
