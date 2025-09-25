import os
import uvicorn
from . import create_app

# Instantiate FastAPI app via factory
app = create_app()

if __name__ == "__main__":
    # Read host/port from env for flexibility
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload_flag = os.getenv("RELOAD", "true").lower() == "true"

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload_flag,
        log_level=os.getenv("LOG_LEVEL", "info"),
    )
