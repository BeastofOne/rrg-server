# Jake's Handwriting Stroke Font — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Convert JakesHandwriting-Regular.ttf (outline font) into a single-stroke SVG font for AxiDraw's Hershey Text Advanced extension.

**Architecture:** Single Python script (`convert_to_stroke_font.py`) that rasterizes each TTF glyph, extracts the centerline skeleton via morphological thinning, traces skeleton pixels into ordered path segments, applies standard English stroke ordering, and exports an HTA-compatible SVG font plus a PDF preview for visual review.

**Tech Stack:** Python 3.9, fontTools, Pillow, scikit-image, scipy, numpy, reportlab

**Design doc:** `docs/plans/2026-03-11-handwriting-stroke-font-design.md`

---

### Task 1: Project Setup

**Files:**
- Create: `~/Downloads/stroke-font/convert_to_stroke_font.py`
- Create: `~/Downloads/stroke-font/requirements.txt`

**Step 1: Create project directory and requirements**

```bash
mkdir -p ~/Downloads/stroke-font
```

**Step 2: Write requirements.txt**

```
fontTools
Pillow
scikit-image
scipy
numpy
reportlab
```

**Step 3: Verify all deps are available**

```bash
python3 -c "import fontTools, PIL, skimage, scipy, numpy, reportlab; print('All deps OK')"
```

Expected: `All deps OK`

**Step 4: Create script skeleton**

Create `convert_to_stroke_font.py` with the following structure:

```python
#!/usr/bin/env python3
"""Convert a TTF outline font to a single-stroke SVG font for AxiDraw HTA."""

import sys
import numpy as np
from pathlib import Path
from PIL import Image, ImageFont, ImageDraw
from fontTools.ttLib import TTFont
from skimage.morphology import skeletonize
from scipy.ndimage import convolve, label
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from collections import defaultdict


# === Configuration ===

RENDER_SIZE = 400        # Font size for rasterization (px)
CANVAS_W = 500           # Render canvas width
CANVAS_H = 600           # Render canvas height
RENDER_OFFSET = (50, 50) # Top-left offset for rendering
SPUR_THRESHOLD = 8       # Min branch length (pixels) to keep
SIMPLIFY_TOLERANCE = 2.0 # Path simplification tolerance (pixels)

# Standard stroke ordering for English letters.
# Each entry: list of stroke descriptors in pen-down order.
# Descriptors: 'top-down', 'left-right', 'diagonal-down-right', etc.
# Used to sort traced strokes into correct writing order.
STROKE_ORDER = {}  # Populated in Task 5


def main():
    if len(sys.argv) < 2:
        print("Usage: convert_to_stroke_font.py <input.ttf> [output.svg]")
        sys.exit(1)

    ttf_path = Path(sys.argv[1])
    svg_path = Path(sys.argv[2]) if len(sys.argv) > 2 else ttf_path.with_suffix('.svg')
    pdf_path = svg_path.with_suffix('.pdf')

    font_data = load_font(ttf_path)
    glyphs = {}
    for char, glyph_name in font_data['char_map'].items():
        img = rasterize_glyph(font_data, char)
        skeleton = extract_skeleton(img)
        strokes = trace_strokes(skeleton)
        strokes = order_strokes(strokes, char)
        font_coords = pixel_to_font_coords(strokes, font_data)
        glyphs[char] = {
            'name': glyph_name,
            'strokes': font_coords,
            'advance_width': font_data['advances'][glyph_name],
        }

    write_svg_font(glyphs, font_data, svg_path)
    write_preview_pdf(glyphs, font_data, pdf_path)
    print(f"SVG font: {svg_path}")
    print(f"Preview:  {pdf_path}")


if __name__ == '__main__':
    main()
```

**Step 5: Commit**

```bash
cd ~/Downloads/stroke-font
git init && git add -A && git commit -m "feat: scaffold stroke font converter"
```

---

### Task 2: Font Loading and Glyph Rasterization

**Files:**
- Modify: `~/Downloads/stroke-font/convert_to_stroke_font.py`

**Step 1: Implement load_font()**

