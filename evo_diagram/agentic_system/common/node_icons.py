"""Portable node icons: trusted assets, explicit ownership and content geometry."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from typing import Any

ICON_SIZE = 26
ICON_PADDING = 16
ICON_GAP = 10
ICON_KEY = "evoDesignIcon"


@lru_cache(maxsize=1)
def bundled_icons() -> dict[str, str]:
    return json.loads((Path(__file__).parent / "assets/material_icons.json").read_text())


def icon_svg(name: str, color: str) -> str:
    """Tint only a trusted, packaged icon; never parse arbitrary remote SVG."""
    color = color if re.fullmatch(r"#[0-9a-fA-F]{6}", color or "") else "#475569"
    root = ET.fromstring(bundled_icons()[name])
    # Excalidraw's SVG importer requires an unprefixed <svg> root.
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    root.set("fill", color)
    for element in root.iter():
        for attr in ("fill", "stroke"):
            value = element.get(attr)
            if value and value not in {"none", "transparent"}:
                element.set(attr, color)
    return ET.tostring(root, encoding="unicode")


def icon_file(name: str, color: str) -> dict[str, Any]:
    svg = icon_svg(name, color)
    return {
        "id": hashlib.sha256(svg.encode()).hexdigest()[:20],
        "mimeType": "image/svg+xml",
        "dataURL": "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode(),
        "created": 1, "lastRetrieved": 1,
    }


def icon_owner(icon: dict, elements: list[dict], id_map: dict | None = None) -> dict | None:
    """Groups survive native duplication; IDs also support ungrouped/legacy scenes."""
    data = (icon.get("customData") or {}).get(ICON_KEY) or {}
    groups = icon.get("groupIds") or []
    hosts = [e for e in elements if e.get("type") in {"rectangle", "ellipse"} and not e.get("is_group")]
    # The innermost group is the node+label+icon group. Native duplication
    # rewrites group IDs but cannot rewrite arbitrary customData host IDs.
    if groups:
        matches = [e for e in hosts if groups[0] in (e.get("groupIds") or [])]
        if len(matches) == 1:
            return matches[0]
    host_id = data.get("hostId")
    if not host_id and id_map:
        key = next((k for k, v in id_map.items() if v == icon.get("id") and k.endswith(":icon")), None)
        host_id = id_map.get(key[:-5]) if key else None
    return next((e for e in hosts if e.get("id") == host_id), None)


def set_node_icon(manifest: dict, host_id: str, name: str) -> bool:
    """Add/replace a trusted icon on an existing node; preserve all source text."""
    elements = manifest.get("elements") or []
    host = next((e for e in elements if e.get("id") == host_id), None)
    if name not in bundled_icons():
        raise ValueError("Icon must be a bundled Material icon name.")
    if (not host or host.get("type") not in {"rectangle", "ellipse"}
            or host.get("isDeleted") or host.get("is_group") or host.get("locked")):
        raise ValueError("Icon host must be an unlocked visible rectangle or ellipse node.")
    texts = [e for e in elements if e.get("type") == "text" and e.get("containerId") == host_id and not e.get("isDeleted")]
    if not texts:
        raise ValueError("Icon host must retain a bound node label.")
    existing = next((e for e in elements if e.get("type") == "image" and not e.get("isDeleted")
                     and (e.get("customData") or {}).get(ICON_KEY)
                     and icon_owner(e, elements) is host), None)
    if existing:
        if existing["customData"][ICON_KEY].get("name") == name:
            return False
        existing["customData"][ICON_KEY]["name"] = name
    else:
        icon_id = hashlib.sha256(("refined-icon:" + host_id).encode()).hexdigest()[:20]
        if any(e.get("id") == icon_id for e in elements):
            raise ValueError("Icon ID already exists; refusing to overwrite an element.")
        group_id = "icon-group-" + icon_id
        groups = [group_id, *host.get("groupIds", [])]
        host["groupIds"] = groups
        for text in texts:
            text["groupIds"] = list(groups)
        elements.append({
            "id": icon_id, "type": "image", "x": host["x"], "y": host["y"],
            "width": ICON_SIZE, "height": ICON_SIZE, "angle": 0,
            "strokeColor": "transparent", "backgroundColor": "transparent",
            "fillStyle": "solid", "strokeWidth": 1, "strokeStyle": "solid",
            "roughness": 0, "opacity": 100, "groupIds": groups,
            "frameId": host.get("frameId"), "roundness": None,
            "index": max((e.get("index") or "a0" for e in elements), default="a0") + "V",
            "seed": 1, "version": 1, "versionNonce": 1, "updated": 1,
            "isDeleted": False, "boundElements": [], "link": None, "locked": False,
            "status": "saved", "scale": [1, 1], "crop": None,
            "customData": {ICON_KEY: {"hostId": host_id, "name": name}},
        })
    sync_node_icons(manifest, host_id)
    host["version"] = int(host.get("version", 1)) + 1
    return True


def sync_node_icons(manifest: dict, host_id: str | None = None) -> None:
    """Keep generated icons and labels attached after geometry/style edits.

    Imported ordinary images are deliberately untouched. Existing icon metadata
    or a canonical semantic companion ID is required; geometry is not ownership.
    """
    elements = manifest.get("elements") or []
    id_map = (manifest.get("_meta") or {}).get("id_map") or {}
    legacy_ids = {v for k, v in id_map.items() if k.endswith(":icon")}
    for icon in elements:
        if icon.get("type") != "image" or icon.get("isDeleted"):
            continue
        data = (icon.get("customData") or {}).get(ICON_KEY)
        if not data and icon.get("id") not in legacy_ids:
            continue
        host = icon_owner(icon, elements, id_map)
        if not host or (host_id and host.get("id") != host_id):
            continue
        before_icon = dict(icon)
        if host.get("isDeleted"):
            icon["isDeleted"] = True
        else:
            text = next((e for e in elements if e.get("type") == "text"
                         and e.get("containerId") == host["id"] and not e.get("isDeleted")), None)
            size = min(ICON_SIZE, max(12.0, float(host["height"]) - 16))
            # An ellipse's bounding box is not its usable content area. Fit
            # icon + label inside its central inscribed rectangle.
            inset_scale = math.sqrt(2) if host.get("type") == "ellipse" else 1
            if text:
                host["width"] = max(float(host["width"]), inset_scale*(2*ICON_PADDING+size+ICON_GAP+float(text["width"])))
                host["height"] = max(float(host["height"]), inset_scale*(float(text["height"])+16), inset_scale*(size+16))
            x, y = float(host["x"]), float(host["y"])
            w, h = float(host["width"]), float(host["height"])
            angle = float(host.get("angle", 0))
            def place(element, center_x, center_y, width, height):
                dx, dy = center_x - (x+w/2), center_y - (y+h/2)
                cx = x+w/2 + dx*math.cos(angle)-dy*math.sin(angle)
                cy = y+h/2 + dx*math.sin(angle)+dy*math.cos(angle)
                element.update(x=cx-width/2, y=cy-height/2, width=width, height=height, angle=angle)
            padding = ICON_PADDING + w*(1-1/inset_scale)/2
            place(icon, x+padding+size/2, y+h/2, size, size)
            if text:
                before_text = dict(text)
                left = x+padding+size+ICON_GAP
                right = x+w-padding
                place(text, (left+right)/2, y+h/2, float(text["width"]), float(text["height"]))
                if text != before_text:
                    text["version"] = int(text.get("version", 1)) + 1
            if data:
                icon["customData"] = {**icon.get("customData", {}), ICON_KEY: {**data, "hostId":host["id"]}}
                if data.get("name") in bundled_icons():
                    asset = icon_file(data["name"], host.get("strokeColor", "#475569"))
                    manifest.setdefault("files", {})[asset["id"]] = asset
                    icon["fileId"] = asset["id"]
        if icon != before_icon:
            icon["version"] = int(icon.get("version", 1)) + 1
