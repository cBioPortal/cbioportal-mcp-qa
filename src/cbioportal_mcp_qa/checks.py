"""Deterministic answer checks that don't need the judge; computed at report time, so older runs get them too."""

import re

# Things a non-technical user should never be shown: the agent's own tools, internal tables, guide URIs,
# SQL, and backend jargon. Links are ignored (study ids in URLs are fine).
INTERNAL_PATTERNS = {
    "tool name": re.compile(
        r"\b(list_studies|list_guides|read_guide|get_study_guide|list_study_guides|get_general_guide|"
        r"search_oncotree|clickhouse_\w+|resolve_and_route|navigate_to_\w+|get_studyviewfilter_options)\b"
    ),
    "internal table": re.compile(
        r"\b(\w+_derived|cancer_study_query_preferences|sample_list_list|clinical_attribute_meta|"
        r"genetic_profile|sample_to_gene_panel\w*|type_of_cancer)\b"
    ),
    "guide uri": re.compile(r"cbioportal://[\w/#-]+"),
    "sql": re.compile(r"```sql|\bSELECT\b[^\n]{0,200}\bFROM\b", re.IGNORECASE),
    "backend jargon": re.compile(r"\b(ClickHouse|MCP)\b"),
}
URL = re.compile(r"https?://\S+")


def internal_leaks(answer: str) -> list[str]:
    """What the answer exposes about the agent's internals, e.g. ["tool name: list_studies"]."""
    text = URL.sub("", answer or "")
    found = []
    for label, pattern in INTERNAL_PATTERNS.items():
        hits = sorted({m.group(0).strip("`") for m in pattern.finditer(text)})
        if hits and label == "sql":
            found.append("sql query")
        elif hits:
            shown = ", ".join(h if len(h) <= 40 else h[:37] + "…" for h in hits[:3])
            found.append(f"{label}: {shown}{' …' if len(hits) > 3 else ''}")
    return found
