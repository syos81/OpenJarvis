"""Tests for the CLI skeleton."""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

import openjarvis
from openjarvis.cli import cli, main


class TestMainEntryPoint:
    """Tests for the ``jarvis`` console script entry point."""

    def test_windows_reconfigures_stdout_to_utf8(self) -> None:
        """On Windows, main() must reconfigure stdout/stderr to UTF-8 so that
        CJK characters in CLI output don't trigger UnicodeEncodeError under
        legacy code pages (cp950, cp932, cp949)."""
        stdout_mock = mock.MagicMock(spec=io.TextIOWrapper)
        stderr_mock = mock.MagicMock(spec=io.TextIOWrapper)
        with (
            mock.patch.object(sys, "platform", "win32"),
            mock.patch.object(sys, "stdout", stdout_mock),
            mock.patch.object(sys, "stderr", stderr_mock),
            mock.patch("openjarvis.cli.cli") as cli_mock,
        ):
            main()
        stdout_mock.reconfigure.assert_called_once_with(
            encoding="utf-8", errors="replace"
        )
        stderr_mock.reconfigure.assert_called_once_with(
            encoding="utf-8", errors="replace"
        )
        cli_mock.assert_called_once()

    def test_non_windows_does_not_reconfigure(self) -> None:
        """On non-Windows platforms, stdout/stderr are left untouched."""
        stdout_mock = mock.MagicMock(spec=io.TextIOWrapper)
        with (
            mock.patch.object(sys, "platform", "linux"),
            mock.patch.object(sys, "stdout", stdout_mock),
            mock.patch("openjarvis.cli.cli") as cli_mock,
        ):
            main()
        stdout_mock.reconfigure.assert_not_called()
        cli_mock.assert_called_once()


class TestCLI:
    def test_help(self) -> None:
        result = CliRunner().invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "OpenJarvis" in result.output

    def test_version(self) -> None:
        result = CliRunner().invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert openjarvis.__version__ in result.output

    def test_ask_requires_query(self) -> None:
        result = CliRunner().invoke(cli, ["ask"])
        assert result.exit_code != 0

    def test_serve_survives_a_missing_engine(self, tmp_path, monkeypatch) -> None:
        """A missing engine degrades inference — it does not stop the server.

        The server also carries capabilities that need no model at all, so
        exiting here would take those down with it. Detailed coverage lives in
        ``test_serve_without_engine.py``; this asserts the CLI-level contract.

        ``uvicorn.run`` is stubbed and ``OPENJARVIS_HOME`` redirected on
        purpose: the previous version of this test invoked the real ``serve``
        with neither, so on a host that *did* have a working engine it would
        have bound a real port and never returned.
        """
        import importlib

        import uvicorn

        serve_mod = importlib.import_module("openjarvis.cli.serve")
        heim = tmp_path / "openjarvis-home"
        heim.mkdir()
        (heim / "config.toml").write_text(
            "[telemetry]\nenabled = false\n"
            "[agent_manager]\nenabled = false\n"
            "[channel]\nenabled = false\n"
            "[sessions]\nenabled = false\n"
            "[traces]\nenabled = false\n"
            "[memory]\nenabled = false\n"
            "[agent]\ncontext_from_memory = false\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("OPENJARVIS_HOME", str(heim))
        monkeypatch.setattr(serve_mod, "get_engine", lambda *a, **k: None)
        monkeypatch.setattr(serve_mod, "discover_engines", lambda cfg: [])
        monkeypatch.setattr(serve_mod, "discover_models", lambda engines: {})
        gestartet: list = []
        monkeypatch.setattr(uvicorn, "run", lambda app, **kw: gestartet.append(app))

        result = CliRunner().invoke(cli, ["serve"])

        out = result.output.lower()
        if "not installed" in out:  # server extra absent — nothing to assert
            return
        assert result.exit_code == 0, result.output
        assert "no inference engine" in out
        assert gestartet, "der Server haette starten muessen"

    def test_model_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["model", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "info" in result.output
        assert "pull" in result.output

    def test_memory_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["memory", "--help"])
        assert result.exit_code == 0
        assert "index" in result.output
        assert "search" in result.output
        assert "stats" in result.output

    def test_mine_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["mine", "--help"])
        assert result.exit_code == 0
        assert "doctor" in result.output
        assert "start" in result.output
        assert "stop" in result.output

    def test_telemetry_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["telemetry", "--help"])
        assert result.exit_code == 0
        assert "stats" in result.output
        assert "export" in result.output
        assert "clear" in result.output

    def test_bench_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["bench", "--help"])
        assert result.exit_code == 0
        assert "run" in result.output

    def test_scheduler_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["scheduler", "--help"])
        assert result.exit_code == 0
        assert "create" in result.output
        assert "list" in result.output
        assert "pause" in result.output
        assert "resume" in result.output
        assert "cancel" in result.output

    def test_channel_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["channel", "--help"])
        assert result.exit_code == 0
        assert "send" in result.output
        assert "list" in result.output

    def test_init_creates_config(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".openjarvis"
        config_path = config_dir / "config.toml"
        with (
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_DIR", config_dir),
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path),
            mock.patch("openjarvis.cli.init_cmd.PrivacyScanner"),
        ):
            result = CliRunner().invoke(
                cli, ["init", "--engine", "ollama", "--no-download"]
            )
        assert result.exit_code == 0
        assert config_path.exists()
        content = config_path.read_text()
        assert "[engine]" in content


class TestStartupResilience:
    """Importing the CLI must not force heavy/native deps (#404, #309).

    A broken or slow numpy on Windows otherwise raises at import time and takes
    down every `jarvis` command — including `jarvis serve` — because the CLI
    eagerly pulls the deep-research command chain (-> embeddings -> numpy).
    """

    def test_importing_cli_does_not_import_numpy(self) -> None:
        # Run in a fresh subprocess: the pytest session itself almost certainly
        # has numpy loaded from other tests, so an in-process check is useless.
        code = (
            "import openjarvis.cli, sys; "
            "leaked=[m for m in sys.modules if m=='numpy' or m.startswith('numpy.')]; "
            "assert not leaked, leaked; "
            "print('numpy-free')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True
        )
        assert result.returncode == 0, (
            "importing openjarvis.cli pulled in numpy (a broken numpy would then "
            f"crash `jarvis serve`):\nstdout={result.stdout}\nstderr={result.stderr}"
        )
