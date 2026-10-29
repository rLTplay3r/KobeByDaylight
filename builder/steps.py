"""What a build does, as a list of shell-free steps, plus version / changelog helpers."""

import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

SPEC = "packaging/dbd_overlay.spec"
BUILDER_SPEC = "packaging/builder.spec"
FROZEN = getattr(sys, "frozen", False)

WIN_PY_VERSION = "3.12.8"
WIN_PY = r"C:\Python312\python.exe"
WIN_INSTALLER_URL = f"https://www.python.org/ftp/python/{WIN_PY_VERSION}/python-{WIN_PY_VERSION}-amd64.exe"

# Project paths, filled in by set_root() once the project folder is known
ROOT = BUILD = DIST = VENV_PY = INIT_FILE = CHANGELOG = WIN_PREFIX = WIN_INSTALLER = None
OUTPUTS: dict[str, Path] = {}


def is_project(path: Path) -> bool:
    return (path / SPEC).is_file() and (path / "dbd_overlay" / "__init__.py").is_file()


def find_root(saved: str | None = None) -> Path | None:
    """The project folder: remembered one, $KBD_PROJECT, or near the builder / current dir."""
    here = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
    candidates = [Path(p) for p in (saved, os.environ.get("KBD_PROJECT")) if p]
    for start in (here, Path.cwd()):
        candidates += [start, *start.parents]
    return next((c for c in candidates if is_project(c)), None)


def set_root(root: Path):
    global ROOT, BUILD, DIST, VENV_PY, INIT_FILE, CHANGELOG, WIN_PREFIX, WIN_INSTALLER
    ROOT = root.resolve()
    BUILD = ROOT / "build"
    DIST = ROOT / "dist"
    VENV_PY = BUILD / "venv" / "bin" / "python"
    INIT_FILE = ROOT / "dbd_overlay" / "__init__.py"
    CHANGELOG = ROOT / "CHANGELOG.md"
    WIN_PREFIX = BUILD / "win" / "pfx"
    WIN_INSTALLER = BUILD / "win" / f"python-{WIN_PY_VERSION}-amd64.exe"
    OUTPUTS.clear()
    OUTPUTS.update({
        "linux": DIST / "DBD-Kobe-Overlay",
        "windows": DIST / "DBD-Kobe-Overlay.exe",
        "builder": ROOT / "KBD-Builder",
    })

PIP_QUIET = ["--disable-pip-version-check", "--no-warn-script-location", "-q"]


@dataclass
class Step:
    title: str
    program: str
    args: list[str]
    env: dict[str, str] = field(default_factory=dict)


def wine_env() -> dict[str, str]:
    return {
        "WINEPREFIX": str(WIN_PREFIX),
        "WINEDEBUG": "-all",
        "WINEDLLOVERRIDES": "mscoree,mshtml=",  # no Mono / Gecko install prompts
        "WINEARCH": "win64",
    }


def windows_python_ready() -> bool:
    return (WIN_PREFIX / "drive_c" / "Python312" / "python.exe").is_file()


def missing_tools(targets: list[str]) -> list[str]:
    missing = []
    if not VENV_PY.exists() and not shutil.which("python3"):
        missing.append("python3")
    if "windows" in targets and not shutil.which("wine"):
        missing.append("wine (install it with: sudo dnf install wine)")
    return missing


