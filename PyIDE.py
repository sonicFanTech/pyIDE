import os
import sys
import json
import shlex
import tempfile
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QProcess, QSize, QRect, Signal, QObject
from PySide6.QtGui import (
    QAction, QFont, QTextCursor, QKeySequence,
    QSyntaxHighlighter, QTextCharFormat, QColor
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QPlainTextEdit, QTabWidget,
    QFileDialog, QMessageBox, QToolBar, QStatusBar, QDockWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QLineEdit, QCheckBox, QFormLayout, QGroupBox
)

APP_NAME = "SFT PyIDE"
CONFIG_NAME = "pyide_config.json"


def is_windows() -> bool:
    return os.name == "nt"


def normpath(p: str) -> str:
    return str(Path(p).expanduser().resolve())


def safe_read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def safe_write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8", errors="replace") as f:
        f.write(text)


class PythonSyntaxHighlighter(QSyntaxHighlighter):
    """Very lightweight Python syntax highlighter (regex-free keyword scan)."""

    KEYWORDS = {
        "False", "True", "None",
        "and", "as", "assert", "async", "await",
        "break", "class", "continue", "def", "del",
        "elif", "else", "except", "finally", "for",
        "from", "global", "if", "import", "in",
        "is", "lambda", "nonlocal", "not", "or",
        "pass", "raise", "return", "try", "while",
        "with", "yield", "match", "case",
    }

    def __init__(self, doc):
        super().__init__(doc)

        self.fmt_keyword = QTextCharFormat()
        self.fmt_keyword.setForeground(QColor(86, 156, 214))  # bluish

        self.fmt_string = QTextCharFormat()
        self.fmt_string.setForeground(QColor(206, 145, 120))  # orange

        self.fmt_comment = QTextCharFormat()
        self.fmt_comment.setForeground(QColor(106, 153, 85))   # green

        self.fmt_number = QTextCharFormat()
        self.fmt_number.setForeground(QColor(181, 206, 168))  # pale green

    def highlightBlock(self, text: str) -> None:
        # Comments: everything after first # (naive; ignores strings)
        comment_at = text.find("#")
        if comment_at != -1:
            self.setFormat(comment_at, len(text) - comment_at, self.fmt_comment)

        # Strings (naive): highlight quoted segments for ", ', ''' and """
        # This is intentionally simple (good enough for a starter IDE).
        def highlight_simple_quotes(q: str):
            start = 0
            while True:
                i = text.find(q, start)
                if i == -1:
                    return
                j = text.find(q, i + len(q))
                if j == -1:
                    # highlight until end
                    self.setFormat(i, len(text) - i, self.fmt_string)
                    return
                self.setFormat(i, (j + len(q)) - i, self.fmt_string)
                start = j + len(q)

        highlight_simple_quotes("'''")
        highlight_simple_quotes('"""')
        highlight_simple_quotes("'")
        highlight_simple_quotes('"')

        # Keywords + numbers (naive tokenizer)
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            if ch.isalpha() or ch == "_":
                j = i + 1
                while j < n and (text[j].isalnum() or text[j] == "_"):
                    j += 1
                word = text[i:j]
                if word in self.KEYWORDS:
                    self.setFormat(i, j - i, self.fmt_keyword)
                i = j
                continue
            if ch.isdigit():
                j = i + 1
                while j < n and (text[j].isdigit() or text[j] in ".xXabcdefABCDEF"):
                    j += 1
                self.setFormat(i, j - i, self.fmt_number)
                i = j
                continue
            i += 1


class CodeEditor(QPlainTextEdit):
    modified_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        font = QFont("Consolas" if is_windows() else "Monospace")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(11)
        self.setFont(font)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)

        self._highlighter = PythonSyntaxHighlighter(self.document())
        self.document().modificationChanged.connect(self.modified_changed.emit)

    def set_text(self, text: str) -> None:
        self.setPlainText(text)
        self.document().setModified(False)

    def text(self) -> str:
        return self.toPlainText()


@dataclass
class TabState:
    path: str | None = None
    temp_path: str | None = None  # used when running unsaved buffers


