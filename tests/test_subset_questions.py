import re
from pathlib import Path

import yaml

from cbioportal_mcp_qa import report as report_mod
from cbioportal_mcp_qa.dataset import load_questions

SUBSET = Path("input/questions-subset.yaml")


def test_subset_questions_load_and_parse():
    questions = load_questions(SUBSET)
    assert 20 <= len(questions) <= 30
    assert all(q.id >= 2001 for q in questions)
    assert all(q.has_reference and q.expected_answer and q.checked for q in questions)
    # Ids are stable across the sets: none reused from the main or multi-turn files.
    other = {
        q.id
        for f in ("input/questions.yaml", "input/questions-multiturn.yaml")
        for q in load_questions(Path(f))
    }
    assert not other & {q.id for q in questions}
    assert sum(bool(q.history) for q in questions) >= 2


def test_subset_questions_name_their_reference_sql():
    for raw in yaml.safe_load(SUBSET.read_text()):
        assert "Subtype:" in raw["notes"], raw["id"]
        sql = Path(raw["sql"])
        assert sql == Path(f"input/subset-sql/{raw['id']}.sql")
        text = sql.read_text()
        assert text.startswith(f"-- Q{raw['id']}:")
        # Read-only: every statement is a SELECT, possibly with a WITH clause.
        code = re.sub(r"--[^\n]*", "", text)
        statements = [s.strip() for s in code.split(";") if s.strip()]
        assert statements and all(re.match(r"(WITH|SELECT)\b", s) for s in statements), raw["id"]


def test_subset_set_is_listed_as_its_own_test_set():
    info = report_mod.question_set_info(str(SUBSET))
    assert info["title"] == "Subset questions" and info["n_questions"] == len(info["questions"])
    assert sum(n for _, n in info["categories"]) == info["n_questions"]
