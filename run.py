"""KuroStream launcher.

    python run.py                 # 127.0.0.1:8000
    KS_HOST=0.0.0.0 KS_PORT=8000 python run.py
"""
from __future__ import annotations

import os

import uvicorn

if __name__ == "__main__":
    host = os.getenv("KS_HOST", "127.0.0.1")
    port = int(os.getenv("KS_PORT", "8000"))
    workers = int(os.getenv("KS_WORKERS", "1"))
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=False,
        workers=workers,
        log_level=os.getenv("KS_LOG_LEVEL", "info"),
        proxy_headers=True,
        forwarded_allow_ips=os.getenv("KS_FORWARDED_IPS", "127.0.0.1"),
    )
