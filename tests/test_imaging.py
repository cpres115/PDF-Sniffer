# Author:  Corey Preston
# Company: Fischer Connectors, Inc
# Date:    October 2026
import unittest
from collections import deque

import numpy as np

from pdf_sniffer import imaging


def flood_components(mask):
    """Reference 8-connected labelling by breadth-first search."""
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    out = []
    for y in range(h):
        for x in range(w):
            if mask[y, x] and not seen[y, x]:
                q, pts = deque([(y, x)]), []
                seen[y, x] = True
                while q:
                    cy, cx = q.popleft()
                    pts.append((cy, cx))
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = cy + dy, cx + dx
                            if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                                seen[ny, nx] = True
                                q.append((ny, nx))
                ys, xs = zip(*pts)
                out.append((min(xs), min(ys), max(xs) + 1, max(ys) + 1, len(pts)))
    return sorted(out)


def ring_mask(shape, cx, cy, radius, thickness):
    yy, xx = np.mgrid[:shape[0], :shape[1]]
    d = np.hypot(xx - cx, yy - cy)
    return (d <= radius) & (d >= radius - thickness)


class ComponentTests(unittest.TestCase):
    def test_matches_reference_on_random_masks(self):
        rng = np.random.default_rng(7)
        for density in (0.02, 0.1, 0.3, 0.5):
            mask = rng.random((60, 80)) < density
            got = sorted((c.x0, c.y0, c.x1, c.y1, c.area) for c in imaging.label_components(mask))
            self.assertEqual(got, flood_components(mask), density)

    def test_empty_mask(self):
        self.assertEqual(imaging.label_components(np.zeros((10, 10), bool)), [])


class RingTests(unittest.TestCase):
    def test_finds_rings_and_ignores_non_rings(self):
        shape = (400, 600)
        mask = ring_mask(shape, 300, 200, 60, 5) | ring_mask(shape, 80, 90, 25, 3)
        mask[185:215, 270:275] = True  # letter-like bars inside the big ring
        rings = imaging.find_rings(mask, 30, 200)
        self.assertEqual(sorted(round(r.r_out) for r in rings), [26, 61])
        yy, xx = np.mgrid[:400, :600]
        disc = np.hypot(xx - 300, yy - 200) <= 60
        square = np.zeros(shape, bool)
        square[140:260, 240:360] = True
        square[145:255, 245:355] = False
        half = ring_mask(shape, 300, 200, 60, 5) & (yy < 200)
        for name, m in (("disc", disc), ("square", square), ("half ring", half)):
            self.assertEqual(imaging.find_rings(m, 30, 200), [], name)

    def test_broken_ring_is_bridged(self):
        mask = ring_mask((200, 200), 100, 100, 50, 3)
        mask[48:53, 95:105] = False  # 5px gap in the outline
        self.assertEqual(len(imaging.find_rings(mask, 40, 150)), 1)


class RedMaskTests(unittest.TestCase):
    def test_colours(self):
        px = np.array([[[255, 0, 0], [200, 30, 30], [255, 128, 128], [255, 165, 0], [0, 0, 0],
                        [255, 255, 255], [120, 60, 60], [255, 190, 190], [0, 0, 255]]], dtype=np.uint8)
        # red, dark red, anti-aliased red edge -> ink; orange, black, white, brown, lone pink, blue -> not
        self.assertEqual(imaging.red_mask(px)[0].astype(int).tolist(), [1, 1, 1, 0, 0, 0, 0, 0, 0])


if __name__ == "__main__":
    unittest.main()
