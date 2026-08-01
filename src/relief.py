"""Relief pipeline: photo -> depth map -> watertight relief STL.
Usage: python src/relief.py input/photo.png [width_mm] [relief_mm] [base_mm]
"""
import sys, time, os
import cv2
import torch
import numpy as np
import trimesh

# ---------- Parameters (with sensible defaults) ----------
img_path   = sys.argv[1]
width_mm   = float(sys.argv[2]) if len(sys.argv) > 2 else 80.0   # panel width
relief_mm  = float(sys.argv[3]) if len(sys.argv) > 3 else 4.0    # max relief height
base_mm    = float(sys.argv[4]) if len(sys.argv) > 4 else 3.0    # solid base thickness
GRID       = 256   # mesh resolution: 256x256 height points (~130k triangles, prints fine)

name = os.path.splitext(os.path.basename(img_path))[0]
out_path = f"output/{name}_relief.stl"

# ---------- Step 1: depth estimation ----------
print("Loading model...")
midas = torch.hub.load("intel-isl/MiDaS", "DPT_Hybrid", trust_repo=True)
midas.eval()
transform = torch.hub.load("intel-isl/MiDaS", "transforms", trust_repo=True).dpt_transform

img = cv2.imread(img_path)
if img is None:
    sys.exit(f"Could not read image: {img_path}")
img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

print("Estimating depth...")
t0 = time.time()
with torch.no_grad():
    pred = midas(transform(img_rgb))
    pred = torch.nn.functional.interpolate(
        pred.unsqueeze(1), size=img_rgb.shape[:2],
        mode="bicubic", align_corners=False).squeeze()
depth = pred.cpu().numpy()
print(f"  depth done in {time.time()-t0:.1f}s")

# ---------- Step 2: depth -> heightfield ----------
# Normalize 0..1, then smooth slightly so the print isn't noisy
d = (depth - depth.min()) / (depth.max() - depth.min())
d = cv2.resize(d, (GRID, GRID), interpolation=cv2.INTER_AREA)
d = cv2.GaussianBlur(d, (5, 5), 0)              # mild smoothing, kills pixel noise

h, w = d.shape
aspect = img_rgb.shape[0] / img_rgb.shape[1]     # keep the photo's proportions
size_x, size_y = width_mm, width_mm * aspect

# ---------- Step 3: build a closed solid mesh ----------
print("Building mesh...")
xs = np.linspace(0, size_x, w)
ys = np.linspace(0, size_y, h)
xx, yy = np.meshgrid(xs, ys)
zz_top = base_mm + d * relief_mm                 # top surface: base + relief
verts_top = np.column_stack([xx.ravel(), yy.ravel(), zz_top.ravel()])
verts_bot = np.column_stack([xx.ravel(), yy.ravel(), np.zeros(h*w)])
verts = np.vstack([verts_top, verts_bot])
N = h * w                                        # bottom verts start at index N

def idx(r, c): return r * w + c

faces = []
for r in range(h - 1):                           # top surface triangles
    for c in range(w - 1):
        a, b, cc, dd = idx(r,c), idx(r,c+1), idx(r+1,c), idx(r+1,c+1)
        faces += [[a, b, dd], [a, dd, cc]]
for r in range(h - 1):                           # bottom surface (reversed winding = faces down)
    for c in range(w - 1):
        a, b, cc, dd = idx(r,c)+N, idx(r,c+1)+N, idx(r+1,c)+N, idx(r+1,c+1)+N
        faces += [[a, dd, b], [a, cc, dd]]
for c in range(w - 1):                           # front & back walls
    faces += [[idx(0,c), idx(0,c)+N, idx(0,c+1)], [idx(0,c+1), idx(0,c)+N, idx(0,c+1)+N]]
    r = h - 1
    faces += [[idx(r,c), idx(r,c+1), idx(r,c)+N], [idx(r,c+1), idx(r,c+1)+N, idx(r,c)+N]]
for r in range(h - 1):                           # left & right walls
    faces += [[idx(r,0), idx(r+1,0), idx(r,0)+N], [idx(r+1,0), idx(r+1,0)+N, idx(r,0)+N]]
    c = w - 1
    faces += [[idx(r,c), idx(r,c)+N, idx(r+1,c)], [idx(r+1,c), idx(r,c)+N, idx(r+1,c)+N]]

mesh = trimesh.Trimesh(vertices=verts, faces=np.array(faces))

# ---------- Step 4: verify watertight, repair if needed ----------
if not mesh.is_watertight:
    print("  not watertight, attempting repair...")
    trimesh.repair.fill_holes(mesh)
    trimesh.repair.fix_normals(mesh)
print(f"  watertight: {mesh.is_watertight}")
print(f"  size: {size_x:.0f} x {size_y:.0f} x {base_mm + relief_mm:.0f} mm, "
      f"{len(mesh.faces)} triangles, volume {mesh.volume/1000:.1f} cm3")

mesh.export(out_path)
print(f"Saved: {out_path}  ({os.path.getsize(out_path)//1024} KB)")
