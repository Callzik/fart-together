@echo off
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --onefile --windowed --name FartTogether fart_together.py
echo Готово: dist\FartTogether.exe
pause
