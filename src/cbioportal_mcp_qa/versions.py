"""Versions of everything a run depended on, recorded best-effort in run.json (a failed probe is noted, not fatal)."""

import json
import subprocess
from urllib.parse import urlparse

import httpx

from .agent_prompt import prompt_fingerprint
from .config import TARGETS
from .mcp_http import MCPSession
from .redact import describe_error, run_command

CBIOPORTAL_INFO_URL = "https://www.cbioportal.org/api/info"
NAVIGATOR_DEPLOYMENT = "cbioportal-navigator"  # shared by beta and prod
# The public MCP endpoints serve prod's database MCP; beta's has no public endpoint (k8s-deployment#658).
PROD_MCP_HOSTS = {"mcp.cbioportal.org"}
DATABASE_MCP_ENVS = ("beta", "prod", "local")


def deployments(target: str) -> dict[str, str]:
    """The MCP deployments the target's agent uses, by run.json key."""
    return {"cbioportal_mcp": TARGETS[target].mcp_deployment, "cbioportal_navigator": NAVIGATOR_DEPLOYMENT}


def _env_from_host(url: str) -> str | None:
    """prod or beta when the URL's host says so: the public host, or a deployment's in-cluster service name
    (bare or as a cluster DNS name)."""
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if host in PROD_MCP_HOSTS:
        return "prod"
    service = host.split(".")[0]
    if service in {t.mcp_deployment for t in TARGETS.values()}:
        return "beta" if service.endswith("-beta") else "prod"
    return None


def database_mcp_env(settings) -> str:
    """Which database MCP the claude-code runner reaches: what the URL's host says (the claude.ai connector's
    public endpoint and prod's service are prod, beta's service is beta), else what DATABASE_MCP_ENV declares
    (beta, prod, local) for a port-forward or local image, else unknown. A declaration that contradicts the
    host is a conflict."""
    url = settings.database_mcp_url or settings.database_connector_url
    from_host = _env_from_host(url)
    declared = settings.database_mcp_env
    if declared and declared not in DATABASE_MCP_ENVS:
        return "conflict" if from_host else "unknown"
    if from_host and declared and declared != from_host:
        return "conflict"
    return from_host or declared or "unknown"


def _probe(fn):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - version info must never fail a run
        return {"error": describe_error(exc)}


def cbioportal_api() -> dict:
    info = httpx.get(CBIOPORTAL_INFO_URL, timeout=20).json()
    return {
        "portal_version": info.get("portalVersion"),
        "db_schema_version": info.get("dbVersion"),
        "git_commit": (info.get("gitCommitId") or "")[:12],
        "gene_table_version": info.get("geneTableVersion"),
        "geneset_version": info.get("genesetVersion"),
    }


def mcp_server(url: str) -> dict:
    with MCPSession(url) as mcp:
        info = mcp.initialize()
    out = {"name": info.get("name"), "version": info.get("version")}
    if mcp.instructions:
        out["instructions"] = prompt_fingerprint(mcp.instructions)
    return out


def server_instructions(url: str) -> str | None:
    """The `instructions` in an MCP server's initialize response."""
    with MCPSession(url) as mcp:
        mcp.initialize()
    return mcp.instructions


def _ready_containers(context: str | None, target: str = "prod") -> dict:
    """The first container status of a ready pod of each MCP deployment the target uses."""
    cmd = ["kubectl", *(["--context", context] if context else []), "get", "pods", "-o", "json"]
    pods = json.loads(run_command(cmd, timeout=60))
    out = {}
    for key, prefix in deployments(target).items():
        for pod in pods["items"]:
            name = pod["metadata"]["name"]
            statuses = pod.get("status", {}).get("containerStatuses") or []
            if name.startswith(prefix + "-") and name.count("-") == prefix.count("-") + 2 and statuses:
                if statuses[0].get("ready"):
                    out[key] = statuses[0]
                    break
    return out


def image_digests(context: str | None, target: str = "prod") -> dict:
    """Running image of each MCP deployment in the cluster (cbioportal/mcp images carry no git labels)."""
    return {
        k: s.get("imageID", "").split("@")[-1][:19] for k, s in _ready_containers(context, target).items()
    }


def image_tags(context: str | None, target: str = "prod") -> dict:
    """Image reference (repository:tag) each MCP deployment runs."""
    return {k: s.get("image", "") for k, s in _ready_containers(context, target).items()}


def librechat_image(target: str, context: str | None) -> str:
    """The LibreChat image (fork tag) that serves the target's Agents API."""
    cmd = [
        "kubectl",
        *(["--context", context] if context else []),
        "get",
        "deployment",
        TARGETS[target].librechat_deployment,
    ]
    cmd += ["-o", "jsonpath={.spec.template.spec.containers[0].image}"]
    return run_command(cmd, timeout=60).strip()


def claude_code() -> str:
    return subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=30).stdout.strip()


def collect(settings, runner: str, target: str) -> dict:
    versions = {
        "cbioportal_api": _probe(cbioportal_api),
        "deployments": deployments(target),
        "image_digests": _probe(lambda: image_digests(settings.kube_context, target)),
        "image_tags": _probe(lambda: image_tags(settings.kube_context, target)),
        "cbioportal_navigator": _probe(lambda: mcp_server(settings.navigator_mcp_url)),
    }
    if settings.database_mcp_url:
        versions["cbioportal_mcp"] = _probe(lambda: mcp_server(settings.database_mcp_url))
    if runner == "claude-code":
        versions["claude_code"] = _probe(claude_code)
    else:
        versions["librechat"] = _probe(lambda: librechat_image(target, settings.kube_context))
    return versions
