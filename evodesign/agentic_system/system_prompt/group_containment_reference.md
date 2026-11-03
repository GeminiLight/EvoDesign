# Group & Containment Reference

Groups use matching `groupIds` on member elements. For diagram groups (lanes, layers, containers), use the **background rectangle + title pattern**:

## Group Background Pattern

```json
// 1. Background rectangle (rendered first, behind children)
{
  "type": "rectangle",
  "id": "group-bg",
  "x": 50, "y": 50, "width": 400, "height": 300,
  "strokeColor": "#868e96",
  "backgroundColor": "#f8f9fa",
  "fillStyle": "solid",
  "strokeStyle": "dashed",
  "strokeWidth": 1,
  "groupIds": ["my-group"],
  "boundElements": null
}

// 2. Title text (positioned at top of background)
{
  "type": "text",
  "id": "group-title",
  "x": 60, "y": 55,
  "text": "Group Name",
  "fontSize": 20,
  "fontFamily": 2,
  "groupIds": ["my-group"],
  "containerId": null
}

// 3. Child elements (inside the background, sharing groupIds)
{
  "type": "rectangle",
  "id": "child-1",
  "x": 70, "y": 100, "width": 120, "height": 60,
  "groupIds": ["my-group"]
}
```

## Nested Groups

For nested containment, use multiple groupIds (innermost first):
```json
"groupIds": ["inner-group", "outer-group"]
```

## Group Boundary Derivation Rule

Group background rectangles must be **derived from children**, not guessed:
1. Find the bounding box of all children
2. Add title clearance at top (~40-50px)
3. Add padding on all sides (~20-30px)
4. The background must contain ALL children