```python
def load_font(ttf_path):
    """Load TTF and extract metadata needed for conversion."""
    tt = TTFont(str(ttf_path))
    gs = tt.getGlyphSet()
    upm = tt['head'].unitsPerEm

    # Build unicode → glyph name map
    cmap = tt.getBestCmap()
    char_map = {}
    advances = {}
    for codepoint, glyph_name in cmap.items():
        char = chr(codepoint)
        if glyph_name in gs:
            char_map[char] = glyph_name
            advances[glyph_name] = gs[glyph_name].width

    pil_font = ImageFont.truetype(str(ttf_path), RENDER_SIZE)

    return {
        'tt': tt,
        'glyph_set': gs,
        'upm': upm,
        'char_map': char_map,
        'advances': advances,
        'pil_font': pil_font,
        'ttf_path': ttf_path,
    }
```

**Step 2: Implement rasterize_glyph()**

```python
def rasterize_glyph(font_data, char):
    """Render a single character to a binary numpy array."""
    font = font_data['pil_font']
    img = Image.new('L', (CANVAS_W, CANVAS_H), 0)
    draw = ImageDraw.Draw(img)
    draw.text(RENDER_OFFSET, char, fill=255, font=font)
    return np.array(img) > 128
```

**Step 3: Test rasterization**

```bash
cd ~/Downloads/stroke-font
python3 -c "
from convert_to_stroke_font import *
fd = load_font(Path('/Users/jacobphillips/Downloads/JakesHandwriting-Regular.ttf'))
print(f'Loaded {len(fd[\"char_map\"])} glyphs, UPM={fd[\"upm\"]}')
img = rasterize_glyph(fd, 'A')
print(f'A rasterized: {img.shape}, pixels={np.count_nonzero(img)}')
img = rasterize_glyph(fd, 'g')
print(f'g rasterized: {img.shape}, pixels={np.count_nonzero(img)}')
"
```

Expected: Glyph counts loaded, non-zero pixel counts for A and g.

**Step 4: Commit**

```bash
git add -A && git commit -m "feat: font loading and glyph rasterization"
```

---

### Task 3: Skeleton Extraction and Spur Pruning

**Files:**
- Modify: `~/Downloads/stroke-font/convert_to_stroke_font.py`

**Step 1: Implement extract_skeleton()**

```python
def extract_skeleton(binary_img):
    """Skeletonize a binary glyph image and prune short spurs."""
    skeleton = skeletonize(binary_img)
    skeleton = prune_spurs(skeleton)
    return skeleton


def prune_spurs(skeleton, min_length=SPUR_THRESHOLD):
    """Remove short branches (spurs) from skeleton."""
    kernel = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]])
    changed = True
    while changed:
        changed = False
        neighbor_count = convolve(skeleton.astype(np.uint8), kernel, mode='constant')
        # Endpoints have exactly 1 neighbor
        endpoints = (neighbor_count == 1) & skeleton
        ep_coords = np.argwhere(endpoints)
        for ey, ex in ep_coords:
            # Trace from endpoint until we hit a junction or another endpoint
            path = trace_single_branch(skeleton, ey, ex)
            if len(path) < min_length:
                # Check if the other end is a junction (not another endpoint)
                ly, lx = path[-1]
                nc = neighbor_count[ly, lx]
                if nc >= 3 or len(path) < min_length:
                    # Remove this spur
                    for py, px in path[:-1]:  # Keep the junction point
                        skeleton[py, px] = False
                    changed = True
    return skeleton


def trace_single_branch(skeleton, start_y, start_x):
    """Trace a branch from an endpoint until hitting a junction or dead end."""
    kernel = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]])
    path = [(start_y, start_x)]
    visited = {(start_y, start_x)}
    y, x = start_y, start_x
    while True:
        # Find unvisited neighbors
        neighbors = []
        for dy in [-1, 0, 1]:
            for dx in [-1, 0, 1]:
                if dy == 0 and dx == 0:
                    continue
                ny, nx = y + dy, x + dx
                if (0 <= ny < skeleton.shape[0] and 0 <= nx < skeleton.shape[1]
                        and skeleton[ny, nx] and (ny, nx) not in visited):
                    neighbors.append((ny, nx))
        if len(neighbors) == 0:
            break  # Dead end
        if len(neighbors) > 1:
            break  # Junction
        # Continue along single path
        y, x = neighbors[0]
        path.append((y, x))
        visited.add((y, x))
    return path
```

