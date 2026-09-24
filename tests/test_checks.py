from cbioportal_mcp_qa.checks import internal_leaks


def test_flags_tool_advice_to_the_user():
    answer = 'Want to explore a study? Use `list_studies(search="...")` to browse available cohorts.'
    assert internal_leaks(answer) == ["tool name: list_studies"]


def test_flags_tables_sql_guide_uris_and_jargon():
    answer = (
        "I queried `clinical_data_derived` (see cbioportal://clinical-data-guide) in ClickHouse:\n"
        "```sql\nSELECT count() FROM clinical_data_derived\n```"
    )
    assert internal_leaks(answer) == [
        "internal table: clinical_data_derived",
        "guide uri: cbioportal://clinical-data-guide",
        "sql query",
        "backend jargon: ClickHouse",
    ]


def test_plain_answers_and_links_are_fine():
    answer = (
        "TP53 is mutated in 32 of 143 profiled samples (22.4%). "
        "[Open the study](https://www.cbioportal.org/study/summary?id=os_target_gdc&tab=clinicalData)"
    )
    assert internal_leaks(answer) == []
    assert internal_leaks("") == []


def test_technical_questions_are_exempt_from_the_internals_check():
    from cbioportal_mcp_qa.dataset import Question

    assert Question.from_dict({"id": 1, "question": "write python code", "technical": True}).technical
    assert not Question.from_dict({"id": 2, "question": "how many samples?"}).technical
