import sqlite3, numpy as np
from PIL import Image, ImageFilter
from app import imagecheck

def make_img(seed, size=(640, 480)):
    rng = np.random.default_rng(seed)
    base = Image.fromarray(rng.uniform(60, 200, (6, 8, 3)).astype("uint8")).resize(size, Image.BICUBIC)
    a = np.asarray(base).astype(float)
    for _ in range(12):
        x, y = int(rng.integers(0, size[0] - 80)), int(rng.integers(0, size[1] - 80))
        a[y:y + int(rng.integers(20, 80)), x:x + int(rng.integers(20, 80))] = rng.uniform(0, 255, 3)
    a += rng.normal(0, 12, a.shape)
    return Image.fromarray(np.clip(a, 0, 255).astype("uint8"))

def test_clean_blur_dark_bright(tmp_path):
    im = make_img(1)
    p = tmp_path / "a.png"; im.save(p)
    assert imagecheck.analyze(str(p))["flags"] == []
    im.filter(ImageFilter.GaussianBlur(4)).save(p)
    assert "BLURRY" in imagecheck.analyze(str(p))["flags"]
    im.point(lambda v: int(v * 0.25)).save(p)
    assert "TOO_DARK" in imagecheck.analyze(str(p))["flags"]
    im.point(lambda v: int(v * 0.2 + 200)).save(p)
    assert "TOO_BRIGHT" in imagecheck.analyze(str(p))["flags"]

def test_low_resolution(tmp_path):
    p = tmp_path / "s.png"; make_img(2, (300, 200)).save(p)
    assert "LOW_RESOLUTION" in imagecheck.analyze(str(p))["flags"]

def test_duplicate_detection_and_storage(tmp_path):
    c = sqlite3.connect(":memory:"); imagecheck.init(c)
    im = make_img(3)
    p1, p2, p3 = tmp_path / "1.png", tmp_path / "2.jpg", tmp_path / "3.png"
    im.save(p1); im.resize((512, 384)).save(p2, quality=60); make_img(4).save(p3)
    assert imagecheck.analyze_and_store(c, 1, 10, str(p1)) == []
    assert "DUPLICATE_OF_OTHER_TICKET" in imagecheck.analyze_and_store(c, 2, 11, str(p2))
    assert "DUPLICATE_OF_OTHER_TICKET" not in imagecheck.analyze_and_store(c, 3, 12, str(p3))
    assert imagecheck.flags_for_ticket(c, 11)[0]["media_id"] == 2