**Step 2: Test skeleton extraction**

```bash
python3 -c "
from convert_to_stroke_font import *
fd = load_font(Path('/Users/jacobphillips/Downloads/JakesHandwriting-Regular.ttf'))
for ch in ['A', 'H', 'o', 'i']:
    img = rasterize_glyph(fd, ch)
    skel = extract_skeleton(img)
    print(f'{ch}: {np.count_nonzero(skel)} skeleton pixels')
"
```

Expected: Reasonable pixel counts (200-800 per character), lower than without pruning.

**Step 3: Commit**

```bash
git add -A && git commit -m "feat: skeleton extraction with spur pruning"
```

---

### Task 4: Skeleton Tracing — Pixels to Path Segments

**Files:**
- Modify: `~/Downloads/stroke-font/convert_to_stroke_font.py`

This is the most complex task. We need to convert a 1px-wide skeleton bitmap into a list of ordered polyline strokes.

**Step 1: Implement find_topology()**

```python
def find_topology(skeleton):
    """Find endpoints, junctions, and merge nearby junction clusters."""
    kernel = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]])
    neighbor_count = convolve(skeleton.astype(np.uint8), kernel, mode='constant')
    neighbor_count = neighbor_count * skeleton

    endpoint_mask = (neighbor_count == 1) & skeleton
    junction_mask = (neighbor_count >= 3) & skeleton

    # Merge nearby junction pixels into single junction points
    labeled, n_junctions = label(junction_mask)
    junctions = []
    for i in range(1, n_junctions + 1):
        cluster = np.argwhere(labeled == i)
        center = cluster.mean(axis=0).astype(int)
        junctions.append(tuple(center))

    endpoints = [tuple(p) for p in np.argwhere(endpoint_mask)]

    return endpoints, junctions
```

**Step 2: Implement trace_strokes()**

