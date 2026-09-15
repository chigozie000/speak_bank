from fastapi import FastAPI

from app.routes import router

app = FastAPI(title="AI Phone Banking Prototype")

app.include_router(router)


@app.get("/")
def health_check():
    return {"status": "ok", "service": "ai-phone-banking"}
