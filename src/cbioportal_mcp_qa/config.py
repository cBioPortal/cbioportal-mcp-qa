import os
from dataclasses import dataclass

from dotenv import load_dotenv


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
    key: str
    label: str
    bedrock_id: str
    price: Price


MODELS = {
    "haiku": Model(
        "haiku",
        "Haiku 4.5",
        "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        Price(1.0, 5.0, 1.25, 0.10),
    ),
    "sonnet": Model("sonnet", "Sonnet 5", "us.anthropic.claude-sonnet-5", Price(2.0, 10.0, 2.5, 0.20)),
    "sonnet-4.6": Model(
        "sonnet-4.6",
        "Sonnet 4.6",
        "us.anthropic.claude-sonnet-4-6",
        Price(3.0, 15.0, 3.75, 0.30),
    ),
}
PRICES_BY_BEDROCK_ID = {m.bedrock_id: m.price for m in MODELS.values()}


@dataclass(frozen=True)
class Target:
    """A deployed LibreChat instance and the modelSpec that selects each model."""

    name: str
    url: str
    agent_id: str
    specs: dict[str, str]


TARGETS = {
    "beta": Target(
        "beta",
        "https://beta.chat.cbioportal.org",
        "agent_OHVSJI9Gd6gwsDnFSL-Xl",
        {"haiku": "cBioPortalChatBeta", "sonnet": "cBioPortalChatBetaSonnet"},
    ),
    "prod": Target(
        "prod",
        "https://chat.cbioportal.org",
        "agent_9ZXhcwLIsROBQX0u4JS5F",
        {"haiku": "cBioPortalChat", "sonnet": "cBioPortalChatSonnet"},
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


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        api_key=os.environ.get("LIBRECHAT_API_KEY", ""),
        langfuse_host=os.environ.get("LANGFUSE_HOST", "https://us.cloud.langfuse.com"),
        langfuse_public_key=os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
        langfuse_secret_key=os.environ.get("LANGFUSE_SECRET_KEY", ""),
        judge_model=os.environ.get("JUDGE_MODEL", MODELS["sonnet-4.6"].bedrock_id),
        aws_region=os.environ.get("AWS_REGION", "us-east-1"),
        aws_profile=os.environ.get("AWS_PROFILE") or None,
    )
