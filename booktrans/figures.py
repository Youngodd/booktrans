"""Clean ink layer of a scanned page: lines, curves and symbols on white paper."""

INK_DPI = 200
INK_LEVEL = 150  # after flattening, pixels darker than this (of 255) count as ink


def ink_layer(page, erase_rects):
    """JPEG bytes of the page's ink on white, with the text in `erase_rects` removed.

    The scan's paper tone and shadows are divided out, so the background turns
    white. The rectangles are the English text that gets redrawn in Chinese;
    everything else dark (rules, curves, symbols, figure drawings) is kept.
    Dark blobs touching the page edge (binding shadow, scanner border) and
    specks are dropped.
    """
    import cv2
    import numpy as np
    import fitz

    pix = page.get_pixmap(dpi=INK_DPI, colorspace=fitz.csGRAY, alpha=False)
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    k = int(INK_DPI * 0.12) | 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    paper = cv2.GaussianBlur(cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel), (0, 0), k / 2)
    flat = np.clip(gray.astype(np.float32) / np.maximum(paper, 1) * 255, 0, 255)

    ink = (flat < INK_LEVEL).astype(np.uint8)
    s = INK_DPI / 72
    for r in erase_rects:
        x0, y0 = max(int((r[0] - 1.5) * s), 0), max(int((r[1] - 1.5) * s), 0)
        ink[y0:int((r[3] + 1.5) * s), x0:int((r[2] + 1.5) * s)] = 0

    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    edge = 0.015 * max(pix.width, pix.height)
    keep = np.zeros(n, dtype=bool)
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        touches = x < edge or y < edge or x + w > pix.width - edge or y + h > pix.height - edge
        keep[i] = area >= 30 and not touches
    mask = cv2.dilate(keep[labels].astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    out = np.full(gray.shape, 255, dtype=np.uint8)
    out[mask] = flat[mask].astype(np.uint8)
    # JPEG, not PNG: PDF stores a decoded PNG nearly uncompressed (several MB a page)
    return cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()
