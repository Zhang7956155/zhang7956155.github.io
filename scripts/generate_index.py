#!/usr/bin/env python3
"""Generate DSH plugin index.json from GitHub repositories of a fixed owner.

Designed to run inside GitHub Actions on the zhang7956155.github.io repository.
No third-party dependencies: only Python 3 standard library is used.

Rules for a repository to be included as a DSH plugin:
  - root contains client.js AND cordis.patch.yml AND package.json
  - package.json has a string "version" (fallback "0.0.0")

Display metadata for known plugins is kept in METADATA below so that curated
Chinese/English titles and descriptions are not lost on regeneration. Any new
fork that matches the plugin structure is picked up automatically with
reasonable defaults derived from its package.json.
"""

import base64
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

OWNER = "Zhang7956155"
API = "https://api.github.com"
OUTPUT = Path(__file__).resolve().parent.parent / "index.json"

INDEX_TITLE = {"en": "Zhang's DSH plugins", "zh": "Zhang 的 DSH 插件源"}
INDEX_DESC = {
    "en": "Plugins maintained in Zhang7956155's GitHub repositories.",
    "zh": "Zhang7956155 GitHub 仓库中维护的 DSH 插件。",
}

# Curated display metadata, keyed by repository name.
# "order" keeps the existing hand-picked ordering; new repos are appended by
# publish time. Everything not listed here is auto-derived.
METADATA = {
    "dsh-purge-community-1.6.86": {
        "order": 1,
        "name": "dsh-purge-community",
        "title": {"en": "dsh-purge Community", "zh": "dsh-purge 社区版"},
        "description": {
            "en": "Community-maintained DSH add-on: host compatibility, status diagnostics, prompt/rule management, verified updates and local backup/rollback.",
            "zh": "DSH 社区维护版：宿主兼容、状态诊断、提示词与规则管理、校验更新与本机备份回滚。",
        },
        "color": "#166534",
        "letter": "D",
    },
    "dsh-purge-1.1.96": {
        "order": 2,
        "name": "dsh-purge",
        "title": {"en": "dsh-purge 1.1.96", "zh": "dsh-purge 1.1.96"},
        "description": {
            "en": "Multi-model prompt/rule switching plugin for DeepSeek Harness (community fork).",
            "zh": "DeepSeek Harness 多模型提示词与规则切换插件（社区维护分支）。",
        },
        "color": "#1d4ed8",
        "letter": "D",
    },
    "dsh-purge-021rc5": {
        "order": 3,
        "name": "dsh-purge-safe",
        "title": {"en": "dsh-purge (021 rc5)", "zh": "dsh-purge（021 rc5）"},
        "description": {
            "en": "Community fork of dsh-purge with per-model prompt profiles.",
            "zh": "dsh-purge 社区分支，支持按模型切换提示词配置。",
        },
        "color": "#7c3aed",
        "letter": "D",
    },
    "dsh-preset-plus": {
        "order": 4,
        "name": "@rain-kl/dsh-preset-plus",
        "title": {"en": "DSH Preset Plus", "zh": "DSH 预设增强"},
        "description": {
            "en": "Editable preset editor for system/user/assistant entries, with one-click preset apply.",
            "zh": "可编辑的预设编辑器，支持系统/用户/助手条目与一键应用预设。",
        },
        "color": "#0891b2",
        "letter": "D",
    },
    "dsh-purge-1.1.71": {
        "order": 5,
        "name": "dsh-purge",
        "title": {"en": "dsh-purge 1.1.71 (mirror)", "zh": "dsh-purge 1.1.71（镜像）"},
        "description": {
            "en": "Source mirror of dsh-purge v1.1.71 for DeepSeek Harness.",
            "zh": "dsh-purge v1.1.71 源码镜像，适用于 DeepSeek Harness。",
        },
        "color": "#b45309",
        "letter": "D",
    },
    "dsh-market": {
        "order": 6,
        "name": "dshmarket",
        "title": {"en": "dsh-market", "zh": "DSH 插件市场"},
        "description": {
            "en": "The visual plugin market inside DeepSeek Harness: browse, search, install, update.",
            "zh": "DeepSeek Harness 可视化插件市场：浏览、搜索、安装与更新。",
        },
        "color": "#be123c",
        "letter": "D",
    },
}

AUTO_COLORS = ["#0f766e", "#4338ca", "#a16207", "#9d174d", "#1e3a8a", "#4d7c0f"]
# Core DSH plugin markers. A repo needs these to be auto-discovered.
REQUIRED_FILES = {"client.js", "cordis.patch.yml", "package.json"}
# Known-good repos are always included even if their layout differs slightly
# (e.g. dsh-market has no client.js but is a valid marketplace plugin).
KNOWN_REPOS = set(METADATA.keys())


