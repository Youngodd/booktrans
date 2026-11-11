"""Draws the Book Translator icon and exports icon.svg, PNGs and BookTranslator.ico.

Single source of truth: the geometry below (512x512 canvas). Run:
    python assets/icon/make_icon.py
Needs only Pillow. Re-run after any colour/shape edit.
"""
import io, struct, pathlib
from PIL import Image, ImageDraw

OUT = pathlib.Path(__file__).parent
RED, WHITE, EDGE = "#E4351C", "#FFFFFF", "#FFC4B0"   # vivid vermilion-terracotta, page, page edge

PAGES = [  # (colour, polygon)
    (EDGE,  [(88, 344), (248, 384), (248, 410), (88, 370)]),
    (EDGE,  [(424, 344), (264, 384), (264, 410), (424, 370)]),
    (WHITE, [(88, 156), (248, 196), (248, 384), (88, 344)]),
    (WHITE, [(424, 156), (264, 196), (264, 384), (424, 344)]),
]
GLYPH = [  # (width, [points]) round-capped strokes in RED: "A" left, simplified "文" right
    (22, [(130, 330), (168, 218), (206, 330)]), (22, [(145, 296), (191, 296)]),
    (20, [(344, 204), (344, 224)]), (20, [(300, 246), (388, 246)]),
    (20, [(358, 250), (308, 332)]), (20, [(322, 262), (384, 332)]),
]
SMALL_GLYPH = []       # 16/24 px: plain book, glyphs would turn to noise

def svg(glyph=GLYPH):
    p = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">',
         f'<rect x="40" y="40" width="432" height="432" rx="104" fill="{RED}"/>']
    for c, pts in PAGES:
        p.append(f'<polygon points="{" ".join(f"{x},{y}" for x, y in pts)}" fill="{c}"/>')
    for w, pts in glyph:
        p.append(f'<polyline points="{" ".join(f"{x},{y}" for x, y in pts)}" fill="none" stroke="{RED}" '
                 f'stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"/>')
    return "\n".join(p) + "\n</svg>\n"

def render(size, glyph=GLYPH, ss=8):
    S = size * ss; k = S / 512
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rounded_rectangle([40*k, 40*k, 472*k, 472*k], radius=104*k, fill=RED)
    for c, pts in PAGES:
        d.polygon([(x*k, y*k) for x, y in pts], fill=c)
    for w, pts in glyph:
        r = w*k/2
        for a, b in zip(pts, pts[1:]):
            d.line([(a[0]*k, a[1]*k), (b[0]*k, b[1]*k)], fill=RED, width=round(w*k))
        for x, y in pts:
            d.ellipse([x*k-r, y*k-r, x*k+r, y*k+r], fill=RED)
    return im.resize((size, size), Image.LANCZOS)

def pick(size):
    return SMALL_GLYPH if size <= 24 else GLYPH

(OUT / "icon.svg").write_text(svg())
sizes_png = [16, 20, 24, 30, 32, 36, 40, 48, 60, 64, 72, 80, 96, 128, 256, 512]
for s in sizes_png:
    render(s, pick(s)).save(OUT / f"icon_{s}.png")

ico_sizes = [16, 24, 32, 48, 64, 128, 256]
blobs = []
for s in ico_sizes:
    b = io.BytesIO(); render(s, pick(s)).save(b, "PNG"); blobs.append(b.getvalue())
hdr = struct.pack("<HHH", 0, 1, len(ico_sizes)); off = 6 + 16 * len(ico_sizes); ent = b""
for s, data in zip(ico_sizes, blobs):
    ent += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), off); off += len(data)
(OUT / "BookTranslator.ico").write_bytes(hdr + ent + b"".join(blobs))

# contact sheet: 16/32/48/256 on light and dark
sheet = Image.new("RGB", (2 * 420, 300))
for i, bg in enumerate([(245, 243, 240), (32, 32, 32)]):
    sheet.paste(Image.new("RGB", (420, 300), bg), (i * 420, 0))
    x = i * 420 + 16
    for s in (16, 32, 48, 256):
        im = render(s, pick(s)); sheet.paste(im, (x, 20 if s == 256 else 130), im); x += s + 20
sheet.save(OUT / "contact_sheet.png")
