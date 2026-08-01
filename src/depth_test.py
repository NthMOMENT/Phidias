"""Sanity test: load DPT-Hybrid, run depth estimation on one photo, save result."""
import sys, time
import cv2
import torch
import numpy as np

img_path = sys.argv[1]                          # photo path passed on the command line
out_path = "output/depth_test.png"

print("Loading model (first run downloads ~470MB, be patient)...")
model_type = "DPT_Hybrid"
midas = torch.hub.load("intel-isl/MiDaS", model_type)
midas.eval()
transforms = torch.hub.load("intel-isl/MiDaS", "transforms")
transform = transforms.dpt_transform

img = cv2.imread(img_path)                      # load photo
if img is None:
    sys.exit(f"Could not read image: {img_path}")
img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)  # OpenCV loads BGR; model wants RGB

print("Estimating depth...")
t0 = time.time()
with torch.no_grad():                           # inference only, no training — saves memory
    batch = transform(img_rgb)
    pred = midas(batch)
    pred = torch.nn.functional.interpolate(     # resize depth map back to photo size
        pred.unsqueeze(1), size=img_rgb.shape[:2],
        mode="bicubic", align_corners=False
    ).squeeze()
depth = pred.cpu().numpy()
print(f"Done in {time.time()-t0:.1f}s")

# Normalize to 0-255 grayscale: closer = brighter
depth_img = ((depth - depth.min()) / (depth.max() - depth.min()) * 255).astype(np.uint8)
cv2.imwrite(out_path, depth_img)
print(f"Depth map saved to {out_path}")
