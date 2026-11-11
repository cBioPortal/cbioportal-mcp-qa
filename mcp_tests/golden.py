"""Absolute assertions on MCP data, independent of the released server."""


def records(content: list) -> list[dict]:
    """Accept compact tables, legacy rows, and SDK text blocks containing either."""
    out = []
    for item in content:
        if isinstance(item, list):
            out.extend(records(item))
        elif isinstance(item, dict):
            if "rows" in item:
                rows = item["rows"]
                if "columns" in item:
                    rows = [dict(zip(item["columns"], row, strict=True)) for row in rows]
                out.extend(rows)
            else:
                out.append(item)
    return out


def _contains(value, expected) -> bool:
    if isinstance(value, list):
        return any(_contains(v, expected) for v in value)
    if isinstance(value, dict):
        if all(value.get(k) == v for k, v in expected.items()):
            return True
        return any(_contains(v, expected) for v in value.values())
    return False


def assert_golden(content: list, spec: dict) -> None:
    # Fail closed on typos in the call file.
    assert spec and not spec.keys() - {"contains", "min_rows", "max_rows", "kind"}, spec
    rows = records(content)
    if "contains" in spec:
        assert _contains(content, spec["contains"]) or _contains(rows, spec["contains"]), spec
    assert len(rows) >= spec.get("min_rows", 0), f"too few rows: {rows}"
    if "max_rows" in spec:
        assert len(rows) <= spec["max_rows"], f"too many rows: {rows}"
    kind = spec.get("kind")
    assert kind in (None, "frequency", "profiled_counts"), kind
    for row in rows:
        if kind == "frequency":
            altered, profiled = int(row["altered_samples"]), int(row["profiled_samples"])
            assert 0 <= altered <= profiled
            pct = row["frequency_pct"]
            if profiled:
                assert pct is not None and 0 <= float(pct) <= 100
                assert abs(float(pct) - 100 * altered / profiled) <= 0.051
            else:
                assert pct is None
        elif kind == "profiled_counts":
            assert 0 <= int(row["patients"]) <= int(row["samples"])
            assert 0 <= int(row["wes_samples"]) <= int(row["samples"])
