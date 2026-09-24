"""Versions of everything a run depended on, recorded best-effort in run.json (a failed probe is noted, not fatal)."""

import json
import subprocess

import httpx

from .mcp_http import MCPSession

CBIOPORTAL_INFO_URL = "https://www.cbioportal.org/api/info"
DEPLOYMENTS = {"cbioportal_mcp": "cbioagent-clickhouse-mcp", "cbioportal_navigator": "cbioportal-navigator"}


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


def clickhouse_database(database_mcp_url: str) -> dict:
    """The database the MCP server actually queries, and when its tables were built (the daily clone)."""
    query = (
        "SELECT currentDatabase() AS database, toString(max(metadata_modification_time)) AS built "
        "FROM system.tables WHERE database = currentDatabase()"
    )
    with MCPSession(database_mcp_url) as mcp:
        mcp.initialize()
        text = mcp.call_tool("clickhouse_run_select_query", {"query": query})
    rows = json.loads(text).get("rows") or [{}]
    return rows[0]


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


def claude_code() -> str:
    return subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=30).stdout.strip()


def collect(settings, runner: str) -> dict:
    versions = {
        "cbioportal_api": _probe(cbioportal_api),
        "image_digests": _probe(lambda: image_digests(settings.kube_context)),
        "cbioportal_mcp": _probe(lambda: mcp_server(settings.database_mcp_url)),
        "cbioportal_navigator": _probe(lambda: mcp_server(settings.navigator_mcp_url)),
        "clickhouse": _probe(lambda: clickhouse_database(settings.database_mcp_url)),
    }
    if runner == "claude-code":
        versions["claude_code"] = _probe(claude_code)
    return versions
