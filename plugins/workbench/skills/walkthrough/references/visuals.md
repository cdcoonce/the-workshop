# Visual Generation Guide

## Architecture

The walkthrough skill generates self-contained HTML files with rich interactive visuals, opened in the browser during the session. No sandbox restrictions — full CDN access.

## CDN Libraries

```html
<!-- Mermaid for standard diagrams -->
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>

<!-- D3 for custom interactive visuals -->
<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
```

## HTML Template

Every generated visual follows this structure:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>[Artifact Name] — Walkthrough</title>
  <style>
    /* Dark theme base */
    :root {
      --bg: #1a1a2e;
      --surface: #16213e;
      --text: #e0e0e0;
      --accent: #4fc3f7;
      --accent2: #81c784;
      --accent3: #ffb74d;
      --danger: #e57373;
      --muted: #888;
    }
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
      padding: 2rem;
      line-height: 1.6;
    }
    h1, h2, h3 { color: var(--accent); margin-bottom: 0.5rem; }
    .container { max-width: 1400px; margin: 0 auto; }
    .card {
      background: var(--surface);
      border-radius: 12px;
      padding: 1.5rem;
      margin-bottom: 1.5rem;
      border: 1px solid rgba(255,255,255,0.05);
    }
    .mermaid { text-align: center; margin: 1rem 0; }

    /* D3 container */
    svg { width: 100%; height: auto; }
    .node { cursor: pointer; }
    .node:hover { opacity: 0.8; }
    .link { stroke: var(--muted); stroke-opacity: 0.6; }

    /* Tooltip */
    .tooltip {
      position: absolute;
      background: var(--surface);
      border: 1px solid var(--accent);
      border-radius: 8px;
      padding: 0.75rem;
      font-size: 0.85rem;
      pointer-events: none;
      opacity: 0;
      transition: opacity 0.2s;
      max-width: 300px;
    }
  </style>
</head>
<body>
  <div class="container">
    <h1>[Title]</h1>
    <p class="subtitle" style="color: var(--muted); margin-bottom: 2rem;">[Subtitle/context]</p>

    <!-- Diagram content here -->

  </div>

  <!-- Scripts at bottom -->
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
  <script>
    mermaid.initialize({ theme: 'dark', startOnLoad: true });
    // D3 code here if needed
  </script>
</body>
</html>
```

## When to Use Mermaid vs D3

| Use Case | Tool | Why |
|----------|------|-----|
| ER diagrams | Mermaid | Native ER syntax, clear notation |
| Flowcharts | Mermaid | Simple, declarative, readable |
| Sequence diagrams | Mermaid | Built-in support for actors/messages |
| Class diagrams | Mermaid | Good for showing type relationships |
| Force-directed graphs | D3 | Interactive, handles large node counts |
| Treemaps | D3 | Size-encoded data (file sizes, change magnitude) |
| Timelines | D3 | Custom positioning and interaction |
| Annotated text overlays | Custom HTML/CSS | No library needed |
| Hierarchical navigation | D3 | Collapsible tree with zoom |

## Interactivity Patterns

### Hover Tooltips (D3)
Show detail on hover — node description, metrics, relationships.

### Click to Focus (D3)
Click a node to center it, dim unrelated nodes, show its connections highlighted.

### Zoom & Pan (D3)
For large diagrams, enable `d3.zoom()` on the SVG container.

### Collapsible Sections (HTML)
Use `<details>/<summary>` for secondary information that shouldn't crowd the main visual.

## Complexity Management

- **Max 15-20 nodes** per diagram. If the artifact has more components, group them into clusters and offer drill-down into each cluster.
- **Color meaningfully** — use color to encode a dimension (status, type, change magnitude), not decoration.
- **Label edges** — unlabeled arrows are ambiguous. Every connection should say what it represents.
- **Legend** — if using more than 3 colors or shapes, include a legend.

## File Management

- Write HTML to `/tmp/walkthrough-*.html` (ephemeral, session-only).
- Open with the browser tool.
- When the visual needs updating (drill-down), generate a new HTML file rather than mutating the existing one.
