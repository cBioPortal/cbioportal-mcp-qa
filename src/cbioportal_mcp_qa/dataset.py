import re
from dataclasses import dataclass
from pathlib import Path

import yaml

URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")

DEFAULT_QUESTIONS = Path("input/questions.yaml")
ROLES = ("user", "assistant")
TRACKS = ("data", "navigation", "analysis", "out_of_scope")
CATEGORIES = (
    "Study discovery",
    "Cohort & clinical counts",
    "Alteration frequency",
    "Variants & hotspots",
    "Co-occurrence & exclusivity",
    "Expression & multi-omics",
    "Survival & outcomes",
    "Treatment",
    "Patient & sample lookup",
    "Out of scope",
)


@dataclass(frozen=True)
class Question:
    id: int
    category: str
    study: str
    question: str
    track: str = "data"
    expected_answer: str = ""
    expected_links: tuple[str, ...] = ()
    notes: str = ""
    checked: str | None = None
    source: str = "curated"
    technical: bool = False  # asks for code, schema or how the agent works: technical detail is expected
    # Earlier turns of the conversation, oldest first: ({"role": "user"|"assistant", "content": ...}, ...).
    # The question is the user's next message.
    history: tuple[dict, ...] = ()

    @property
    def has_reference(self) -> bool:
        return bool(self.expected_answer or self.expected_links or "must" in self.notes.lower())

    @classmethod
    def from_dict(cls, d: dict) -> "Question":
        return cls(
            id=int(d["id"]),
            category=d.get("category") or d.get("type") or "",
            study=d.get("study") or "",
            question=d["question"].strip(),
            track=d.get("track") or "data",
            expected_answer=str(d.get("expected_answer") or "").strip(),
            expected_links=tuple(d.get("expected_links") or ()),
            notes=(d.get("notes") or "").strip(),
            checked=str(d["checked"]) if d.get("checked") else None,
            source=d.get("source") or "curated",
            technical=bool(d.get("technical")),
            history=tuple(
                {"role": t["role"], "content": t["content"].strip()} for t in d.get("history") or ()
            ),
        )


def extract_urls(text: str) -> list[str]:
    return [u.rstrip(".,;:") for u in URL_RE.findall(text or "")]


def load_questions(path: Path = DEFAULT_QUESTIONS) -> list[Question]:
    questions = [Question.from_dict(d) for d in yaml.safe_load(path.read_text())]
    ids = [q.id for q in questions]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"Duplicate question ids in {path}: {sorted(duplicates)}")
    bad_tracks = sorted(q.id for q in questions if q.track not in TRACKS)
    if bad_tracks:
        raise ValueError(f"Unknown track for question ids {bad_tracks}; use one of {TRACKS}")
    bad_history = sorted(
        q.id
        for q in questions
        if len(q.history) % 2
        or [t["role"] for t in q.history] != [ROLES[i % 2] for i in range(len(q.history))]
    )
    if bad_history:
        raise ValueError(f"history must alternate user/assistant turns, ending with assistant: {bad_history}")
    bad_categories = sorted(q.id for q in questions if q.category not in CATEGORIES)
    if bad_categories:
        raise ValueError(f"Unknown category for question ids {bad_categories}; use one of {CATEGORIES}")
    return questions


def parse_selection(spec: str | None, questions: list[Question]) -> list[Question]:
    """Select questions by id, e.g. "1-5,8,12-14". None selects all."""
    if not spec:
        return questions
    wanted: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            wanted.update(range(int(lo), int(hi) + 1))
        elif part:
            wanted.add(int(part))
    return [q for q in questions if q.id in wanted]
