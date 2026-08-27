"""Capture-only command configuration tests."""

from boss_zhipin import capture_cli
from boss_zhipin.capture_cli import build_parser


def test_capture_parser_defaults():
    args = build_parser().parse_args([])
    assert args.limit == 30
    assert args.label is None
    assert args.database is None


def test_capture_parser_accepts_explicit_values(tmp_path):
    database = tmp_path / "jobs.db"
    args = build_parser().parse_args(
        ["--limit", "8", "--label", "AI 产品", "--database", str(database)]
    )
    assert args.limit == 8
    assert args.label == "AI 产品"
    assert args.database == database


def test_main_reports_login_timeout_without_traceback(monkeypatch):
    class FakeLoop:
        def run_until_complete(self, coroutine):
            coroutine.close()
            raise TimeoutError("login timed out")

    monkeypatch.setattr(capture_cli.uc, "loop", lambda: FakeLoop())
    assert capture_cli.main(["--limit", "1"]) == 1
