from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

app = FastAPI(
    title="Gametimarr",
    description="Sports event downloader for NCAAF, MLB, and NFL",
    version="0.1.0"
)

# Setup templates (will add later)
# app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
# templates = Jinja2Templates(directory="app/web/templates")

@app.get("/")
async def root():
    return {"message": "Gametimarr is running!"}

@app.get("/health")
async def health():
    return {"status": "ok"}