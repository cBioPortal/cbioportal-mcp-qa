"""Benchmarks stay off production unless asked: prod needs --allow-prod, and a beta target needs beta's MCP."""

from click.testing import CliRunner

from cbioportal_mcp_qa import cli


def test_ask_on_prod_needs_allow_prod():
    out = CliRunner().invoke(cli.cli, ["ask", "q?", "--target", "prod"])
    assert out.exit_code == 2
    assert "--allow-prod" in out.output


def test_run_on_prod_needs_allow_prod():
    out = CliRunner().invoke(cli.cli, ["run", "--target", "prod", "--no-grade"])
    assert out.exit_code == 2
    assert "--allow-prod" in out.output


def test_beta_needs_no_flag():
    cli._check_target_allowed("beta", False)
    cli._check_target_allowed("prod", True)


def test_require_beta_mcp_is_the_default():
    ask = cli.cli.commands["ask"]
    opt = next(p for p in ask.params if p.name == "require_beta_mcp")
    assert opt.default is True
