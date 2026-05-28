@echo off
cd /d "D:\VScodeProjects\基金助手\project"
call activate TraeAI-3
python auto_invest_cron.py
pause