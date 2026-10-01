import re
from pathlib import Path

import yaml

from cbioportal_mcp_qa import report as report_mod
from cbioportal_mcp_qa.dataset import load_questions

SUBSET = Path("input/questions-subset.yaml")


def test_subset_questions_load_and_parse():
    questions = load_questions(SUBSET)
    assert [q.id for q in questions] == list(range(2001, 2027))
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
        # Every "Must not" names the concrete baseline numbers a wrong cohort or level would give.
        must_not = [line for line in raw["notes"].splitlines() if line.startswith("Must not")]
        assert must_not and all(re.search(r"\d", line) for line in must_not), raw["id"]
        sql = Path(raw["sql"])
        assert sql == Path(f"input/subset-sql/{raw['id']}.sql")
        text = sql.read_text()
        assert text.startswith(f"-- Q{raw['id']}:")
        # Read-only: every statement is a SELECT, possibly with a WITH clause.
        code = re.sub(r"--[^\n]*", "", text)
        statements = [s.strip() for s in code.split(";") if s.strip()]
        assert statements and all(re.match(r"(WITH|SELECT)\b", s) for s in statements), raw["id"]
        # The reference query comes first; any further statement is a labelled baseline for the same question.
        headers = re.findall(r"^-- (Q\d+|Baseline for Q\d+)", text, re.M)
        assert headers[0] == f"Q{raw['id']}" and set(headers[1:]) <= {f"Baseline for Q{raw['id']}"}
        assert len(set(statements)) == len(statements), raw["id"]


def test_subset_set_is_listed_as_its_own_test_set():
    info = report_mod.question_set_info(str(SUBSET))
    assert info["title"] == "Subset questions" and info["n_questions"] == len(info["questions"])
    assert sum(n for _, n in info["categories"]) == info["n_questions"]
