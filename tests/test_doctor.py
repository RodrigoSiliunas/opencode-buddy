from unittest.mock import patch

from opencode_buddy.doctor import ToolCheck, check_path, format_report, run_doctor


def test_check_path_found():
    with patch("opencode_buddy.doctor.shutil.which", return_value="/usr/bin/foo"):
        result = check_path("foo", "install foo")
    assert result.found is True
    assert result.path == "/usr/bin/foo"
    assert result.name == "foo"


def test_check_path_missing():
    with patch("opencode_buddy.doctor.shutil.which", return_value=None):
        result = check_path("foo", "install foo")
    assert result.found is False
    assert result.path is None
    assert result.install_hint == "install foo"


def test_run_doctor_returns_three_checks():
    results = run_doctor()
    names = {r.name for r in results}
    assert names == {"opencode", "litellm", "node"}


def test_format_report_all_ok():
    results = [
        ToolCheck("opencode", True, "/bin/opencode", "x"),
        ToolCheck("litellm", True, "/bin/litellm", "x"),
        ToolCheck("node", True, "/bin/node", "x"),
    ]
    out = format_report(results)
    assert "Tudo pronto" in out
    assert "MISS" not in out


def test_format_report_some_missing():
    results = [
        ToolCheck("opencode", False, None, "npm i -g opencode-ai"),
        ToolCheck("litellm", True, "/bin/litellm", "x"),
        ToolCheck("node", False, None, "https://nodejs.org/"),
    ]
    out = format_report(results)
    assert "MISS" in out
    assert "npm i -g opencode-ai" in out
    assert "2 ferramenta(s) faltando" in out
