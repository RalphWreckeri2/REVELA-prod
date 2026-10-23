"""Extract authentic road/shoreline linework from the supplied Mataasnakahoy map.

Optional design-time tool (Pillow and NumPy required); the generated PNG is
checked in as an ordinary frontend asset and has no runtime dependency.
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
source = Image.open(ROOT / "src/assets/mkahoybg.png").convert("RGB")
# Includes the western shoreline, winding main road, and dense town streets.
crop = source.crop((700, 350, 3900, 2150)).resize((1200, 675), Image.Resampling.LANCZOS)
pixels = np.asarray(crop, dtype=np.float32)
luminance = pixels[..., 0] * 0.299 + pixels[..., 1] * 0.587 + pixels[..., 2] * 0.114
softened = np.asarray(Image.fromarray(np.uint8(luminance)).filter(ImageFilter.GaussianBlur(2.6)), dtype=np.float32)

# Isolate darker narrow features from local land/water colors. Large flat
# regions stay transparent; this retains the original road bends and coast.
detail = np.clip((softened - luminance - 1.5) * 8.5, 0, 210)
dark_road = np.where(luminance < 185, np.clip((185 - luminance) * 2.4, 0, 175), 0)
alpha = np.uint8(np.maximum(detail, dark_road))
rgba = np.empty((*alpha.shape, 4), dtype=np.uint8)
rgba[..., :3] = (13, 73, 56)
rgba[..., 3] = alpha
output = ROOT / "src/assets/intro-map-roads.png"
Image.fromarray(rgba, "RGBA").save(output, optimize=True)
print(f"Wrote {output} ({output.stat().st_size:,} bytes)")
