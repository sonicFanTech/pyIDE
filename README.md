# SFT PyIDE

A lightweight, starter **Python IDE** built with **PySide6** for Windows (and other desktop platforms) that focuses on the essentials: **tabbed editing**, **running code inside the IDE**, and **choosing which Python interpreter/version** to run your scripts with.

This project is designed to be a clean foundation that you can keep expanding over time (features can be added later without rewriting everything).

---

## Features

- **Tabbed editor**: open and edit multiple `.py` files at once  
- **Run inside the IDE**: executes the active file and shows **stdout/stderr** in a docked output panel  
- **Interpreter selection**: choose which installed **Python version/interpreter** runs your code  
  - On Windows, it can auto-detect interpreters via `py -0p` (Python Launcher)  
- **Stop running scripts**: kill a running process from the IDE  
- **Compiler window (PyInstaller)**: a separate window for building executables  
  - Supports common PyInstaller options (one-file, windowed, icon, clean, etc.)  
  - Can install/update PyInstaller via pip using the selected interpreter

---

## Requirements

- Python 3.10+ recommended (works with newer versions too)
- PySide6

Install dependencies:

```bash
pip install PySide6
```

---

## Run

```bash
python SFT_PyIDE.py
```

---

## Notes

- If you run **unsaved** code, the IDE can run it using a temporary file.
- To use the built-in compiler, PyInstaller must be installed (the Compiler window can do this for you).

---

## Planned / Ideas for future updates

Some features you can add later:

- Project/file explorer sidebar
- Find/Replace (Ctrl+F / Ctrl+H)
- Line numbers + minimap
- Auto-indent, formatting, linting (ruff/black)
- Autocomplete / IntelliSense (LSP)
- Run configurations (args, working directory, env vars)
- Debugger integration
- Themes (light/dark), custom fonts, UI customization

---

## License

Choose the license you want for your project (MIT is common).  
If you haven’t picked one yet, add a `LICENSE` file when you’re ready.
