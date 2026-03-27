import uvicorn
import sys
import os

if __name__ == "__main__":
    try:
        print(f"Starting uvicorn on port 8000 with host 127.0.0.1...")
        uvicorn.run("main:app", host="127.0.0.1", port=8000, log_level="debug", reload=False)
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        sys.exit(1)
