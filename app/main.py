from fastapi import FastAPI

from app.api.endpoints.routes import router

app = FastAPI(title="AI Phone Banking Prototype")

# --- Routes ---
app.include_router(router)


# --- Health check endpoint (liveness) ---
@app.get("/")
def health_check():
    return {"status": "ok", "service": "ai-phone-banking"}
