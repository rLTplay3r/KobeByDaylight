"""Runs build steps one after another with QProcess and streams their output."""

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from . import steps
from .steps import FROZEN, Step


class Runner(QObject):
    step_started = Signal(int, int, str)   # index, total, title
    output = Signal(str)
    finished = Signal(bool, str)           # ok, message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._steps: list[Step] = []
        self._index = -1
        self._proc: QProcess | None = None
        self._cancelled = False

    @property
    def running(self) -> bool:
        return self._proc is not None

    def start(self, plan: list[Step]):
        self._steps, self._index, self._cancelled = plan, -1, False
        (steps.BUILD / "tmp").mkdir(parents=True, exist_ok=True)
        (steps.BUILD / "win").mkdir(parents=True, exist_ok=True)
        self._next()

    def cancel(self):
        self._cancelled = True
        if self._proc:
            self._proc.kill()

    def _next(self):
        self._index += 1
        if self._index >= len(self._steps):
            self._proc = None
            self.finished.emit(True, "Build finished")
            return
        step = self._steps[self._index]
        self.step_started.emit(self._index, len(self._steps), step.title)
        self.output.emit(f"\n=== {step.title} ===\n$ {step.program} {' '.join(step.args)}\n")

        env = QProcessEnvironment.systemEnvironment()
        # /tmp is often a small RAM disk; PyInstaller and pip unpack a lot
        env.insert("TMPDIR", str(steps.BUILD / "tmp"))
        env.insert("PYTHONUNBUFFERED", "1")
        if FROZEN:
            # Don't leak this app's bundled Qt / libraries into python, pip or wine
            for var in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
                env.remove(var)
            orig = env.value("LD_LIBRARY_PATH_ORIG")
            if orig:
                env.insert("LD_LIBRARY_PATH", orig)
            else:
                env.remove("LD_LIBRARY_PATH")
        for k, v in step.env.items():
            env.insert(k, v)
        proc = QProcess(self)
        proc.setProcessEnvironment(env)
        proc.setWorkingDirectory(str(steps.ROOT))
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.readyReadStandardOutput.connect(self._read)
        proc.finished.connect(self._done)
        proc.errorOccurred.connect(self._error)
        self._proc = proc
        proc.start(step.program, step.args)

    def _read(self):
        if self._proc:
            self.output.emit(bytes(self._proc.readAllStandardOutput()).decode(errors="replace"))

    def _error(self, err):
        if err == QProcess.ProcessError.FailedToStart and self._proc:
            step = self._steps[self._index]
            self._proc = None
            self.finished.emit(False, f"Could not start '{step.program}' ({step.title})")

    def _done(self, code, status):
        if self._proc is None:  # already reported by _error
            return
        self._read()
        self._proc = None
        if self._cancelled:
            self.finished.emit(False, "Build cancelled")
        elif status != QProcess.ExitStatus.NormalExit or code != 0:
            self.finished.emit(False, f"'{self._steps[self._index].title}' failed (exit code {code})")
        else:
            self._next()
