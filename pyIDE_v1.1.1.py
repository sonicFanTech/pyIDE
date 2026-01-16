import os
import sys
import json
import shlex
import tempfile
import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    Qt, QProcess, QSize, QRect, Signal, QObject, QTimer, QModelIndex
)
from PySide6.QtGui import (
    QAction, QActionGroup, QFont, QTextCursor, QKeySequence,
    QSyntaxHighlighter, QTextCharFormat, QColor,
    QPainter, QPalette, QTextDocument
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QPlainTextEdit, QTabWidget,
    QFileDialog, QMessageBox, QToolBar, QStatusBar, QDockWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QLineEdit, QCheckBox, QFormLayout, QGroupBox, QDialog,
    QDialogButtonBox, QMenu, QTreeView, QFileSystemModel, QSpinBox,
    QCompleter, QListWidget, QListWidgetItem
)

APP_NAME = "SFT PyIDE"
CONFIG_NAME = "pyide_config.json"


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _preferred_config_dir() -> Path:
    # If frozen (PyInstaller EXE), store config next to the EXE.
    if _is_frozen():
        try:
            return Path(sys.executable).resolve().parent
        except Exception:
            return Path.cwd()
    return Path(__file__).resolve().parent


def _fallback_config_dir() -> Path:
    # Fallback if EXE folder isn't writable (e.g., Program Files).
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return Path(base) / "SFT_PyIDE"
    return Path.home() / ".sft_pyide"


def get_config_dir() -> Path:
    d = _preferred_config_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        test_path = d / "._pyide_write_test"
        test_path.write_text("ok", encoding="utf-8")
        try:
            test_path.unlink(missing_ok=True)
        except Exception:
            pass
        return d
    except Exception:
        fd = _fallback_config_dir()
        try:
            fd.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return fd

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


# ----------------------------
# App Config (single JSON)
# ----------------------------
class AppConfig:
    def __init__(self, path: str):
        self.path = path
        self.data = {
            "interpreters": [],
            "last_selected": None,
            "recent_files": [],
            "custom_consoles": [],
            "project": {"root": None},
            "settings": {
                "theme": "dark",                 # dark | light
                "autosave_enabled": True,
                "autosave_interval_sec": 45,
                "recent_files_limit": 10,
                "run_external_console_default": False,
                "external_console": "cmd",
                "completion_enabled": True,
            },
        }
        self.load()
        # Ensure config file exists (especially important when frozen builds run from a temp folder)
        self.save()

    def load(self):
        try:
            if os.path.isfile(self.path):
                d = json.loads(safe_read_text(self.path))
                if isinstance(d, dict):
                    for k, v in d.items():
                        self.data[k] = v

                    self.data.setdefault("settings", {})
                    self.data["settings"] = {
                        **{
                            "theme": "dark",
                            "autosave_enabled": True,
                            "autosave_interval_sec": 45,
                            "recent_files_limit": 10,
                            "run_external_console_default": False,
                            "completion_enabled": True,
                            "external_console": "cmd",
                        },
                        **(self.data.get("settings") or {}),
                    }

                    self.data.setdefault("project", {})
                    self.data["project"] = {**{"root": None}, **(self.data.get("project") or {})}

                    self.data.setdefault("interpreters", [])
                    self.data.setdefault("recent_files", [])
                    self.data.setdefault("custom_consoles", [])
        except Exception:
            pass

    def save(self):
        try:
            safe_write_text(self.path, json.dumps(self.data, indent=2))
        except Exception:
            pass

    @property
    def interpreters(self) -> list[str]:
        return [p for p in (self.data.get("interpreters") or []) if p]

    @interpreters.setter
    def interpreters(self, value: list[str]):
        self.data["interpreters"] = value

    @property
    def last_selected(self) -> Optional[str]:
        return self.data.get("last_selected")

    @last_selected.setter
    def last_selected(self, value: Optional[str]):
        self.data["last_selected"] = value

    def add_recent_file(self, path: str):
        p = normpath(path)
        lst = [x for x in (self.data.get("recent_files") or []) if x]
        lst = [x for x in lst if normpath(x) != p]
        lst.insert(0, p)
        limit = int(self.data.get("settings", {}).get("recent_files_limit", 10) or 10)
        lst = lst[:max(0, limit)]
        self.data["recent_files"] = lst
        self.save()

    def recent_files(self) -> list[str]:
        return [x for x in (self.data.get("recent_files") or []) if x and os.path.exists(x)]

    @property
    def project_root(self) -> Optional[str]:
        root = (self.data.get("project") or {}).get("root")
        return root if root else None

    @project_root.setter
    def project_root(self, value: Optional[str]):
        self.data.setdefault("project", {})
        self.data["project"]["root"] = value
        self.save()

    def setting(self, key: str, default=None):
        return (self.data.get("settings") or {}).get(key, default)

    def set_setting(self, key: str, value):
        self.data.setdefault("settings", {})
        self.data["settings"][key] = value
        self.save()


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
        self.fmt_keyword.setForeground(QColor(86, 156, 214))

        self.fmt_string = QTextCharFormat()
        self.fmt_string.setForeground(QColor(206, 145, 120))

        self.fmt_comment = QTextCharFormat()
        self.fmt_comment.setForeground(QColor(106, 153, 85))

        self.fmt_number = QTextCharFormat()
        self.fmt_number.setForeground(QColor(181, 206, 168))

    def highlightBlock(self, text: str) -> None:
        comment_at = text.find("#")
        if comment_at != -1:
            self.setFormat(comment_at, len(text) - comment_at, self.fmt_comment)

        def highlight_simple_quotes(q: str):
            start = 0
            while True:
                i = text.find(q, start)
                if i == -1:
                    return
                j = text.find(q, i + len(q))
                if j == -1:
                    self.setFormat(i, len(text) - i, self.fmt_string)
                    return
                self.setFormat(i, (j + len(q)) - i, self.fmt_string)
                start = j + len(q)

        highlight_simple_quotes("'''")
        highlight_simple_quotes('"""')
        highlight_simple_quotes("'")
        highlight_simple_quotes('"')

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


class LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self.code_editor = editor

    def sizeHint(self):
        return QSize(self.code_editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.code_editor.line_number_area_paint_event(event)


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

        # Line numbers
        self._line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self._update_line_number_area_width(0)

        # Completion
        self.completion_enabled = True
        self._completer = QCompleter(self)
        self._completer.setWidget(self)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.popup().setMinimumWidth(360)
        self._completer.activated.connect(self._insert_completion)

        self._basic_words = sorted(list(PythonSyntaxHighlighter.KEYWORDS) + dir(__builtins__))

        self._has_jedi = False
        try:
            import jedi  # noqa: F401
            self._has_jedi = True
        except Exception:
            self._has_jedi = False

    # ----- line numbers -----
    def line_number_area_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 10 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(self, rect: QRect, dy: int):
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(0, rect.y(), self._line_number_area.width(), rect.height())

        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def line_number_area_paint_event(self, event):
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), self.palette().color(QPalette.Base).darker(115))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.setPen(self.palette().color(QPalette.Text).darker(130))
                painter.drawText(
                    0,
                    top,
                    self._line_number_area.width() - 6,
                    self.fontMetrics().height(),
                    Qt.AlignRight,
                    number,
                )
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

    # ----- completion -----
    def _current_word_prefix(self) -> str:
        tc = self.textCursor()
        tc.select(QTextCursor.WordUnderCursor)
        return tc.selectedText()

    def _build_completion_list(self) -> list[str]:
        prefix = self._current_word_prefix() or ""

        if self._has_jedi:
            try:
                import jedi
                code = self.toPlainText()
                cursor = self.textCursor()
                line = cursor.block().blockNumber() + 1
                col = cursor.positionInBlock()
                script = jedi.Script(code=code, path=None)
                comps = script.complete(line, col)
                items = []
                for c in comps:
                    name = getattr(c, "name", None)
                    if name and (not prefix or name.lower().startswith(prefix.lower())):
                        items.append(name)
                if items:
                    seen = set()
                    out = []
                    for it in items:
                        if it not in seen:
                            out.append(it)
                            seen.add(it)
                    return out[:250]
            except Exception:
                pass

        if prefix:
            return [w for w in self._basic_words if w.lower().startswith(prefix.lower())][:250]
        return self._basic_words[:250]

    def trigger_completion(self):
        if not self.completion_enabled:
            return
        words = self._build_completion_list()
        if not words:
            return
        from PySide6.QtCore import QStringListModel
        model = QStringListModel(words, self._completer)
        self._completer.setModel(model)

        cr = self.cursorRect()
        cr.setWidth(self._completer.popup().sizeHintForColumn(0) + 24)
        self._completer.complete(cr)

    def _insert_completion(self, completion: str):
        tc = self.textCursor()
        tc.select(QTextCursor.WordUnderCursor)
        tc.removeSelectedText()
        tc.insertText(completion)
        self.setTextCursor(tc)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space and (event.modifiers() & Qt.ControlModifier):
            self.trigger_completion()
            event.accept()
            return

        if self._completer.popup().isVisible():
            if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab):
                event.ignore()
                return

        super().keyPressEvent(event)

    def set_text(self, text: str) -> None:
        self.setPlainText(text)
        self.document().setModified(False)

    def text(self) -> str:
        return self.toPlainText()


@dataclass
class TabState:
    path: str | None = None
    temp_path: str | None = None


class InterpreterManager(QObject):
    interpreters_changed = Signal()

    def __init__(self, config: AppConfig):
        super().__init__()
        self.cfg = config
        self.interpreters: list[str] = []
        self.last_selected: str | None = None
        self.load()

        if not self.interpreters:
            self.discover()
            self.save()

    def load(self):
        self.interpreters = [p for p in (self.cfg.interpreters or []) if p]
        self.last_selected = self.cfg.last_selected

    def save(self):
        self.cfg.interpreters = self.interpreters
        self.cfg.last_selected = self.last_selected
        self.cfg.save()

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
        try:
            found.add(normpath(sys.executable))
        except Exception:
            pass

        if is_windows():
            try:
                out = subprocess.check_output(["py", "-0p"], text=True, stderr=subprocess.STDOUT)
                for line in out.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split()
                    maybe_path = parts[-1]
                    if os.path.isfile(maybe_path) and maybe_path.lower().endswith("python.exe"):
                        found.add(normpath(maybe_path))
            except Exception:
                pass

            candidates = []
            local = os.environ.get("LOCALAPPDATA", "")
            prog = os.environ.get("ProgramFiles", "")
            progx = os.environ.get("ProgramFiles(x86)", "")
            for base in (local, prog, progx):
                if base:
                    candidates += list(Path(base).glob(r"Programs\Python\Python*\python.exe"))
                    candidates += list(Path(base).glob(r"Python*\python.exe"))

            for c in candidates:
                if c.is_file():
                    found.add(normpath(str(c)))
        else:
            for cmd in ("python3", "python"):
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

        root.addWidget(QLabel("Build log:"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        root.addWidget(self.log, 1)

    def _reload_interpreters(self):
        current = self.interp_combo.currentText()
        self.interp_combo.clear()
        for p in self.manager.interpreters:
            self.interp_combo.addItem(p)
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


class FindReplaceDialog(QDialog):
    def __init__(self, parent: "MainWindow"):
        super().__init__(parent)
        self.setWindowTitle("Find / Replace")
        self.setModal(False)
        self.setMinimumWidth(520)
        self.main = parent

        root = QVBoxLayout(self)

        form = QFormLayout()
        self.find_edit = QLineEdit()
        self.replace_edit = QLineEdit()
        form.addRow("Find:", self.find_edit)
        form.addRow("Replace:", self.replace_edit)

        self.case_chk = QCheckBox("Case sensitive")
        self.word_chk = QCheckBox("Whole words")
        opts = QWidget()
        opts_l = QHBoxLayout(opts)
        opts_l.setContentsMargins(0, 0, 0, 0)
        opts_l.addWidget(self.case_chk)
        opts_l.addWidget(self.word_chk)
        opts_l.addStretch(1)

        root.addLayout(form)
        root.addWidget(opts)

        btns_row = QHBoxLayout()
        self.find_next_btn = QPushButton("Find Next")
        self.find_prev_btn = QPushButton("Find Prev")
        self.replace_btn = QPushButton("Replace")
        self.replace_all_btn = QPushButton("Replace All")
        btns_row.addWidget(self.find_next_btn)
        btns_row.addWidget(self.find_prev_btn)
        btns_row.addWidget(self.replace_btn)
        btns_row.addWidget(self.replace_all_btn)
        btns_row.addStretch(1)

        root.addLayout(btns_row)

        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.close)
        root.addWidget(box)

        self.find_next_btn.clicked.connect(lambda: self._find(next_=True))
        self.find_prev_btn.clicked.connect(lambda: self._find(next_=False))
        self.replace_btn.clicked.connect(self._replace_one)
        self.replace_all_btn.clicked.connect(self._replace_all)

        self.find_edit.returnPressed.connect(lambda: self._find(next_=True))

    def _flags(self) -> QTextDocument.FindFlags:
        flags = QTextDocument.FindFlags()
        if self.case_chk.isChecked():
            flags |= QTextDocument.FindCaseSensitively
        if self.word_chk.isChecked():
            flags |= QTextDocument.FindWholeWords
        return flags

    def _find(self, next_: bool):
        ed = self.main.current_editor()
        if not ed:
            return
        needle = self.find_edit.text()
        if not needle:
            return

        flags = self._flags()
        if not next_:
            flags |= QTextDocument.FindBackward

        ok = ed.find(needle, flags)
        if not ok:
            cursor = ed.textCursor()
            cursor.movePosition(QTextCursor.Start if next_ else QTextCursor.End)
            ed.setTextCursor(cursor)
            ok = ed.find(needle, flags)

        if not ok:
            QMessageBox.information(self, "Find", "No matches found.")

    def _replace_one(self):
        ed = self.main.current_editor()
        if not ed:
            return
        needle = self.find_edit.text()
        repl = self.replace_edit.text()
        if not needle:
            return

        tc = ed.textCursor()
        if tc.hasSelection() and tc.selectedText() == needle:
            tc.insertText(repl)
            ed.setTextCursor(tc)
            self._find(next_=True)
        else:
            self._find(next_=True)
            tc = ed.textCursor()
            if tc.hasSelection() and tc.selectedText() == needle:
                tc.insertText(repl)
                ed.setTextCursor(tc)

    def _replace_all(self):
        ed = self.main.current_editor()
        if not ed:
            return
        needle = self.find_edit.text()
        repl = self.replace_edit.text()
        if not needle:
            return

        flags = self._flags()
        cursor = ed.textCursor()
        cursor.movePosition(QTextCursor.Start)
        ed.setTextCursor(cursor)

        count = 0
        while ed.find(needle, flags):
            tc = ed.textCursor()
            tc.insertText(repl)
            count += 1

        QMessageBox.information(self, "Replace All", f"Replaced {count} occurrence(s).")


class SettingsDialog(QDialog):
    def __init__(self, parent: "MainWindow"):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(QSize(520, 280))
        self.main = parent

        root = QVBoxLayout(self)
        form = QFormLayout()

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["dark", "light"])
        self.theme_combo.setCurrentText(str(self.main.cfg.setting("theme", "dark")))

        self.autosave_chk = QCheckBox("Enable auto-save")
        self.autosave_chk.setChecked(bool(self.main.cfg.setting("autosave_enabled", True)))

        self.autosave_spin = QSpinBox()
        self.autosave_spin.setRange(5, 3600)
        self.autosave_spin.setSuffix(" sec")
        self.autosave_spin.setValue(int(self.main.cfg.setting("autosave_interval_sec", 45) or 45))

        self.recent_spin = QSpinBox()
        self.recent_spin.setRange(0, 50)
        self.recent_spin.setValue(int(self.main.cfg.setting("recent_files_limit", 10) or 10))

        self.external_console_chk = QCheckBox("Run in external console by default (for CLI/curses apps)")
        self.external_console_chk.setChecked(bool(self.main.cfg.setting("run_external_console_default", False)))

        self.completion_chk = QCheckBox("Enable autocomplete (Ctrl+Space)")
        self.completion_chk.setChecked(bool(self.main.cfg.setting("completion_enabled", True)))

        form.addRow("Theme:", self.theme_combo)
        form.addRow("", self.autosave_chk)
        form.addRow("Auto-save interval:", self.autosave_spin)
        form.addRow("Recent files limit:", self.recent_spin)
        form.addRow("", self.external_console_chk)
        form.addRow("", self.completion_chk)

        root.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _save(self):
        self.main.cfg.set_setting("theme", self.theme_combo.currentText().strip())
        self.main.cfg.set_setting("autosave_enabled", bool(self.autosave_chk.isChecked()))
        self.main.cfg.set_setting("autosave_interval_sec", int(self.autosave_spin.value()))
        self.main.cfg.set_setting("recent_files_limit", int(self.recent_spin.value()))
        self.main.cfg.set_setting("run_external_console_default", bool(self.external_console_chk.isChecked()))
        self.main.cfg.set_setting("completion_enabled", bool(self.completion_chk.isChecked()))

        self.main.apply_theme()
        self.main.configure_autosave_timer()
        self.main.refresh_recent_files_menu()

        for i in range(self.main.tabs.count()):
            ed = self.main.tabs.widget(i)
            if isinstance(ed, CodeEditor):
                ed.completion_enabled = bool(self.main.cfg.setting("completion_enabled", True))

        self.accept()




