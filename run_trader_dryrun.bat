@echo off
REM Dry run: attaches to the open MT5 terminal, scans and PRINTS the orders it would place - sends nothing.
cd /d "%~dp0"
python trader.py --symbol XAUUSD.t --commission 7 --trader partial_r=0.6,partial_frac=0.25,tp2_r=2.5 --dry-run --once
pause
