"""
FastAPI application for the 3D Mesh POC.
Upload a shirt photo → Tripo3D generates mesh → optimize → store → render.
"""

import os
import uuid
import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from dotenv import load_dotenv

from database import init_db, create_model, update_model, get_model, get_all_models, delete_model
from tripo_client import TripoClient, TripoError
from mesh_optimizer import optimize_mesh

# Setup
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
MODELS_DIR = BASE_DIR / "static" / "models"
STATIC_DIR = BASE_DIR / "static"

# Ensure directories exist
UPLOAD_DIR.mkdir(exist_ok=True)
MODELS_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB on startup."""
    await init_db()
    logger.info("Database initialized")
    yield

app = FastAPI(title="3D Mesh POC", lifespan=lifespan)

# Serve static files (models, frontend assets)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the main HTML page."""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(404, "Frontend not found")
    return FileResponse(str(index_path), media_type="text/html")


@app.post("/api/upload")
async def upload_and_generate(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    name: str = Form("Shirt Model"),
):
    """
    Upload a shirt image and trigger the full pipeline:
    upload → Tripo3D → optimize → store → DB entry.
    Returns immediately with model_id; processing happens in background.
    """
    api_key = os.getenv("TRIPO3D_API_KEY")
    if not api_key or api_key == "your_api_key_here":
        raise HTTPException(400, "TRIPO3D_API_KEY not configured in .env file")

    # Validate file type
    if file.content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(400, f"Unsupported image type: {file.content_type}. Use JPEG, PNG, or WebP.")

    # Save uploaded image
    file_id = str(uuid.uuid4())[:8]
    ext = file.filename.split(".")[-1] if "." in file.filename else "png"
    image_filename = f"{file_id}.{ext}"
    image_path = UPLOAD_DIR / image_filename

    content = await file.read()
    with open(image_path, "wb") as f:
        f.write(content)

    logger.info(f"Image saved: {image_path} ({len(content)/1024:.1f} KB)")

    # Create DB record in 'processing' status
    model_id = await create_model(
        name=name,
        original_image=f"/static/uploads/{image_filename}",
        status="processing",
    )

    # Run the pipeline in background
    background_tasks.add_task(_run_pipeline, model_id, str(image_path), api_key, file_id)

    return {"model_id": model_id, "status": "processing", "message": "Generation started. Poll /api/models/{id} for status."}


async def _run_pipeline(model_id: int, image_path: str, api_key: str, file_id: str):
    """Background task: Tripo3D generation → optimization → storage."""
    try:
        # Step 1: Generate with Tripo3D
        await update_model(model_id, status="generating")
        client = TripoClient(api_key)
        raw_path = str(MODELS_DIR / f"{file_id}_raw.glb")
        result = await client.generate_from_image(image_path, raw_path)

        await update_model(model_id, tripo_task_id=result["task_id"], status="optimizing")

        # Step 2: Optimize mesh
        optimized_path = str(MODELS_DIR / f"{file_id}.glb")
        opt_result = await asyncio.to_thread(
            optimize_mesh, raw_path, optimized_path, target_faces=20000, apply_draco=False
        )

        # Step 3: Update DB with final info
        relative_path = f"/static/models/{file_id}.glb"
        await update_model(
            model_id,
            filepath=relative_path,
            original_size_bytes=opt_result["original_size"],
            optimized_size_bytes=opt_result["optimized_size"],
            original_faces=opt_result["original_faces"],
            optimized_faces=opt_result["optimized_faces"],
            status="ready",
        )

        # Cleanup raw file
        if os.path.exists(raw_path):
            os.remove(raw_path)

        logger.info(f"Model {model_id} ready: {relative_path}")

    except TripoError as e:
        logger.error(f"Tripo3D error for model {model_id}: {e}")
        await update_model(model_id, status=f"error: {str(e)[:200]}")
    except Exception as e:
        logger.error(f"Pipeline error for model {model_id}: {e}", exc_info=True)
        await update_model(model_id, status=f"error: {str(e)[:200]}")


@app.get("/api/models")
async def list_models():
    """List all models."""
    models = await get_all_models()
    return {"models": models}


@app.get("/api/models/{model_id}")
async def get_model_by_id(model_id: int):
    """Get a single model by ID."""
    model = await get_model(model_id)
    if not model:
        raise HTTPException(404, "Model not found")
    return model


@app.delete("/api/models/{model_id}")
async def delete_model_by_id(model_id: int):
    """Delete a model and its files."""
    model = await get_model(model_id)
    if not model:
        raise HTTPException(404, "Model not found")

    # Delete the GLB file
    if model.get("filepath"):
        file_path = str(BASE_DIR) + model["filepath"]
        if os.path.exists(file_path):
            os.remove(file_path)

    # Delete DB record
    await delete_model(model_id)
    return {"message": "Model deleted"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
