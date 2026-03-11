# Jake's Handwriting Stroke Font — Design

**Date**: 2026-03-11
**Purpose**: Convert JakesHandwriting-Regular.ttf (closed outline font) into a single-stroke SVG font compatible with AxiDraw's Hershey Text Advanced extension.

## Problem

TTF fonts store characters as closed outline shapes (filled bezier contours). The AxiDraw pen plotter needs single open strokes — the path a pen actually takes to write each character. Drawing outlines makes letters look traced rather than handwritten.

## Source

- **Font**: `~/Downloads/JakesHandwriting-Regular.ttf`
- **Glyphs**: 81 (A-Z, a-z, 0-9, common punctuation)

## Target

- **Format**: SVG font compatible with HTA (`~/.config/inkscape/extensions/axidraw_deps/hta/svg_fonts/`)
- **Coordinate system**: units-per-em=1000, paths using M/L commands (moveto/lineto)
- **Reference**: Existing EMS fonts in `hta/svg_fonts/` directory

## Pipeline

```
JakesHandwriting-Regular.ttf
    → fontTools: extract glyph outlines as bezier paths
    → Pillow: rasterize each glyph at high resolution (~500px tall)
    → scikit-image: morphological skeletonization (Zhang-Suen thinning → 1px skeleton)
    → Vectorize: trace skeleton pixels back into vector path segments
    → Stroke ordering: apply standard English letter construction rules
    → Scale: convert to HTA coordinate system (units-per-em=1000)
    → Export: SVG font file + PDF preview
```

## Stroke Ordering Rules

Standard English print letter construction:
- Top to bottom, left to right
- Vertical strokes before horizontal crossbars
- Main body before details (dots on i/j, cross on t/f)
- Continuous strokes where the pen naturally stays down
- Well-documented standard order for all 26 uppercase + 26 lowercase characters

## Output Files

1. **`JakesHandwriting.svg`** — HTA-compatible SVG font, installs to `hta/svg_fonts/`
2. **`stroke_preview.pdf`** — Visual review document with pages for each character group (A-M, N-Z, a-m, n-z, digits, punctuation), showing numbered/colored strokes with direction arrows

## Dependencies

Python packages (all pip-installable):
- `fontTools` — TTF parsing
- `Pillow` — glyph rasterization
- `scikit-image` — skeletonization
- `numpy` — array ops
- `svgwrite` — SVG font generation
- `reportlab` — PDF preview generation

## Iteration Workflow

1. Generate font + preview PDF
2. Jake reviews PDF, identifies issues per character
3. Fix and regenerate
4. Repeat until all 81 glyphs are correct
5. Copy final SVG to Inkscape extensions directory
