"""
Mesh optimization pipeline.
Takes a raw high-poly .glb from Tripo3D and produces a lightweight, web-ready .glb.
"""

import trimesh
import pymeshlab
import tempfile
import os
import shutil
import subprocess
import logging

logger = logging.getLogger(__name__)
DEFAULT_TARGET_FACES = 40000


def get_mesh_info(filepath):
    """Get basic mesh info (face count, vertex count, file size)."""
    try:
        scene = trimesh.load(filepath, force="scene")
        faces = sum(len(g.faces) for g in scene.geometry.values() if hasattr(g, "faces"))
        verts = sum(len(g.vertices) for g in scene.geometry.values() if hasattr(g, "vertices"))
        return {"faces": faces, "vertices": verts, "file_size": os.path.getsize(filepath)}
    except Exception:
        mesh = trimesh.load(filepath, force="mesh")
        return {"faces": len(mesh.faces), "vertices": len(mesh.vertices), "file_size": os.path.getsize(filepath)}


def optimize_mesh(input_path, output_path, target_faces=DEFAULT_TARGET_FACES, apply_draco=False):
    """Full mesh optimization: clean -> decimate -> export GLB -> optional Draco."""
    logger.info(f"Optimizing: {input_path}")
    original_info = get_mesh_info(input_path)
    logger.info(f"Original: {original_info['faces']} faces, {original_info['file_size']/1024:.1f} KB")

    if original_info["faces"] <= target_faces:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        shutil.copy2(input_path, output_path)
        return {
            "original_faces": original_info["faces"],
            "optimized_faces": original_info["faces"],
            "original_size": original_info["file_size"],
            "optimized_size": os.path.getsize(output_path),
            "reduction_ratio": 1.0,
        }

    ratio = min(1.0, target_faces / max(1, original_info["faces"]))
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Use gltf-transform to simplify the mesh. 
    # This natively preserves PBR materials, textures, and normals perfectly!
    try:
        subprocess.run(
            [
                "npx", "-y", "@gltf-transform/cli", "simplify", 
                input_path, output_path, 
                "--ratio", str(ratio), 
                "--error", "0.05"
            ],
            check=True,
            capture_output=True,
            text=True
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"gltf-transform failed: {e.stderr}")
        # Fallback to copy if optimization fails
        shutil.copy2(input_path, output_path)

    # Optional Draco compression
    if apply_draco:
        draco_out = output_path.replace(".glb", "_draco.glb")
        if _apply_draco(output_path, draco_out):
            shutil.move(draco_out, output_path)

    optimized_info = get_mesh_info(output_path)
    final_ratio = optimized_info["file_size"] / original_info["file_size"] if original_info["file_size"] > 0 else 1.0
    result = {
        "original_faces": original_info["faces"],
        "optimized_faces": optimized_info["faces"],
        "original_size": original_info["file_size"],
        "optimized_size": optimized_info["file_size"],
        "reduction_ratio": final_ratio,
    }
    logger.info(f"Done: {result['original_faces']}->{result['optimized_faces']} faces, "
                f"{result['original_size']/1024:.1f}->{result['optimized_size']/1024:.1f} KB")
    return result


def _apply_draco(input_path, output_path):
    """Apply Draco compression via gltf-pipeline CLI."""
    try:
        r = subprocess.run(
            ["npx", "-y", "gltf-pipeline", "-i", input_path, "-o", output_path, "-d"],
            capture_output=True, text=True, timeout=60,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