def plan(targets: list[str]) -> list[Step]:
    py = str(VENV_PY)
    steps: list[Step] = []
    if not VENV_PY.exists():
        # The builder can't install packages into itself, so builds run in their own venv
        steps.append(Step("Create Linux build environment", "python3", ["-m", "venv", str(BUILD / "venv")]))
    steps += [
        Step("Install build tools (Linux Python)", py,
             ["-m", "pip", "install", *PIP_QUIET, "-r", "requirements.txt", "pyinstaller"]),
        Step("Install keyboard backend (Linux Python)", py,
             ["-m", "pip", "install", *PIP_QUIET, "--no-deps", "-r", "requirements-nodeps.txt"]),
    ]
    if "linux" in targets or "windows" in targets:
        # Dance videos keyed into transparent frames once, so the app doesn't have to
        steps.append(Step("Prepare dance frames", py, ["-m", "dbd_overlay.dance", "--prepare", "build/dance-frames"],
                          {"QT_QPA_PLATFORM": "offscreen"}))
    if "linux" in targets:
        steps.append(Step("Build Linux executable", py,
                          ["-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", "dist",
                           "--workpath", "build/linux-work", SPEC]))
    if "windows" in targets:
        env = wine_env()
        if not windows_python_ready():
            steps += [
                Step(f"Download Windows Python {WIN_PY_VERSION}", py,
                     ["-c", "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])",
                      WIN_INSTALLER_URL, str(WIN_INSTALLER)]),
                Step("Create Wine prefix", "wineboot", ["-i"], env),
                Step("Install Windows Python into Wine", "wine",
                     [str(WIN_INSTALLER), "/quiet", "InstallAllUsers=0", r"TargetDir=C:\Python312",
                      "Include_test=0", "Include_doc=0", "Include_tcltk=0", "Include_launcher=0",
                      "PrependPath=0", "Shortcuts=0"], env),
            ]
        steps += [
            Step("Install build tools (Windows Python)", "wine",
                 [WIN_PY, "-m", "pip", "install", *PIP_QUIET, "-r", "requirements.txt", "pyinstaller"], env),
            Step("Make Windows icon", py, ["packaging/make_icon.py"], {"QT_QPA_PLATFORM": "offscreen"}),
            Step("Build Windows executable", "wine",
                 [WIN_PY, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", "dist",
                  "--workpath", "build/win/work", SPEC], env),
        ]
    if "builder" in targets:
        steps.append(Step("Build the builder app", py,
                          ["-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", ".",
                           "--workpath", "build/builder-work", BUILDER_SPEC]))
    return steps


# -- version ---------------------------------------------------------------------

_VERSION_RE = re.compile(r'^__version__ = "([^"]+)"', re.MULTILINE)


def read_version() -> str:
    m = _VERSION_RE.search(INIT_FILE.read_text(encoding="utf-8"))
    return m.group(1) if m else "0.0.0"


def next_version(version: str) -> str:
    parts = version.split(".")
    try:
        parts[-1] = str(int(parts[-1]) + 1)
    except ValueError:
        return version
    return ".".join(parts)


def valid_version(version: str) -> bool:
    return bool(re.fullmatch(r"\d+(\.\d+){1,3}", version))


def write_version(version: str, notes: str) -> list[str]:
    """Sets __version__ and, when there are notes, adds a CHANGELOG section. Returns what changed."""
    done = []
    text = INIT_FILE.read_text(encoding="utf-8")
    if _VERSION_RE.search(text).group(1) != version:
        INIT_FILE.write_text(_VERSION_RE.sub(f'__version__ = "{version}"', text, count=1), encoding="utf-8")
        done.append(f"version set to {version}")
    lines = [l.strip().lstrip("-* ").strip() for l in notes.splitlines() if l.strip()]
    if lines:
        log = CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.exists() else "# Changelog\n"
        section = f"## {version}\n" + "".join(f"- {l}\n" for l in lines) + "\n"
        existing = re.search(rf"^## {re.escape(version)}\n", log, re.MULTILINE)
        if existing:
            # Same version again: append the notes to the end of its section
            following = re.search(r"^## ", log[existing.end():], re.MULTILINE)
            end = existing.end() + following.start() if following else len(log)
            body = log[existing.end():end].rstrip("\n") + "\n"
            log = log[:existing.end()] + body + "".join(f"- {l}\n" for l in lines) + "\n" + log[end:]
        else:
            first = re.search(r"^## ", log, re.MULTILINE)
            insert = first.start() if first else len(log)
            log = log[:insert] + section + log[insert:]
        CHANGELOG.write_text(log, encoding="utf-8")
        done.append(f"{len(lines)} note(s) added to CHANGELOG.md")
    return done


def size_text(path: Path) -> str:
    return f"{path.stat().st_size / 1_048_576:.0f} MB"


set_root(find_root() or Path(__file__).resolve().parent.parent)
