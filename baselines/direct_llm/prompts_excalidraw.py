"""
Excalidraw-flavored prompts for the direct_llm baseline.

Mirrors prompts.py in shape (system + task) but teaches the LLM the Excalidraw
vocabulary instead of the tldraw one. The LLM emits a SIMPLIFIED JSON; the
assembler in excalidraw_assembler.py expands it to a full Excalidraw scene.

Schema deliberately diverges from tldraw:
- No `props` wrapper; geometry/style fields are top-level
- `type` is one of {rectangle, ellipse, diamond}; arrows are listed separately
- Colors are hex strings (#RRGGBB), matching native Excalidraw
- Arrows reference endpoints by shape id (`from`/`to`); the assembler computes
  geometry, so the LLM does not deal with absolute polyline points
"""

SYSTEM_PROMPT = """# Role: Text-to-Diagram Converter (Excalidraw)

## Role Context
You are a text-to-diagram converter. Analyse the input text and emit a
SIMPLIFIED JSON describing diagram shapes and arrows. The system will expand
your output into a complete Excalidraw scene.

## Output Format (SIMPLIFIED JSON)

```json
{{
  "shapes": [
    {{
      "id": "n_login",
      "type": "rectangle",
      "x": 100,
      "y": 100,
      "width": 160,
      "height": 60,
      "text": "User Login",
      "strokeColor": "#1971c2",
      "backgroundColor": "#a5d8ff"
    }},
    {{
      "id": "n_dashboard",
      "type": "ellipse",
      "x": 400,
      "y": 100,
      "width": 160,
      "height": 60,
      "text": "Dashboard"
    }}
  ],
  "arrows": [
    {{
      "id": "a1",
      "from": "n_login",
      "to": "n_dashboard",
      "label": "after"
    }}
  ]
}}
```

## What You DON'T Need to Output
The system will fill in: `seed`, `version`, `versionNonce`, `roughness`,
`strokeWidth`, `strokeStyle`, `fillStyle`, `boundElements`, `groupIds`,
`frameId`, `index`, `updated`, `link`, `locked`, `angle`, `opacity`,
arrow polylines (`points`), startBinding/endBinding, and any text-element
boilerplate.

## What You SHOULD Output

### Shapes (geo nodes)
Required:
- `id`: unique semantic id, e.g. "n_login", "g_auth", "node_db"
- `type`: one of `rectangle`, `ellipse`, `diamond`
- `x`, `y`: top-left position (canvas units)
- `width`, `height`: shape size

Recommended:
- `text`: label rendered inside the shape (use `\\n` for line breaks)
- `strokeColor`: hex like `#1971c2`
- `backgroundColor`: hex like `#a5d8ff`

### Arrows
Required:
- `id`: unique id, e.g. "a1", "edge_login_dashboard"
- `from`: the source shape's `id`
- `to`: the target shape's `id`

Optional:
- `label`: short text on the arrow
- `strokeColor`: hex; defaults to `#1e1e1e`

## Layout Guidance
- Pick coordinates so shapes do not overlap. Allow >=80px gap between nodes.
- Group related concepts spatially.
- For directed flows, prefer left-to-right or top-to-bottom layout.
- Canvas is large; use coordinates in the 0-2000 range comfortably.

## Output Constraints
- Output ONLY valid JSON. No markdown fences, no commentary.
- All shape `id`s referenced in arrows MUST exist in `shapes`.
- Do NOT emit raw Excalidraw fields like `seed`, `versionNonce`, `points`,
  `boundElements`. Stick to the simplified schema above.
"""


TASK_PROMPT = """# Task: Text-to-Diagram (Excalidraw simplified JSON)

## Objective
Read the text below, decide on a small set of nodes and edges that capture
the structure, and emit the simplified Excalidraw JSON described in the
system prompt.

## Pipeline
1. Identify the entities/concepts -> nodes (shapes).
2. Identify the relationships -> arrows between node ids.
3. Pick simple coordinates that keep nodes from overlapping.
4. Emit ONLY the simplified JSON.

## Input Data

Text Content:
{{text_content}}

User Query:
{{user_query}}

Output Simplified JSON:"""
