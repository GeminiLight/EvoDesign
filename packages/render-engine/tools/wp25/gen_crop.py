# WP25 acceptance-review script (see migration/PHASE2_REPORT.md §3).
import json, os, sys, hashlib, shutil
import numpy as np, cv2
from PIL import Image
from evodesign.agentic_system.render_engine.shared.image_cropper import smart_crop
D = sys.argv[1]
rng = np.random.default_rng(7)
cases = []
def add(name, arr, mode=None, **kw):
    src = os.path.join(D, name + ".png")
    if mode == "pil":
        arr.save(src)
    else:
        cv2.imwrite(src, arr)
    cases.append((name, src, kw))
# 1 excalidraw white bg with content
a = np.full((300, 420, 3), 255, np.uint8); cv2.rectangle(a, (100,50),(350,95),(32,33,36),-1); cv2.line(a,(20,120),(20,124),(250,252,253),1)
add("ex_basic", a, padding=60, canvas_engine="excalidraw")
# 2 excalidraw: diff exactly 2 vs 3 near threshold
a = np.full((120, 160, 3), 200, np.uint8); a[10,10]=(202,200,200); a[100,150]=(203,200,200)
add("ex_threshold", a, padding=5, canvas_engine="excalidraw")
# 3 blank -> warning
add("ex_blank", np.full((50,60,3), 255, np.uint8), padding=60, canvas_engine="excalidraw")
# 4 tldraw noisy, otsu+morphology, bottom_offset default 120
a = np.full((400, 500, 3), 245, np.uint8); cv2.circle(a,(250,150),60,(10,80,200),-1); cv2.rectangle(a,(30,30),(33,250),(120,120,120),-1)
noise = rng.integers(0, 30, size=a.shape, dtype=np.uint8); a = cv2.subtract(a, noise); a[350:,:] = (0,0,0)
add("td_noise", a, padding=0, canvas_engine="tldraw")
# 5 unknown engine (bottom 100), top_left explicit
a = np.full((260, 300, 3), 255, np.uint8); a[5:20,5:20]=0; cv2.ellipse(a,(150,100),(80,40),15,0,360,(0,0,255),3)
add("other_engine", a, padding=3, canvas_engine="Mermaid", top_left_margin=25)
# 6 RGBA transparent PNG (alpha stripped not composited)
rgba = np.zeros((80,100,4), np.uint8); rgba[20:40,30:70] = (10,200,30,255); rgba[60,90]=(5,5,5,0)
add("ex_rgba", Image.fromarray(rgba, "RGBA"), mode="pil", padding=4, canvas_engine="excalidraw")
# 7 grayscale 8-bit
g = np.full((70,90), 230, np.uint8); g[30:35, 10:80] = 40
add("ex_gray", Image.fromarray(g, "L"), mode="pil", padding=2, canvas_engine="EXCALIDRAW")
# 8 palette
p = Image.fromarray(np.full((40,50,3),255,np.uint8)); p.paste((255,0,0),(10,10,20,30)); p = p.convert("P", palette=Image.ADAPTIVE, colors=4)
add("ex_palette", p, mode="pil", padding=1, canvas_engine="excalidraw")
# 9 16-bit RGB
a16 = (np.full((30,40,3), 65000, np.uint16)); a16[10:15,10:30] = 1000
cv2.imwrite(os.path.join(D,"ex_16.png"), a16); cases.append(("ex_16", os.path.join(D,"ex_16.png"), dict(padding=7, canvas_engine="excalidraw")))
# 10 bottom offset larger than image, excalidraw explicit
add("ex_bigbottom", np.full((40,40,3), 0, np.uint8), padding=0, canvas_engine="excalidraw", bottom_offset=100)
# 11 tldraw large image with thin lines
a = np.full((600, 800, 3), 255, np.uint8)
for i in range(0,800,37): cv2.line(a,(i,100),(i+5,300),(180,180,180),1)
cv2.putText(a,"Hello",(200,450),cv2.FONT_HERSHEY_SIMPLEX,2,(0,0,0),3)
add("td_lines", a, padding=10, canvas_engine="tldraw")
# 12 negative padding
a = np.full((100,100,3),255,np.uint8); a[40:60,40:60]=0
add("ex_negpad", a, padding=-5, canvas_engine="excalidraw")
out = []
for name, src, kw in cases:
    dst = os.path.join(D, name + "_py_out.jpg")
    try:
        msg = smart_crop.invoke({"image_path": src, "output_path": dst, **kw}); err=None
    except Exception as e:
        msg = ""; err = type(e).__name__
    png = os.path.splitext(dst)[0] + ".png"
    rec = {"name": name, "src": src, "kw": kw, "msg": msg.replace(D, "<D>"), "error": err}
    if os.path.exists(png):
        img = cv2.imread(png, cv2.IMREAD_UNCHANGED)
        rec["shape"] = list(img.shape); rec["sha"] = hashlib.sha256(np.ascontiguousarray(img).tobytes()).hexdigest()
    out.append(rec)
json.dump(out, open(os.path.join(D, "vectors.json"), "w"), indent=1)
print(len(out))
