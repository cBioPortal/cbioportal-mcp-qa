import os
import re
from dataclasses import dataclass

from dotenv import load_dotenv

from .redact import add_env_secrets, add_secret


@dataclass(frozen=True)
class Price:
    """USD per million tokens, Anthropic list price. Bedrock billing can differ."""

    input: float
    output: float
    cache_write: float
    cache_read: float

    def cost(self, uncached: int, output: int, cache_write: int, cache_read: int) -> float:
        return (
            uncached * self.input
            + output * self.output
            + cache_write * self.cache_write
            + cache_read * self.cache_read
        ) / 1_000_000


@dataclass(frozen=True)
class Model:
    """A model under test. Without a bedrock_id and price it is a label for whatever the agent runs (e.g. the
    handoff router, which calls several models): each answer is then priced per LLM call from its trace."""

    key: str
    label: str
    bedrock_id: str | None
    price: Price | None
    claude_code_id: str | None = None


MODELS = {
    "haiku": Model(
        "haiku",
        "Haiku 4.5",
        "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        Price(1.0, 5.0, 1.25, 0.10),
        "claude-haiku-4-5-20251001",
    ),
    "sonnet": Model(
        "sonnet", "Sonnet 5", "us.anthropic.claude-sonnet-5", Price(2.0, 10.0, 2.5, 0.20), "claude-sonnet-5"
    ),
    # Claude Code runner only (no Bedrock id configured); Claude API list price, same as Sonnet 5.
    "sonnet-5.5": Model("sonnet-5.5", "Sonnet 5.5", None, Price(2.0, 10.0, 2.5, 0.20), "claude-sonnet-5-5"),
    "sonnet-4.6": Model(
        "sonnet-4.6",
        "Sonnet 4.6",
        "us.anthropic.claude-sonnet-4-6",
        Price(3.0, 15.0, 3.75, 0.30),
    ),
    "router": Model("router", "Handoff router", None, None),
    "unified": Model("unified", "Unified agent", None, None),
}
PRICES_BY_BEDROCK_ID = {m.bedrock_id: m.price for m in MODELS.values() if m.bedrock_id and m.price}


def _model_family(model_id: str) -> str:
    """`us.anthropic.claude-haiku-4-5-20251001-v1:0` -> `claude-haiku-4-5-20251001`."""
    name = model_id.rsplit("/", 1)[-1]
    name = re.sub(r"^((us|eu|apac|global)\.)?(anthropic\.)?", "", name)
    return re.sub(r"-v\d+(:\d+)?$", "", name)


def price_for(model_id: str | None) -> Price | None:
    """List price for a model id as Langfuse records it (Bedrock id, with or without region prefix)."""
    if not model_id:
        return None
    if model_id in PRICES_BY_BEDROCK_ID:
        return PRICES_BY_BEDROCK_ID[model_id]
    family = _model_family(model_id)
    return next((p for bid, p in PRICES_BY_BEDROCK_ID.items() if _model_family(bid) == family), None)


@dataclass(frozen=True)
class Target:
    """A deployed LibreChat instance, its agent, and the modelSpec that selects each model. A model whose spec is
    None is asked without a spec, so the agent runs its own model_parameters."""

    name: str
    url: str
    agent_id: str
    specs: dict[str, str | None]
    librechat_deployment: str
    # The database MCP the target's LibreChat talks to. Beta runs its own (knowledgesystems-k8s-deployment#658:
    # `cbioportal/mcp:beta` on beta's ClickHouse buffers, in-cluster only); the navigator is shared.
    mcp_deployment: str = "cbioagent-clickhouse-mcp"


TARGETS = {
    "beta": Target(
        "beta",
        "https://beta.chat.cbioportal.org",
        "agent_OHVSJI9Gd6gwsDnFSL-Xl",
        {"haiku": "cBioPortalChatBeta", "sonnet": "cBioPortalChatBetaSonnet"},
        "cbioagent-librechat-beta",
        "cbioagent-clickhouse-mcp-beta",
    ),
    # Once cBioPortalChatBeta points at the handoff router (knowledgesystems-k8s-deployment#655), the specs above
    # no longer select a model for the unified agent (400 invalid_spec). These ask an agent directly, no spec.
    "beta-router": Target(
        "beta-router",
        "https://beta.chat.cbioportal.org",
        "agent_cbiobeta_router",
        {"router": None},
        "cbioagent-librechat-beta",
        "cbioagent-clickhouse-mcp-beta",
    ),
    "beta-unified": Target(
        "beta-unified",
        "https://beta.chat.cbioportal.org",
        "agent_OHVSJI9Gd6gwsDnFSL-Xl",
        {"unified": None},
        "cbioagent-librechat-beta",
        "cbioagent-clickhouse-mcp-beta",
    ),
    "prod": Target(
        "prod",
        "https://chat.cbioportal.org",
        "agent_9ZXhcwLIsROBQX0u4JS5F",
        {"haiku": "cBioPortalChat", "sonnet": "cBioPortalChatSonnet"},
        "cbioagent-librechat",
    ),
}


@dataclass(frozen=True)
class Settings:
    api_key: str
    langfuse_host: str
    langfuse_public_key: str
    langfuse_secret_key: str
    judge_model: str
    aws_region: str
    aws_profile: str | None
    chromium_path: str | None
    database_mcp_url: str | None
    database_connector_url: str
    navigator_mcp_url: str
    database_connector: str | None
    kube_context: str | None
    database_mcp_env: str | None = None


def load_settings() -> Settings:
    load_dotenv()
    # Everything written to results/ masks these (and any other secret-looking variable) wherever they appear.
    add_env_secrets()
    settings = Settings(
        api_key=os.environ.get("LIBRECHAT_API_KEY", ""),
        langfuse_host=os.environ.get("LANGFUSE_HOST", "https://us.cloud.langfuse.com"),
        langfuse_public_key=os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
        langfuse_secret_key=os.environ.get("LANGFUSE_SECRET_KEY", ""),
        judge_model=os.environ.get("JUDGE_MODEL", MODELS["sonnet-4.6"].bedrock_id),
        aws_region=os.environ.get("AWS_REGION", "us-east-1"),
        aws_profile=os.environ.get("AWS_PROFILE") or None,
        chromium_path=os.environ.get("CHROMIUM_PATH") or None,
        database_mcp_url=os.environ.get("DATABASE_MCP_URL") or None,
        database_connector_url=os.environ.get("DATABASE_CONNECTOR_URL", "https://mcp.cbioportal.org/db/mcp"),
        navigator_mcp_url=os.environ.get("NAVIGATOR_MCP_URL", "https://mcp.cbioportal.org/navigator/mcp"),
        database_connector=os.environ.get("CLAUDE_AI_DATABASE_CONNECTOR") or None,
        kube_context=os.environ.get("KUBE_CONTEXT") or None,
        # What a DATABASE_MCP_URL that can't be told apart by its host (a port-forward, a local image) serves.
        database_mcp_env=(os.environ.get("DATABASE_MCP_ENV") or "").strip().lower() or None,
    )
    for value in (settings.api_key, settings.langfuse_secret_key, settings.langfuse_public_key):
        add_secret(value)
    return settings
