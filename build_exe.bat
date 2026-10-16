@echo off
python -m pip install -r requirements.txt
python setup.py build_apps
echo Готово: build\win_amd64\FartTogether.exe
pause
