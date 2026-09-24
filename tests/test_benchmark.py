import json

import pytest

from cbioportal_mcp_qa import report as report_mod
from cbioportal_mcp_qa import run as run_mod
from cbioportal_mcp_qa.dataset import Question, load_questions, parse_selection
from cbioportal_mcp_qa.grade import StudyValidator, cbio_links, describe_link, invalid_studies, number_match
from cbioportal_mcp_qa.report import record_cost, summarize, write_report
from cbioportal_mcp_qa.run import Run
from cbioportal_mcp_qa.traces import _tool_calls


class OfflineStudies(StudyValidator):
    def __init__(self, known: set[str]):
        self.known = known

    def exists(self, study_id: str) -> bool:
        return study_id in self.known


def q(**overrides) -> Question:
    base = dict(
        id=1, category="Cohort & clinical counts", study="msk_chord_2024", question="How many patients?"
    )
    return Question(**{**base, **overrides})


def test_repo_questions_load_with_unique_ids():
    questions = load_questions()
    assert len(questions) >= 69
    assert len({x.id for x in questions}) == len(questions)


def test_parse_selection():
    questions = [q(id=i) for i in range(1, 11)]
    assert [x.id for x in parse_selection("1-3,7", questions)] == [1, 2, 3, 7]
    assert parse_selection(None, questions) == questions


@pytest.mark.parametrize(
    ("expected", "answer", "result"),
    [
        ("7", "There are 7 glioblastoma studies.", True),
        ("25,040", "MSK-CHORD has 25040 patients", True),
        ("5.1%", "about 5.05% of profiled samples", True),
        ("548", "cBioPortal hosts 550 studies", False),
        ("7", "There are 8 studies.", False),
        ("TP53, KRAS", "TP53", None),
        ("26 patients (5.1%)", "26", None),
    ],
)
def test_number_match(expected, answer, result):
    assert number_match(expected, answer) is result


def test_links_flag_unknown_studies():
    answer = (
        "See https://www.cbioportal.org/study/summary?id=msk_chord_2024,made_up_study "
        "and https://www.cbioportal.org/results/oncoprint?cancer_study_list=luad_tcga and https://example.org"
    )
    links = cbio_links(answer)
    assert len(links) == 2
    assert invalid_studies(links, OfflineStudies({"msk_chord_2024", "luad_tcga"})) == ["made_up_study"]


def test_repo_questions_have_valid_tracks_and_categories():
    from cbioportal_mcp_qa.dataset import CATEGORIES, TRACKS

    questions = load_questions()
    assert {q.track for q in questions} <= set(TRACKS)
    assert {q.category for q in questions} <= set(CATEGORIES)


def test_tool_calls_parse_errors_from_tool_batch():
    obs = {
        "output": {
            "messages": [
                {
                    "id": ["langchain_core", "messages", "ToolMessage"],
                    "kwargs": {
                        "name": "navigate_to_results_view_mcp_cbioportal-navigator",
                        "status": "error",
                        "content": "Error: Received tool input did not match expected schema",
                    },
                },
                {
                    "id": ["langchain_core", "messages", "ToolMessage"],
                    "kwargs": {
                        "name": "clickhouse_run_select_query_mcp_cbioportal-database",
                        "status": "success",
                        "content": '{"rows": []}',
                    },
                },
                {"id": ["langchain_core", "messages", "AIMessage"], "kwargs": {}},
            ]
        }
    }
    calls = _tool_calls(obs)
    assert [(c.name, c.ok) for c in calls] == [
        ("navigate_to_results_view", False),
        ("clickhouse_run_select_query", True),
    ]
    assert "expected schema" in calls[0].error


def _record(
    qid, model, passed, answer="42", status=200, cache=True, tool_ok=True, declined=False, track="data"
):
    reply = {
        "answer": answer,
        "response_id": f"chatcmpl-{qid}-{model}",
        "status": status,
        "error": None if status == 200 else "boom",
        "latency_s": 30.0 + qid,
        "started_at": 0.0,
        "prompt_tokens": 100_000,
        "completion_tokens": 1_000,
        "cache_read_tokens": 80_000 if cache else None,
        "cache_write_tokens": 10_000 if cache else None,
    }
    rec = {
        "question": {
            "id": qid,
            "category": "Cohort & clinical counts",
            "track": track,
            "study": "msk_chord_2024",
            "question": f"Q{qid}?",
            "expected_answer": "42",
            "expected_links": [],
            "notes": "",
            "checked": None,
            "source": "curated",
        },
        "model": model,
        "repeat": 1,
        "reply": reply,
        "trace": {
            "trace_id": "t",
            "url": "https://example/t",
            "llm_calls": 3,
            "models": [],
            "tool_calls": [
                {
                    "name": "clickhouse_run_select_query",
                    "ok": tool_ok,
                    "error": None if tool_ok else "did not match expected schema",
                }
            ],
        },
    }
    if status != 200:
        rec.pop("trace")
    if passed is not None:
        rec["grade"] = {
            "passed": passed,
            "declined": declined,
            "rationale": "because",
            "number_match": True,
            "links": [],
            "invalid_studies": [],
            "judge_input_tokens": 500,
            "judge_output_tokens": 50,
        }
    return rec


