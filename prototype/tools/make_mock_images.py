# -*- coding: utf-8 -*-
"""Generate placeholder images for the Culture Verify prototype (P0).

These are intentionally synthetic "generated images": flat vector-ish scenes,
so the prototype does not need any real model output or licensed material.

Run:
    python tools/make_mock_images.py
Output:
    ../mock/a1.png ... a6.png, b1a/b1b, b2a/b2b, b3a/b3b (900 x 900)
"""
from __future__ import annotations

import math
import os
import random

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "mock"))
os.makedirs(OUT, exist_ok=True)

SIZE = 900
K = 2  # supersampling factor
CANVAS = SIZE * K

FONT_CN = r"C:\Windows\Fonts\msyh.ttc"
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def hx(s: str):
    s = s.lstrip("#")
    return tuple(int(s[i : i + 2], 16) for i in (0, 2, 4))


def mix(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


_FCACHE = {}


def fnt(size, bold=False):
    key = (size, bold)
    if key not in _FCACHE:
        path = FONT_BOLD if bold else FONT_CN
        try:
            _FCACHE[key] = ImageFont.truetype(path, size)
        except OSError:
            _FCACHE[key] = ImageFont.load_default()
    return _FCACHE[key]


def vgrad(top, bottom):
    arr = np.zeros((CANVAS, CANVAS, 3), dtype=np.float32)
    t = np.linspace(0.0, 1.0, CANVAS, dtype=np.float32)[:, None]
    for i in range(3):
        arr[:, :, i] = top[i] + (bottom[i] - top[i]) * t
    return Image.fromarray(arr.astype(np.uint8), "RGB")


class Pen:
    """Draws in 900x900 coordinates onto the supersampled canvas."""

    def __init__(self, draw):
        self.d = draw

    def ellipse(self, box, fill=None, outline=None, width=0):
        self.d.ellipse([c * K for c in box], fill=fill, outline=outline, width=int(width * K))

    def rect(self, box, fill=None, outline=None, width=0):
        self.d.rectangle([c * K for c in box], fill=fill, outline=outline, width=int(width * K))

    def rrect(self, box, r, fill=None, outline=None, width=0):
        self.d.rounded_rectangle(
            [c * K for c in box], radius=r * K, fill=fill, outline=outline, width=int(width * K)
        )

    def poly(self, pts, fill=None, outline=None):
        self.d.polygon([(x * K, y * K) for x, y in pts], fill=fill, outline=outline)

    def line(self, pts, fill=None, width=1):
        self.d.line([(x * K, y * K) for x, y in pts], fill=fill, width=max(1, int(width * K)), joint="curve")

    def arc(self, box, start, end, fill=None, width=1):
        self.d.arc([c * K for c in box], start, end, fill=fill, width=int(width * K))

    def text(self, xy, s, size, fill, bold=False, anchor="la"):
        self.d.text((xy[0] * K, xy[1] * K), s, font=fnt(int(size * K), bold), fill=fill, anchor=anchor)


def new_canvas(top, bottom):
    img = vgrad(hx(top), hx(bottom))
    return img, Pen(ImageDraw.Draw(img))


def qbez(p0, p1, p2, n=26):
    pts = []
    for i in range(n + 1):
        t = i / n
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]
        pts.append((x, y))
    return pts


def vtext(p, x, y, s, size, fill, bold=True, step=1.22):
    f = fnt(int(size * K), bold)
    for i, ch in enumerate(s):
        p.d.text(
            (x * K, (y + size * step * i) * K),
            ch,
            font=f,
            fill=fill,
            anchor="mm",
        )


def seal(p, x, y, s, color, size=74):
    p.rrect([x, y, x + size, y + size], 7, fill=color)
    f = fnt(int(size * 0.42 * K), True)
    for i, ch in enumerate(s[:2]):
        p.d.text(
            ((x + size / 2) * K, (y + size * (0.30 + 0.42 * i)) * K),
            ch,
            font=f,
            fill=hx("#F7ECDC"),
            anchor="mm",
        )


def caption(p, s):
    p.rrect([30, 806, 520, 862], 12, fill=(24, 19, 16))
    p.text((48, 822), s, 23, (240, 232, 220))


