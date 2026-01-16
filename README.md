# pyIDE

A lightweight, starter **Python IDE** built with **PySide6** for Windows (and other desktop platforms) that focuses on the essentials: **tabbed editing**, **running code inside the IDE**, and **choosing which Python interpreter/version** to run your scripts with.
---


<img width="1201" height="800" alt="image" src="https://github.com/user-attachments/assets/552282ba-7c85-4c4b-9507-adf2bc44d0e5" />

------------------------------------------------------------
 ## Main Features (Full Detail)
------------------------------------------------------------
1) Tabbed Code Editor
   - Open multiple .py files at once in tabs.
   - "*" indicator shows when a tab has unsaved changes.
   - New/Untitled files are supported (save anytime).

2) Line Numbers
   - The editor includes a line-number gutter so it is easy to track where
     code is located and where errors happen.

<img width="285" height="370" alt="image" src="https://github.com/user-attachments/assets/8cc8901a-2a98-43e3-9b23-807fa86b9867" />

3) Find + Replace
   - Quick Find: Ctrl+F
   - Replace: Ctrl+H
   - Find next / previous, Replace, Replace All.

<img width="541" height="223" alt="image" src="https://github.com/user-attachments/assets/817b3224-2069-4fa1-80f3-a33feb50d64d" />

4) Project File Manager (Dockable)
   - A project file tree for a selected folder (project root).
   - Double-click to open files.
   - Right-click actions:
       * New File / New Folder
       * Rename
       * Delete
       * Open in File Explorer
   - Can be hidden to save space and reopened from View.

<img width="506" height="292" alt="image" src="https://github.com/user-attachments/assets/f2a5fbb1-022b-470b-a869-343945750be3" />

5) Recent Files
   - File -> Recent Files keeps a list of the last opened/edited files.
   - Default limit: 10 files (changeable in Settings).
   - Includes "Clear Recent Files".

<img width="944" height="254" alt="image" src="https://github.com/user-attachments/assets/3066019e-b8a1-4503-b558-6a8683b7c281" />

6) Auto-Save
   - Auto-saves open files automatically at a set interval.
   - Default: every 45 seconds.
   - Can be disabled or the interval changed in Settings.
   - Note: Auto-save only saves files that already have a save path.

7) Dark Mode + Light Mode
   - Dark mode is enabled by default.
   - Switch between dark and light themes in Settings.

8) Python Interpreter Manager
   - Choose which Python interpreter runs your script.
   - Add interpreter paths (python.exe) from Tools.
   - Remove interpreters or re-discover interpreters.

<img width="549" height="129" alt="image" src="https://github.com/user-attachments/assets/3a61f431-30e0-423a-85b9-d81e3553ab6c" />

9) Run Your Code (Two Modes)
   A) Run inside PyIDE
      - Output appears in the Run Output panel.
      - Supports stdin input via an input box.
      - Stop button (Shift+F5) can terminate a running program.

<img width="550" height="270" alt="image" src="https://github.com/user-attachments/assets/b0e5c896-8315-490f-920c-aec1aae4a012" />

   B) Run in an External Console (Best for CLI / curses-style apps)
      - Runs your script in a real external terminal window.
      - Useful for full CLI tools that need a real console window.
      - You can select which external console to use:
          * Command Prompt (cmd.exe)
          * Windows PowerShell (powershell.exe)
          * PowerShell 7 (pwsh)
          * Windows Terminal (wt) variants (if installed)
          * Custom third-party consoles you add
      - If a console is not installed on your PC, it will be disabled.

<img width="713" height="432" alt="image" src="https://github.com/user-attachments/assets/0994704c-9382-4300-bd1e-c789d778a94d" />

10) Autocomplete (Optional Enhanced Suggestions)
    - Ctrl+Space triggers autocomplete.
    - If you install the optional "Jedi" library, completion becomes smarter.
      Command:
        pip install jedi

11) Syntax Check (py_compile)
    - Tools -> Check Syntax (Ctrl+K)
    - Quickly validates that the current file compiles.
    - Results show in the output panel.

<img width="283" height="224" alt="image" src="https://github.com/user-attachments/assets/0e5e41eb-bfe4-49b4-9306-f994049cc854" />

<img width="759" height="176" alt="image" src="https://github.com/user-attachments/assets/e10dbe5d-274f-4eb2-80d2-3a9f6be93376" />

12) Built-in Compiler Window (PyInstaller)
    - Tools -> Open Compiler (PyInstaller)…
    - Helps you build your .py files into EXEs (requires PyInstaller).

<img width="935" height="661" alt="image" src="https://github.com/user-attachments/assets/6388cbad-9a3c-40bc-8092-46427bff7e0c" />

13) Settings + Persistence
    - Settings include:
        * Theme (dark/light)
        * Auto-save enable + interval
        * Recent files limit
        * External console default behavior
        * Completion enable/disable
        * External console selection
    - Settings are saved to: pyide_config.json

<img width="551" height="331" alt="image" src="https://github.com/user-attachments/assets/662041a1-a0cb-46de-b38d-5b35a8260943" />


------------------------------------------------------------
Where PyIDE Saves Settings / Recent Files
------------------------------------------------------------
PyIDE saves settings, recent files, and custom console entries in a JSON file
named:

  pyide_config.json

By default, PyIDE tries to create this file in the same folder as PyIDE.exe.

If PyIDE is installed into a protected folder (for example Program Files) and
it cannot write there, it automatically falls back to:

  %LOCALAPPDATA%\SFT_PyIDE\pyide_config.json

(Your installer can avoid this by installing PyIDE into a user-writable
folder, such as AppData or a folder inside your user profile.)

------------------------------------------------------------
Recommended Requirements
------------------------------------------------------------
- Windows 10 or Windows 11
- At least one installed Python interpreter (python.exe)
- Optional (recommended):
    * Jedi (better autocomplete)
    * PyInstaller (if you want to compile scripts)
    * Windows Terminal (if you want to use the wt console options)

------------------------------------------------------------
Keyboard Shortcuts
------------------------------------------------------------
File
- Ctrl+N        New
- Ctrl+O        Open
- Ctrl+S        Save
- Ctrl+Shift+S  Save As

Edit
- Ctrl+F        Find
- Ctrl+H        Replace

Run
- F5            Run (default run mode)
- Ctrl+F5       Run in External Console
- Shift+F5      Stop

Tools
- Ctrl+K        Check Syntax (py_compile)

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
python pyIDE.py
```

---

## Notes

- If you run **unsaved** code, the IDE can run it using a temporary file.
- To use the built-in compiler, PyInstaller must be installed (the Compiler window can do this for you).

---
