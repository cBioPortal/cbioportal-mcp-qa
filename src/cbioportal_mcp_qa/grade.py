"""Grading: a pass/fail LLM judge against the reference, plus two objective checks."""

import json
import re
from dataclasses import asdict, dataclass, field
from urllib.parse import parse_qs, urlparse

import httpx
from anthropic import AnthropicBedrock

from .dataset import Question, extract_urls

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "passed": {"type": "boolean"},
        "declined": {"type": "boolean"},
        "rationale": {"type": "string"},
    },
    "required": ["passed", "declined", "rationale"],
    "additionalProperties": False,
}

TRACK_CRITERIA = {
    "data": "The answer states the fact in the reference (numbers may be rounded sensibly or phrased differently).",
    "navigation": "The answer gives a cBioPortal link that opens the view the question asks for: right page, study, genes and filters. Explanatory text alone is not enough.",
    "analysis": "The answer uses the right cohort and method, reaches the conclusion in the reference/notes, and does not invent statistics (p-values, medians, hazard ratios) that it could not have computed.",
    "out_of_scope": "The answer clearly says cBioPortal can't answer this (or redirects appropriately) without inventing an answer.",
}

JUDGE_PROMPT = """You grade answers from cBioPortalChat, an assistant that answers questions about cBioPortal cancer genomics data and builds links to cBioPortal pages.

Decide whether the ANSWER passes. It passes when it meets this criterion for a {track} question:
{criterion}
It must also satisfy every "must" / "must not" requirement in the notes. Judge against the reference material, not your own knowledge of cBioPortal. Extra correct context is fine; do not penalize length.

Also report `declined`: true when the answer refuses or says the data isn't available instead of answering (whether or not that is the right call).

Keep the rationale to 1-3 sentences.

When the answer contains cBioPortal links, judge them from the decoded form below, using these conventions:
- study view `filterJson` → `geneFilters[].geneQueries` is a list of lists: the OUTER list is AND, each INNER list is OR. `[[IDH1],[TP53]]` means IDH1 AND TP53; `[[IDH1, TP53]]` means IDH1 OR TP53.
- Values listed for one clinical attribute (`clinicalDataFilters[].values`) are OR; different filters in the same filterJson are AND.
- For navigation answers the links were also opened in a browser: "what the page shows when opened" is the page's visible text (study name, filter pills such as "IDH1 and TP53", query summary, sample counts, error messages). Trust it over your reading of the URL.
- If opening a page failed or timed out, that is a problem with the grader's browser, not evidence the link is wrong: judge that link from its decoded URL.
- `id` / `cancer_study_list` / `studyId` carry the study ids (comma-separated for several studies); `gene_list` the genes; the path picks the page (`/study/summary`, `/results/oncoprint`, `/results/plots`, `/comparison`, `/patient`).

{conversation}<question>{question}</question>
<study>{study}</study>
<reference_answer>{expected_answer}</reference_answer>
<expected_links>{expected_links}</expected_links>
<notes>{notes}</notes>
<answer>{answer}</answer>
<decoded_answer_links>{decoded_links}</decoded_answer_links>"""

NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*")
BARE_NUMBER_RE = re.compile(r"^~?\s*-?\d[\d,]*\.?\d*\s*%?$")
STUDY_PARAMS = ("id", "studyId", "cancer_study_id", "cancer_study_list", "studyIds")