def finish(img, grain=4.0, seed=1, vignette=0.28):
    arr = np.asarray(img).astype(np.float32)
    h, w = arr.shape[:2]
    rng = np.random.default_rng(seed)
    arr += rng.normal(0, grain, (h, w, 1))
    yy, xx = np.mgrid[0:h, 0:w]
    cx, cy = w / 2.0, h / 2.0
    r = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2) / math.sqrt(2)
    arr *= (1.0 - vignette * r**2)[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def soften(img):
    img = img.filter(ImageFilter.GaussianBlur(1.45))
    img = ImageEnhance.Contrast(img).enhance(0.92)
    img = ImageEnhance.Color(img).enhance(0.88)
    return finish(img, grain=9.0, seed=17, vignette=0.36)


def sharpen(img):
    img = img.filter(ImageFilter.UnsharpMask(radius=2.2, percent=70, threshold=2))
    img = ImageEnhance.Contrast(img).enhance(1.07)
    img = ImageEnhance.Color(img).enhance(1.06)
    return finish(img, grain=2.2, seed=5, vignette=0.30)


def save(img, name):
    path = os.path.join(OUT, name)
    img.resize((SIZE, SIZE), Image.LANCZOS).save(path, optimize=True)
    print("wrote", os.path.relpath(path, HERE))


# --------------------------------------------------------------------------
# scenes — part 1 (single image)
# --------------------------------------------------------------------------
def scene_a1():
    """唐制齐胸襦裙"""
    img, p = new_canvas("#F9EDDF", "#E2B9A9")
    p.ellipse([580, 80, 840, 340], fill=mix(hx("#F9EDDF"), hx("#FFF8EF"), 0.9))
    p.poly(
        [(0, 690), (170, 610), (330, 680), (520, 600), (740, 690), (900, 640), (900, 900), (0, 900)],
        fill=hx("#D8A796"),
    )
    p.rect([0, 782, 900, 900], fill=hx("#C79584"))

    cx = 420
    # skirt + pleats
    p.poly([(cx - 96, 468), (cx + 96, 468), (cx + 212, 806), (cx - 212, 806)], fill=hx("#B03A46"))
    for k in range(-4, 5):
        p.line([(cx + k * 22, 480), (cx + k * 51, 800)], fill=hx("#8E2B36"), width=3)
    # skirt hem
    p.line([(cx - 212, 806), (cx + 212, 806)], fill=hx("#7C2530"), width=8)
    # 团花
    for fx, fy in [(cx - 120, 650), (cx + 120, 650), (cx, 735)]:
        for r in (20, 11):
            p.ellipse([fx - r, fy - r, fx + r, fy + r], outline=hx("#E6B45B"), width=3)
    # torso
    p.poly([(cx - 70, 316), (cx + 70, 316), (cx + 62, 486), (cx - 62, 486)], fill=hx("#C4525C"))
    p.poly([(cx - 34, 316), (cx, 392), (cx + 34, 316), (cx, 352)], fill=hx("#F5E4CD"))
    # sleeves
    p.poly([(cx - 66, 322), (cx - 200, 392), (cx - 210, 474), (cx - 118, 452), (cx - 76, 396)], fill=hx("#C4525C"))
    p.poly([(cx + 66, 322), (cx + 200, 392), (cx + 210, 474), (cx + 118, 452), (cx + 76, 396)], fill=hx("#C4525C"))
    # sash
    p.rect([cx - 68, 466, cx + 68, 500], fill=hx("#7E2531"))
    p.line([(cx - 30, 498), (cx - 40, 606), (cx - 20, 706)], fill=hx("#E8B04B"), width=9)
    # 披帛
    left_rib = qbez((cx - 196, 404), (cx - 274, 540), (cx - 198, 648))
    left_rib += qbez((cx - 198, 648), (cx - 142, 706), (cx - 62, 604))[1:]
    right_rib = qbez((cx + 196, 404), (cx + 276, 522), (cx + 196, 640))
    right_rib += qbez((cx + 196, 640), (cx + 138, 700), (cx + 76, 596))[1:]
    p.line(left_rib, fill=hx("#F4DCAE"), width=15)
    p.line(right_rib, fill=hx("#F4DCAE"), width=15)
    # neck / head
    p.rect([cx - 16, 274, cx + 16, 322], fill=hx("#E6C0A2"))
    p.ellipse([cx - 46, 190, cx + 46, 296], fill=hx("#F1D2B7"))
    p.ellipse([cx - 52, 176, cx + 52, 232], fill=hx("#2B211F"))
    p.ellipse([cx - 78, 226, cx - 38, 302], fill=hx("#2B211F"))
    p.ellipse([cx + 38, 226, cx + 78, 302], fill=hx("#2B211F"))
    p.ellipse([cx - 34, 146, cx + 34, 198], fill=hx("#2B211F"))
    # face
    p.line([(cx - 24, 242), (cx - 10, 242)], fill=hx("#3A2A28"), width=3)
    p.line([(cx + 10, 242), (cx + 24, 242)], fill=hx("#3A2A28"), width=3)
    p.ellipse([cx - 5, 214, cx + 5, 224], fill=hx("#C0392B"))
    p.ellipse([cx - 7, 264, cx + 7, 272], fill=hx("#C25A5A"))

    vtext(p, 812, 128, "大唐", 50, hx("#432A24"))
    seal(p, 762, 330, "仕女", hx("#B23A48"), 78)
    caption(p, "MOCK · A01 唐制齐胸襦裙")
    return finish(img, grain=3.0, seed=11)


def scene_a2():
    """京都清水寺"""
    img, p = new_canvas("#E9F3ED", "#A4CCBE")
    p.ellipse([612, 78, 792, 258], fill=hx("#D9584F"))
    p.poly(
        [(0, 620), (200, 500), (380, 600), (560, 520), (760, 610), (900, 560), (900, 900), (0, 900)],
        fill=hx("#8DBEB0"),
    )
    p.poly(
        [(0, 690), (240, 590), (470, 680), (700, 600), (900, 670), (900, 900), (0, 900)],
        fill=hx("#6B9F91"),
    )
    px, base = 300, 690
    for w, y in [(150, 570), (126, 512), (102, 454), (78, 396), (54, 338)]:
        p.poly([(px - w, y), (px + w, y), (px + w - 34, y - 30), (px - w + 34, y - 30)], fill=hx("#33403B"))
        p.rect([px - 38, y - 4, px + 38, y + 44], fill=hx("#8A6448"))
    p.rect([px - 7, 296, px + 7, 318], fill=hx("#33403B"))
    p.rect([px - 72, 690, px + 72, 764], fill=hx("#A8836A"))
    p.rect([px - 96, 764, px + 96, 786], fill=hx("#8A6448"))
    # steps
    for i in range(3):
        p.rect([px - 120 - i * 18, 786 + i * 10, px + 120 + i * 18, 796 + i * 10], fill=hx("#B39277"))

    rng = random.Random(7)
    for _ in range(64):
        x, y = rng.randint(16, 884), rng.randint(96, 720)
        r = rng.choice([4, 5, 6, 8])
        p.ellipse([x - r, y - r, x + r, y + r], fill=hx("#F3B9C8") if rng.random() < 0.75 else hx("#E98BA5"))

    vtext(p, 816, 452, "清水", 44, hx("#2F3A35"))
    caption(p, "MOCK · A02 京都清水寺")
    return finish(img, grain=3.0, seed=12)

def scene_a3():
    """开罗哈利利市场"""
    img, p = new_canvas("#F9EDD2", "#D8AC70")
    p.rect([0, 700, 900, 900], fill=hx("#C79A63"))
    for i in range(3):
        x = 42 + i * 282
        p.poly(
            [(x, 700), (x, 434), (x + 30, 382), (x + 70, 352), (x + 110, 382), (x + 140, 434), (x + 140, 700)],
            fill=hx("#7C4F2E"),
        )
        p.poly(
            [(x + 28, 700), (x + 28, 458), (x + 50, 416), (x + 70, 396), (x + 90, 416), (x + 112, 458), (x + 112, 700)],
            fill=hx("#2E2117"),
        )
    for lx, ly in [(180, 118), (452, 88), (724, 138)]:
        p.line([(lx, 0), (lx, ly)], fill=hx("#5B3A22"), width=3)
        p.poly([(lx - 26, ly), (lx + 26, ly), (lx + 34, ly + 54), (lx - 34, ly + 54)], fill=hx("#C9873A"))
        p.rect([lx - 20, ly + 54, lx + 20, ly + 64], fill=hx("#5B3A22"))
        p.ellipse([lx - 12, ly + 18, lx + 12, ly + 44], fill=hx("#F6D57A"))

    p.rrect([556, 462, 836, 624], 10, fill=hx("#3A2A1C"))
    p.rrect([570, 476, 822, 610], 6, outline=hx("#C9A15E"), width=3)
    rng = random.Random(3)
    for i in range(3):
        y = 508 + i * 34
        pts = [(598, y)]
        for k in range(6):
            pts.append((598 + (k + 1) * 34, y + rng.choice([-10, 0, 9])))
        p.line(pts, fill=hx("#E8D3A6"), width=6)

    # carpet on the ground
    p.rect([300, 790, 600, 856], fill=hx("#8E2F35"))
    for i in range(4):
        p.rect([316 + i * 70, 800, 346 + i * 70, 846], outline=hx("#D9A441"), width=3)

    vtext(p, 70, 120, "开罗", 50, hx("#4A3018"))
    caption(p, "MOCK · A03 开罗哈利利市场")
    return finish(img, grain=3.2, seed=13)


def scene_a4():
    """首尔景福宫"""
    img, p = new_canvas("#F3E9F5", "#C7B0D6")
    p.poly([(90, 432), (810, 432), (722, 344), (178, 344)], fill=hx("#3A2E3A"))
    p.poly([(150, 344), (750, 344), (700, 302), (200, 302)], fill=hx("#2C232C"))
    p.line([(90, 432), (36, 456)], fill=hx("#3A2E3A"), width=10)
    p.line([(810, 432), (864, 456)], fill=hx("#3A2E3A"), width=10)
    p.rect([110, 432, 790, 470], fill=hx("#8E6547"))
    for x in [150, 300, 450, 600, 750]:
        p.rect([x - 16, 470, x + 16, 762], fill=hx("#7A4E33"))
    p.rect([80, 762, 820, 800], fill=hx("#A9825F"))
    # autumn leaves
    rng = random.Random(21)
    for _ in range(26):
        x, y = rng.randint(20, 880), rng.randint(480, 760)
        r = rng.choice([5, 6, 8])
        p.ellipse([x - r, y - r, x + r, y + r], fill=hx("#D98B4A") if rng.random() < 0.6 else hx("#C25A3A"))

    cx = 650
    # chima (full skirt)
    p.poly([(cx - 62, 470), (cx + 62, 470), (cx + 172, 806), (cx - 172, 806)], fill=hx("#8E5A7A"))
    for k in range(-3, 4):
        p.line([(cx + k * 20, 486), (cx + k * 44, 800)], fill=hx("#7A4866"), width=3)
    # jeogori
    p.poly([(cx - 58, 360), (cx + 58, 360), (cx + 66, 480), (cx - 66, 480)], fill=hx("#F0DCE4"))
    p.poly([(cx - 34, 360), (cx, 424), (cx + 34, 360), (cx, 386)], fill=hx("#E7C3CF"))
    # sleeves
    p.poly([(cx - 58, 366), (cx - 150, 410), (cx - 146, 468), (cx - 70, 446)], fill=hx("#F0DCE4"))
    p.poly([(cx + 58, 366), (cx + 150, 410), (cx + 146, 468), (cx + 70, 446)], fill=hx("#F0DCE4"))
    # goreum ribbon
    p.line([(cx - 4, 420), (cx - 14, 520), (cx + 8, 566)], fill=hx("#7A3F61"), width=9)
    # head
    p.rect([cx - 14, 316, cx + 14, 362], fill=hx("#EBCBAF"))
    p.ellipse([cx - 42, 238, cx + 42, 336], fill=hx("#F2D5BC"))
    p.ellipse([cx - 48, 226, cx + 48, 280], fill=hx("#241C22"))
    p.line([(cx - 22, 288), (cx - 9, 288)], fill=hx("#3A2A28"), width=3)
    p.line([(cx + 9, 288), (cx + 22, 288)], fill=hx("#3A2A28"), width=3)
    p.ellipse([cx - 6, 308, cx + 6, 314], fill=hx("#C25A5A"))
    # hair bun
    p.ellipse([cx - 30, 214, cx + 30, 250], fill=hx("#241C22"))
    p.ellipse([cx - 6, 196, cx + 6, 220], fill=hx("#D9A441"))

    vtext(p, 810, 110, "景福", 46, hx("#3A2E3A"))
    caption(p, "MOCK · A04 首尔景福宫")
    return finish(img, grain=3.0, seed=14)


def scene_a5():
    """墨西哥亡灵节"""
    img, p = new_canvas("#2C1B3E", "#5B2A52")
    p.line([(0, 132), (900, 190)], fill=hx("#E9C46A"), width=4)
    colors = ["#E76F51", "#F4A261", "#E9C46A", "#2A9D8F", "#8E7DBE"]
    for i in range(9):
        x = 34 + i * 100
        y = 138 + i * 6
        p.poly([(x, y), (x + 74, y), (x + 37, y + 78)], fill=hx(colors[i % 5]))
        p.ellipse([x + 29, y + 26, x + 45, y + 42], fill=hx("#2B1A3C"))

    # altar
    p.rect([238, 596, 662, 700], fill=hx("#6E3F28"))
    p.rect([268, 548, 632, 596], fill=hx("#8E5A38"))
    p.rect([312, 500, 588, 548], fill=hx("#6E3F28"))
    # candles
    for x in [286, 356, 544, 614]:
        p.rect([x, 452, x + 18, 500], fill=hx("#F2E3C6"))
        p.ellipse([x + 2, 424, x + 16, 456], fill=hx("#F4A261"))
        p.ellipse([x + 5, 432, x + 13, 448], fill=hx("#FFE9BD"))
    # marigolds
    rng = random.Random(31)
    for _ in range(46):
        x, y = rng.randint(150, 750), rng.randint(604, 760)
        r = rng.choice([8, 10, 12])
        p.ellipse([x - r, y - r, x + r, y + r], fill=hx("#F2A531"))
        p.ellipse([x - r // 2, y - r // 2, x + r // 2, y + r // 2], fill=hx("#E07A2E"))
    # sugar skull
    p.ellipse([382, 552, 518, 640], fill=hx("#F3EAD8"))
    p.ellipse([406, 578, 438, 606], fill=hx("#2B1A3C"))
    p.ellipse([462, 578, 494, 606], fill=hx("#2B1A3C"))
    p.poly([(450, 600), (436, 624), (464, 624)], fill=hx("#2B1A3C"))
    for i in range(4):
        p.line([(424 + i * 18, 632), (424 + i * 18, 642)], fill=hx("#2B1A3C"), width=3)

    p.text((450, 300), "DÍA DE MUERTOS", 36, hx("#F2D9A0"), bold=True, anchor="mm")
    caption(p, "MOCK · A05 墨西哥亡灵节")
    return finish(img, grain=3.4, seed=15)


def scene_a6():
    """印度排灯节"""
    img, p = new_canvas("#301B12", "#7A3A1C")
    # garland
    for i in range(15):
        x = 20 + i * 62
        y = 54 + abs(i - 7) * 7
        p.ellipse([x - 15, y - 15, x + 15, y + 15], fill=hx("#F2A531"))
        p.ellipse([x - 6, y - 6, x + 6, y + 6], fill=hx("#C25A2E"))
    # rangoli
    cx, cy = 450, 548
    for r, col, w in [(236, "#8E3A2A", 5), (204, "#C25A2E", 4), (168, "#E0A23A", 4), (128, "#8E3A2A", 3)]:
        p.ellipse([cx - r, cy - r, cx + r, cy + r], outline=hx(col), width=w)
    for i in range(16):
        a = i * math.pi / 8
        x1, y1 = cx + 128 * math.cos(a), cy + 128 * math.sin(a)
        x2, y2 = cx + 200 * math.cos(a), cy + 200 * math.sin(a)
        p.line([(x1, y1), (x2, y2)], fill=hx("#F2C14E"), width=4)
        p.ellipse(
            [cx + 166 * math.cos(a) - 9, cy + 166 * math.sin(a) - 9, cx + 166 * math.cos(a) + 9, cy + 166 * math.sin(a) + 9],
            fill=hx("#E76F51"),
        )
    # diyas
    for x in range(110, 860, 112):
        p.poly([(x - 28, 762), (x + 28, 762), (x + 19, 806), (x - 19, 806)], fill=hx("#B5653A"))
        p.ellipse([x - 10, 718, x + 10, 760], fill=hx("#F6C453"))
        p.ellipse([x - 5, 732, x + 5, 754], fill=hx("#FFF1C1"))
    vtext(p, 806, 300, "排灯", 44, hx("#F6D68A"))
    caption(p, "MOCK · A06 印度排灯节")
    return finish(img, grain=3.6, seed=16)


# --------------------------------------------------------------------------
# scenes — part 2 (pairwise, identical composition / different rendering)
# --------------------------------------------------------------------------
def scene_b1():
    """敦煌飞天"""
    img, p = new_canvas("#7A3A2A", "#381C17")
    rng = random.Random(5)
    for _ in range(46):
        x, y = rng.randint(0, 900), rng.randint(0, 900)
        r = rng.randint(26, 96)
        p.ellipse(
            [x - r, y - r, x + r, y + r],
            outline=mix(hx("#7A3A2A"), hx("#C98A4B"), rng.random() * 0.55),
            width=rng.randint(1, 3),
        )
    p.arc([56, 56, 844, 844], 180, 360, fill=hx("#C98A4B"), width=18)
    p.arc([100, 100, 800, 800], 180, 360, fill=hx("#3E7C7B"), width=6)

    def apsara(cx, cy, s, skin="#E8C79A"):
        p.ellipse([cx - 18 * s, cy - 18 * s, cx + 18 * s, cy + 18 * s], fill=hx(skin))
        p.poly([(cx - 24 * s, cy + 10 * s), (cx + 24 * s, cy + 10 * s), (cx + 42 * s, cy + 82 * s), (cx - 42 * s, cy + 82 * s)], fill=hx("#C97E5A"))
        p.line([(cx - 24 * s, cy + 26 * s), (cx - 74 * s, cy + 4 * s), (cx - 104 * s, cy - 14 * s)], fill=hx(skin), width=int(10 * s))
        p.line([(cx + 24 * s, cy + 26 * s), (cx + 74 * s, cy + 4 * s), (cx + 104 * s, cy - 14 * s)], fill=hx(skin), width=int(10 * s))
        p.poly([(cx - 42 * s, cy + 78 * s), (cx + 42 * s, cy + 78 * s), (cx + 62 * s, cy + 146 * s), (cx - 62 * s, cy + 146 * s)], fill=hx("#B5643F"))
        left_rib = qbez((cx - 74 * s, cy + 4 * s), (cx - 172 * s, cy + 44 * s), (cx - 186 * s, cy + 148 * s))
        left_rib += qbez((cx - 186 * s, cy + 148 * s), (cx - 140 * s, cy + 190 * s), (cx - 62 * s, cy + 176 * s))[1:]
        right_rib = qbez((cx + 74 * s, cy + 4 * s), (cx + 176 * s, cy - 36 * s), (cx + 186 * s, cy - 136 * s))
        right_rib += qbez((cx + 186 * s, cy - 136 * s), (cx + 140 * s, cy - 182 * s), (cx + 72 * s, cy - 168 * s))[1:]
        p.line(left_rib, fill=hx("#E8C79A"), width=int(6 * s))
        p.line(right_rib, fill=hx("#7FBFB3"), width=int(6 * s))

    apsara(300, 330, 1.0)
    apsara(632, 520, 0.78, "#E2BC8E")

    # lotus
    p.ellipse([330, 720, 570, 830], fill=hx("#3E7C7B"))
    for i in range(7):
        a = math.pi + i * math.pi / 6
        p.ellipse(
            [450 + 80 * math.cos(a) - 34, 760 + 40 * math.sin(a) - 26, 450 + 80 * math.cos(a) + 34, 760 + 40 * math.sin(a) + 26],
            fill=hx("#D9A3A0"),
        )
    vtext(p, 812, 120, "飞天", 44, hx("#E8C79A"))
    caption(p, "MOCK · B01 敦煌飞天")
    return finish(img, grain=3.2, seed=41)


def scene_b2():
    """日本茶室"""
    img, p = new_canvas("#F0E7D7", "#C6B99F")
    p.rect([496, 96, 866, 648], fill=hx("#F5EFE1"))
    for i in range(4):
        for j in range(5):
            x, y = 508 + i * 90, 108 + j * 108
            p.rect([x, y, x + 80, y + 96], outline=hx("#8A7A5E"), width=3)
    p.rect([0, 648, 900, 900], fill=hx("#CBB88C"))
    for y in [712, 792, 872]:
        p.line([(0, y), (900, y)], fill=hx("#B3A075"), width=3)
    for x in [200, 420, 640]:
        p.line([(x, 648), (x, 900)], fill=hx("#B3A075"), width=2)
    # scroll
    p.rect([84, 148, 262, 528], fill=hx("#F7F2E5"))
    p.rect([72, 126, 274, 156], fill=hx("#5B4A35"))
    p.rect([72, 520, 274, 550], fill=hx("#5B4A35"))
    vtext(p, 172, 300, "茶", 92, hx("#3A352C"))
    # table
    p.rect([372, 640, 772, 706], fill=hx("#6B4B32"))
    p.rect([396, 706, 436, 792], fill=hx("#5A3F2A"))
    p.rect([708, 706, 748, 792], fill=hx("#5A3F2A"))
    # teapot + cup
    p.ellipse([462, 586, 588, 660], fill=hx("#46463F"))
    p.rect([508, 548, 548, 594], fill=hx("#46463F"))
    p.ellipse([506, 536, 550, 560], fill=hx("#5A5A52"))
    p.line([(586, 612), (642, 584)], fill=hx("#46463F"), width=11)
    p.arc([596, 596, 648, 640], 270, 30, fill=hx("#46463F"), width=9)
    p.ellipse([656, 616, 726, 662], fill=hx("#DCD3BE"))
    p.ellipse([664, 620, 718, 650], fill=hx("#8A7A5E"))
    # steam
    p.line([(516, 520), (528, 486), (512, 452)], fill=hx("#D8CDBB"), width=5)
    p.line([(546, 524), (558, 492), (546, 462)], fill=hx("#D8CDBB"), width=4)
    caption(p, "MOCK · B02 日本茶室")
    return finish(img, grain=3.0, seed=42)


def scene_b3():
    """中式婚礼"""
    img, p = new_canvas("#8E1B2B", "#430D18")
    p.rect([22, 22, 878, 878], outline=hx("#D9A441"), width=6)
    p.rect([40, 40, 860, 860], outline=hx("#B4802F"), width=2)
    p.text((450, 292), "囍", 268, hx("#E8B04B"), bold=True, anchor="mm")
    for x in [128, 772]:
        p.line([(x, 0), (x, 108)], fill=hx("#D9A441"), width=4)
        p.ellipse([x - 48, 108, x + 48, 232], fill=hx("#E8B04B"))
        p.rect([x - 20, 232, x + 20, 246], fill=hx("#B5653A"))
        p.line([(x, 246), (x, 286)], fill=hx("#D9A441"), width=4)
    # couple silhouettes
    # bride
    p.ellipse([386, 700, 458, 772], fill=hx("#F0D3B4"))
    p.poly([(386, 716), (458, 716), (470, 700), (374, 700)], fill=hx("#B02A3A"))
    p.poly([(378, 770), (466, 770), (508, 900), (336, 900)], fill=hx("#C0392B"))
    p.poly([(392, 690), (452, 690), (470, 742), (374, 742)], fill=hx("#D9A441"))
    # groom
    p.ellipse([510, 690, 574, 754], fill=hx("#E8C4A2"))
    p.poly([(500, 754), (584, 754), (612, 900), (472, 900)], fill=hx("#7A1E2A"))
    p.rect([498, 700, 586, 716], fill=hx("#3A2A24"))
    # confetti
    rng = random.Random(77)
    for _ in range(40):
        x, y = rng.randint(60, 840), rng.randint(480, 880)
        r = rng.choice([4, 5, 7])
        p.ellipse([x - r, y - r, x + r, y + r], fill=hx("#E8B04B") if rng.random() < 0.5 else hx("#F2D9A0"))
    caption(p, "MOCK · B03 中式婚礼")
    return finish(img, grain=3.0, seed=43)


# --------------------------------------------------------------------------
def main():
    for fn, name in [
        (scene_a1, "a1.png"),
        (scene_a2, "a2.png"),
        (scene_a3, "a3.png"),
        (scene_a4, "a4.png"),
        (scene_a5, "a5.png"),
        (scene_a6, "a6.png"),
    ]:
        save(fn(), name)

    for fn, stem, a_kind, b_kind in [
        (scene_b1, "b1", "crisp", "soft"),
        (scene_b2, "b2", "soft", "crisp"),
        (scene_b3, "b3", "crisp", "soft"),
    ]:
        base = fn()
        variants = {"crisp": sharpen(base.copy()), "soft": soften(base.copy())}
        save(variants[a_kind], stem + "a.png")
        save(variants[b_kind], stem + "b.png")


if __name__ == "__main__":
    main()
