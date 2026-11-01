"""Installation, Update und Deinstallation (scripts/install.sh, scripts/uninstall.sh) in einer Sandbox:
eigenes HOME, Ersatz für uname, launchctl, security, pgrep und open. setup.sh und make_app.sh werden in
einem nachgebauten Projektordner durch Platzhalter ersetzt (kein Download, kein Xcode)."""

import os
import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STUBS = {
    "uname": 'echo Darwin',
    "pgrep": 'exit "${FAKE_RUNNING:-1}"',
    "launchctl": 'echo "launchctl $*" >> "$CALLS"',
    "open": 'echo "open $*" >> "$CALLS"',
    # löscht drei Einträge, danach „nicht gefunden“ wie security bei leerem Schlüsselbund
    "security": 'n=$(cat "$CALLS.security" 2>/dev/null || echo 0); [ "$n" -lt 3 ] || exit 44; '
                'echo $((n + 1)) > "$CALLS.security"; echo "security $*" >> "$CALLS"',
}


@pytest.fixture
def sandbox(tmp_path):
    home, bin_dir = tmp_path / "home", tmp_path / "bin"
    home.mkdir()
    bin_dir.mkdir()
    for name, body in STUBS.items():
        (bin_dir / name).write_text(f"#!/bin/bash\n{body}\n", encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    env = {**os.environ, "HOME": str(home), "PATH": f"{bin_dir}:{os.environ['PATH']}", "CALLS": str(tmp_path / "calls")}
    for key in ("ILIAS_LERNER_INSTALL_DIR", "ILIAS_LERNER_APP", "ILIAS_LERNER_ARCHIVE", "ILIAS_LERNER_NO_OPEN",
                "ILIAS_LERNER_OLD_INSTALL_DIR", "ILIAS_LERNER_OLD_APP"):
        env.pop(key, None)
    return home, env, tmp_path / "calls"


def _source(tmp_path: Path, version: str = "9.9.9") -> Path:
    """Nachgebauter Projektordner: echte install.sh/uninstall.sh, Platzhalter für setup.sh und make_app.sh."""
    source = tmp_path / f"quelle-{version}"
    (source / "scripts").mkdir(parents=True)
    (source / "main.py").write_text("# App\n", encoding="utf-8")
    pyproject = f'[project]\nname = "studyhub"\nversion = "{version}"\n'
    (source / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    (source / "demo-data").mkdir()
    for name in ("install.sh", "uninstall.sh"):
        shutil.copy(ROOT / "scripts" / name, source / "scripts" / name)
    (source / "scripts/setup.sh").write_text(
        'cd "$(dirname "$0")/.."; echo "setup $*" >> "$CALLS"; mkdir -p .venv/bin; touch .venv/bin/python\n',
        encoding="utf-8")
    (source / "scripts/make_app.sh").write_text(
        'mkdir -p "$1/Contents"; echo "<string>local.ilias-lerner</string>" > "$1/Contents/Info.plist"\n',
        encoding="utf-8")
    return source


def _run(script: Path, env: dict, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(script), *args], env=env, input=stdin, capture_output=True, text=True,
                          timeout=60)


def _paths(home: Path) -> tuple[Path, Path, Path]:
    return (home / "Library/Application Support/StudyHub/app", home / "Applications/StudyHub.app",
            home / "Library/Application Support/ILIAS-Sync")


def test_install_copies_code_builds_app_and_opens_it(sandbox, tmp_path):
    home, env, calls = sandbox
    result = _run(_source(tmp_path) / "scripts/install.sh", env)
    assert result.returncode == 0, result.stderr
    install, app, _ = _paths(home)
    assert (install / "main.py").exists() and (install / ".ilias-lerner-install").exists()
    assert not (install / "demo-data").exists()
    assert (app / "Contents/Info.plist").exists()
    log = calls.read_text(encoding="utf-8")
    assert "setup --app" in log and f"open {app}" in log
    assert "StudyHub 9.9.9" in result.stdout and "heißt jetzt StudyHub" not in result.stdout


def test_update_replaces_code_but_keeps_python_and_does_not_open(sandbox, tmp_path):
    home, env, calls = sandbox
    assert _run(_source(tmp_path, "1.0.0") / "scripts/install.sh", env).returncode == 0
    install, _, _ = _paths(home)
    (install / "alt.py").write_text("veraltet", encoding="utf-8")
    (install / ".tools").mkdir()
    calls.unlink()
    result = _run(_source(tmp_path, "1.1.0") / "scripts/install.sh", env)
    assert result.returncode == 0, result.stderr
    assert not (install / "alt.py").exists()  # Dateien, die es nicht mehr gibt, verschwinden
    assert (install / ".venv/bin/python").exists() and (install / ".tools").exists()
    assert 'version = "1.1.0"' in (install / "pyproject.toml").read_text(encoding="utf-8")
    assert "open" not in calls.read_text(encoding="utf-8")


def test_install_never_touches_a_foreign_folder_or_a_running_app(sandbox, tmp_path):
    home, env, _ = sandbox
    install, _, _ = _paths(home)
    install.mkdir(parents=True)
    (install / "fremd.txt").write_text("gehört jemand anderem", encoding="utf-8")
    script = _source(tmp_path) / "scripts/install.sh"
    result = _run(script, env)
    assert result.returncode != 0 and "stammt nicht von diesem Skript" in result.stderr
    assert sorted(p.name for p in install.iterdir()) == ["fremd.txt"]

    result = _run(script, {**env, "FAKE_RUNNING": "0"})
    assert result.returncode != 0 and "läuft noch" in result.stderr


def _old_installation(home: Path) -> tuple[Path, Path]:
    """Installation unter dem Namen bis 1.0 (ILIAS-Lerner), wie sie install.sh damals angelegt hat."""
    old_install = home / "Library/Application Support/ILIAS-Lerner/app"
    old_app = home / "Applications/ILIAS-Lerner.app"
    (old_install / ".venv/bin").mkdir(parents=True)
    (old_install / ".ilias-lerner-install").touch()
    (old_install / "main.py").write_text("# alte App\n", encoding="utf-8")
    (old_app / "Contents").mkdir(parents=True)
    (old_app / "Contents/Info.plist").write_text("<string>local.ilias-lerner</string>", encoding="utf-8")
    return old_install, old_app


def test_install_replaces_the_old_ilias_lerner_installation_and_opens_the_app(sandbox, tmp_path):
    home, env, calls = sandbox
    old_install, old_app = _old_installation(home)
    data = _paths(home)[2]
    data.mkdir(parents=True)
    (data / "config.json").write_text("{}", encoding="utf-8")
    result = _run(_source(tmp_path) / "scripts/install.sh", env)
    assert result.returncode == 0, result.stderr
    install, app, _ = _paths(home)
    assert (install / "main.py").exists() and (app / "Contents/Info.plist").exists()
    assert not old_app.exists() and not old_install.exists() and not old_install.parent.exists()
    assert (data / "config.json").exists()  # Daten bleiben
    assert "heißt jetzt StudyHub" in result.stdout
    assert f"open {app}" in calls.read_text(encoding="utf-8")  # App stellt die Hintergrund-Jobs um


def test_install_keeps_a_foreign_ilias_lerner_app(sandbox, tmp_path):
    home, env, _ = sandbox
    old_app = home / "Applications/ILIAS-Lerner.app"
    (old_app / "Contents").mkdir(parents=True)
    (old_app / "Contents/Info.plist").write_text("<string>com.example.fremd</string>", encoding="utf-8")
    assert _run(_source(tmp_path) / "scripts/install.sh", env).returncode == 0
    assert old_app.exists()


def test_uninstall_also_removes_leftovers_of_the_old_name(sandbox, tmp_path):
    home, env, _ = sandbox
    assert _run(_source(tmp_path) / "scripts/install.sh", env).returncode == 0
    old_install, old_app = _old_installation(home)
    install, app, _ = _paths(home)
    result = _run(install / "scripts/uninstall.sh", env)
    assert result.returncode == 0, result.stderr
    assert not any(p.exists() for p in (install, app, old_install, old_app))


def _installed_with_jobs(sandbox, tmp_path, sync_script: str) -> Path:
    home, env, calls = sandbox
    assert _run(_source(tmp_path) / "scripts/install.sh", env).returncode == 0
    agents = home / "Library/LaunchAgents"
    agents.mkdir(parents=True)
    jobs = {"local.ilias-lerner.bibliothek": "/x/server/libraries.py", "local.ilias-sync": sync_script}
    for label, script in jobs.items():
        job = {"Label": label, "ProgramArguments": ["/x/py", script]}
        (agents / f"{label}.plist").write_bytes(plistlib.dumps(job))
    data = _paths(home)[2]
    data.mkdir(parents=True)
    (data / "config.json").write_text("{}", encoding="utf-8")
    calls.unlink()
    return agents


def test_uninstall_removes_app_code_and_jobs_but_keeps_data(sandbox, tmp_path):
    home, env, calls = sandbox
    agents = _installed_with_jobs(sandbox, tmp_path, "/x/ILIAS-Lerner/core/sync.py")
    install, app, data = _paths(home)
    result = _run(install / "scripts/uninstall.sh", env)
    assert result.returncode == 0, result.stderr
    assert not install.exists() and not install.parent.exists() and not app.exists()
    assert not any(agents.iterdir())
    assert (data / "config.json").exists()
    assert "launchctl bootout" in calls.read_text(encoding="utf-8")
    assert "security" not in calls.read_text(encoding="utf-8")


def test_uninstall_keeps_the_sync_job_of_the_terminal_version(sandbox, tmp_path):
    home, env, _ = sandbox
    agents = _installed_with_jobs(sandbox, tmp_path, "/x/ILIAS-Sync/app/sync.py")
    assert _run(_paths(home)[0] / "scripts/uninstall.sh", env).returncode == 0
    assert [p.name for p in agents.iterdir()] == ["local.ilias-sync.plist"]


def test_uninstall_everything_asks_and_deletes_data_and_keychain(sandbox, tmp_path):
    home, env, calls = sandbox
    _installed_with_jobs(sandbox, tmp_path, "/x/core/sync.py")
    install, app, data = _paths(home)
    result = _run(install / "scripts/uninstall.sh", env, "--alles", stdin="n\n")
    assert result.returncode == 0 and "Nichts gelöscht" in result.stdout
    assert install.exists() and app.exists() and data.exists()

    result = _run(install / "scripts/uninstall.sh", env, "--alles", stdin="j\n")
    assert result.returncode == 0, result.stderr
    assert not data.exists() and not install.exists()
    assert calls.read_text(encoding="utf-8").count("security delete-generic-password -s ILIAS-Sync") == 3
    assert "3 Einträge" in result.stdout


def test_uninstall_everything_keeps_data_shared_with_the_terminal_version(sandbox, tmp_path):
    home, env, calls = sandbox
    _installed_with_jobs(sandbox, tmp_path, "/x/core/sync.py")
    install, _, data = _paths(home)
    (data / "app").mkdir()
    (data / "app/cli.py").write_text("# Terminal-Version", encoding="utf-8")
    result = _run(install / "scripts/uninstall.sh", env, "--alles")
    assert result.returncode == 0, result.stderr
    assert (data / "config.json").exists() and not install.exists()
    assert "security" not in calls.read_text(encoding="utf-8")


def test_setup_uses_only_uv_managed_python(sandbox, tmp_path):
    """Ein altes Intel-Python im Suchpfad (/Library/Frameworks/…/3.9) brach auf Apple-Chips mit „Bad CPU type“
    ab: setup.sh lässt uv nur sein eigenes Python 3.13 verwenden."""
    _, env, calls = sandbox
    project = tmp_path / "projekt"
    (project / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts/setup.sh", project / "scripts/setup.sh")
    (project / ".tools").mkdir()
    fake_uv = project / ".tools/uv"  # passende Version: setup.sh lädt nichts herunter
    fake_uv.write_text('#!/bin/bash\n[ "$1" = "--version" ] && { echo "uv 0.12.19"; exit 0; }\n'
                       'echo "uv $* | $UV_PYTHON_PREFERENCE | $UV_PYTHON" >> "$CALLS"\n', encoding="utf-8")
    fake_uv.chmod(0o755)
    bin_dir = tmp_path / "bin-arm"
    bin_dir.mkdir()
    (bin_dir / "uname").write_text('#!/bin/bash\n[ "$1" = "-m" ] && echo arm64 || echo Darwin\n', encoding="utf-8")
    (bin_dir / "uname").chmod(0o755)
    env = {**env, "PATH": f"{bin_dir}:{env['PATH']}"}
    result = _run(project / "scripts/setup.sh", env, "--app")
    assert result.returncode == 0, result.stderr
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "uv sync --quiet --locked --no-dev | only-managed | 3.13"]


def test_setup_under_rosetta_takes_the_apple_chip_version(sandbox, tmp_path):
    """Ein Terminal unter Rosetta meldet auf Apple-Chips x86_64; für Intel fehlen fertige Pakete (cryptography).
    setup.sh lädt trotzdem uv für Apple-Chips und räumt eine frühere Intel-Einrichtung weg."""
    _, env, calls = sandbox
    project = tmp_path / "projekt"
    (project / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts/setup.sh", project / "scripts/setup.sh")
    (project / ".tools/python").mkdir(parents=True)
    (project / ".venv/bin").mkdir(parents=True)
    (project / ".tools/uv").write_text("#!/bin/bash\necho uv 0.12.19\n", encoding="utf-8")
    (project / ".tools/uv").chmod(0o755)
    bin_dir = tmp_path / "bin-rosetta"
    bin_dir.mkdir()
    stubs = {
        "uname": '[ "$1" = "-m" ] && echo x86_64 || echo Darwin',
        "sysctl": 'echo 1',
        "file": 'echo "Mach-O 64-bit executable x86_64"',
        "curl": 'echo "curl $*" >> "$CALLS"; exit 1',  # kein Download im Test
    }
    for name, body in stubs.items():
        (bin_dir / name).write_text(f"#!/bin/bash\n{body}\n", encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    env = {**env, "PATH": f"{bin_dir}:{env['PATH']}"}
    result = _run(project / "scripts/setup.sh", env, "--app")
    assert result.returncode != 0
    assert "uv-aarch64-apple-darwin.tar.gz" in calls.read_text(encoding="utf-8")
    assert not (project / ".venv").exists() and not (project / ".tools/python").exists()