class InterpreterManager(QObject):
    interpreters_changed = Signal()

    def __init__(self, config_path: str):
        super().__init__()
        self.config_path = config_path
        self.interpreters: list[str] = []
        self.last_selected: str | None = None
        self.load()

        if not self.interpreters:
            self.discover()
            self.save()

    def load(self):
        try:
            if os.path.isfile(self.config_path):
                data = json.loads(safe_read_text(self.config_path))
                self.interpreters = [p for p in data.get("interpreters", []) if p]
                self.last_selected = data.get("last_selected")
        except Exception:
            # ignore config errors
            self.interpreters = []
            self.last_selected = None

    def save(self):
        data = {
            "interpreters": self.interpreters,
            "last_selected": self.last_selected,
        }
        try:
            safe_write_text(self.config_path, json.dumps(data, indent=2))
        except Exception:
            pass

    def add_interpreter(self, path: str):
        p = normpath(path)
        if p not in self.interpreters and os.path.isfile(p):
            self.interpreters.append(p)
            self.interpreters.sort(key=lambda x: x.lower())
            self.interpreters_changed.emit()
            self.save()

    def remove_interpreter(self, path: str):
        p = normpath(path)
        if p in self.interpreters:
            self.interpreters.remove(p)
            if self.last_selected == p:
                self.last_selected = None
            self.interpreters_changed.emit()
            self.save()

    def discover(self):
        found: set[str] = set()

        # Always include current interpreter
        try:
            found.add(normpath(sys.executable))
        except Exception:
            pass

        # Windows: use py launcher to list installed interpreters
        if is_windows():
            try:
                # py -0p prints paths, one per line (usually)
                out = subprocess.check_output(["py", "-0p"], text=True, stderr=subprocess.STDOUT)
                for line in out.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    # sometimes lines look like: "-3.12-64        C:\Path\python.exe"
                    parts = line.split()
                    maybe_path = parts[-1]
                    if os.path.isfile(maybe_path) and maybe_path.lower().endswith("python.exe"):
                        found.add(normpath(maybe_path))
            except Exception:
                pass

            # Common fallback locations
            candidates = []
            local = os.environ.get("LOCALAPPDATA", "")
            prog = os.environ.get("ProgramFiles", "")
            progx = os.environ.get("ProgramFiles(x86)", "")
            for base in [local, prog, progx]:
                if base:
                    candidates += list(Path(base).glob(r"Programs\Python\Python*\python.exe"))
                    candidates += list(Path(base).glob(r"Python*\python.exe"))

            for c in candidates:
                if c.is_file():
                    found.add(normpath(str(c)))

        else:
            # Non-Windows: try python3 and python
            for cmd in ["python3", "python"]:
                try:
                    p = subprocess.check_output(["which", cmd], text=True).strip()
                    if p and os.path.isfile(p):
                        found.add(normpath(p))
                except Exception:
                    pass

        self.interpreters = sorted(found, key=lambda x: x.lower())
        self.interpreters_changed.emit()

    def pick_default(self) -> str | None:
        if self.last_selected and self.last_selected in self.interpreters:
            return self.last_selected
        if self.interpreters:
            return self.interpreters[0]
        return None


