"""Local development helper — loads .env then runs the pipeline.

Usage:
    python scripts/run_local.py

Requires:
    .env file with TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
    (copy from .env.example and fill in real values)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow imports from project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env before importing any project module
from dotenv import load_dotenv

env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    load_dotenv(env_path)
    print(f"[run_local] Loaded env from {env_path}")
else:
    print(f"[run_local] WARNING: .env not found at {env_path} — running without Telegram secrets")

from src.main import run_pipeline

if __name__ == "__main__":
    run_pipeline()