@pytest.fixture
def fake_run(tmp_path, monkeypatch):
    monkeypatch.setattr(run_mod, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(report_mod, "RESULTS_DIR", tmp_path)
    bench = Run.create(
        "beta", ["haiku", "sonnet"], 1, "us.anthropic.claude-sonnet-4-6", "input/questions.yaml"
    )
    records = [
        _record(1, "haiku", True),
        _record(1, "sonnet", True),
        _record(2, "haiku", False, tool_ok=False, track="navigation"),
        _record(2, "sonnet", False, declined=True, track="navigation"),
        _record(3, "haiku", None, status=500),
        _record(3, "sonnet", None, cache=False),
    ]
    for rec in records:
        bench.records[run_mod.record_key(rec["question"]["id"], rec["model"], 1)] = rec
    bench.save()
    return bench


def test_record_cost_uses_cache_split():
    cost, complete = record_cost(_record(1, "haiku", True))
    # 10k uncached @1 + 10k write @1.25 + 80k read @0.10 + 1k out @5, per million
    assert complete is True
    assert cost == pytest.approx((10_000 * 1 + 10_000 * 1.25 + 80_000 * 0.10 + 1_000 * 5) / 1e6)


def test_summarize_outcomes_tracks_and_disagreements(fake_run):
    summary = summarize(fake_run)
    haiku, sonnet = summary["models"]
    assert haiku.outcomes == {"pass": 1, "fail": 1, "error": 1}
    assert haiku.pass_rate == 50.0 and haiku.answers == 2
    assert haiku.schema_errors == 1 and haiku.tool_error_rate == 50.0
    assert haiku.number_disagreements == 1  # number found but judged fail
    assert sonnet.outcomes == {"pass": 1, "declined": 1, "ungraded": 1}
    assert sonnet.precision == 100.0 and sonnet.coverage == 50.0
    assert sonnet.cost_complete is False
    rates = {row["track"]: row["values"] for row in summary["by_track"]}
    assert rates["data"] == {"haiku": 100.0, "sonnet": 100.0}
    assert rates["navigation"] == {"haiku": 0.0, "sonnet": 0.0}


def test_write_report_renders_report_and_index(fake_run):
    out = write_report(fake_run)
    html = out.read_text()
    assert "Haiku 4.5" in html and "Sonnet 5" in html and "Request failed" in html
    assert (out.parent.parent / "index.html").exists()
    headline = json.loads((out.parent / "summary.json").read_text())
    assert headline["models"]["haiku"]["pass_rate"] == 50.0
    assert headline["models"]["sonnet"]["by_track"]["navigation"] == 0.0
    assert headline["models"]["haiku"]["by_category"]["Cohort & clinical counts"] == 50.0


def test_describe_link_decodes_study_view_filter_json():
    url = (
        "https://www.cbioportal.org/study/summary?id=lgg_tcga_pan_can_atlas_2018#filterJson="
        "%7B%22geneFilters%22%3A%5B%7B%22geneQueries%22%3A%5B%5B%7B%22hugoGeneSymbol%22%3A%22IDH1%22%7D%5D%2C"
        "%5B%7B%22hugoGeneSymbol%22%3A%22TP53%22%7D%5D%5D%2C%22molecularProfileIds%22%3A%5B%22"
        "lgg_tcga_pan_can_atlas_2018_mutations%22%5D%7D%5D%7D"
    )
    text = describe_link(url)
    assert "page: /study/summary" in text
    assert "id: lgg_tcga_pan_can_atlas_2018" in text
    assert '"hugoGeneSymbol": "IDH1"' in text and '"hugoGeneSymbol": "TP53"' in text
    assert cbio_links(f"See {url} for details.") == [url]
