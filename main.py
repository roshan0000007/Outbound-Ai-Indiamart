"""
Root-level entry point - allows running the app with: python main.py
This script sets up the Python path and then starts the FastAPI application.
"""

import sys
import os

project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

if __name__ == "__main__":
    from app.main import app, APP_HOST, APP_PORT, LOG_LEVEL
    import uvicorn
    import logging

    logging.basicConfig(level=getattr(logging, LOG_LEVEL))

    uvicorn.run(
        app,
        host=APP_HOST,
        port=APP_PORT,
        reload=False,
        log_level=LOG_LEVEL.lower(),
    )
