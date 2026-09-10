@echo off
rem Windows draws cmd's console before this line runs, so a .bat always blinks
rem for ~130ms no matter what. Use run.vbs (or the shortcut it makes) to avoid
rem it entirely. start hands off without waiting, so the blink stays that short.
cd /d "%~dp0"
start "" pythonw "%~dp0main.py" 2>nul || start "" pyw "%~dp0main.py"
