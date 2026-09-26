"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import router as api_router
from app.api.modify import router as modify_router

app = FastAPI(title="FormatAI", version="1.0.0")

# CORS - allow frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files at /static
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Include API routers
app.include_router(api_router, prefix="/api")
app.include_router(modify_router, prefix="/api")


@app.get("/")
async def root():
    """Serve the frontend."""
    return FileResponse("app/static/index.html")


@app.get("/modify")
async def modify_page():
    """Serve the natural-language format-modification page."""
    return FileResponse("app/static/modify.html")
