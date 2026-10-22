@echo off
chcp 65001 >nul
echo ===================================================
echo     DNS Switcher - Сборка Portable EXE
echo ===================================================
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Создание виртуального окружения Python 3.12...
    uv venv --python 3.12
)

echo [2/3] Проверка и установка зависимостей...
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
if errorlevel 1 exit /b 1

echo [3/3] Запуск сборки через PyInstaller...
.venv\Scripts\python.exe build_exe.py
if errorlevel 1 exit /b 1

echo.
echo Сборка завершена!
pause
