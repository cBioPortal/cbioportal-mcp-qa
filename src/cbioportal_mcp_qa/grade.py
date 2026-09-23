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

<question>{question}</question>
<study>{study}</study>
<reference_answer>{expected_answer}</reference_answer>
<expected_links>{expected_links}</expected_links>
<notes>{notes}</notes>
<answer>{answer}</answer>"""

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
    """Checks study ids in links exist on the public portal (cached per run)."""

    def __init__(self):
        self.http = httpx.Client(base_url="https://www.cbioportal.org/api", timeout=30)
        self.cache: dict[str, bool] = {}

    def exists(self, study_id: str) -> bool:
        if study_id not in self.cache:
            try:
                self.cache[study_id] = self.http.get(f"/studies/{study_id}").status_code == 200
            except httpx.HTTPError:
                self.cache[study_id] = True
        return self.cache[study_id]


def invalid_studies(links: list[str], studies: StudyValidator) -> list[str]:
    return sorted({s for url in links for s in study_ids(url) if not studies.exists(s)})


class Judge:
    def __init__(self, model: str, aws_region: str, aws_profile: str | None):
        self.model = model
        self.client = AnthropicBedrock(aws_region=aws_region, aws_profile=aws_profile)

    def grade(self, q: Question, answer: str, studies: StudyValidator) -> Grade:
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
            question=q.question,
            study=q.study,
            expected_answer=q.expected_answer or "(none)",
            expected_links="\n".join(q.expected_links) or "(none)",
            notes=q.notes or "(none)",
            answer=answer,
        )
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
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
