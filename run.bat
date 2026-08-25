@echo off
python -m uvicorn app.main:app --reload --port 8765
