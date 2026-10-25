"""GitHub-only CFG publisher. Issue data is parsed, never executed."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request

MARKER = "<!-- crimson-cfg:v1 -->"
MAX_CONFIG = 48000
SECTIONS = {"Aim", "ESP", "Chams", "Camera", "Viewmodel", "HitFeedback", "BulletTrails",
            "Cosmetics", "WorldEffects", "WorldPaint", "Radar", "VisualEffects", "NativeAim",
            "Trigger", "Colors", "Keys", "Misc", "Movement", "Crosshair"}
SECTIONS.update("Aim." + n for n in ("Pistol", "Rifle", "Sniper", "SMG", "Shotgun", "Heavy"))
DENIED = {"captureprotection", "inputreconstruction", "menu", "menuhold", "stop", "stophold"}
KEY = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")


def validate_config(text: str) -> str:
    if not isinstance(text, str) or not text or len(text.encode()) > MAX_CONFIG:
        raise ValueError("Config size is invalid")
    section = ""
    seen = set()
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith((";", "#")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            if section not in SECTIONS:
                raise ValueError("Unknown config section")
            lines.append("[" + section + "]")
            continue
        if not section or "=" not in line:
            raise ValueError("Invalid config entry")
        key, value = (s.strip() for s in line.split("=", 1))
        if not KEY.fullmatch(key) or key.lower() in DENIED:
            raise ValueError("Protected config field")
        if len(value) > 32 or not re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", value):
            raise ValueError("Only numeric settings are accepted")
        if not math.isfinite(float(value)) or abs(float(value)) > 1_000_000:
            raise ValueError("Config value is outside the accepted range")
        identity = (section.lower(), key.lower())
        if identity in seen:
            raise ValueError("Duplicate config entry")
        seen.add(identity)
        lines.append(key + "=" + value)
    if not seen or len(seen) > 1000:
        raise ValueError("Config must contain settings")
    return "\n".join(lines) + "\n"


def parse_submission(body: str) -> dict:
    if not isinstance(body, str) or len(body.encode()) > 64000 or not body.startswith(MARKER):
        raise ValueError("Not a CFG submission")
    rest = body[len(MARKER):].strip()
    if not rest.startswith("```json\n") or not rest.endswith("```"):
        raise ValueError("Invalid submission envelope")
    payload = json.loads(rest[8:-3])
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        raise ValueError("Unsupported config schema")
    name = payload.get("name", "")
    description = payload.get("description", "")
    if (not isinstance(name, str) or not 1 <= len(name.encode()) <= 80 or name != name.strip()
            or re.search(r'[\x00-\x1f\x7f<>:"/\\|?*]', name)):
        raise ValueError("Invalid config name")
    if not isinstance(description, str) or len(description.encode()) > 500 or any(ord(c) < 32 for c in description):
        raise ValueError("Invalid description")
    return {"name": name, "description": description, "config": validate_config(payload.get("config"))}


class GitHub:
    def __init__(self, repository: str, token: str):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Invalid repository")
        self.repository = repository
        self.token = token

    def call(self, method: str, path: str, data=None, binary=False, missing=False):
        url = path if path.startswith("https://uploads.github.com/") else "https://api.github.com" + path
        headers = {"Authorization": "Bearer " + self.token, "User-Agent": "Crimson-CFG-Publisher",
                   "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if binary:
            body = data
            headers["Content-Type"] = "application/octet-stream"
        else:
            body = None if data is None else json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, data=body, method=method, headers=headers)
                with urllib.request.urlopen(request, timeout=45) as response:
                    payload = response.read(4_000_001)
                    if len(payload) > 4_000_000:
                        raise ValueError("GitHub response too large")
                    return json.loads(payload) if payload else None
            except urllib.error.HTTPError as error:
                if error.code == 404 and missing:
                    return None
                if error.code >= 500 and attempt < 2 and method in ("GET", "PUT", "PATCH", "DELETE"):
                    time.sleep(attempt + 1)
                    continue
                raise RuntimeError("GitHub request failed: " + str(error.code)) from None

    def path(self, suffix):
        return "/repos/" + self.repository + suffix

    def catalog(self):
        document = self.call("GET", self.path("/contents/catalog.json"), missing=True)
        if not document:
            return {"schema": 1, "repository": self.repository, "updated_at": "", "profiles": []}
        catalog = json.loads(base64.b64decode(document["content"]))
        if catalog.get("schema") != 1 or not isinstance(catalog.get("profiles"), list):
            raise ValueError("Invalid existing catalog")
        return catalog

    def commit(self, files: dict[str, str], message: str):
        repo = self.call("GET", self.path(""))
        branch = repo["default_branch"]
        ref = self.call("GET", self.path("/git/ref/heads/" + urllib.parse.quote(branch, safe="")))
        parent = ref["object"]["sha"]
        base = self.call("GET", self.path("/git/commits/" + parent))["tree"]["sha"]
        entries = [{"path": path, "mode": "100644", "type": "blob", "content": content} for path, content in files.items()]
        tree = self.call("POST", self.path("/git/trees"), {"base_tree": base, "tree": entries})["sha"]
        commit = self.call("POST", self.path("/git/commits"), {"message": message, "tree": tree, "parents": [parent]})["sha"]
        # Never force-push over a maintainer's concurrent edit.
        self.call("PATCH", self.path("/git/refs/heads/" + urllib.parse.quote(branch, safe="")), {"sha": commit, "force": False})

    def release_asset(self, issue: int, content: bytes):
        tag = "cfg-" + str(issue)
        release = self.call("GET", self.path("/releases/tags/" + tag), missing=True)
        if release is None:
            release = self.call("POST", self.path("/releases"), {"tag_name": tag, "name": tag,
                "body": "Validated community configuration. See catalog.json for author and details.",
                "draft": False, "prerelease": False, "make_latest": "false"})
        assets = self.call("GET", self.path("/releases/" + str(release["id"]) + "/assets?per_page=100"))
        digest = hashlib.sha256(content).hexdigest()
        same = next((a for a in assets if a["name"] == digest + ".ini"), None)
        if same is None:
            if len(assets) >= 100:
                raise ValueError("Config revision limit reached")
            # Immutable revision assets retain GitHub download counters on updates.
            url = release["upload_url"].split("{", 1)[0] + "?name=" + digest + ".ini"
            same = self.call("POST", url, content, binary=True)
            assets.append(same)
        count = sum(int(a.get("download_count", 0)) for a in assets if a["name"].endswith(".ini"))
        return release["id"], same["id"], count, digest


def publish(github: GitHub, issue: dict, catalog: dict) -> bool:
    number = issue["number"]
    author = issue["user"]["login"]
    if not isinstance(number, int) or number <= 0 or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", author):
        raise ValueError("Invalid issue identity")
    records = catalog["profiles"]
    previous = next((p for p in records if p["issue"] == number), None)
    if previous and previous["author"].lower() != author.lower():
        raise ValueError("Config owner does not match issue author")
    if issue["state"] == "closed":
        if previous is None:
            return False
        records.remove(previous)
        catalog["updated_at"] = issue["updated_at"]
        github.commit({"catalog.json": json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"}, "Unlist CFG #" + str(number))
        return True
    payload = parse_submission(issue.get("body", ""))
    if previous is None and len(records) >= 1000:
        raise ValueError("Community catalog is full")
    if previous is None and sum(p["author"].lower() == author.lower() for p in records) >= 30:
        raise ValueError("Each author can publish up to 30 configs")
    # One issue is one stable config; edits are revisions by the same author.
    release, asset, downloads, digest = github.release_asset(number, payload["config"].encode())
    record = {"issue": number, "name": payload["name"], "description": payload["description"], "author": author,
              "created_at": issue["created_at"], "updated_at": issue["updated_at"], "sha256": digest,
              "bytes": len(payload["config"].encode()), "release_id": release, "asset_id": asset,
              "downloads": downloads, "revision": digest[:8]}
    if previous:
        records.remove(previous)
    records.append(record)
    records.sort(key=lambda p: p["issue"], reverse=True)
    catalog["updated_at"] = issue["updated_at"]
    folder = "configs/" + str(number) + "/"
    github.commit({folder + "config.ini": payload["config"], folder + "metadata.json": json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                   "catalog.json": json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"}, "Publish CFG #" + str(number))
    return True


def refresh_counts(github: GitHub, catalog: dict):
    totals = {}
    for page in range(1, 11):
        releases = github.call("GET", github.path("/releases?per_page=100&page=" + str(page)))
        for release in releases:
            totals[release["id"]] = sum(int(a.get("download_count", 0)) for a in release.get("assets", []) if a["name"].endswith(".ini"))
        if len(releases) < 100:
            break
    changed = False
    for record in catalog["profiles"]:
        if record["release_id"] in totals and record["downloads"] != totals[record["release_id"]]:
            record["downloads"] = totals[record["release_id"]]
            changed = True
    if changed:
        catalog["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        github.commit({"catalog.json": json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"}, "Refresh download statistics")


def reconcile(github: GitHub, catalog: dict):
    # GitHub concurrency keeps one pending run. Reconcile recent issue changes
    # on scheduled/manual runs so a burst of edits cannot lose a publication.
    for page in range(1, 11):
        issues = github.call("GET", github.path("/issues?state=all&sort=updated&direction=desc&per_page=100&page=" + str(page)))
        for issue in issues:
            if issue.get("pull_request"):
                continue
            previous = next((p for p in catalog["profiles"] if p["issue"] == issue["number"]), None)
            if not previous and (issue["state"] == "closed" or not (issue.get("body") or "").startswith(MARKER)):
                continue
            if previous and issue["state"] != "closed" and previous["updated_at"] == issue["updated_at"]:
                continue
            try:
                publish(github, issue, catalog)
            except (ValueError, json.JSONDecodeError):
                # Invalid public input is skipped without hourly comment spam.
                continue
        if len(issues) < 100:
            break


def main():
    github = GitHub(os.environ["CFG_REPOSITORY"], os.environ["GITHUB_TOKEN"])
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    catalog = github.catalog()
    if event_name == "issues":
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        supplied = event.get("issue", {})
        known = any(p["issue"] == supplied.get("number") for p in catalog["profiles"])
        if supplied.get("pull_request") or (not known and not (supplied.get("body") or "").startswith(MARKER)):
            return
        number = int(supplied["number"])
        # Fetch current issue after serialization; stale queued edit events cannot roll back a revision.
        issue = github.call("GET", github.path("/issues/" + str(number)))
        try:
            publish(github, issue, catalog)
        except (ValueError, json.JSONDecodeError) as error:
            github.call("POST", github.path("/issues/" + str(number) + "/comments"),
                        {"body": "CFG was not published: " + str(error) + ". Save and share again after correcting it."})
            raise SystemExit(1) from None
    else:
        reconcile(github, catalog)
        refresh_counts(github, catalog)


if __name__ == "__main__":
    main()
