"""
Tripo3D API client for image-to-3D mesh generation.
Workflow: upload image -> create task -> poll -> download .glb
"""

import httpx
import asyncio
import os
import logging

logger = logging.getLogger(__name__)
BASE_URL = "https://api.tripo3d.ai/v2/openapi"


class TripoError(Exception):
    """Custom exception for Tripo3D API errors."""
    pass


class TripoClient:
    """Async client for the Tripo3D API."""

    def __init__(self, api_key):
        self.api_key = api_key
        self.headers = {"Authorization": f"Bearer {api_key}"}

    async def upload_image(self, image_path):
        """Upload an image file to Tripo3D, return the image token."""
        logger.info(f"Uploading image: {image_path}")
        async with httpx.AsyncClient(timeout=60.0) as client:
            with open(image_path, "rb") as f:
                filename = os.path.basename(image_path)
                files = {"file": (filename, f, "image/png")}
                response = await client.post(f"{BASE_URL}/upload", headers=self.headers, files=files)
        if response.status_code != 200:
            raise TripoError(f"Upload failed ({response.status_code}): {response.text}")
        data = response.json()
        if data.get("code") != 0:
            raise TripoError(f"Upload API error: {data}")
        token = data["data"]["image_token"]
        logger.info(f"Upload successful, token: {token[:20]}...")
        return token

    async def create_task(self, image_token):
        """Create an image-to-model generation task, return task_id."""
        logger.info("Creating image_to_model task...")
        payload = {"type": "image_to_model", "file": {"type": "jpg", "file_token": image_token}}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{BASE_URL}/task",
                headers={**self.headers, "Content-Type": "application/json"},
                json=payload,
            )
        if response.status_code != 200:
            raise TripoError(f"Task creation failed ({response.status_code}): {response.text}")
        data = response.json()
        if data.get("code") != 0:
            raise TripoError(f"Task API error: {data}")
        task_id = data["data"]["task_id"]
        logger.info(f"Task created: {task_id}")
        return task_id

    async def poll_task(self, task_id, poll_interval=3.0, max_wait=300.0):
        """Poll a task until it reaches a terminal state."""
        logger.info(f"Polling task {task_id}...")
        elapsed = 0.0
        async with httpx.AsyncClient(timeout=30.0) as client:
            while elapsed < max_wait:
                try:
                    response = await client.get(f"{BASE_URL}/task/{task_id}", headers=self.headers)
                    if response.status_code != 200:
                        raise TripoError(f"Poll failed ({response.status_code}): {response.text}")
                    data = response.json()
                    if data.get("code") != 0:
                        raise TripoError(f"Poll API error: {data}")
                    task_data = data["data"]
                    status = task_data.get("status")
                    progress = task_data.get("progress", 0)
                    logger.info(f"Task {task_id}: status={status}, progress={progress}%")
                    if status == "success":
                        return task_data
                    elif status in ("failed", "banned", "expired", "cancelled", "unknown"):
                        raise TripoError(f"Task {task_id} ended with status: {status}")
                except httpx.RequestError as e:
                    logger.warning(f"Network error during poll for task {task_id}: {e}. Retrying...")
                
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
        raise TripoError(f"Task {task_id} timed out after {max_wait}s")

    async def download_model(self, task_data, output_path):
        """Download the GLB model from a completed task."""
        output = task_data.get("output", {})
        model_url = output.get("model") or output.get("pbr_model") or output.get("base_model")
        if not model_url:
            raise TripoError(f"No model URL found in task output: {output}")
        logger.info(f"Downloading model from: {model_url[:60]}...")
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            response = await client.get(model_url)
        if response.status_code != 200:
            raise TripoError(f"Download failed ({response.status_code})")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(response.content)
        file_size = os.path.getsize(output_path)
        logger.info(f"Model saved: {output_path} ({file_size / 1024:.1f} KB)")
        return output_path

    async def generate_from_image(self, image_path, output_path):
        """Full pipeline: upload -> create task -> poll -> download."""
        token = await self.upload_image(image_path)
        task_id = await self.create_task(token)
        task_data = await self.poll_task(task_id)
        await self.download_model(task_data, output_path)
        return {"task_id": task_id, "output_path": output_path, "file_size": os.path.getsize(output_path)}
