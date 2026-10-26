"""Check generated node companions, without treating ordinary images as icons."""

import math

from evo_diagram.agentic_system.common.node_icons import ICON_KEY, icon_owner
from .finding import Finding


def check_node_icons(manifest: dict, canvas_library: str) -> list[Finding]:
    if canvas_library != "excalidraw":
        return []
    elements = manifest.get("elements") or []
    findings = []
    for icon in elements:
        if icon.get("type") != "image" or icon.get("isDeleted") or not (icon.get("customData") or {}).get(ICON_KEY):
            continue
        def report(category, message):
            findings.append(Finding(category=f"icon/{category}", severity="major", message=message, element_id=icon["id"]))
        host = icon_owner(icon, elements)
        if not host or host.get("isDeleted"):
            report("missing_host", "Generated icon has no active host node.")
            continue
        asset = (manifest.get("files") or {}).get(icon.get("fileId"))
        if not isinstance(asset, dict) or not str(asset.get("dataURL", "")).startswith("data:image/"):
            report("missing_asset", "Generated icon must have an embedded image asset for portable exports.")
        angle = float(host.get("angle", 0))
        def local_box(element):
            dx = element["x"]+element["width"]/2 - (host["x"]+host["width"]/2)
            dy = element["y"]+element["height"]/2 - (host["y"]+host["height"]/2)
            cx = host["width"]/2 + dx*math.cos(angle)+dy*math.sin(angle)
            cy = host["height"]/2 - dx*math.sin(angle)+dy*math.cos(angle)
            return cx-element["width"]/2, cy-element["height"]/2, element["width"], element["height"]
        x,y,w,h = local_box(icon)
        if x < -1 or y < -1 or x+w > host["width"]+1 or y+h > host["height"]+1:
            report("outside_host", "Generated icon extends outside its host node.")
        elif host.get("type") == "ellipse" and host["width"] > 0 and host["height"] > 0:
            if any(((cx-host["width"]/2)/(host["width"]/2))**2
                   + ((cy-host["height"]/2)/(host["height"]/2))**2 > 1.01
                   for cx in (x, x+w) for cy in (y, y+h)):
                report("outside_host", "Generated icon extends beyond its elliptical host boundary.")
        for text in elements:
            if text.get("type") != "text" or text.get("containerId") != host["id"] or text.get("isDeleted"):
                continue
            tx,ty,tw,th = local_box(text)
            if min(x+w,tx+tw)-max(x,tx)>1 and min(y+h,ty+th)-max(y,ty)>1:
                report("text_overlap", "Generated icon overlaps its node label; restore separate icon and text areas.")
    return findings
