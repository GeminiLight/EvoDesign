#!/usr/bin/env python3
"""Portable, account-free design rule export and additive import via the DNA API."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from uuid import uuid4

FORMAT = "evodesign.design-memory"
CABINS = ("structure", "style", "layout")
FIELDS = {"cabin_id", "title", "preview", "source", "enabled", "pinned"}
MAX_BYTES = 256 * 1024


def validate(document):
    if not isinstance(document, dict) or document.get("format") != FORMAT or document.get("version") != 1:
        raise ValueError("Expected an EvoDesign design-memory document, version 1.")
    rules = document.get("rules")
    if not isinstance(rules, list) or len(rules) > 500:
        raise ValueError("rules must be a list with at most 500 entries.")
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != FIELDS:
            raise ValueError("Rules must contain only the six portable design fields.")
        if rule["cabin_id"] not in CABINS or rule["source"] not in ("manual", "ai"):
            raise ValueError("Unknown rule category or source.")
        for field, limit in [("title", 255), ("preview", 10000)]:
            if not isinstance(rule[field], str) or not rule[field].strip() or len(rule[field]) > limit:
                raise ValueError(f"Invalid rule {field}.")
        if type(rule["enabled"]) is not bool or type(rule["pinned"]) is not bool:
            raise ValueError("enabled and pinned must be booleans.")
    return rules


def export_rules(payload):
    document = {"format": FORMAT, "version": 1, "rules": [
        {key: rule[key] for key in sorted(FIELDS)}
        for cabin in CABINS for rule in payload[cabin]
    ]}
    validate(document)
    return document


def merge_rules(payload, rules):
    result = {cabin: list(payload[cabin]) for cabin in CABINS}
    result["project_id"] = payload.get("project_id")
    signature = lambda rule: (rule["cabin_id"], rule["title"].strip(), rule["preview"].strip())
    seen = {signature(rule) for cabin in CABINS for rule in result[cabin]}
    added = 0
    for rule in rules:
        if signature(rule) in seen:
            continue
        seen.add(signature(rule))
        result[rule["cabin_id"]].append({**rule, "rule_id": str(uuid4()), "usage_count": 0, "updated_at": datetime.now(timezone.utc).isoformat()})
        added += 1
    return result, added


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward a bearer token to a redirected host.
        return None


def api_request(base, token, project_id=None, payload=None):
    parsed = urlsplit(base)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Use a base API URL without credentials, a query, or a fragment.")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")):
        raise ValueError("Remote API connections require HTTPS.")
    url = base.rstrip("/") + "/api/v1/dna/rules"
    if project_id:
        url += "?" + urlencode({"project_id": project_id})
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(url, data=data, method="PUT" if data is not None else "GET", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with build_opener(NoRedirect).open(request, timeout=30) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("import", "export", "validate"))
    parser.add_argument("file", type=Path)
    parser.add_argument("--api", default="http://127.0.0.1:3010")
    parser.add_argument("--project-id", help="Optional project scope; otherwise your global library.")
    args = parser.parse_args()
    rules = None
    if args.action in ("import", "validate"):
        if args.file.stat().st_size > MAX_BYTES:
            raise ValueError("Design-memory file exceeds 256 KiB.")
        rules = validate(json.loads(args.file.read_text()))
        if args.action == "validate":
            print(f"Valid portable design memory: {len(rules)} rules.")
            return
    token = os.environ.get("EVO_API_TOKEN", "").strip()
    if not token:
        raise ValueError("Set EVO_API_TOKEN to your signed-in account token; guest browser rules stay in browser storage.")
    existing = api_request(args.api, token, args.project_id)
    if args.action == "export":
        document = export_rules(existing)
        # Exclusive creation avoids overwriting someone's existing backup.
        with args.file.open("x") as stream:
            args.file.chmod(0o600)
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        print(f"Exported {len(document['rules'])} rules without account identifiers.")
    else:
        merged, added = merge_rules(existing, rules)
        if added:
            api_request(args.api, token, args.project_id, merged)
        print(f"Imported {added} new rules; existing rules preserved. Avoid editing the same scope while importing.")


if __name__ == "__main__":
    try:
        main()
    except HTTPError as exc:
        print(f"API returned HTTP {exc.code}; check your account token and project access.", file=sys.stderr)
        sys.exit(1)
    except (ValueError, OSError, URLError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
