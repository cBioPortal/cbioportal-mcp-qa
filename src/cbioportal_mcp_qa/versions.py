"""Versions of everything a run depended on, recorded best-effort in run.json (a failed probe is noted, not fatal)."""

import json
import subprocess

import httpx

from .mcp_http import MCPSession

CBIOPORTAL_INFO_URL = "https://www.cbioportal.org/api/info"
DEPLOYMENTS = {"cbioportal_mcp": "cbioagent-clickhouse-mcp", "cbioportal_navigator": "cbioportal-navigator"}
LIBRECHAT_DEPLOYMENTS = {"beta": "cbioagent-librechat-beta", "prod": "cbioagent-librechat"}


def _probe(fn):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - version info must never fail a run
        return {"error": f"{type(exc).__name__}: {exc}"[:200]}


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
    return {"name": info.get("name"), "version": info.get("version")}


def image_digests(context: str | None) -> dict:
    """Running image of each MCP deployment in the cluster (cbioportal/mcp images carry no git labels)."""
    cmd = ["kubectl", *(["--context", context] if context else []), "get", "pods", "-o", "json"]
    pods = json.loads(subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60).stdout)
    out = {}
    for key, prefix in DEPLOYMENTS.items():
        for pod in pods["items"]:
            name = pod["metadata"]["name"]
            statuses = pod.get("status", {}).get("containerStatuses") or []
            if name.startswith(prefix + "-") and name.count("-") == prefix.count("-") + 2 and statuses:
                if statuses[0].get("ready"):
                    out[key] = statuses[0].get("imageID", "").split("@")[-1][:19]
                    break
    return out


def librechat_image(target: str, context: str | None) -> str:
    """The LibreChat image (fork tag) that serves the target's Agents API."""
    cmd = [
        "kubectl",
        *(["--context", context] if context else []),
        "get",
        "deployment",
        LIBRECHAT_DEPLOYMENTS[target],
    ]
    cmd += ["-o", "jsonpath={.spec.template.spec.containers[0].image}"]
    return subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60).stdout.strip()


def claude_code() -> str:
    return subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=30).stdout.strip()


def collect(settings, runner: str, target: str) -> dict:
    versions = {
        "cbioportal_api": _probe(cbioportal_api),
        "image_digests": _probe(lambda: image_digests(settings.kube_context)),
        "cbioportal_navigator": _probe(lambda: mcp_server(settings.navigator_mcp_url)),
    }
    if settings.database_mcp_url:
        versions["cbioportal_mcp"] = _probe(lambda: mcp_server(settings.database_mcp_url))
    if runner == "claude-code":
        versions["claude_code"] = _probe(claude_code)
    else:
        versions["librechat"] = _probe(lambda: librechat_image(target, settings.kube_context))
    return versions