```python
def trace_strokes(skeleton):
    """Trace skeleton into a list of polyline strokes.

    Returns: list of strokes, where each stroke is a list of (y, x) pixel coords.
    """
    endpoints, junctions = find_topology(skeleton)
    special_points = set(endpoints + junctions)

    # Trace all paths between special points
    strokes = []
    visited_edges = set()  # Track visited pixel pairs to avoid duplicates

    # Start from endpoints first (they give clean stroke starts)
    start_points = endpoints + junctions
    for sy, sx in start_points:
        # Try tracing from each unvisited direction
        for dy in [-1, 0, 1]:
            for dx in [-1, 0, 1]:
                if dy == 0 and dx == 0:
                    continue
                ny, nx = sy + dy, sx + dx
                if (0 <= ny < skeleton.shape[0] and 0 <= nx < skeleton.shape[1]
                        and skeleton[ny, nx]
                        and ((sy, sx, ny, nx) not in visited_edges)):
                    stroke = trace_path(skeleton, sy, sx, ny, nx,
                                       special_points, visited_edges)
                    if stroke and len(stroke) >= 2:
                        strokes.append(stroke)

    # Simplify paths (reduce point count while preserving shape)
    strokes = [simplify_path(s, SIMPLIFY_TOLERANCE) for s in strokes]
    return strokes


def trace_path(skeleton, sy, sx, ny, nx, special_points, visited_edges):
    """Trace a single path from (sy,sx) through (ny,nx) until hitting
    another special point or dead end."""
    path = [(sy, sx)]
    visited_edges.add((sy, sx, ny, nx))
    visited_edges.add((ny, nx, sy, sx))
    visited = {(sy, sx)}

    y, x = ny, nx
    path.append((y, x))
    visited.add((y, x))

    while (y, x) not in special_points or len(path) == 2:
        if (y, x) in special_points and len(path) > 2:
            break
        neighbors = []
        for dy in [-1, 0, 1]:
            for dx in [-1, 0, 1]:
                if dy == 0 and dx == 0:
                    continue
                cy, cx = y + dy, x + dx
                if (0 <= cy < skeleton.shape[0] and 0 <= cx < skeleton.shape[1]
                        and skeleton[cy, cx] and (cy, cx) not in visited):
                    neighbors.append((cy, cx))
        if len(neighbors) == 0:
            break
        # Pick the neighbor closest to continuing straight
        if len(path) >= 2:
            prev_y, prev_x = path[-2]
            dir_y, dir_x = y - prev_y, x - prev_x
            best = min(neighbors, key=lambda n: abs((n[0]-y) - dir_y) + abs((n[1]-x) - dir_x))
        else:
            best = neighbors[0]
        ny2, nx2 = best
        visited_edges.add((y, x, ny2, nx2))
        visited_edges.add((ny2, nx2, y, x))
        y, x = ny2, nx2
        path.append((y, x))
        visited.add((y, x))

    return path


def simplify_path(path, tolerance):
    """Ramer-Douglas-Peucker path simplification."""
    if len(path) <= 2:
        return path

    # Find point farthest from line between first and last
    start = np.array(path[0], dtype=float)
    end = np.array(path[-1], dtype=float)
    line_vec = end - start
    line_len = np.linalg.norm(line_vec)

    if line_len < 1e-10:
        # Start and end are same point — find farthest from start
        dists = [np.linalg.norm(np.array(p) - start) for p in path]
        max_idx = np.argmax(dists)
        max_dist = dists[max_idx]
    else:
        line_unit = line_vec / line_len
        dists = []
        for p in path:
            v = np.array(p, dtype=float) - start
            proj = np.dot(v, line_unit)
            closest = start + proj * line_unit
            dists.append(np.linalg.norm(np.array(p) - closest))
        max_idx = np.argmax(dists)
        max_dist = dists[max_idx]

    if max_dist <= tolerance:
        return [path[0], path[-1]]

    left = simplify_path(path[:max_idx + 1], tolerance)
    right = simplify_path(path[max_idx:], tolerance)
    return left[:-1] + right
```

**Step 3: Test stroke tracing on multiple characters**

```bash
python3 -c "
from convert_to_stroke_font import *
fd = load_font(Path('/Users/jacobphillips/Downloads/JakesHandwriting-Regular.ttf'))
for ch in ['A', 'H', 'i', 'o', 'T', 'E']:
    img = rasterize_glyph(fd, ch)
    skel = extract_skeleton(img)
    strokes = trace_strokes(skel)
    total_pts = sum(len(s) for s in strokes)
    print(f'{ch}: {len(strokes)} strokes, {total_pts} total points')
"
```

Expected: Each letter decomposes into a reasonable number of strokes (A=3-4, H=3, i=2, o=1, T=2, E=4).

**Step 4: Commit**

```bash
git add -A && git commit -m "feat: skeleton tracing — pixels to polyline strokes"
```

---

### Task 5: Stroke Ordering

**Files:**
- Modify: `~/Downloads/stroke-font/convert_to_stroke_font.py`

**Step 1: Implement order_strokes()**

Standard English print letter stroke ordering. Rather than hard-coding every letter, use heuristic rules with overrides for letters that need specific ordering.

