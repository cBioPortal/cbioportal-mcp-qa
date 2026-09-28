import pytest

from cbioportal_mcp_qa import compare as compare_mod
from cbioportal_mcp_qa import report as report_mod
from cbioportal_mcp_qa import run as run_mod


@pytest.fixture
def results_dir(tmp_path, monkeypatch):
    """A temporary results/ directory for everything that reads or writes runs."""
    for mod in (run_mod, report_mod, compare_mod):
        monkeypatch.setattr(mod, "RESULTS_DIR", tmp_path)
    return tmp_path
