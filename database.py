"""
SQLite database module for storing 3D model metadata.
Uses aiosqlite for async operations with FastAPI.
"""

import aiosqlite
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "meshes.db")


async def init_db():
    """Initialize the database and create the models table if it doesn't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS models (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                original_image TEXT,
                filepath TEXT NOT NULL,
                original_size_bytes INTEGER,
                optimized_size_bytes INTEGER,
                original_faces INTEGER,
                optimized_faces INTEGER,
                tripo_task_id TEXT,
                status TEXT DEFAULT 'processing',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


async def create_model(name, original_image=None, filepath="", status="processing", tripo_task_id=None):
    """Insert a new model record and return its ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO models (name, original_image, filepath, status, tripo_task_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, original_image, filepath, status, tripo_task_id, datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
        )
        await db.commit()
        return cursor.lastrowid


async def update_model(model_id, **kwargs):
    """Update model fields by ID."""
    kwargs["updated_at"] = datetime.utcnow().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in kwargs.keys())
    values = list(kwargs.values()) + [model_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE models SET {set_clause} WHERE id = ?", values)
        await db.commit()


async def get_model(model_id):
    """Get a single model by ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM models WHERE id = ?", (model_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_all_models():
    """Get all models, ordered by most recent first."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM models ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def delete_model(model_id):
    """Delete a model by ID. Returns True if a row was deleted."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM models WHERE id = ?", (model_id,))
        await db.commit()
        return cursor.rowcount > 0