```python
def order_strokes(strokes, char):
    """Order strokes according to standard English writing conventions.

    Rules:
    1. Top-to-bottom (strokes starting higher come first)
    2. Left-to-right (ties broken by leftmost start)
    3. Main body before details (long strokes before short)
    4. Vertical before horizontal at same position

    Special cases are handled for letters where these heuristics fail.
    """
    if not strokes:
        return strokes

    def stroke_start(s):
        """Return the 'natural' start point of a stroke (top-left)."""
        y0, x0 = s[0]
        y1, x1 = s[-1]
        # Prefer the end that is higher (lower y); if same, prefer left
        if y0 < y1 - 5:
            return (y0, x0)
        elif y1 < y0 - 5:
            return (y1, x1)
        elif x0 <= x1:
            return (y0, x0)
        else:
            return (y1, x1)

    def orient_stroke(s):
        """Orient stroke so it goes in natural writing direction."""
        y0, x0 = s[0]
        y1, x1 = s[-1]
        dy = y1 - y0
        dx = x1 - x0
        # Primarily top-to-bottom
        if abs(dy) > abs(dx) * 0.5:
            if dy < 0:
                return list(reversed(s))
        # Horizontal: left to right
        elif dx < 0:
            return list(reversed(s))
        return s

    def stroke_sort_key(s):
        """Sort key: primary=vertical position, secondary=horizontal."""
        start = stroke_start(s)
        length = len(s)
        is_mainly_horizontal = abs(s[-1][0] - s[0][0]) < abs(s[-1][1] - s[0][1]) * 0.5
        # Horizontal crossbars (like in H, A, E) go after verticals
        h_penalty = 1000 if is_mainly_horizontal else 0
        return (h_penalty, start[0], start[1], -length)

    # Orient each stroke in natural direction
    strokes = [orient_stroke(s) for s in strokes]

    # Sort by position with horizontal-after-vertical rule
    strokes.sort(key=stroke_sort_key)

    return strokes
```

**Step 2: Test stroke ordering**

```bash
python3 -c "
from convert_to_stroke_font import *
fd = load_font(Path('/Users/jacobphillips/Downloads/JakesHandwriting-Regular.ttf'))
for ch in ['H', 'T', 'E', 'A']:
    img = rasterize_glyph(fd, ch)
    skel = extract_skeleton(img)
    strokes = trace_strokes(skel)
    ordered = order_strokes(strokes, ch)
    print(f'{ch}: {len(ordered)} strokes')
    for i, s in enumerate(ordered):
        y0, x0 = s[0]
        y1, x1 = s[-1]
        vert = 'V' if abs(y1-y0) > abs(x1-x0) else 'H'
        print(f'  Stroke {i+1}: ({x0},{y0}) -> ({x1},{y1}) [{vert}]')
"
```

Expected: H shows left-vertical, right-vertical, then horizontal crossbar. T shows horizontal top, then vertical stem.

**Step 3: Commit**

```bash
git add -A && git commit -m "feat: stroke ordering with writing convention heuristics"
```

---

### Task 6: Coordinate Conversion and SVG Font Export

**Files:**
- Modify: `~/Downloads/stroke-font/convert_to_stroke_font.py`

**Step 1: Implement pixel_to_font_coords()**

```python
def pixel_to_font_coords(strokes, font_data):
    """Convert pixel coordinates back to font coordinate space.

    Pixel space: origin top-left, y increases downward
    Font space: origin baseline-left, y increases upward, units-per-em=1000
    """
    upm = font_data['upm']
    # Calculate scale: RENDER_SIZE pixels = upm font units
    scale = upm / RENDER_SIZE

    # Get font metrics for baseline position
    tt = font_data['tt']
    ascent = tt['OS/2'].sTypoAscender
    # In pixel space, baseline is at RENDER_OFFSET[1] + (ascent / upm * RENDER_SIZE)
    baseline_px = RENDER_OFFSET[1] + (ascent / upm * RENDER_SIZE)

    converted = []
    for stroke in strokes:
        new_stroke = []
        for py, px in stroke:
            # Convert pixel to font coords
            fx = (px - RENDER_OFFSET[0]) * scale
            fy = (baseline_px - py) * scale  # Flip y axis
            new_stroke.append((round(fx, 1), round(fy, 1)))
        converted.append(new_stroke)
    return converted
```

**Step 2: Implement write_svg_font()**

