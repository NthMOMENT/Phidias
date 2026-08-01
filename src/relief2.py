"""Phidias relief pipeline v2 — three height modes + customer parameters.

Usage:
  python src/relief2.py input/photo.png --mode depth
  python src/relief2.py input/art.png --mode luminance --invert
  python src/relief2.py input/flower.jpg --mode blend --width 120 --relief 5

Modes:
  depth      physical 3D subjects (flower, coin, carving) — uses AI depth
  luminance  flat artwork/patterns (drawing, logo, nail design) — brightness = height
  blend      textured 3D subjects — 70% depth + 30% luminance detail
"""
import sys, time, os, argparse
import cv2
import numpy as np
import trimesh

p = argparse.ArgumentParser()
p.add_argument("image")
p.add_argument("--mode", choices=["depth", "luminance", "blend"], default="depth")
p.add_argument("--width", type=float, default=80.0, help="panel width in mm")
p.add_argument("--relief", type=float, default=4.0, help="max relief height in mm")
p.add_argument("--base", type=float, default=3.0, help="base thickness in mm")
p.add_argument("--invert", action="store_true", help="dark areas raised instead of bright")
p.add_argument("--grid", type=int, default=256, help="mesh resolution")
args = p.parse_args()

name = os.path.splitext(os.path.basename(args.image))[0]
out_path = f"output/{name}_{args.mode}{'_inv' if args.invert else ''}.stl"

img = cv2.imread(args.image)
if img is None:
    sys.exit(f"Could not read image: {args.image}")
img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

# ---------- Height source(s) ----------
def get_depth(img_rgb):
    import torch
    print("Loading depth model...")
    midas = torch.hub.load("intel-isl/MiDaS", "DPT_Hybrid", trust_repo=True)
    midas.eval()
    tfm = torch.hub.load("intel-isl/MiDaS", "transforms", trust_repo=True).dpt_transform
    t0 = time.time()
    with torch.no_grad():
        pred = midas(tfm(img_rgb))
        pred = torch.nn.functional.interpolate(
            pred.unsqueeze(1), size=img_rgb.shape[:2],
            mode="bicubic", align_corners=False).squeeze()
    print(f"  depth: {time.time()-t0:.1f}s")
    d = pred.cpu().numpy()
    return (d - d.min()) / (d.max() - d.min())

def get_luminance(img_rgb):
    g = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
    g = cv2.bilateralFilter(g, 9, 0.1, 9)        # smooth noise, KEEP edges sharp
    return g

if args.mode == "depth":
    height = get_depth(img_rgb)
elif args.mode == "luminance":
    height = get_luminance(img_rgb)
else:  # blend
    height = 0.7 * get_depth(img_rgb) + 0.3 * get_luminance(img_rgb)
    height = (height - height.min()) / (height.max() - height.min())

if args.invert:
    height = 1.0 - height

# ---------- Heightfield ----------
G = args.grid
h_img = cv2.resize(height, (G, G), interpolation=cv2.INTER_AREA)
h_img = cv2.GaussianBlur(h_img, (3, 3), 0)
H, W = h_img.shape
aspect = img_rgb.shape[0] / img_rgb.shape[1]
size_x, size_y = args.width, args.width * aspect

# ---------- Solid mesh ----------
print("Building mesh...")
xs = np.linspace(0, size_x, W); ys = np.linspace(0, size_y, H)
xx, yy = np.meshgrid(xs, ys)
zz = args.base + h_img * args.relief
verts = np.vstack([
    np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()]),
    np.column_stack([xx.ravel(), yy.ravel(), np.zeros(H*W)])])
N = H * W
def idx(r, c): return r * W + c
faces = []
for r in range(H-1):
    for c in range(W-1):
        a,b,cc,dd = idx(r,c), idx(r,c+1), idx(r+1,c), idx(r+1,c+1)
        faces += [[a,b,dd],[a,dd,cc]]                      # top
        faces += [[a+N,dd+N,b+N],[a+N,cc+N,dd+N]]          # bottom (reversed)
for c in range(W-1):
    faces += [[idx(0,c), idx(0,c)+N, idx(0,c+1)], [idx(0,c+1), idx(0,c)+N, idx(0,c+1)+N]]
    r = H-1
    faces += [[idx(r,c), idx(r,c+1), idx(r,c)+N], [idx(r,c+1), idx(r,c+1)+N, idx(r,c)+N]]
for r in range(H-1):
    faces += [[idx(r,0), idx(r+1,0), idx(r,0)+N], [idx(r+1,0), idx(r+1,0)+N, idx(r,0)+N]]
    c = W-1
    faces += [[idx(r,c), idx(r,c)+N, idx(r+1,c)], [idx(r+1,c), idx(r,c)+N, idx(r+1,c)+N]]

mesh = trimesh.Trimesh(vertices=verts, faces=np.array(faces))
if not mesh.is_watertight:
    trimesh.repair.fill_holes(mesh); trimesh.repair.fix_normals(mesh)
print(f"  watertight: {mesh.is_watertight} | {size_x:.0f}x{size_y:.0f}x{args.base+args.relief:.0f}mm | "
      f"{len(mesh.faces)} faces | {mesh.volume/1000:.1f} cm3")
mesh.export(out_path)
print(f"Saved: {out_path}")