def api_get(path, token):
    """GET a GitHub API path, returning parsed JSON. Raises on any HTTP error."""
    req = urllib.request.Request(
        API + path,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "dsh-index-generator",
            "Authorization": "Bearer " + token,
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def list_repos(token):
    """Return every repo owned by OWNER, following pagination."""
    repos = []
    page = 1
    while True:
        batch = api_get(
            f"/users/{OWNER}/repos?per_page=100&page={page}&type=owner&sort=full_name",
            token,
        )
        if not isinstance(batch, list):
            raise RuntimeError("Unexpected repo list response: " + repr(batch)[:200])
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
        if page > 10:
            break
    return repos


def discover_plugins(repos, token):
    """Filter repos down to those that look like DSH plugins, collecting facts."""
    found = []
    for repo in repos:
        name = repo["name"]
        try:
            contents = api_get(f"/repos/{OWNER}/{name}/contents/", token)
        except urllib.error.HTTPError as exc:
            # Empty repos return 409; just skip them.
            if exc.code in (404, 409):
                continue
            raise
        if not isinstance(contents, list):
            continue
        names = {item.get("name") for item in contents}
        # Known plugins are kept even without the full marker set; new repos
        # must look like a real DSH plugin (client.js + cordis.patch.yml + package.json).
        if name not in KNOWN_REPOS and not REQUIRED_FILES.issubset(names):
            continue

        try:
            pkg_file = api_get(f"/repos/{OWNER}/{name}/contents/package.json", token)
            pkg = json.loads(base64.b64decode(pkg_file["content"]).decode("utf-8"))
        except (KeyError, ValueError, urllib.error.HTTPError) as exc:
            print(f"  ! skip {name}: cannot read package.json ({exc})", file=sys.stderr)
            continue

        try:
            commits = api_get(f"/repos/{OWNER}/{name}/commits?per_page=1", token)
            commit = commits[0]
            sha = commit["sha"]
            date = commit["commit"]["committer"]["date"]
        except (IndexError, KeyError, urllib.error.HTTPError) as exc:
            print(f"  ! skip {name}: cannot read HEAD commit ({exc})", file=sys.stderr)
            continue

        found.append(
            {
                "repo": name,
                "pkg_name": pkg.get("name") or name,
                "version": pkg.get("version") or "0.0.0",
                "description": pkg.get("description") or "",
                "sha": sha,
                "date": date,
            }
        )
    return found


def make_icon(letter, color):
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        f'<rect width="64" height="64" rx="14" fill="{color}"/>'
        f'<text x="32" y="45" text-anchor="middle" fill="white" font-size="42" '
        f'font-family="sans-serif">{letter}</text></svg>'
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def to_timestamp(date_str):
    return int(dt.datetime.fromisoformat(date_str.replace("Z", "+00:00")).timestamp())


def render(plugins):
    """Turn collected facts into the final index document."""
    curated = []
    auto = []
    for item in plugins:
        meta = METADATA.get(item["repo"])
        if meta:
            curated.append((meta["order"], item, meta))
        else:
            auto.append(item)

    auto.sort(key=lambda x: to_timestamp(x["date"]), reverse=True)

    out_plugins = []
    all_sorted = curated + [(1000 + i, item, None) for i, item in enumerate(auto)]
    for _, item, meta in sorted(all_sorted, key=lambda t: t[0]):
        repo = item["repo"]
        if meta:
            name = meta["name"]
            title = meta["title"]
            description = meta["description"]
            color = meta["color"]
            letter = meta["letter"]
        else:
            name = item["pkg_name"]
            desc = (item["description"] or f"DSH plugin from {OWNER}/{repo}.").strip()
            title = {"en": name, "zh": name}
            description = {"en": desc, "zh": desc}
            idx = len(out_plugins) % len(AUTO_COLORS)
            color = AUTO_COLORS[idx]
            letter = name.lstrip("@").split("/")[-1][:1].upper() or "P"

        out_plugins.append(
            {
                "name": name,
                "title": title,
                "description": description,
                "author": OWNER,
                "homepage": f"https://github.com/{OWNER}/{repo}#readme",
                "repository": {"url": f"https://github.com/{OWNER}/{repo}"},
                "icon": make_icon(letter, color),
                "versions": [
                    {
                        "version": item["version"],
                        "publishTimestamp": to_timestamp(item["date"]),
                        "source": {
                            "type": "git",
                            "url": f"https://github.com/{OWNER}/{repo}",
                            "commit": item["sha"],
                        },
                    }
                ],
            }
        )

    return {
        "format": 1,
        "title": INDEX_TITLE,
        "description": INDEX_DESC,
        "plugins": out_plugins,
    }


def main():
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("ERROR: GITHUB_TOKEN is not set", file=sys.stderr)
        return 2

    print(f"Scanning repositories of {OWNER} ...")
    repos = list_repos(token)
    print(f"  found {len(repos)} repositories")
    plugins = discover_plugins(repos, token)
    print(f"  identified {len(plugins)} DSH plugins:")
    for item in plugins:
        print(f"    - {item['repo']:32s} v{item['version']:10s} {item['sha'][:12]}")

    # Safety valve: never overwrite a good index with an empty/partial result.
    if len(plugins) < 3:
        print(
            f"ERROR: only {len(plugins)} plugins found; refusing to overwrite index.json",
            file=sys.stderr,
        )
        return 3

    doc = render(plugins)
    text = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    json.loads(text)  # self-check before writing

    old = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
    if old == text:
        print("No changes to index.json")
        return 0

    OUTPUT.write_text(text, encoding="utf-8")
    print(f"Wrote {OUTPUT} ({len(doc['plugins'])} plugins, {len(text)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