```python
def write_svg_font(glyphs, font_data, svg_path):
    """Write HTA-compatible SVG font file."""
    upm = font_data['upm']
    tt = font_data['tt']
    ascent = tt['OS/2'].sTypoAscender
    descent = tt['OS/2'].sTypoDescender

    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8" ?>')
    lines.append('<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
                 '"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd" >')
    lines.append('')
    lines.append('<svg xmlns="http://www.w3.org/2000/svg" '
                 'xmlns:xlink="http://www.w3.org/1999/xlink" version="1.1">')
    lines.append('')
    lines.append('<metadata>')
    lines.append("Font name:               Jake's Handwriting")
    lines.append('Converted by:            stroke font converter')
    lines.append('Source:                   JakesHandwriting-Regular.ttf')
    lines.append('</metadata>')
    lines.append('<defs>')

    # Default advance width (median of all glyphs)
    adv_widths = [g['advance_width'] for g in glyphs.values()]
    default_adv = int(np.median(adv_widths)) if adv_widths else 500

    lines.append(f'<font id="JakesHandwriting" horiz-adv-x="{default_adv}" >')
    lines.append('<font-face')
    lines.append(f'font-family="Jakes Handwriting"')
    lines.append(f'units-per-em="{upm}"')
    lines.append(f'ascent="{ascent}"')
    lines.append(f'descent="{descent}"')
    lines.append(f'cap-height="700"')
    lines.append(f'x-height="500"')
    lines.append('/>')
    lines.append(f'<missing-glyph horiz-adv-x="{default_adv}" />')

    # Space glyph
    space_adv = glyphs.get(' ', {}).get('advance_width', default_adv)
    lines.append(f'<glyph unicode=" " glyph-name="space" horiz-adv-x="{space_adv}" />')

    for char, glyph in sorted(glyphs.items()):
        if char == ' ':
            continue
        # Build path data from strokes
        path_parts = []
        for stroke in glyph['strokes']:
            if not stroke:
                continue
            fx, fy = stroke[0]
            path_parts.append(f'M {fx} {fy}')
            for fx, fy in stroke[1:]:
                path_parts.append(f'L {fx} {fy}')
        d = ' '.join(path_parts)

        # Escape special XML chars
        unicode_str = char
        if char == '"':
            unicode_str = '&#x22;'
        elif char == '&':
            unicode_str = '&amp;'
        elif char == "'":
            unicode_str = '&apos;'
        elif char == '<':
            unicode_str = '&#x3c;'
        elif char == '>':
            unicode_str = '&#x3e;'

        adv = glyph['advance_width']
        name = glyph['name']
        if d:
            lines.append(f'<glyph unicode="{unicode_str}" glyph-name="{name}" '
                        f'horiz-adv-x="{adv}" d="{d}" />')
        else:
            lines.append(f'<glyph unicode="{unicode_str}" glyph-name="{name}" '
                        f'horiz-adv-x="{adv}" />')

    lines.append('</font>')
    lines.append('</defs>')
    lines.append('</svg>')

    svg_path.write_text('\n'.join(lines))
```

**Step 3: Test SVG generation on a few characters**

```bash
python3 -c "
from convert_to_stroke_font import *
fd = load_font(Path('/Users/jacobphillips/Downloads/JakesHandwriting-Regular.ttf'))
# Process just A, B, C
test_glyphs = {}
for char in ['A', 'B', 'C']:
    gname = fd['char_map'].get(char)
    if not gname: continue
    img = rasterize_glyph(fd, char)
    skel = extract_skeleton(img)
    strokes = trace_strokes(skel)
    strokes = order_strokes(strokes, char)
    fc = pixel_to_font_coords(strokes, fd)
    test_glyphs[char] = {'name': gname, 'strokes': fc, 'advance_width': fd['advances'][gname]}
write_svg_font(test_glyphs, fd, Path('/tmp/test_font.svg'))
print(open('/tmp/test_font.svg').read()[:2000])
"
```

Expected: Valid SVG font XML with glyph elements containing M/L path data.

**Step 4: Commit**

```bash
git add -A && git commit -m "feat: coordinate conversion and SVG font export"
```

---

### Task 7: PDF Preview Generator

**Files:**
- Modify: `~/Downloads/stroke-font/convert_to_stroke_font.py`

**Step 1: Implement write_preview_pdf()**