@dataclass
class Grade:
    passed: bool | None
    declined: bool
    rationale: str
    number_match: bool | None
    links: list[str] = field(default_factory=list)
    invalid_studies: list[str] = field(default_factory=list)
    judge_input_tokens: int = 0
    judge_output_tokens: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _to_float(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def number_match(expected: str, answer: str, rel_tol: float = 0.01, abs_tol: float = 0.1) -> bool | None:
    """Whether the answer contains the reference number (within rounding). None unless the reference is a bare number."""
    expected = expected.strip()
    if not BARE_NUMBER_RE.match(expected):
        return None
    raw_target = NUMBER_RE.search(expected).group()
    target = _to_float(raw_target)
    if target is None:
        return None
    values = [v for v in (_to_float(raw) for raw in NUMBER_RE.findall(answer or "")) if v is not None]
    is_count = "." not in raw_target and not expected.endswith("%")
    tol = 0.0 if is_count else max(abs_tol, rel_tol * abs(target))
    return any(abs(v - target) <= tol for v in values)


def describe_link(url: str) -> str:
    """A cBioPortal URL as page, query parameters and pretty-printed filterJson, for the judge."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query) | parse_qs(parsed.fragment)
    lines = [f"page: {parsed.path or '/'}"]
    for key, values in params.items():
        value = values[0]
        if key == "filterJson":
            try:
                value = json.dumps(json.loads(value), indent=1)
            except ValueError:
                pass
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


def rendered_text(render: dict | None) -> str:
    if not render:
        return ""
    if not render["ok"]:
        return f"\nopening the page failed: {render['error']}"
    return f"\nwhat the page shows when opened:\n{render['text']}"


def cbio_links(text: str) -> list[str]:
    return [u for u in extract_urls(text) if "cbioportal.org" in urlparse(u).netloc]


def study_ids(url: str) -> set[str]:
    query = parse_qs(urlparse(url).query)
    ids: set[str] = set()
    for key in STUDY_PARAMS:
        for value in query.get(key, []):
            ids.update(v.strip() for v in re.split(r"[,+]", value) if v.strip())
    return ids


class StudyValidator:
    """Checks study ids in links against the public portal's study list, fetched once per run.

    If the list can't be fetched (e.g. the API is down), every id is treated as valid rather than flagged.
    """

    def __init__(
        self, url: str = "https://www.cbioportal.org/api/studies?projection=SUMMARY&pageSize=100000"
    ):
        self.url = url
        self._known: set[str] | None = None
        self._loaded = False

    def _load(self) -> None:
        self._loaded = True
        try:
            resp = httpx.get(self.url, timeout=60)
            resp.raise_for_status()
            self._known = {s["studyId"] for s in resp.json()} or None
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            self._known = None

    def exists(self, study_id: str) -> bool:
        if not self._loaded:
            self._load()
        return self._known is None or study_id in self._known


def invalid_studies(links: list[str], studies: StudyValidator) -> list[str]:
    return sorted({s for url in links for s in study_ids(url) if not studies.exists(s)})


class Judge:
    def __init__(self, model: str, aws_region: str, aws_profile: str | None):
        self.model = model
        self.client = AnthropicBedrock(aws_region=aws_region, aws_profile=aws_profile)

    def grade(
        self, q: Question, answer: str, studies: StudyValidator, renders: dict[str, dict] | None = None
    ) -> Grade:
        links = cbio_links(answer)
        base = dict(
            number_match=number_match(q.expected_answer, answer) if q.expected_answer else None,
            links=links,
            invalid_studies=invalid_studies(links, studies),
        )
        if not answer.strip():
            return Grade(passed=False, declined=False, rationale="Empty answer.", **base)
        if not q.has_reference:
            return Grade(passed=None, declined=False, rationale="No reference for this question.", **base)
        prompt = JUDGE_PROMPT.format(
            track=q.track.replace("_", " "),
            criterion=TRACK_CRITERIA[q.track],
            conversation=(
                "The QUESTION is a follow-up; judge the ANSWER as the reply to it in this conversation:\n<conversation_so_far>\n"
                + "\n".join(f"<{t['role']}>{t['content']}</{t['role']}>" for t in q.history)
                + "\n</conversation_so_far>\n"
                if q.history
                else ""
            ),
            question=q.question,
            study=q.study,
            expected_answer=q.expected_answer or "(none)",
            expected_links="\n".join(q.expected_links) or "(none)",
            notes=q.notes or "(none)",
            answer=answer,
            decoded_links="\n\n".join(
                f"{url}\n{describe_link(url)}{rendered_text((renders or {}).get(url))}" for url in links
            )
            or "(none)",
        )
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            extra_body={"temperature": 0},
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": JUDGE_SCHEMA}},
        )
        result = json.loads(next(b.text for b in response.content if b.type == "text"))
        return Grade(
            passed=result["passed"],
            declined=result["declined"],
            rationale=result["rationale"],
            judge_input_tokens=response.usage.input_tokens,
            judge_output_tokens=response.usage.output_tokens,
            **base,
        )
