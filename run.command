#!/bin/bash
# Bấm đúp file này để mở App (macOS/Linux). Windows: xem run.bat
cd "$(dirname "$0")"
exec ./.venv/bin/python app/gui.py
