"""Управление автозапуском с правами администратора через Планировщик заданий Windows."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple
from xml.sax.saxutils import escape

from core.elevation import ElevationHelper

TASK_NAME = "DNS Switcher AI+"


def _schtasks_path() -> str:
    return str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "schtasks.exe")


def _no_window_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _current_user() -> str:
    user = os.environ.get("USERNAME", "").strip()
    domain = os.environ.get("USERDOMAIN", "").strip()
    if domain and user:
        return f"{domain}\\{user}"
    return user


def autostart_target() -> Tuple[str, str, str]:
    """Returns (executable, arguments, working_directory) for launching minimized at logon."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        return str(exe), "--minimized", str(exe.parent)
    exe = Path(sys.executable).resolve()
    main_py = Path(__file__).resolve().parents[1] / "main.py"
    return str(exe), f'"{main_py}" --minimized', str(main_py.parent.parent)


def build_task_xml(command: str, arguments: str, working_dir: str, user_id: Optional[str] = None) -> str:
    """Builds Windows Task Scheduler XML for elevated interactive logon without AC/battery or 72h limits."""
    uid = user_id if user_id is not None else _current_user()
    user_block = f"\n      <UserId>{escape(uid)}</UserId>" if uid else ""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.3" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Автозапуск DNS Switcher AI+ с правами администратора (свёрнуто в трей)</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>{user_block}
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">{user_block}
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <DisallowStartOnRemoteAppSession>false</DisallowStartOnRemoteAppSession>
    <UseUnifiedSchedulingEngine>true</UseUnifiedSchedulingEngine>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(command)}</Command>
      <Arguments>{escape(arguments)}</Arguments>
      <WorkingDirectory>{escape(working_dir)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def is_autostart_enabled() -> bool:
    """Checks whether the elevated scheduled task exists."""
    if os.name != "nt":
        return False
    try:
        res = subprocess.run(
            [_schtasks_path(), "/Query", "/TN", TASK_NAME],
            capture_output=True,
            check=False,
            timeout=5,
            creationflags=_no_window_flags(),
        )
        return res.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def set_autostart(enabled: bool) -> bool:
    """Creates or deletes the elevated logon scheduled task."""
    if os.name != "nt":
        raise OSError("Автозапуск поддерживается только в Windows.")

    schtasks = _schtasks_path()
    if not enabled:
        if ElevationHelper.is_admin():
            res = subprocess.run(
                [schtasks, "/Delete", "/TN", TASK_NAME, "/F"],
                capture_output=True,
                text=True,
                check=False,
                timeout=8,
                creationflags=_no_window_flags(),
            )
            if res.returncode != 0 and is_autostart_enabled():
                err = (res.stderr or res.stdout or "").strip() or f"Код {res.returncode}"
                raise OSError(f"Не удалось удалить задачу автозапуска: {err}")
            return True

        script = (
            f"& {_ps_quote(schtasks)} /Delete /TN {_ps_quote(TASK_NAME)} /F *> $null; "
            f"& {_ps_quote(schtasks)} /Query /TN {_ps_quote(TASK_NAME)} *> $null; "
            "if ($LASTEXITCODE -eq 0) { exit 1 } else { exit 0 }"
        )
        if not ElevationHelper.run_elevated_powershell(script):
            raise PermissionError("Требуются права администратора для отключения автозапуска.")
        return True

    cmd, args, workdir = autostart_target()
    xml_content = build_task_xml(cmd, args, workdir)
    fd, tmp_xml = tempfile.mkstemp(prefix="dns_sw_task_", suffix=".xml")
    os.close(fd)
    try:
        Path(tmp_xml).write_bytes(xml_content.encode("utf-16"))
        if ElevationHelper.is_admin():
            res = subprocess.run(
                [schtasks, "/Create", "/TN", TASK_NAME, "/XML", tmp_xml, "/F"],
                capture_output=True,
                text=True,
                check=False,
                timeout=8,
                creationflags=_no_window_flags(),
            )
            if res.returncode != 0:
                err = (res.stderr or res.stdout or "").strip() or f"Код {res.returncode}"
                raise OSError(f"Не удалось создать задачу автозапуска: {err}")
            return True

        script = (
            f"& {_ps_quote(schtasks)} /Create /TN {_ps_quote(TASK_NAME)} "
            f"/XML {_ps_quote(tmp_xml)} /F *> $null; exit $LASTEXITCODE"
        )
        if not ElevationHelper.run_elevated_powershell(script):
            raise PermissionError("Требуются права администратора для настройки автозапуска.")
        return True
    finally:
        if os.path.exists(tmp_xml):
            try:
                os.unlink(tmp_xml)
            except OSError:
                pass