```python
# Color palette for numbering strokes
STROKE_COLORS = [
    (1, 0, 0),       # red
    (0, 0, 1),       # blue
    (0, 0.6, 0),     # green
    (0.8, 0, 0.8),   # purple
    (1, 0.5, 0),     # orange
    (0, 0.7, 0.7),   # teal
    (0.6, 0.3, 0),   # brown
    (0.5, 0.5, 0.5), # gray
]


def write_preview_pdf(glyphs, font_data, pdf_path):
    """Generate PDF showing each glyph with numbered, colored strokes."""
    c = canvas.Canvas(str(pdf_path), pagesize=letter)
    page_w, page_h = letter

    # Layout: grid of characters, 6 columns x 8 rows per page
    cols, rows = 6, 8
    cell_w = (page_w - 80) / cols
    cell_h = (page_h - 100) / rows
    margin_x, margin_y = 40, 60

    chars = sorted(glyphs.keys())
    per_page = cols * rows

    for page_start in range(0, len(chars), per_page):
        page_chars = chars[page_start:page_start + per_page]

        # Page title
        c.setFont("Helvetica-Bold", 14)
        group_start = page_chars[0] if page_chars else '?'
        group_end = page_chars[-1] if page_chars else '?'
        c.drawString(margin_x, page_h - 30,
                     f"Jake's Handwriting Stroke Font — {group_start} to {group_end}")
        c.setFont("Helvetica", 8)
        c.drawString(margin_x, page_h - 42, "Strokes numbered and colored in pen order")

        for idx, char in enumerate(page_chars):
            col = idx % cols
            row = idx // cols
            cx = margin_x + col * cell_w
            cy = page_h - margin_y - (row + 1) * cell_h

            # Cell border
            c.setStrokeColorRGB(0.8, 0.8, 0.8)
            c.setLineWidth(0.5)
            c.rect(cx, cy, cell_w, cell_h)

            # Character label
            c.setFillColorRGB(0, 0, 0)
            c.setFont("Helvetica", 10)
            label = char if char.isprintable() else f'U+{ord(char):04X}'
            c.drawString(cx + 3, cy + cell_h - 12, label)

            glyph = glyphs[char]
            if not glyph['strokes']:
                continue

            # Find bounding box of all strokes for scaling
            all_pts = [pt for s in glyph['strokes'] for pt in s]
            if not all_pts:
                continue
            xs = [p[0] for p in all_pts]
            ys = [p[1] for p in all_pts]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            span_x = max_x - min_x or 1
            span_y = max_y - min_y or 1

            # Scale to fit cell with padding
            pad = 15
            draw_w = cell_w - 2 * pad
            draw_h = cell_h - 2 * pad - 12  # -12 for label
            scale = min(draw_w / span_x, draw_h / span_y) * 0.85

            def to_pdf(fx, fy):
                px = cx + pad + (fx - min_x) * scale
                py = cy + pad + (fy - min_y) * scale
                return px, py

            # Draw strokes
            for si, stroke in enumerate(glyph['strokes']):
                color = STROKE_COLORS[si % len(STROKE_COLORS)]
                c.setStrokeColorRGB(*color)
                c.setLineWidth(1.5)

                path = c.beginPath()
                px, py = to_pdf(*stroke[0])
                path.moveTo(px, py)
                for pt in stroke[1:]:
                    px, py = to_pdf(*pt)
                    path.lineTo(px, py)
                c.drawPath(path, stroke=1, fill=0)

                # Stroke number at start
                sx, sy = to_pdf(*stroke[0])
                c.setFillColorRGB(*color)
                c.setFont("Helvetica-Bold", 7)
                c.drawString(sx - 3, sy + 3, str(si + 1))

                # Arrow at end
                if len(stroke) >= 2:
                    ex, ey = to_pdf(*stroke[-1])
                    px2, py2 = to_pdf(*stroke[-2])
                    draw_arrow(c, px2, py2, ex, ey, color)

        c.showPage()
    c.save()


def draw_arrow(c, x1, y1, x2, y2, color):
    """Draw a small arrowhead at (x2, y2) pointing from (x1, y1)."""
    import math
    dx = x2 - x1
    dy = y2 - y1
    length = math.sqrt(dx * dx + dy * dy)
    if length < 1:
        return
    dx /= length
    dy /= length
    # Arrowhead size
    size = 4
    # Two points of arrowhead
    ax1 = x2 - size * (dx + dy * 0.5)
    ay1 = y2 - size * (dy - dx * 0.5)
    ax2 = x2 - size * (dx - dy * 0.5)
    ay2 = y2 - size * (dy + dx * 0.5)
    c.setFillColorRGB(*color)
    path = c.beginPath()
    path.moveTo(x2, y2)
    path.lineTo(ax1, ay1)
    path.lineTo(ax2, ay2)
    path.close()
    c.drawPath(path, stroke=0, fill=1)
```