class ManageExternalConsolesDialog(QDialog):
    def __init__(self, parent: "MainWindow"):
        super().__init__(parent)
        self.setWindowTitle("Manage External Consoles")
        self.setMinimumSize(QSize(680, 380))
        self.main = parent

        root = QHBoxLayout(self)

        # Left: list
        left = QVBoxLayout()
        self.listw = QListWidget()
        left.addWidget(QLabel("Custom consoles:"))
        left.addWidget(self.listw, 1)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("Add")
        self.del_btn = QPushButton("Remove")
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.del_btn)
        btn_row.addStretch(1)
        left.addLayout(btn_row)

        root.addLayout(left, 1)

        # Right: editor
        right = QVBoxLayout()
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.exe_edit = QLineEdit()
        self.exe_browse = QPushButton("Browse…")
        exe_row = QWidget()
        exe_l = QHBoxLayout(exe_row)
        exe_l.setContentsMargins(0, 0, 0, 0)
        exe_l.addWidget(self.exe_edit)
        exe_l.addWidget(self.exe_browse)

        self.args_edit = QLineEdit()
        self.args_edit.setPlaceholderText('Example: /cmd {command}   (placeholders: {command}, {cmd_wrapper}, {ps_wrapper}, {workdir})')

        form.addRow("Name:", self.name_edit)
        form.addRow("Console EXE:", exe_row)
        form.addRow("Args template:", self.args_edit)

        right.addLayout(form)
        right.addWidget(QLabel(
            "Notes:\n"
            "• Args template is optional but usually needed for 3rd-party consoles.\n"
            "• {command} is a ready-to-run command line (cmd /k ...).\n"
            "• {cmd_wrapper}/{ps_wrapper} are the wrapper script paths.\n"
            "• {workdir} is the script folder."
        ))

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        right.addWidget(buttons)
        root.addLayout(right, 2)

        buttons.accepted.connect(self._save_all)
        buttons.rejected.connect(self.close)
        self.add_btn.clicked.connect(self._add_item)
        self.del_btn.clicked.connect(self._remove_item)
        self.exe_browse.clicked.connect(self._browse_exe)
        self.listw.currentRowChanged.connect(self._load_selected)

        self._reload_list()

    def _cfg_list(self):
        lst = self.main.cfg.data.get("custom_consoles") or []
        if not isinstance(lst, list):
            lst = []
        return lst

    def _reload_list(self):
        self.listw.clear()
        for item in self._cfg_list():
            name = str(item.get("name") or "(Unnamed)")
            self.listw.addItem(name)
        if self.listw.count() > 0:
            self.listw.setCurrentRow(0)
        else:
            self._clear_fields()

    def _clear_fields(self):
        self.name_edit.setText("")
        self.exe_edit.setText("")
        self.args_edit.setText("")

    def _load_selected(self, row: int):
        lst = self._cfg_list()
        if row < 0 or row >= len(lst):
            self._clear_fields()
            return
        item = lst[row]
        self.name_edit.setText(str(item.get("name") or ""))
        self.exe_edit.setText(str(item.get("path") or ""))
        self.args_edit.setText(str(item.get("args") or ""))

    def _apply_fields_to_selected(self):
        row = self.listw.currentRow()
        lst = self._cfg_list()
        if row < 0 or row >= len(lst):
            return
        lst[row] = {
            "name": self.name_edit.text().strip() or "Custom Console",
            "path": self.exe_edit.text().strip(),
            "args": self.args_edit.text().strip(),
        }
        self.main.cfg.data["custom_consoles"] = lst

    def _save_all(self):
        self._apply_fields_to_selected()
        self.main.cfg.save()
        self._reload_list()
        # refresh menu in main window
        self.main.refresh_external_console_menu()

    def _add_item(self):
        lst = self._cfg_list()
        lst.append({"name": "Custom Console", "path": "", "args": ""})
        self.main.cfg.data["custom_consoles"] = lst
        self.main.cfg.save()
        self._reload_list()
        self.listw.setCurrentRow(self.listw.count() - 1)
        self.main.refresh_external_console_menu()

    def _remove_item(self):
        row = self.listw.currentRow()
        lst = self._cfg_list()
        if row < 0 or row >= len(lst):
            return
        lst.pop(row)
        self.main.cfg.data["custom_consoles"] = lst
        self.main.cfg.save()
        self._reload_list()
        self.main.refresh_external_console_menu()

    def _browse_exe(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select console executable", "", "Executables (*.exe);;All Files (*.*)")
        if path:
            self.exe_edit.setText(path)
            self._apply_fields_to_selected()
            self.main.cfg.save()
            self.main.refresh_external_console_menu()


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.setMinimumSize(QSize(520, 260))

        root = QVBoxLayout(self)
        title = QLabel(f"<b style='font-size:16px'>{APP_NAME}</b>")
        root.addWidget(title)

        body = QLabel(
            "A lightweight Python IDE with tabs, interpreter selection, a run-output dock, "
            "and a PyInstaller compiler window.\n\n"
            "New in this update:\n"
            "• Line numbers\n"
            "• Find/Replace (Ctrl+F / Ctrl+H)\n"
            "• Project file manager dock (View menu)\n"
            "• Auto-save + Recent files\n"
            "• Dark mode (default) + settings\n"
            "• Autocomplete (Ctrl+Space)\n"
            "• External console run mode for CLI/curses apps\n\n"
            "Tip: On Windows, interpreter auto-discovery uses:  py -0p"
        )
        body.setWordWrap(True)
        root.addWidget(body, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.close)
        root.addWidget(btns)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(QSize(1180, 760))

        self.app_dir = str(get_config_dir())
        self.config_path = os.path.join(self.app_dir, CONFIG_NAME)
        self.cfg = AppConfig(self.config_path)

        self.manager = InterpreterManager(self.cfg)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._update_window_title)
        self.setCentralWidget(self.tabs)

        self.tab_states: dict[int, TabState] = {}

        self._build_console_dock()
        self._build_project_dock()
        self._build_toolbar()
        self._build_menus()
        self.setStatusBar(QStatusBar())

        self.compiler_win: Optional[CompilerWindow] = None
        self.find_dialog: Optional[FindReplaceDialog] = None

        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self._autosave_tick)
        self.configure_autosave_timer()

        self.apply_theme()

        if self.cfg.project_root and os.path.isdir(self.cfg.project_root):
            self.set_project_root(self.cfg.project_root)
        else:
            self.project_dock.hide()
            if hasattr(self, 'a_toggle_project'):
                self.a_toggle_project.setChecked(False)

        self.new_file()

    # ---------- Theme ----------
    def apply_theme(self):
        """Apply light/dark theme.
        Uses Fusion style so the palette is respected across platforms, then applies a small stylesheet
        to keep common widgets consistent (menus, docks, editors, tree views, etc).
        """
        theme = str(self.cfg.setting("theme", "dark")).lower().strip()
        app = QApplication.instance()
        if not app:
            return

        # Fusion respects custom palettes better than the native styles on many systems.
        try:
            app.setStyle("Fusion")
        except Exception:
            pass

        if theme == "light":
            app.setPalette(app.style().standardPalette())
            app.setStyleSheet("")
        else:
            pal = QPalette()
            pal.setColor(QPalette.Window, QColor(37, 37, 38))
            pal.setColor(QPalette.WindowText, QColor(220, 220, 220))
            pal.setColor(QPalette.Base, QColor(30, 30, 30))
            pal.setColor(QPalette.AlternateBase, QColor(37, 37, 38))
            pal.setColor(QPalette.ToolTipBase, QColor(30, 30, 30))
            pal.setColor(QPalette.ToolTipText, QColor(220, 220, 220))
            pal.setColor(QPalette.Text, QColor(220, 220, 220))
            pal.setColor(QPalette.Button, QColor(45, 45, 48))
            pal.setColor(QPalette.ButtonText, QColor(220, 220, 220))
            pal.setColor(QPalette.BrightText, QColor(255, 0, 0))
            pal.setColor(QPalette.Link, QColor(86, 156, 214))
            pal.setColor(QPalette.Highlight, QColor(86, 156, 214))
            # IMPORTANT: highlighted text should be bright on the blue highlight
            pal.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
            app.setPalette(pal)

            # Keep a consistent dark theme for common widgets.
            app.setStyleSheet("""
                QMainWindow, QWidget { background: #252526; color: #DCDCDC; }
                QMenuBar, QMenuBar::item { background: #2D2D30; color: #DCDCDC; }
                QMenuBar::item:selected { background: #3E3E42; }
                QMenu { background: #2D2D30; color: #DCDCDC; }
                QMenu::item:selected { background: #094771; }
                QToolBar { background: #2D2D30; border: 0px; }
                QStatusBar { background: #2D2D30; color: #DCDCDC; }
                QDockWidget::title { background: #2D2D30; padding: 4px; }
                QTabWidget::pane { border: 1px solid #3E3E42; }
                QTabBar::tab { background: #2D2D30; padding: 6px 10px; border: 1px solid #3E3E42; }
                QTabBar::tab:selected { background: #1E1E1E; }
                QPlainTextEdit, QTextEdit { background: #1E1E1E; color: #DCDCDC; selection-background-color: #094771; }
                QLineEdit { background: #1E1E1E; color: #DCDCDC; border: 1px solid #3E3E42; padding: 4px; }
                QTreeView { background: #1E1E1E; color: #DCDCDC; selection-background-color: #094771; }
                QComboBox, QSpinBox { background: #1E1E1E; color: #DCDCDC; border: 1px solid #3E3E42; padding: 3px; }
                QPushButton { background: #3E3E42; color: #DCDCDC; border: 1px solid #555; padding: 5px 10px; }
                QPushButton:hover { background: #4B4B50; }
                QPushButton:pressed { background: #2D2D30; }
            """)

        # propagate completion setting
        for i in range(self.tabs.count()):
            ed = self.tabs.widget(i)
            if isinstance(ed, CodeEditor):
                ed.completion_enabled = bool(self.cfg.setting("completion_enabled", True))


    # ---------- Auto save ----------
    def configure_autosave_timer(self):
        enabled = bool(self.cfg.setting("autosave_enabled", True))
        sec = int(self.cfg.setting("autosave_interval_sec", 45) or 45)
        if enabled:
            self.autosave_timer.start(max(5, sec) * 1000)
        else:
            self.autosave_timer.stop()

    def _autosave_tick(self):
        for i in range(self.tabs.count()):
            ed = self.tabs.widget(i)
            if not isinstance(ed, CodeEditor):
                continue
            st = self.tab_states.get(i, TabState())
            if st.path and ed.document().isModified():
                try:
                    safe_write_text(st.path, ed.text())
                    ed.document().setModified(False)
                    self.tabs.setTabText(i, self._tab_title(st.path, False))
                except Exception:
                    pass

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

        self.console_dock = QDockWidget("Run Output", self)
        self.console_dock.setWidget(w)
        self.console_dock.setAllowedAreas(Qt.BottomDockWidgetArea | Qt.TopDockWidgetArea)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.console_dock)

        self.run_proc = QProcess(self)
        self.run_proc.setProcessChannelMode(QProcess.SeparateChannels)
        self.run_proc.readyReadStandardOutput.connect(self._on_run_stdout)
        self.run_proc.readyReadStandardError.connect(self._on_run_stderr)
        self.run_proc.finished.connect(self._on_run_finished)
        # Syntax check / diagnostics runner (lightweight "LSP-like" helper)
        self.lint_proc = QProcess(self)
        self._lint_temp_path = None
        self.lint_proc.setProcessChannelMode(QProcess.MergedChannels)
        self.lint_proc.readyReadStandardOutput.connect(self._on_lint_output)
        self.lint_proc.finished.connect(self._on_lint_finished)

    def _build_project_dock(self):
        self.fs_model = QFileSystemModel(self)
        self.fs_model.setReadOnly(False)
        self.fs_model.setRootPath(self.cfg.project_root or str(Path.home()))

        self.project_tree = QTreeView()
        self.project_tree.setModel(self.fs_model)
        self.project_tree.doubleClicked.connect(self._on_project_double_click)
        self.project_tree.setSortingEnabled(True)
        self.project_tree.sortByColumn(0, Qt.AscendingOrder)
        self.project_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.project_tree.customContextMenuRequested.connect(self._on_project_context_menu)

        self.project_dock = QDockWidget("Project", self)
        self.project_dock.setWidget(self.project_tree)
        self.project_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.project_dock)

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

        self.run_btn.clicked.connect(self.run_current_default)
        self.stop_btn.clicked.connect(self.stop_run)

        tb.addSeparator()
        tb.addWidget(self.run_btn)
        tb.addWidget(self.stop_btn)

    def _build_menus(self):
        self.m_file = self.menuBar().addMenu("&File")

        a_new = QAction("&New", self)
        a_new.setShortcut(QKeySequence.New)
        a_new.triggered.connect(self.new_file)

        a_open = QAction("&Open…", self)
        a_open.setShortcut(QKeySequence.Open)
        a_open.triggered.connect(self.open_file_dialog)

        a_open_proj = QAction("Open &Project Folder…", self)
        a_open_proj.setShortcut(QKeySequence("Ctrl+Shift+O"))
        a_open_proj.triggered.connect(self.open_project_folder_dialog)

        a_save = QAction("&Save", self)
        a_save.setShortcut(QKeySequence.Save)
        a_save.triggered.connect(self.save_current)

        a_saveas = QAction("Save &As…", self)
        a_saveas.setShortcut(QKeySequence.SaveAs)
        a_saveas.triggered.connect(self.save_current_as)

        self.recent_menu = self.m_file.addMenu("Recent Files")
        self.refresh_recent_files_menu()

        a_exit = QAction("E&xit", self)
        a_exit.setShortcut(QKeySequence.Quit)
        a_exit.triggered.connect(self.close)

        self.m_file.addActions([a_new, a_open, a_open_proj])
        self.m_file.addSeparator()
        self.m_file.addActions([a_save, a_saveas])
        self.m_file.addSeparator()
        self.m_file.addMenu(self.recent_menu)
        self.m_file.addSeparator()
        self.m_file.addAction(a_exit)

        m_edit = self.menuBar().addMenu("&Edit")
        a_find = QAction("&Find…", self)
        a_find.setShortcut(QKeySequence("Ctrl+F"))
        a_find.triggered.connect(self.open_find_dialog)

        a_replace = QAction("&Replace…", self)
        a_replace.setShortcut(QKeySequence("Ctrl+H"))
        a_replace.triggered.connect(self.open_find_dialog)

        m_edit.addActions([a_find, a_replace])

        m_view = self.menuBar().addMenu("&View")
        self.a_toggle_project = QAction("Project File Manager", self, checkable=True)
        self.a_toggle_project.setChecked(True)
        self.a_toggle_project.triggered.connect(lambda checked: self.project_dock.setVisible(checked))
        self.a_toggle_output = QAction("Run Output", self, checkable=True)
        self.a_toggle_output.setChecked(True)
        self.a_toggle_output.triggered.connect(lambda checked: self.console_dock.setVisible(checked))
        m_view.addActions([self.a_toggle_project, self.a_toggle_output])

        m_run = self.menuBar().addMenu("&Run")
        a_run = QAction("&Run", self)
        a_run.setShortcut(QKeySequence("F5"))
        a_run.triggered.connect(self.run_current_default)

        a_run_console = QAction("Run in External &Console", self)
        a_run_console.setShortcut(QKeySequence("Ctrl+F5"))
        a_run_console.triggered.connect(self.run_in_external_console)

        # External console selection submenu
        self.external_console_menu = QMenu("External Console", self)
        self.external_console_group = QActionGroup(self)
        self.external_console_group.setExclusive(True)
        self.refresh_external_console_menu()

        a_stop = QAction("&Stop", self)
        a_stop.setShortcut(QKeySequence("Shift+F5"))
        a_stop.triggered.connect(self.stop_run)

        m_run.addAction(a_run)
        m_run.addAction(a_run_console)
        m_run.addMenu(self.external_console_menu)
        m_run.addAction(a_stop)

        m_tools = self.menuBar().addMenu("&Tools")
        a_settings = QAction("&Settings…", self)
        a_settings.triggered.connect(self.open_settings)

        a_manage_consoles = QAction("Manage External Consoles…", self)
        a_manage_consoles.triggered.connect(self.open_manage_external_consoles)

        a_add_interp = QAction("Add Python interpreter…", self)
        a_add_interp.triggered.connect(self.add_interpreter)

        a_remove_interp = QAction("Remove selected interpreter", self)
        a_remove_interp.triggered.connect(self.remove_selected_interpreter)

        a_refresh = QAction("Re-discover interpreters", self)
        a_refresh.triggered.connect(self.manager.discover)

        a_compiler = QAction("Open Compiler (PyInstaller)…", self)
        a_compiler.triggered.connect(self.open_compiler_window)

        m_tools.addAction(a_settings)
        m_tools.addAction(a_manage_consoles)
        a_syntax = QAction("Check Syntax (py_compile)…", self)
        a_syntax.setShortcut(QKeySequence("Ctrl+K"))
        a_syntax.triggered.connect(self.check_syntax_current)
        m_tools.addAction(a_syntax)
        m_tools.addSeparator()
        m_tools.addAction(a_compiler)
        m_tools.addSeparator()
        m_tools.addActions([a_add_interp, a_remove_interp, a_refresh])

        m_help = self.menuBar().addMenu("&Help")
        a_about = QAction("&About", self)
        a_about.triggered.connect(self.about)
        m_help.addAction(a_about)

    # ---------- Recent Files ----------
    def refresh_recent_files_menu(self):
        self.recent_menu.clear()
        recent = self.cfg.recent_files()
        if not recent:
            a_none = QAction("(No recent files)", self)
            a_none.setEnabled(False)
            self.recent_menu.addAction(a_none)
            return

        for p in recent:
            act = QAction(p, self)
            act.triggered.connect(lambda _=False, pp=p: self.open_file_from_path(pp))
            self.recent_menu.addAction(act)

        self.recent_menu.addSeparator()
        clear_act = QAction("Clear Recent Files", self)
        clear_act.triggered.connect(self._clear_recent_files)
        self.recent_menu.addAction(clear_act)

    def _clear_recent_files(self):
        self.cfg.data["recent_files"] = []
        self.cfg.save()
        self.refresh_recent_files_menu()

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

    def current_editor(self) -> Optional[CodeEditor]:
        w = self.tabs.currentWidget()
        return w if isinstance(w, CodeEditor) else None

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
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
        )
        if r == QMessageBox.Cancel:
            return False
        if r == QMessageBox.No:
            return True
        self.tabs.setCurrentIndex(idx)
        return self.save_current()

    # ---------- File actions ----------
    def new_file(self):
        ed = CodeEditor()
        ed.completion_enabled = bool(self.cfg.setting("completion_enabled", True))
        idx = self.tabs.addTab(ed, "Untitled.py")
        self.tabs.setCurrentIndex(idx)
        self.tab_states[idx] = TabState()
        ed.modified_changed.connect(lambda _m, i=idx: self._update_tab_text(i))
        self._update_tab_text(idx)

    def open_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open file", "", "Python Files (*.py);;All Files (*.*)")
        if path:
            self.open_file_from_path(path)

    def open_file_from_path(self, path: str):
        if not path or not os.path.isfile(path):
            return
        try:
            text = safe_read_text(path)
        except Exception as e:
            QMessageBox.critical(self, "Open failed", str(e))
            return

        ed = CodeEditor()
        ed.completion_enabled = bool(self.cfg.setting("completion_enabled", True))
        ed.set_text(text)
        idx = self.tabs.addTab(ed, "")
        self.tabs.setCurrentIndex(idx)

        self.tab_states[idx] = TabState(path=normpath(path))
        ed.modified_changed.connect(lambda _m, i=idx: self._update_tab_text(i))
        self._update_tab_text(idx)

        self.cfg.add_recent_file(path)
        self.refresh_recent_files_menu()

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
            self.cfg.add_recent_file(st.path)
            self.refresh_recent_files_menu()
            return True
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))
            return False

    def save_current_as(self) -> bool:
        ed = self.current_editor()
        if not ed:
            return False
        path, _ = QFileDialog.getSaveFileName(self, "Save file", "Untitled.py", "Python Files (*.py);;All Files (*.*)")
        if not path:
            return False

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

        old_states = self.tab_states
        self.tab_states = {}
        for i in range(self.tabs.count()):
            tab_text = self.tabs.tabText(i).lstrip("*")
            matched = None
            for st_old in old_states.values():
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

    # ---------- Project ----------
    def open_project_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, "Select project folder", self.cfg.project_root or "")
        if folder:
            self.set_project_root(folder)

    def set_project_root(self, folder: str):
        folder = normpath(folder)
        if not os.path.isdir(folder):
            return
        self.cfg.project_root = folder
        self.fs_model.setRootPath(folder)
        self.project_tree.setRootIndex(self.fs_model.index(folder))
        self.project_tree.setColumnHidden(1, True)
        self.project_tree.setColumnHidden(2, True)
        self.project_tree.setColumnHidden(3, True)
        self.project_dock.show()
        self.a_toggle_project.setChecked(True)
        self.statusBar().showMessage(f"Project set: {folder}", 2500)

    def _on_project_double_click(self, index):
        if not index or not index.isValid():
            return
        path = self.fs_model.filePath(index)
        if os.path.isfile(path):
            self.open_file_from_path(path)

    def _on_project_context_menu(self, pos):
        # Right-click menu for managing project files/folders
        index = self.project_tree.indexAt(pos)
        if index.isValid():
            target_path = self.fs_model.filePath(index)
        else:
            target_path = self.cfg.project_root

        if not target_path:
            return

        menu = QMenu(self)
        a_new_file = QAction("New File…", self)
        a_new_folder = QAction("New Folder…", self)
        a_rename = QAction("Rename…", self)
        a_delete = QAction("Delete", self)
        a_reveal = QAction("Open in File Explorer", self)

        a_new_file.triggered.connect(lambda: self._project_new_file(target_path))
        a_new_folder.triggered.connect(lambda: self._project_new_folder(target_path))
        a_rename.triggered.connect(lambda: self._project_rename(target_path))
        a_delete.triggered.connect(lambda: self._project_delete(target_path))
        a_reveal.triggered.connect(lambda: self._project_reveal(target_path))

        menu.addAction(a_new_file)
        menu.addAction(a_new_folder)
        menu.addSeparator()

        # Only allow rename/delete when a specific item is selected and it is not the root folder
        if index.isValid() and self.cfg.project_root and normpath(target_path) != normpath(self.cfg.project_root):
            menu.addAction(a_rename)
            menu.addAction(a_delete)
            menu.addSeparator()

        menu.addAction(a_reveal)
        menu.exec(self.project_tree.viewport().mapToGlobal(pos))

    def _project_target_dir(self, path: str) -> str:
        return path if os.path.isdir(path) else str(Path(path).parent)

    def _project_new_file(self, path: str):
        target_dir = self._project_target_dir(path)
        name, ok = self._simple_text_prompt("New File", "File name (e.g., main.py):", "main.py")
        if not ok or not name.strip():
            return
        fp = os.path.join(target_dir, name.strip())
        if os.path.exists(fp):
            QMessageBox.warning(self, "Exists", "That file already exists.")
            return
        try:
            safe_write_text(fp, "")
        except Exception as e:
            QMessageBox.critical(self, "Create failed", str(e))

    def _project_new_folder(self, path: str):
        target_dir = self._project_target_dir(path)
        name, ok = self._simple_text_prompt("New Folder", "Folder name:", "NewFolder")
        if not ok or not name.strip():
            return
        fp = os.path.join(target_dir, name.strip())
        if os.path.exists(fp):
            QMessageBox.warning(self, "Exists", "That folder already exists.")
            return
        try:
            os.makedirs(fp, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, "Create failed", str(e))

    def _project_rename(self, path: str):
        base = Path(path).name
        name, ok = self._simple_text_prompt("Rename", "New name:", base)
        if not ok or not name.strip():
            return
        new_path = str(Path(path).parent / name.strip())
        try:
            os.rename(path, new_path)
        except Exception as e:
            QMessageBox.critical(self, "Rename failed", str(e))

    def _project_delete(self, path: str):
        if self.cfg.project_root and normpath(path) == normpath(self.cfg.project_root):
            return
        r = QMessageBox.question(self, "Delete", f"Delete this?\n\n{path}", QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        try:
            if os.path.isdir(path):
                import shutil
                shutil.rmtree(path)
            else:
                os.remove(path)
        except Exception as e:
            QMessageBox.critical(self, "Delete failed", str(e))

    def _project_reveal(self, path: str):
        try:
            if is_windows():
                subprocess.Popen(["explorer", "/select,", path])
            else:
                subprocess.Popen(["xdg-open", str(Path(path).parent if os.path.isfile(path) else path)])
        except Exception:
            pass

    def _simple_text_prompt(self, title: str, label: str, default: str = ""):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(label))
        edit = QLineEdit(default)
        lay.addWidget(edit)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        lay.addWidget(btns)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        ok = dlg.exec() == QDialog.Accepted
        return edit.text(), ok

    # ---------- Find/Replace ----------
    def open_find_dialog(self):
        if self.find_dialog is None:
            self.find_dialog = FindReplaceDialog(self)
        self.find_dialog.show()
        self.find_dialog.raise_()
        self.find_dialog.activateWindow()



    # ---------- External Console Selection ----------
    def _windows_cmd_path(self) -> str:
        return os.environ.get("ComSpec") or "cmd.exe"

    def _windows_powershell_path(self) -> Optional[str]:
        # Windows PowerShell 5
        sysroot = os.environ.get("SystemRoot") or "C:\\Windows"
        p = Path(sysroot) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        return str(p) if p.is_file() else None

    def _windows_pwsh_path(self) -> Optional[str]:
        p = shutil.which("pwsh")
        if p:
            return p
        # Common install locations
        prog = os.environ.get("ProgramFiles")
        if prog:
            cand = Path(prog) / "PowerShell" / "7" / "pwsh.exe"
            if cand.is_file():
                return str(cand)
        return None

    def _windows_terminal_path(self) -> Optional[str]:
        p = shutil.which("wt")
        if p:
            return p
        local = os.environ.get("LOCALAPPDATA")
        if local:
            cand = Path(local) / "Microsoft" / "WindowsApps" / "wt.exe"
            if cand.is_file():
                return str(cand)
        return None

    def _external_console_choice(self) -> str:
        return str(self.cfg.setting("external_console", "cmd") or "cmd")

    def _set_external_console_choice(self, choice: str):
        self.cfg.set_setting("external_console", choice)
        self.refresh_external_console_menu()

    def refresh_external_console_menu(self):
        if not hasattr(self, 'external_console_menu'):
            return
        self.external_console_menu.clear()

        choice = self._external_console_choice()

        wt = self._windows_terminal_path() if is_windows() else None
        ps = self._windows_powershell_path() if is_windows() else None
        pwsh = self._windows_pwsh_path() if is_windows() else None

        items = [
            ("cmd", "Command Prompt (cmd.exe)", True),
            ("powershell", "Windows PowerShell", bool(ps)),
            ("pwsh", "PowerShell 7 (pwsh)", bool(pwsh)),
            ("wt_cmd", "Windows Terminal (cmd)", bool(wt)),
            ("wt_powershell", "Windows Terminal (PowerShell)", bool(wt and ps)),
            ("wt_pwsh", "Windows Terminal (pwsh)", bool(wt and pwsh)),
        ]

        # Custom consoles
        custom_list = self.cfg.data.get("custom_consoles") or []
        if not isinstance(custom_list, list):
            custom_list = []

        # If chosen console is unavailable, fall back to cmd
        available_ids = {cid for cid, _label, enabled in items if enabled}
        for idx, c in enumerate(custom_list):
            cid = f"custom:{idx}"
            exe = str(c.get("path") or "")
            enabled = bool(exe and os.path.isfile(exe))
            if enabled:
                available_ids.add(cid)

        if choice not in available_ids:
            choice = "cmd"
            self.cfg.set_setting("external_console", "cmd")

        for cid, label, enabled in items:
            act = QAction(label, self)
            act.setCheckable(True)
            act.setEnabled(enabled)
            act.setChecked(choice == cid)
            self.external_console_group.addAction(act)
            act.triggered.connect(lambda _=False, c=cid: self._set_external_console_choice(c))
            self.external_console_menu.addAction(act)

        if custom_list:
            self.external_console_menu.addSeparator()
            for idx, c in enumerate(custom_list):
                name = str(c.get("name") or f"Custom {idx+1}")
                exe = str(c.get("path") or "")
                enabled = bool(exe and os.path.isfile(exe))
                cid = f"custom:{idx}"
                act = QAction(name, self)
                act.setCheckable(True)
                act.setEnabled(enabled)
                act.setChecked(choice == cid)
                self.external_console_group.addAction(act)
                act.triggered.connect(lambda _=False, cc=cid: self._set_external_console_choice(cc))
                self.external_console_menu.addAction(act)

        self.external_console_menu.addSeparator()
        manage = QAction("Manage External Consoles…", self)
        manage.triggered.connect(self.open_manage_external_consoles)
        self.external_console_menu.addAction(manage)

    def open_manage_external_consoles(self):
        dlg = ManageExternalConsolesDialog(self)
        dlg.exec()

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

        st = self.current_state()
        if st.temp_path and os.path.isfile(st.temp_path):
            try:
                os.remove(st.temp_path)
            except Exception:
                pass
            st.temp_path = None

    def _on_lint_output(self):
        data = self.lint_proc.readAllStandardOutput().data().decode("utf-8", errors="replace")
        self._append_console(data)

    def _on_lint_finished(self, code, status):
        if code == 0:
            self._append_console("\n[Syntax check] OK\n")
        else:
            self._append_console(f"\n[Syntax check] exitCode={code} status={status}\n")
        # cleanup temp file used for this check (if any)
        if getattr(self, "_lint_temp_path", None) and os.path.isfile(self._lint_temp_path):
            try:
                os.remove(self._lint_temp_path)
            except Exception:
                pass
        self._lint_temp_path = None

        self.statusBar().showMessage("Syntax check finished", 2500)

    def check_syntax_current(self):
        if self.lint_proc.state() != QProcess.NotRunning:
            QMessageBox.information(self, "Syntax check", "A syntax check is already running.")
            return

        interp = self.interp_combo.currentText().strip()
        if not interp or not os.path.isfile(interp):
            QMessageBox.warning(self, "No interpreter", "Select a valid Python interpreter first.")
            return

        ed = self.current_editor()
        if not ed:
            return

        # Use a temp file if the buffer isn't saved or has unsaved changes
        st = self.current_state()
        script_path = st.path
        self._lint_temp_path = None

        if not script_path or ed.document().isModified():
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode="w", encoding="utf-8")
            tf.write(ed.text())
            tf.close()
            self._lint_temp_path = tf.name
            script_path = tf.name

        self.console.clear()
        self._append_console(f"Checking syntax with:\n  {interp}\nFile:\n  {script_path}\n\n")

        self.lint_proc.start(interp, ["-m", "py_compile", script_path])

    def _send_stdin(self):
        if self.run_proc.state() == QProcess.NotRunning:
            return
        line = self.input_line.text()
        self.input_line.clear()
        self.run_proc.write((line + "\n").encode("utf-8", errors="replace"))

    def stop_run(self):
        if self.run_proc.state() != QProcess.NotRunning:
            self.run_proc.kill()

    def run_current_default(self):
        if bool(self.cfg.setting("run_external_console_default", False)):
            self.run_in_external_console()
        else:
            self.run_current_internal()

    def _resolve_script_to_run(self) -> Optional[str]:
        ed = self.current_editor()
        if not ed:
            return None
        st = self.current_state()

        script_path = st.path
        if script_path and ed.document().isModified():
            r = QMessageBox.question(
                self,
                "Run modified file?",
                "This file has unsaved changes.\n\nSave before running?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            )
            if r == QMessageBox.Cancel:
                return None
            if r == QMessageBox.Yes:
                if not self.save_current():
                    return None

        if not st.path:
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode="w", encoding="utf-8")
            tf.write(ed.text())
            tf.close()
            st.temp_path = tf.name
            script_path = tf.name

        return script_path

    def run_current_internal(self):
        if self.run_proc.state() != QProcess.NotRunning:
            QMessageBox.information(self, "Already running", "A program is already running. Stop it first.")
            return

        interp = self.interp_combo.currentText().strip()
        if not interp or not os.path.isfile(interp):
            QMessageBox.warning(self, "No interpreter", "Select a valid Python interpreter first.")
            return

        script_path = self._resolve_script_to_run()
        if not script_path:
            return

        self.console.clear()
        self._append_console(f"Running (internal) with:\n  {interp}\nScript:\n  {script_path}\n\n")

        args = ["-u", script_path]
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.statusBar().showMessage("Running…")

        self.run_proc.start(interp, args)



    def run_in_external_console(self):
        interp = self.interp_combo.currentText().strip()
        if not interp or not os.path.isfile(interp):
            QMessageBox.warning(self, "No interpreter", "Select a valid Python interpreter first.")
            return

        script_path = self._resolve_script_to_run()
        if not script_path:
            return

        if not is_windows():
            QMessageBox.information(
                self,
                "External console",
                "External console launch is only implemented for Windows in this version.\n\nRunning internally instead.",
            )
            self.run_current_internal()
            return

        st = self.current_state()
        delete_script_after = bool(st.temp_path and normpath(st.temp_path) == normpath(script_path))

        work_dir = None
        try:
            work_dir = str(Path(script_path).parent)
        except Exception:
            work_dir = None

        choice = self._external_console_choice()
        cmd_exe = self._windows_cmd_path()
        ps_exe = self._windows_powershell_path()
        pwsh_exe = self._windows_pwsh_path()
        wt_exe = self._windows_terminal_path()

        def _escape_ps_single(s: str) -> str:
            return s.replace("'", "''")

        # Build wrappers
        cmd_wrapper_path = None
        ps_wrapper_path = None

        try:
            # Always create cmd wrapper (works for most consoles)
            wrapper = tempfile.NamedTemporaryFile(delete=False, suffix=".cmd", mode="w", encoding="utf-8")
            cmd_wrapper_path = wrapper.name
            lines = []
            lines.append("@echo off")
            if work_dir:
                lines.append(f'cd /d "{work_dir}"')
            lines.append(f'"{interp}" -u "{script_path}"')
            lines.append("echo.")
            lines.append("pause")
            if delete_script_after:
                lines.append(f'del /f /q "{script_path}" >nul 2>&1')
                st.temp_path = None
            lines.append('del /f /q "%~f0" >nul 2>&1')
            wrapper.write("\n".join(lines) + "\n")
            wrapper.close()
        except Exception:
            cmd_wrapper_path = None

        # Create PowerShell wrapper only if needed/available
        def _ensure_ps_wrapper() -> Optional[str]:
            nonlocal ps_wrapper_path
            if ps_wrapper_path:
                return ps_wrapper_path
            if not work_dir:
                wd = ""
            else:
                wd = work_dir
            try:
                psw = tempfile.NamedTemporaryFile(delete=False, suffix=".ps1", mode="w", encoding="utf-8")
                ps_wrapper_path = psw.name
                # Use single-quoted strings with doubled single quotes for escaping.
                ps_lines = []
                ps_lines.append("$ErrorActionPreference = 'Continue'")
                if wd:
                    ps_lines.append(f"Set-Location -LiteralPath '{_escape_ps_single(wd)}'")
                ps_lines.append(f"& '{_escape_ps_single(interp)}' -u '{_escape_ps_single(script_path)}'")
                ps_lines.append("Write-Host ''")
                ps_lines.append("Read-Host 'Press Enter to close'")
                if delete_script_after:
                    ps_lines.append(f"Remove-Item -LiteralPath '{_escape_ps_single(script_path)}' -Force -ErrorAction SilentlyContinue")
                    st.temp_path = None
                ps_lines.append("Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue")
                psw.write("\n".join(ps_lines) + "\n")
                psw.close()
                return ps_wrapper_path
            except Exception:
                ps_wrapper_path = None
                return None

        try:
            creationflags = subprocess.CREATE_NEW_CONSOLE
        except Exception:
            creationflags = 0

        # A ready-to-run command line that many 3rd-party consoles can accept.
        command_line = f'cmd.exe /k ""{cmd_wrapper_path}""' if cmd_wrapper_path else f'"{interp}" -u "{script_path}"'

        try:
            if choice == "cmd":
                if not cmd_wrapper_path:
                    raise RuntimeError("Failed to create wrapper.")
                subprocess.Popen(
                    [cmd_exe, "/k", f'""{cmd_wrapper_path}""'],
                    creationflags=creationflags,
                    cwd=work_dir or None,
                )

            elif choice == "powershell":
                if not ps_exe:
                    raise RuntimeError("Windows PowerShell not found.")
                psw = _ensure_ps_wrapper()
                if not psw:
                    raise RuntimeError("Failed to create PowerShell wrapper.")
                subprocess.Popen(
                    [ps_exe, "-NoExit", "-ExecutionPolicy", "Bypass", "-File", psw],
                    creationflags=creationflags,
                    cwd=work_dir or None,
                )

            elif choice == "pwsh":
                if not pwsh_exe:
                    raise RuntimeError("pwsh not found.")
                psw = _ensure_ps_wrapper()
                if not psw:
                    raise RuntimeError("Failed to create PowerShell wrapper.")
                subprocess.Popen(
                    [pwsh_exe, "-NoExit", "-ExecutionPolicy", "Bypass", "-File", psw],
                    creationflags=creationflags,
                    cwd=work_dir or None,
                )

            elif choice.startswith("wt_"):
                if not wt_exe:
                    raise RuntimeError("Windows Terminal (wt.exe) not found.")
                if choice == "wt_cmd":
                    if not cmd_wrapper_path:
                        raise RuntimeError("Failed to create wrapper.")
                    subprocess.Popen(
                        [wt_exe, "cmd.exe", "/k", f'""{cmd_wrapper_path}""'],
                        creationflags=creationflags,
                        cwd=work_dir or None,
                    )
                elif choice == "wt_powershell":
                    if not ps_exe:
                        raise RuntimeError("Windows PowerShell not found.")
                    psw = _ensure_ps_wrapper()
                    if not psw:
                        raise RuntimeError("Failed to create PowerShell wrapper.")
                    subprocess.Popen(
                        [wt_exe, ps_exe, "-NoExit", "-ExecutionPolicy", "Bypass", "-File", psw],
                        creationflags=creationflags,
                        cwd=work_dir or None,
                    )
                elif choice == "wt_pwsh":
                    if not pwsh_exe:
                        raise RuntimeError("pwsh not found.")
                    psw = _ensure_ps_wrapper()
                    if not psw:
                        raise RuntimeError("Failed to create PowerShell wrapper.")
                    subprocess.Popen(
                        [wt_exe, pwsh_exe, "-NoExit", "-ExecutionPolicy", "Bypass", "-File", psw],
                        creationflags=creationflags,
                        cwd=work_dir or None,
                    )

            elif choice.startswith("custom:"):
                idx = int(choice.split(":", 1)[1])
                custom_list = self.cfg.data.get("custom_consoles") or []
                if not isinstance(custom_list, list) or idx < 0 or idx >= len(custom_list):
                    raise RuntimeError("Custom console not configured.")
                c = custom_list[idx]
                exe = str(c.get("path") or "").strip()
                if not exe or not os.path.isfile(exe):
                    raise RuntimeError("Custom console executable not found.")
                args_tpl = str(c.get("args") or "").strip()

                psw = ps_wrapper_path or ""
                if ("{ps_wrapper}" in args_tpl) or ("{ps_wrapper}" in args_tpl and (ps_exe or pwsh_exe)):
                    _ensure_ps_wrapper()
                    psw = ps_wrapper_path or ""

                resolved = args_tpl
                resolved = resolved.replace("{command}", command_line)
                resolved = resolved.replace("{cmd_wrapper}", cmd_wrapper_path or "")
                resolved = resolved.replace("{ps_wrapper}", psw or "")
                resolved = resolved.replace("{workdir}", work_dir or "")

                argv = [exe]
                if resolved:
                    argv += shlex.split(resolved, posix=False)

                subprocess.Popen(
                    argv,
                    creationflags=creationflags,
                    cwd=work_dir or None,
                )

            else:
                # Fallback
                self._set_external_console_choice("cmd")
                if not cmd_wrapper_path:
                    raise RuntimeError("Failed to create wrapper.")
                subprocess.Popen(
                    [cmd_exe, "/k", f'""{cmd_wrapper_path}""'],
                    creationflags=creationflags,
                    cwd=work_dir or None,
                )

            self.statusBar().showMessage("Running in external console…", 2500)

        except Exception as e:
            QMessageBox.critical(self, "Run failed", str(e))


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

    def open_settings(self):
        dlg = SettingsDialog(self)
        dlg.exec()

    def about(self):
        dlg = AboutDialog(self)
        dlg.exec()

    def closeEvent(self, event):
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
