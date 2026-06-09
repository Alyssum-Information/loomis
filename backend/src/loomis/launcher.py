"""One-click local launcher (the `loomis up` entry point).

Starts the backend (uvicorn) and, in dev, the frontend (Vite), multiplexes both
logs into one terminal with coloured prefixes, health-waits until ready, and on
Ctrl-C / terminal close tears down **only Loomis's own children** — never
external services like Ollama.

Cross-platform: POSIX uses sessions + signals; Windows uses a new process group +
CTRL_BREAK_EVENT with a taskkill escalation.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import get_settings

IS_WIN = os.name == "nt"

# launcher.py -> loomis -> src -> backend -> repo root
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND_ROOT.parent
_WEB_DIR = _REPO_ROOT / "web"
_VITE_JS = _WEB_DIR / "node_modules" / "vite" / "bin" / "vite.js"

_VITE_PORT = 3000  # keep in sync with web/vite.config.mts
_HEALTH_TIMEOUT = 40.0
_SHUTDOWN_GRACE = 8.0


class _C:
    BACKEND = "\033[36m"
    FRONTEND = "\033[35m"
    OK = "\033[32m"
    WARN = "\033[33m"
    ERR = "\033[31m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def _enable_ansi() -> None:
    """Robust stdout on legacy codepages; enable VT colours on Windows."""
    with suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(errors="replace")  # type: ignore[union-attr]
    if not IS_WIN:
        return
    with suppress(Exception):
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VT_PROCESSING


# --- prerequisites ---


@dataclass(slots=True)
class Prereq:
    name: str
    ok: bool
    detail: str
    required: bool


def _module_installed(name: str) -> bool:
    """True if an import would succeed, without importing the (heavy) module."""
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def check_prerequisites(*, need_frontend: bool) -> list[Prereq]:
    """Verify tools. Optional deps (ffmpeg, Ollama, STT/diarize models) are informational."""
    node = shutil.which("node")
    pnpm = shutil.which("pnpm")
    ffmpeg = shutil.which("ffmpeg")
    ollama = shutil.which("ollama")
    whisperx = _module_installed("whisperx")
    pyannote = _module_installed("pyannote.audio")
    return [
        Prereq("Python", True, sys.version.split()[0], required=True),
        Prereq(
            "Node.js",
            node is not None,
            node or "install Node 18+ — https://nodejs.org",
            required=need_frontend,
        ),
        Prereq(
            "pnpm",
            pnpm is not None,
            pnpm or "install pnpm — `npm i -g pnpm`",
            required=need_frontend,
        ),
        Prereq(
            "ffmpeg",
            ffmpeg is not None,
            ffmpeg or "needed for STT/transcode — run ./install.sh",
            required=False,
        ),
        Prereq(
            "Ollama",
            ollama is not None,
            ollama or "needed for summaries — run ./install.sh",
            required=False,
        ),
        Prereq(
            "whisperx",
            whisperx,
            "transcription engine" if whisperx else "needed for STT — run ./install.sh",
            required=False,
        ),
        Prereq(
            "pyannote",
            pyannote,
            "diarization/voiceprints" if pyannote else "needed for speakers — run ./install.sh",
            required=False,
        ),
    ]


def report(checks: list[Prereq]) -> bool:
    """Print the check table; return True iff every required prerequisite is present."""
    print(f"{_C.BOLD}Loomis — prerequisite check{_C.RESET}")
    all_required_ok = True
    for c in checks:
        if c.ok:
            mark, color = "OK  ", _C.OK
        elif c.required:
            mark, color = "MISS", _C.ERR
            all_required_ok = False
        else:
            mark, color = "skip", _C.WARN
        print(f"  {color}[{mark}]{_C.RESET} {c.name:<10} {_C.DIM}{c.detail}{_C.RESET}")
    if not all_required_ok:
        print(f"{_C.ERR}Missing required prerequisites — fix the above and retry.{_C.RESET}")
    return all_required_ok


def run_prerequisite_check(*, need_frontend: bool = True) -> bool:
    _enable_ansi()
    return report(check_prerequisites(need_frontend=need_frontend))


# --- data safety: snapshot the DB before the backend migrates it ---


def backup_db() -> Path | None:
    settings = get_settings()
    db = settings.core.resolved_data_dir / "loomis.db"
    if not db.exists():
        return None
    backups = settings.core.resolved_data_dir / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    dst = backups / f"loomis-{ts}.db"
    shutil.copy2(db, dst)
    return dst


# --- process management ---


@dataclass(slots=True)
class Child:
    name: str
    proc: subprocess.Popen[str]
    color: str


def _popen(cmd: list[str], cwd: Path) -> subprocess.Popen[str]:
    # Branch on sys.platform (not IS_WIN) so mypy applies platform narrowing and
    # each call passes literal, type-correct kwargs. errors="replace" stops a
    # child's unicode (e.g. Vite) from crashing the log pump on legacy codepages.
    if sys.platform == "win32":
        return subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    return subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,  # child becomes its own process-group leader
    )


def _pump(child: Child) -> threading.Thread:
    def run() -> None:
        assert child.proc.stdout is not None
        for line in child.proc.stdout:
            sys.stdout.write(f"{child.color}[{child.name}]{_C.RESET} {line.rstrip()}\n")
            sys.stdout.flush()

    thread = threading.Thread(target=run, name=f"log-{child.name}", daemon=True)
    thread.start()
    return thread


def _taskkill_tree(pid: int) -> None:
    with suppress(OSError):
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False)


def _terminate(child: Child) -> None:
    proc = child.proc
    if proc.poll() is not None:
        return
    print(f"{child.color}[{child.name}]{_C.RESET} {_C.DIM}stopping…{_C.RESET}")

    if sys.platform == "win32":
        with suppress(OSError):
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        try:
            proc.wait(timeout=_SHUTDOWN_GRACE)
            return
        except subprocess.TimeoutExpired:
            _taskkill_tree(proc.pid)
        with suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=_SHUTDOWN_GRACE)
        return

    with suppress(ProcessLookupError, OSError):
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    try:
        proc.wait(timeout=_SHUTDOWN_GRACE)
        return
    except subprocess.TimeoutExpired:
        pass
    with suppress(ProcessLookupError, OSError):
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)


# --- health wait ---


def _health_url() -> str:
    s = get_settings()
    host = "127.0.0.1" if s.api.host in {"0.0.0.0", "::"} else s.api.host
    return f"http://{host}:{s.api.port}/api/v1/health"


def wait_healthy(timeout: float = _HEALTH_TIMEOUT) -> bool:
    url = _health_url()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310 (local http)
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.5)
    return False


# --- frontend build (prod) ---


def build_frontend() -> None:
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        raise RuntimeError("pnpm not found — cannot build the frontend")
    print(f"{_C.FRONTEND}[frontend]{_C.RESET} installing deps…")
    subprocess.run([pnpm, "install"], cwd=str(_WEB_DIR), check=True)  # noqa: S603
    print(f"{_C.FRONTEND}[frontend]{_C.RESET} building SPA…")
    # Build via vite's JS entry to bypass pnpm's build-script approval pre-check.
    subprocess.run([_node_exe(), str(_VITE_JS), "build"], cwd=str(_WEB_DIR), check=True)  # noqa: S603


# --- orchestration ---


def _node_exe() -> str:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node not found — install Node.js")
    return node


def up(*, prod: bool = False, open_browser: bool = True) -> int:
    _enable_ansi()
    settings = get_settings()

    if not report(check_prerequisites(need_frontend=True)):
        return 1

    if prod:
        try:
            build_frontend()
        except (subprocess.CalledProcessError, RuntimeError) as exc:
            print(f"{_C.ERR}Frontend build failed: {exc}{_C.RESET}")
            return 1

    bak = backup_db()
    if bak is not None:
        print(f"{_C.DIM}DB backed up → {bak}{_C.RESET}")

    children: list[Child] = []

    backend = Child(
        "backend",
        _popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "loomis.app:create_app",
                "--factory",
                "--host",
                settings.api.host,
                "--port",
                str(settings.api.port),
            ],
            cwd=_BACKEND_ROOT,
        ),
        _C.BACKEND,
    )
    children.append(backend)
    _pump(backend)

    app_url = f"http://127.0.0.1:{settings.api.port}"
    if not prod:
        if not _VITE_JS.exists():
            print(f"{_C.ERR}Frontend deps missing — run `pnpm install` in web/ first.{_C.RESET}")
            _terminate(backend)
            return 1
        frontend = Child(
            "frontend",
            _popen([_node_exe(), str(_VITE_JS), "--port", str(_VITE_PORT)], cwd=_WEB_DIR),
            _C.FRONTEND,
        )
        children.append(frontend)
        _pump(frontend)
        app_url = f"http://localhost:{_VITE_PORT}"

    if wait_healthy():
        print(f"{_C.OK}{_C.BOLD}Loomis is up → {app_url}{_C.RESET}")
        if open_browser:
            webbrowser.open(app_url)
    else:
        print(f"{_C.WARN}Backend did not report healthy in time; logs continue below.{_C.RESET}")

    return _run_until_exit(children)


def _run_until_exit(children: list[Child]) -> int:
    stop = threading.Event()

    def handler(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, handler)

    exit_code = 0
    while not stop.is_set():
        for child in children:
            if child.proc.poll() is not None:
                print(
                    f"{child.color}[{child.name}]{_C.RESET} "
                    f"{_C.WARN}exited (code {child.proc.returncode}); shutting down.{_C.RESET}"
                )
                exit_code = child.proc.returncode or 0
                stop.set()
                break
        stop.wait(0.5)

    print(f"\n{_C.DIM}Shutting down Loomis (external services left running)…{_C.RESET}")
    for child in children:
        _terminate(child)
    return exit_code
