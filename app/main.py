from fastapi import FastAPI

from app.api.endpoints.routes import router

app = FastAPI(title="AI Phone Banking Prototype")



##################################3 included all routes ############################################
app.include_router(router)



########################### health check endpoint for livenes of app #########################################
@app.get("/")
def health_check():
    return {"status": "ok", "service": "ai-phone-banking"}