class CompilerWindow(QMainWindow):
    def __init__(self, manager: InterpreterManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Compiler (PyInstaller)")
        self.setMinimumSize(QSize(900, 600))
        self.manager = manager

        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._on_ready)
        self.proc.finished.connect(self._on_finished)

        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # Form
        form_box = QGroupBox("Build options")
        form = QFormLayout(form_box)

        self.interp_combo = QComboBox()
        self._reload_interpreters()
        self.manager.interpreters_changed.connect(self._reload_interpreters)

        self.entry_edit = QLineEdit()
        self.entry_btn = QPushButton("Browse…")
        self.entry_btn.clicked.connect(self._browse_entry)
        entry_row = QWidget()
        entry_row_l = QHBoxLayout(entry_row)
        entry_row_l.setContentsMargins(0, 0, 0, 0)
        entry_row_l.addWidget(self.entry_edit)
        entry_row_l.addWidget(self.entry_btn)

        self.onefile_chk = QCheckBox("One-file (--onefile)")
        self.windowed_chk = QCheckBox("Windowed/No console (--windowed)")
        self.clean_chk = QCheckBox("Clean build (--clean)")
        self.noconfirm_chk = QCheckBox("No confirm (--noconfirm)")
        self.icon_edit = QLineEdit()
        self.icon_btn = QPushButton("Browse…")
        self.icon_btn.clicked.connect(self._browse_icon)
        icon_row = QWidget()
        icon_row_l = QHBoxLayout(icon_row)
        icon_row_l.setContentsMargins(0, 0, 0, 0)
        icon_row_l.addWidget(self.icon_edit)
        icon_row_l.addWidget(self.icon_btn)

        form.addRow("Python interpreter:", self.interp_combo)
        form.addRow("Entry .py file:", entry_row)
        form.addRow("", self.onefile_chk)
        form.addRow("", self.windowed_chk)
        form.addRow("", self.clean_chk)
        form.addRow("", self.noconfirm_chk)
        form.addRow("Icon (.ico):", icon_row)

        root.addWidget(form_box)

        # Buttons
        btn_row = QHBoxLayout()
        self.build_btn = QPushButton("Build")
        self.stop_btn = QPushButton("Stop")
        self.install_btn = QPushButton("Install/Update PyInstaller (pip)")
        self.stop_btn.setEnabled(False)

        self.build_btn.clicked.connect(self._build)
        self.stop_btn.clicked.connect(self._stop)
        self.install_btn.clicked.connect(self._install_pyinstaller)

        btn_row.addWidget(self.build_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addWidget(self.install_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        # Log
        root.addWidget(QLabel("Build log:"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        root.addWidget(self.log, 1)

    def _reload_interpreters(self):
        current = self.interp_combo.currentText()
        self.interp_combo.clear()
        for p in self.manager.interpreters:
            self.interp_combo.addItem(p)
        # restore selection
        default = self.manager.pick_default()
        if current and current in self.manager.interpreters:
            self.interp_combo.setCurrentText(current)
        elif default:
            self.interp_combo.setCurrentText(default)

    def _browse_entry(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select entry Python file", "", "Python Files (*.py)")
        if path:
            self.entry_edit.setText(path)

    def _browse_icon(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select icon", "", "Icons (*.ico)")
        if path:
            self.icon_edit.setText(path)

    def _append(self, text: str):
        self.log.moveCursor(QTextCursor.End)
        self.log.insertPlainText(text)
        self.log.moveCursor(QTextCursor.End)

    def _on_ready(self):
        data = self.proc.readAllStandardOutput().data().decode("utf-8", errors="replace")
        self._append(data)

    def _on_finished(self, code, status):
        self._append(f"\n\n[Process finished] exitCode={code} status={status}\n")
        self.build_btn.setEnabled(True)
        self.install_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def _stop(self):
        if self.proc.state() != QProcess.NotRunning:
            self.proc.kill()

    def _install_pyinstaller(self):
        interp = self.interp_combo.currentText().strip()
        if not interp or not os.path.isfile(interp):
            QMessageBox.warning(self, "No interpreter", "Select a valid Python interpreter first.")
            return

        self.log.clear()
        self._append(f"Installing/updating PyInstaller using:\n  {interp}\n\n")
        self.build_btn.setEnabled(False)
        self.install_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        args = ["-m", "pip", "install", "--upgrade", "pyinstaller"]
        self.proc.start(interp, args)

    def _build(self):
        interp = self.interp_combo.currentText().strip()
        entry = self.entry_edit.text().strip()

        if not interp or not os.path.isfile(interp):
            QMessageBox.warning(self, "No interpreter", "Select a valid Python interpreter first.")
            return
        if not entry or not os.path.isfile(entry):
            QMessageBox.warning(self, "No entry file", "Select a valid entry .py file.")
            return

        args = ["-m", "PyInstaller"]

        if self.onefile_chk.isChecked():
            args.append("--onefile")
        if self.windowed_chk.isChecked():
            args.append("--windowed")
        if self.clean_chk.isChecked():
            args.append("--clean")
        if self.noconfirm_chk.isChecked():
            args.append("--noconfirm")

        icon = self.icon_edit.text().strip()
        if icon:
            if os.path.isfile(icon):
                args += ["--icon", icon]
            else:
                QMessageBox.warning(self, "Icon not found", "The icon path you selected does not exist.")
                return

        args.append(entry)

        self.log.clear()
        self._append("Running:\n")
        self._append(f"  {interp} {' '.join(shlex.quote(a) for a in args)}\n\n")

        self.build_btn.setEnabled(False)
        self.install_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        self.proc.start(interp, args)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(QSize(1100, 700))

        self.app_dir = str(Path(__file__).resolve().parent)
        self.config_path = os.path.join(self.app_dir, CONFIG_NAME)

        self.manager = InterpreterManager(self.config_path)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._update_window_title)

        self.setCentralWidget(self.tabs)

        self.tab_states: dict[int, TabState] = {}

        self._build_console_dock()
        self._build_toolbar()
        self._build_menus()
        self.setStatusBar(QStatusBar())

        self.compiler_win: CompilerWindow | None = None

        self.new_file()

    # ---------- UI building ----------
    def _build_console_dock(self):
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        font = QFont("Consolas" if is_windows() else "Monospace")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(10)
        self.console.setFont(font)

        self.input_line = QLineEdit()
        self.input_line.setPlaceholderText("stdin (press Enter to send to running program)…")
        self.input_line.returnPressed.connect(self._send_stdin)

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(self.console, 1)
        lay.addWidget(self.input_line, 0)

        dock = QDockWidget("Run Output", self)
        dock.setWidget(w)
        dock.setAllowedAreas(Qt.BottomDockWidgetArea | Qt.TopDockWidgetArea)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)

        self.run_proc = QProcess(self)
        self.run_proc.setProcessChannelMode(QProcess.SeparateChannels)
        self.run_proc.readyReadStandardOutput.connect(self._on_run_stdout)
        self.run_proc.readyReadStandardError.connect(self._on_run_stderr)
        self.run_proc.finished.connect(self._on_run_finished)

    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        self.interp_combo = QComboBox()
        self._reload_interpreters()
        self.manager.interpreters_changed.connect(self._reload_interpreters)
        self.interp_combo.currentTextChanged.connect(self._interp_changed)

        tb.addWidget(QLabel("Python: "))
        tb.addWidget(self.interp_combo)

        self.run_btn = QPushButton("Run")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)

        self.run_btn.clicked.connect(self.run_current)
        self.stop_btn.clicked.connect(self.stop_run)

        tb.addSeparator()
        tb.addWidget(self.run_btn)
        tb.addWidget(self.stop_btn)

    def _build_menus(self):
        # File
        m_file = self.menuBar().addMenu("&File")

        a_new = QAction("&New", self)
        a_new.setShortcut(QKeySequence.New)
        a_new.triggered.connect(self.new_file)

        a_open = QAction("&Open…", self)
        a_open.setShortcut(QKeySequence.Open)
        a_open.triggered.connect(self.open_file)

        a_save = QAction("&Save", self)
        a_save.setShortcut(QKeySequence.Save)
        a_save.triggered.connect(self.save_current)

        a_saveas = QAction("Save &As…", self)
        a_saveas.setShortcut(QKeySequence.SaveAs)
        a_saveas.triggered.connect(self.save_current_as)

        a_exit = QAction("E&xit", self)
        a_exit.setShortcut(QKeySequence.Quit)
        a_exit.triggered.connect(self.close)

        m_file.addActions([a_new, a_open, a_save, a_saveas])
        m_file.addSeparator()
        m_file.addAction(a_exit)

        # Run
        m_run = self.menuBar().addMenu("&Run")
        a_run = QAction("&Run", self)
        a_run.setShortcut(QKeySequence("F5"))
        a_run.triggered.connect(self.run_current)

        a_stop = QAction("&Stop", self)
        a_stop.setShortcut(QKeySequence("Shift+F5"))
        a_stop.triggered.connect(self.stop_run)

        m_run.addActions([a_run, a_stop])

        # Tools
        m_tools = self.menuBar().addMenu("&Tools")

        a_add_interp = QAction("Add Python interpreter…", self)
        a_add_interp.triggered.connect(self.add_interpreter)

        a_remove_interp = QAction("Remove selected interpreter", self)
        a_remove_interp.triggered.connect(self.remove_selected_interpreter)

        a_refresh = QAction("Re-discover interpreters", self)
        a_refresh.triggered.connect(self.manager.discover)

        a_compiler = QAction("Open Compiler (PyInstaller)…", self)
        a_compiler.triggered.connect(self.open_compiler_window)

        m_tools.addActions([a_compiler])
        m_tools.addSeparator()
        m_tools.addActions([a_add_interp, a_remove_interp, a_refresh])

        # Help
        m_help = self.menuBar().addMenu("&Help")
        a_about = QAction("&About", self)
        a_about.triggered.connect(self.about)
        m_help.addAction(a_about)

    # ---------- Helpers ----------
    def _reload_interpreters(self):
        current = self.interp_combo.currentText()
        self.interp_combo.blockSignals(True)
        self.interp_combo.clear()
        for p in self.manager.interpreters:
            self.interp_combo.addItem(p)

        default = self.manager.pick_default()
        if current and current in self.manager.interpreters:
            self.interp_combo.setCurrentText(current)
        elif default:
            self.interp_combo.setCurrentText(default)

        self.interp_combo.blockSignals(False)

    def _interp_changed(self, text: str):
        t = text.strip()
        if t and os.path.isfile(t):
            self.manager.last_selected = t
            self.manager.save()

    def current_editor(self) -> CodeEditor | None:
        w = self.tabs.currentWidget()
        if isinstance(w, CodeEditor):
            return w
        return None

    def current_state(self) -> TabState:
        idx = self.tabs.currentIndex()
        if idx not in self.tab_states:
            self.tab_states[idx] = TabState()
        return self.tab_states[idx]

    def _tab_title(self, path: str | None, modified: bool) -> str:
        name = Path(path).name if path else "Untitled.py"
        return f"*{name}" if modified else name

    def _update_tab_text(self, idx: int):
        w = self.tabs.widget(idx)
        if not isinstance(w, CodeEditor):
            return
        st = self.tab_states.get(idx, TabState())
        self.tabs.setTabText(idx, self._tab_title(st.path, w.document().isModified()))
        self._update_window_title()

    def _update_window_title(self):
        ed = self.current_editor()
        st = self.current_state()
        if ed:
            name = st.path if st.path else "Untitled.py"
            star = "*" if ed.document().isModified() else ""
            self.setWindowTitle(f"{APP_NAME} - {Path(name).name}{star}")
        else:
            self.setWindowTitle(APP_NAME)

    def _maybe_save(self, idx: int) -> bool:
        w = self.tabs.widget(idx)
        if not isinstance(w, CodeEditor):
            return True
        if not w.document().isModified():
            return True

        st = self.tab_states.get(idx, TabState())
        name = Path(st.path).name if st.path else "Untitled.py"

        r = QMessageBox.question(
            self,
            "Unsaved changes",
            f"Save changes to {name}?",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
        )
        if r == QMessageBox.Cancel:
            return False
        if r == QMessageBox.No:
            return True
        # Yes
        self.tabs.setCurrentIndex(idx)
        return self.save_current()

    # ---------- File actions ----------
    def new_file(self):
        ed = CodeEditor()
        idx = self.tabs.addTab(ed, "Untitled.py")
        self.tabs.setCurrentIndex(idx)
        self.tab_states[idx] = TabState()

        ed.modified_changed.connect(lambda _m, i=idx: self._update_tab_text(i))
        self._update_tab_text(idx)

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Python file", "", "Python Files (*.py);;All Files (*.*)")
        if not path:
            return
        text = safe_read_text(path)

        ed = CodeEditor()
        ed.set_text(text)
        idx = self.tabs.addTab(ed, "")
        self.tabs.setCurrentIndex(idx)

        self.tab_states[idx] = TabState(path=normpath(path))
        ed.modified_changed.connect(lambda _m, i=idx: self._update_tab_text(i))
        self._update_tab_text(idx)

    def save_current(self) -> bool:
        ed = self.current_editor()
        if not ed:
            return False
        idx = self.tabs.currentIndex()
        st = self.current_state()

        if not st.path:
            return self.save_current_as()

        try:
            safe_write_text(st.path, ed.text())
            ed.document().setModified(False)
            self.statusBar().showMessage(f"Saved: {st.path}", 2500)
            self._update_tab_text(idx)
            return True
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))
            return False

    def save_current_as(self) -> bool:
        ed = self.current_editor()
        if not ed:
            return False
        path, _ = QFileDialog.getSaveFileName(self, "Save Python file", "Untitled.py", "Python Files (*.py)")
        if not path:
            return False

        idx = self.tabs.currentIndex()
        st = self.current_state()
        st.path = normpath(path)

        return self.save_current()

    def close_tab(self, idx: int):
        if not self._maybe_save(idx):
            return
        w = self.tabs.widget(idx)
        self.tabs.removeTab(idx)
        if w:
            w.deleteLater()

        # rebuild state map because indices shift
        new_states: dict[int, TabState] = {}
        for i in range(self.tabs.count()):
            # try to preserve by widget identity; easiest is re-assign sequentially
            # (good enough for starter)
            pass
        # We’ll just rebuild from scratch but keep current states if possible
        # by matching current tab texts to paths (best-effort).
        old_states = self.tab_states
        self.tab_states = {}
        for i in range(self.tabs.count()):
            tab_text = self.tabs.tabText(i).lstrip("*")
            matched = None
            for k, st_old in old_states.items():
                if st_old.path and Path(st_old.path).name == tab_text:
                    matched = st_old
                    break
            self.tab_states[i] = matched if matched else TabState()
            ed = self.tabs.widget(i)
            if isinstance(ed, CodeEditor):
                ed.modified_changed.connect(lambda _m, ii=i: self._update_tab_text(ii))
            self._update_tab_text(i)

        if self.tabs.count() == 0:
            self.new_file()

    # ---------- Run ----------
    def _append_console(self, text: str):
        self.console.moveCursor(QTextCursor.End)
        self.console.insertPlainText(text)
        self.console.moveCursor(QTextCursor.End)

    def _on_run_stdout(self):
        data = self.run_proc.readAllStandardOutput().data().decode("utf-8", errors="replace")
        self._append_console(data)

    def _on_run_stderr(self):
        data = self.run_proc.readAllStandardError().data().decode("utf-8", errors="replace")
        self._append_console(data)

    def _on_run_finished(self, code, status):
        self._append_console(f"\n[Finished] exitCode={code} status={status}\n")
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.statusBar().showMessage("Run finished", 2500)

        # cleanup temp file if we created one
        idx = self.tabs.currentIndex()
        st = self.current_state()
        if st.temp_path and os.path.isfile(st.temp_path):
            try:
                os.remove(st.temp_path)
            except Exception:
                pass
            st.temp_path = None

    def _send_stdin(self):
        if self.run_proc.state() == QProcess.NotRunning:
            return
        line = self.input_line.text()
        self.input_line.clear()
        # Send with newline
        self.run_proc.write((line + "\n").encode("utf-8", errors="replace"))

    def stop_run(self):
        if self.run_proc.state() != QProcess.NotRunning:
            self.run_proc.kill()

    def run_current(self):
        if self.run_proc.state() != QProcess.NotRunning:
            QMessageBox.information(self, "Already running", "A program is already running. Stop it first.")
            return

        ed = self.current_editor()
        if not ed:
            return
        idx = self.tabs.currentIndex()
        st = self.current_state()

        interp = self.interp_combo.currentText().strip()
        if not interp or not os.path.isfile(interp):
            QMessageBox.warning(self, "No interpreter", "Select a valid Python interpreter first.")
            return

        # Determine script path to run
        script_path = st.path
        if script_path and ed.document().isModified():
            # Ask to save (recommended) before running
            r = QMessageBox.question(
                self,
                "Run modified file?",
                "This file has unsaved changes.\n\nSave before running?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
            )
            if r == QMessageBox.Cancel:
                return
            if r == QMessageBox.Yes:
                if not self.save_current():
                    return

        if not st.path:
            # Run unsaved buffer via temp file
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode="w", encoding="utf-8")
            tf.write(ed.text())
            tf.close()
            st.temp_path = tf.name
            script_path = tf.name

        if not script_path:
            QMessageBox.warning(self, "No script", "No script path available to run.")
            return

        # Clear console & run
        self.console.clear()
        self._append_console(f"Running with:\n  {interp}\nScript:\n  {script_path}\n\n")

        args = ["-u", script_path]
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.statusBar().showMessage("Running…")

        self.run_proc.start(interp, args)

    # ---------- Tools ----------
    def add_interpreter(self):
        caption = "Select Python interpreter (python.exe)"
        start = str(Path(sys.executable).parent) if sys.executable else ""
        path, _ = QFileDialog.getOpenFileName(self, caption, start, "Python Executable (python.exe);;All Files (*.*)")
        if path:
            self.manager.add_interpreter(path)
            self.interp_combo.setCurrentText(normpath(path))

    def remove_selected_interpreter(self):
        interp = self.interp_combo.currentText().strip()
        if not interp:
            return
        r = QMessageBox.question(self, "Remove interpreter", f"Remove this interpreter from the list?\n\n{interp}")
        if r == QMessageBox.Yes:
            self.manager.remove_interpreter(interp)

    def open_compiler_window(self):
        if self.compiler_win is None:
            self.compiler_win = CompilerWindow(self.manager, self)
        self.compiler_win.show()
        self.compiler_win.raise_()
        self.compiler_win.activateWindow()

    # ---------- Help ----------
    def about(self):
        # Note: QAction must be imported from PySide6.QtGui (not QtWidgets).
        QMessageBox.information(
            self,
            "About",
            f"{APP_NAME}\n\n"
            "Starter IDE with tabs, interpreter selection, run output console, and a PyInstaller compiler window.\n\n"
            "Tip: On Windows, interpreter auto-discovery uses: py -0p"
        )

    def closeEvent(self, event):
        # prompt save all modified tabs
        for i in range(self.tabs.count()):
            if not self._maybe_save(i):
                event.ignore()
                return
        event.accept()


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
