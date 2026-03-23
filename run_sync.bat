@echo off
cd /d "C:\Users\igors\Desktop\Python 11.2025\Garmin"
python sync.py >> "%~dp0logs\sync_log.txt" 2>&1
