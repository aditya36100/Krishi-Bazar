"""How the photo-check thresholds behave on SYNTHETIC images (procedural pictures, not real produce photos).
Real photos will behave differently: treat this as a sanity check only."""
import os, sys, tempfile, numpy as np
from PIL import Image, ImageFilter
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import imagecheck as ic

def make_img(seed, size=(640, 480)):
    rng = np.random.default_rng(seed)
    base = Image.fromarray(rng.uniform(60, 200, (6, 8, 3)).astype("uint8")).resize(size, Image.BICUBIC)
    a = np.asarray(base).astype(float)
    for _ in range(12):
        x, y = int(rng.integers(0, size[0] - 80)), int(rng.integers(0, size[1] - 80))
        a[y:y + int(rng.integers(20, 80)), x:x + int(rng.integers(20, 80))] = rng.uniform(0, 255, 3)
    a += rng.normal(0, 12, a.shape)
    return Image.fromarray(np.clip(a, 0, 255).astype("uint8"))

def run(n=60):
    d = tempfile.mkdtemp()
    def fl(im, name="t.png", **kw):
        p = os.path.join(d, name); im.save(p, **kw); return ic.analyze(p)
    ims = [make_img(i) for i in range(n)]
    clean = [fl(im) for im in ims]
    print(f"images={n} clean images wrongly flagged: {sum(bool(r['flags']) for r in clean)}")
    print(f"blur (GaussianBlur 4) detected: {sum('BLURRY' in fl(im.filter(ImageFilter.GaussianBlur(4)))['flags'] for im in ims)}/{n}")
    print(f"mild blur (GaussianBlur 1.5) detected: {sum('BLURRY' in fl(im.filter(ImageFilter.GaussianBlur(1.5)))['flags'] for im in ims)}/{n}")
    print(f"dark detected: {sum('TOO_DARK' in fl(im.point(lambda v: int(v * 0.25)))['flags'] for im in ims)}/{n}")
    print(f"bright detected: {sum('TOO_BRIGHT' in fl(im.point(lambda v: int(v * 0.2 + 200)))['flags'] for im in ims)}/{n}")
    hs = [r["phash"] for r in clean]
    dup = [ic.hamming(h, fl(im.resize((512, 384)), "d.jpg", quality=60)["phash"]) for h, im in zip(hs, ims)]
    diff = [ic.hamming(hs[i], hs[j]) for i in range(n) for j in range(i + 1, n)]
    print(f"recompressed copies within {ic.DUP_BITS} bits: {sum(x <= ic.DUP_BITS for x in dup)}/{n} (max distance {max(dup)})")
    print(f"different images wrongly within {ic.DUP_BITS} bits: {sum(x <= ic.DUP_BITS for x in diff)}/{len(diff)} (min distance {min(diff)})")

if __name__ == "__main__":
    run()
