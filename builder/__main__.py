"""python -m builder            -> builder window
python -m builder --build linux windows [--version 0.0.16] -> build from the terminal"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="Build the Kobe by Daylight executables")
    parser.add_argument("--build", nargs="+", choices=["linux", "windows", "builder"],
                        help="build without the window (builder = this app as an executable)")
    parser.add_argument("--project", help="project folder (default: found next to the builder)")
    parser.add_argument("--version", help="set this version before building")
    parser.add_argument("--notes", default="", help="CHANGELOG lines for the version, separated by ';'")
    args = parser.parse_args()

    from pathlib import Path

    from PySide6.QtCore import QSettings

    from . import steps

    settings = QSettings("KobeByDaylight", "Builder")
    root = Path(args.project) if args.project else steps.find_root(settings.value("project"))

    if args.build:
        from PySide6.QtCore import QCoreApplication

        from .runner import Runner

        if root is None or not steps.is_project(root):
            sys.exit("Project folder not found; run from inside it or pass --project PATH")
        steps.set_root(root)
        app = QCoreApplication(sys.argv)
        missing = steps.missing_tools(args.build)
        if missing:
            sys.exit("Missing tools: " + ", ".join(missing))
        if args.version:
            if not steps.valid_version(args.version):
                sys.exit(f"Not a version: {args.version}")
            for change in steps.write_version(args.version, args.notes.replace(";", "\n")):
                print(f"* {change}")
        runner = Runner()
        result = {}
        runner.step_started.connect(lambda i, n, t: print(f"[{i + 1}/{n}] {t}", flush=True))
        runner.output.connect(lambda text: print(text, end="", flush=True))
        runner.finished.connect(lambda ok, msg: (result.update(ok=ok), print(f"\n{msg}"), app.quit()))
        runner.start(steps.plan(args.build))
        app.exec()
        for target in args.build:
            path = steps.OUTPUTS[target]
            if path.exists():
                print(f"{path} ({steps.size_text(path)})")
        sys.exit(0 if result.get("ok") else 1)

    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    app = QApplication(sys.argv)
    app.setApplicationName("Kobe by Daylight Builder")
    # Started from somewhere else (e.g. a copy on the desktop): ask once where the project is
    while root is None or not steps.is_project(root):
        picked = QFileDialog.getExistingDirectory(None, "Where is the Kobe by Daylight project folder?",
                                                  str(Path.home()))
        if not picked:
            sys.exit(1)
        root = Path(picked)
        if not steps.is_project(root):
            QMessageBox.warning(None, "Not the project", f"{root} has no {steps.SPEC}. Pick the project folder.")
    steps.set_root(root)
    settings.setValue("project", str(steps.ROOT))

    # Imported after the project is known: the theme loads its font from the project
    from dbd_overlay import theme

    from .app import EXTRA_STYLE, BuilderWindow

    theme.load_fonts()
    app.setStyleSheet(theme.stylesheet() + EXTRA_STYLE)
    window = BuilderWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
