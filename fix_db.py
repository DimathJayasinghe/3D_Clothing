"""One-time script to fix the DB and optimize existing raw GLB files."""
import asyncio, os
from database import init_db, create_model, update_model
from mesh_optimizer import optimize_mesh

async def fix():
    # Reset DB
    if os.path.exists('meshes.db'):
        os.remove('meshes.db')
    await init_db()
    print("DB reset.")

    # Optimize existing raw GLBs
    models_dir = 'static/models'
    for f in os.listdir(models_dir):
        if f.endswith('_raw.glb'):
            raw = os.path.join(models_dir, f)
            file_id = f.replace('_raw.glb', '')
            out = os.path.join(models_dir, f"{file_id}.glb")
            print(f"Optimizing {raw}...")
            result = optimize_mesh(raw, out, target_faces=5000)
            mid = await create_model(
                name='My Shirt',
                filepath=f'/static/models/{file_id}.glb',
                status='ready'
            )
            await update_model(mid,
                original_size_bytes=result['original_size'],
                optimized_size_bytes=result['optimized_size'],
                original_faces=result['original_faces'],
                optimized_faces=result['optimized_faces'])
            print(f"  Model {mid}: {result['original_faces']}->{result['optimized_faces']} faces, "
                  f"{result['original_size']//1024}KB->{result['optimized_size']//1024}KB")

    # Cleanup test files
    test = os.path.join(models_dir, 'test_optimized.glb')
    if os.path.exists(test):
        os.remove(test)

    print("Done! Start the server with: .venv/bin/python main.py")

asyncio.run(fix())
