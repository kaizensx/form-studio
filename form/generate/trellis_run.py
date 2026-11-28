"""Run TRELLIS.2 on one picture and write a GLB. Runs in the TRELLIS.2 environment the person installed (its own
Python, from its folder), never in Form Studio's: `python trellis_run.py <picture> <out.glb>`.

The calls are the README's image-to-3D example (microsoft/TRELLIS.2, MIT): the pipeline from_pretrained
"microsoft/TRELLIS.2-4B", run on the picture, simplified to nvdiffrast's limit, exported with
o_voxel.postprocess.to_glb. No video is rendered. The weights are fetched by TRELLIS.2 itself from Hugging Face the
first time, as its README describes.
"""
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")


def main(picture: str, out: str) -> int:
    from PIL import Image
    import o_voxel
    from trellis2.pipelines import Trellis2ImageTo3DPipeline
    pipeline = Trellis2ImageTo3DPipeline.from_pretrained("microsoft/TRELLIS.2-4B")
    pipeline.cuda()
    mesh = pipeline.run(Image.open(picture))[0]
    mesh.simplify(16777216)                       # nvdiffrast limit (README)
    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices, faces=mesh.faces, attr_volume=mesh.attrs, coords=mesh.coords,
        attr_layout=mesh.layout, voxel_size=mesh.voxel_size, aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        decimation_target=1000000, texture_size=4096, remesh=True, remesh_band=1, remesh_project=0, verbose=False)
    glb.export(out, extension_webp=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
