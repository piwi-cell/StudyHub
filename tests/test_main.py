"""Start der App (main.py): pro Datenordner nur eine laufende App."""

import importlib.util
import os
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("main", ROOT / "main.py")
main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(main)


def test_second_instance_with_same_data_dir_is_refused(tmp_path):
    first = main.instance_lock(tmp_path / "daten")
    assert first is not None
    assert main.instance_lock(tmp_path / "daten") is None  # zweite App (z. B. installiert und Projektordner)
    assert main.instance_lock(tmp_path / "demo") is not None  # anderer Datenordner (Demo) geht
    first.close()  # App beendet: Sperre frei
    assert main.instance_lock(tmp_path / "daten") is not None


def test_app_runs_pferd_and_jobs_with_its_own_python(tmp_path):
    """Regression: main.py importierte core vor server/app.py, core.PYTHON zeigte dann auf das venv der
    Terminal-Version (Abgleich scheiterte, Bibliotheks-Job mit EX_CONFIG 78). Frischer Prozess wie beim App-Start."""
    env = {k: v for k, v in os.environ.items() if k != "ILIAS_SYNC_PYTHON"} | {"ILIAS_SYNC_HOME": str(tmp_path)}
    code = ("import importlib.util, sys; spec = importlib.util.spec_from_file_location('main', sys.argv[1]); "
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); core = m.load_core(); "
            "sys.path.insert(0, str(m.ROOT / 'server')); import libraries, schedule; "
            "print(core.PYTHON); print(schedule._job(30)['ProgramArguments'][0]); "
            "print(libraries._job()['ProgramArguments'][0])")
    result = subprocess.run([sys.executable, "-c", code, str(ROOT / "main.py")], env=env, capture_output=True,
                            text=True, timeout=60, check=True)
    assert result.stdout.split() == [sys.executable] * 3


def test_second_start_brings_running_window_to_front(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "yield_activation", lambda pid: None)  # kein AppKit im Test
    shown = threading.Event()
    lock = main.instance_lock(tmp_path)
    listener = main.ShowListener(lock)
    listener.on_show = shown.set
    assert main.instance_lock(tmp_path) is None  # Zweitstart: Sperre bleibt, Port und PID bleiben lesbar
    assert main.bring_to_front(tmp_path)
    assert shown.wait(3)
    listener.sock.close()
    lock.close()


def test_second_start_falls_back_to_alert_without_listener(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "yield_activation", lambda pid: None)
    assert not main.bring_to_front(tmp_path)  # keine Sperrdatei
    (tmp_path / ".app.lock").write_text("")  # ältere App ohne ShowListener
    assert not main.bring_to_front(tmp_path)
    (tmp_path / ".app.lock").write_text(f"{main.free_port()} 1\n")  # Port nicht mehr belegt
    assert not main.bring_to_front(tmp_path)