**Step 2: Test PDF generation**

```bash
python3 -c "
from convert_to_stroke_font import *
fd = load_font(Path('/Users/jacobphillips/Downloads/JakesHandwriting-Regular.ttf'))
glyphs = {}
for char in 'ABCDEHITopqrst':
    gname = fd['char_map'].get(char)
    if not gname: continue
    img = rasterize_glyph(fd, char)
    skel = extract_skeleton(img)
    strokes = trace_strokes(skel)
    strokes = order_strokes(strokes, char)
    fc = pixel_to_font_coords(strokes, fd)
    glyphs[char] = {'name': gname, 'strokes': fc, 'advance_width': fd['advances'][gname]}
write_preview_pdf(glyphs, fd, Path('/tmp/test_preview.pdf'))
print('PDF written to /tmp/test_preview.pdf')
"
```

Expected: Opens in Preview showing characters with colored numbered strokes.

**Step 3: Commit**

```bash
git add -A && git commit -m "feat: PDF preview generator with numbered colored strokes"
```

---

### Task 8: Run Full Pipeline

**Files:**
- Modify: `~/Downloads/stroke-font/convert_to_stroke_font.py` (wire up main)

**Step 1: Verify main() is wired correctly**

The `main()` function from Task 1 should already call all the pieces. Run the full pipeline:

```bash
cd ~/Downloads/stroke-font
python3 convert_to_stroke_font.py /Users/jacobphillips/Downloads/JakesHandwriting-Regular.ttf
```

Expected output:
```
SVG font: /Users/jacobphillips/Downloads/JakesHandwriting-Regular.svg
Preview:  /Users/jacobphillips/Downloads/JakesHandwriting-Regular.pdf
```

**Step 2: Open preview PDF for Jake to review**

```bash
open /Users/jacobphillips/Downloads/JakesHandwriting-Regular.pdf
```

**Step 3: Commit**

```bash
git add -A && git commit -m "feat: complete pipeline — first full font generation"
```

---

### Task 9: Install to Inkscape and Test

**Step 1: Copy SVG font to HTA directory**

```bash
cp /Users/jacobphillips/Downloads/JakesHandwriting-Regular.svg \
   ~/.config/inkscape/extensions/axidraw_deps/hta/svg_fonts/JakesHandwriting.svg
```

**Step 2: Test in Inkscape**

1. Open Inkscape
2. Extensions → AxiDraw Utilities → Hershey Text Advanced
3. Select "Jakes Handwriting" from the font dropdown
4. Type test text and render
5. Verify the paths are single-stroke (not outlines)

**Step 3: Final commit**

```bash
git add -A && git commit -m "feat: install stroke font to Inkscape HTA"
```

---

## Iteration Protocol

After Task 8, Jake reviews the PDF. For each character that needs fixing:

1. Jake describes the issue (e.g., "H crossbar goes wrong direction", "g has a spur at the bottom")
2. We adjust the relevant function (stroke ordering overrides, spur threshold, etc.)
3. Re-run the pipeline
4. Re-review PDF

Common fixes:
- **Wrong stroke direction**: Add override in `orient_stroke()` for specific character
- **Wrong stroke order**: Add character-specific sort in `order_strokes()`
- **Artifacts/spurs**: Increase `SPUR_THRESHOLD` or add per-character cleanup
- **Missing strokes**: Lower simplification tolerance
- **Too many segments**: Increase simplification tolerance
