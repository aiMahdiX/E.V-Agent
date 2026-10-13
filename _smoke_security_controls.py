"""Offline checks for permission controls and channel-specific sudo prompts."""
from __future__ import annotations

import contextlib
import io
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from core.settings import SettingsStore
from security.approval import Approval
from security.permissions import PermissionDenied, PermissionEngine
from tools import shell
from ui.cli.repl import CLI


def test_live_permission_threshold_and_cli() -> None:
    config = {"security": {"auto_approve_until_level": 0,
                           "sudo_via_pkexec": True}}
    engine = PermissionEngine(config=config, approval=Approval(confirm=False))
    try:
        engine.authorize("test_action", level_override=1)
    except PermissionDenied:
        pass
    else:
        raise AssertionError("level above current threshold was auto-approved")

    with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}):
        store = SettingsStore(config, Path(temp) / ".env")
        cli = CLI(object(), config, on_settings=store.snapshot,
                  on_settings_update=store.update_config)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            assert cli._dispatch_slash("/permission set 1")
        assert engine.auto_approve_until == 1
        assert "applies immediately" in output.getvalue()

    config["security"]["auto_approve_until_level"] = 4
    try:
        engine.authorize("test_action", level_override=3)
    except PermissionDenied:
        pass
    else:
        raise AssertionError("Level 3 must still require explicit approval")

    with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}):
        store = SettingsStore(config, Path(temp) / ".env")
        for invalid in (-1, 5, True):
            try:
                store.update_config({
                    "security.auto_approve_until_level": invalid,
                })
            except ValueError:
                pass
            else:
                raise AssertionError(f"invalid permission threshold accepted: {invalid}")


def test_terminal_sudo_uses_hidden_password_prompt() -> None:
    calls = []

    def fake_execute(command, timeout, **kwargs):
        calls.append((command, timeout, kwargs))
        return subprocess.CompletedProcess(command, 0, "root\n", "")

    with (patch("tools.shell.sudo_should_ask_gui", return_value=False),
          patch("tools.shell.announce_sudo"),
          patch("getpass.getpass", return_value="test-password") as password,
          patch("tools.shell._execute", side_effect=fake_execute)):
        result = shell.run_command("sudo whoami")

    password.assert_called_once_with("Enter sudo password: ")
    assert calls[0][0] == "sudo -S whoami"
    assert calls[0][2]["input"] == "test-password\n"
    assert result["executor"] == "sudo -S"
    assert result["stdout"] == "root\n"


def test_hud_sudo_uses_pkexec_and_blocks_without_polkit() -> None:
    previous = shell._sudo_via_pkexec
    config = {"security": {"sudo_via_pkexec": True}}
    shell.set_sudo_via_pkexec(config)
    calls = []

    def fake_execute(command, timeout, **kwargs):
        calls.append((command, timeout, kwargs))
        return subprocess.CompletedProcess(command, 0, "root\n", "")

    try:
        with (patch("tools.shell.sudo_should_ask_gui", return_value=True),
              patch("tools.shell.announce_sudo"),
              patch("tools.shell.shutil.which", return_value="/usr/bin/pkexec"),
              patch("tools.shell._execute", side_effect=fake_execute)):
            result = shell.run_command("sudo whoami")
        assert calls[0][0] == "pkexec whoami"
        assert "input" not in calls[0][2]
        assert result["executor"] == "pkexec"

        calls.clear()
        config["security"]["sudo_via_pkexec"] = False
        with (patch("tools.shell.sudo_should_ask_gui", return_value=True),
              patch("tools.shell.announce_sudo"),
              patch("tools.shell.shutil.which", return_value=None),
              patch("tools.shell._execute", side_effect=fake_execute)):
            blocked = shell.run_command("sudo whoami")
        assert blocked["executor"] == "blocked-web-no-polkit"
        assert not calls
    finally:
        shell.set_sudo_via_pkexec(previous)


def main() -> int:
    test_live_permission_threshold_and_cli()
    test_terminal_sudo_uses_hidden_password_prompt()
    test_hud_sudo_uses_pkexec_and_blocks_without_polkit()
    print("live permission settings and terminal/HUD sudo prompts: ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())