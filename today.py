#!/usr/bin/env python3
"""Redraw the profile card (dark_mode.svg + light_mode.svg).

What it does:
  1. Reads the text fields from config.json and the portrait from ascii_*.txt
  2. Asks the GitHub API for live numbers (repos, stars, followers, commits)
  3. Writes both SVG files

Run by .github/workflows/update.yml every day. Run by hand with:
    python today.py              # needs GITHUB_TOKEN (or PROFILE_TOKEN) in the environment
    python today.py --offline    # no API call, reuse the numbers in cache/stats.json

No third-party packages are needed.
"""
import datetime
import json
import os
import sys
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
CACHE = ROOT / "cache" / "stats.json"
USER = CONFIG["username"]

# ---------------------------------------------------------------- layout
WIDTH, HEIGHT = 985, 530
ART_X, ART_FONT, ART_CELL_W, ART_LINE_H = 16, 5.6, 3.4, 6.8
INFO_X, INFO_FONT, INFO_CELL_W, INFO_LINE_H = 412, 15, 9.0, 19.4
INFO_COLS = 61                      # characters per info line
INFO_TOP = 30

THEMES = {
    "dark": {"bg": "#161b22", "text": "#c9d1d9", "key": "#60a5fa", "value": "#e6edf3",
             "dots": "#4b5563", "art": "#c9d1d9", "border": "#30363d"},
    "light": {"bg": "#f6f8fa", "text": "#24292f", "key": "#1d4ed8", "value": "#0f172a",
              "dots": "#b6bec9", "art": "#24292f", "border": "#d0d7de"},
}


# ---------------------------------------------------------------- GitHub data
def graphql(query, variables, token):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {token}", "User-Agent": f"{USER}-profile-card"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.load(resp)
    if body.get("errors"):
        raise RuntimeError(body["errors"])
    return body["data"]


def fetch_stats(token):
    """Each number is fetched on its own, so one failure does not lose the others."""
    stats = {}

    try:
        repos, stars, cursor = 0, 0, None
        while True:
            data = graphql(
                """query($login:String!,$cursor:String){ user(login:$login){
                     followers{totalCount} createdAt
                     repositories(first:100, after:$cursor, ownerAffiliations:OWNER, isFork:false){
                       totalCount pageInfo{hasNextPage endCursor} nodes{stargazerCount} } } }""",
                {"login": USER, "cursor": cursor}, token)["user"]
            page = data["repositories"]
            repos = page["totalCount"]
            stars += sum(n["stargazerCount"] for n in page["nodes"])
            stats["followers"] = data["followers"]["totalCount"]
            stats["created_at"] = data["createdAt"]
            if not page["pageInfo"]["hasNextPage"]:
                break
            cursor = page["pageInfo"]["endCursor"]
        stats["repos"], stats["stars"] = repos, stars
    except Exception as err:                                   # noqa: BLE001
        print(f"warning: repo/star lookup failed: {err}", file=sys.stderr)

    try:
        first_year = int(stats.get("created_at", "2015")[:4])
        this_year = datetime.date.today().year
        commits = 0
        for year in range(first_year, this_year + 1):
            data = graphql(
                """query($login:String!,$from:DateTime!,$to:DateTime!){ user(login:$login){
                     contributionsCollection(from:$from,to:$to){
                       totalCommitContributions restrictedContributionsCount } } }""",
                {"login": USER, "from": f"{year}-01-01T00:00:00Z", "to": f"{year}-12-31T23:59:59Z"},
                token)["user"]["contributionsCollection"]
            commits += data["totalCommitContributions"] + data["restrictedContributionsCount"]
        stats["commits"] = commits
    except Exception as err:                                   # noqa: BLE001
        print(f"warning: commit lookup failed: {err}", file=sys.stderr)

    return stats


def load_stats(offline):
    cached = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    token = os.environ.get("PROFILE_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if offline or not token:
        if not offline:
            print("warning: no token found, using cached numbers", file=sys.stderr)
        return cached
    cached.update(fetch_stats(token))          # a failed number keeps its old value
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cached, indent=2, sort_keys=True) + "\n")
    return cached


# ---------------------------------------------------------------- text lines
def num(value):
    return f"{value:,}" if isinstance(value, int) else "--"


def row(key, value, width=INFO_COLS):
    """'. Key: ......... value' padded with dots to an exact character width."""
    head = f". {key}:"
    dots = width - len(head) - len(value) - 2
    if dots < 1:
        raise ValueError(f"line too long by {1 - dots} characters: {key}: {value}")
    return [(". ", "dots"), (f"{key}:", "key"), (" " + "." * dots + " ", "dots"), (value, "value")]


def header(title, width=INFO_COLS):
    if title is None:
        return [(CONFIG["prompt"], "text"), (" " + "-" * (width - len(CONFIG["prompt"]) - 1), "dots")]
    return [("- ", "dots"), (title, "text"), (" " + "-" * (width - len(title) - 3), "dots")]


def stat_row(key_a, val_a, key_b, val_b, width=INFO_COLS):
    half = (width - 3) // 2
    left = row(key_a, val_a, half)
    right = row(key_b, val_b, width - half - 3 + 2)[1:]        # drop the leading ". "
    return left + [(" | ", "dots")] + right


def build_lines(stats):
    years = datetime.date.today().year - CONFIG["career_start_year"]
    lines = []
    for section in CONFIG["sections"]:
        if section["title"] is not None:
            lines.append(None)
        lines.append(header(section["title"]))
        for item in section["rows"]:
            lines.append(None if item is None else row(item[0], item[1].format(years=years)))
    lines.append(None)
    lines.append(header("GitHub Stats"))
    lines.append(stat_row("Repos", num(stats.get("repos")), "Stars", num(stats.get("stars"))))
    lines.append(stat_row("Commits", num(stats.get("commits")), "Followers", num(stats.get("followers"))))
    return lines


# ---------------------------------------------------------------- SVG
def render(theme_name, lines):
    c = THEMES[theme_name]
    art = (ROOT / f"ascii_{theme_name}.txt").read_text(encoding="utf-8").rstrip("\n").split("\n")
    cols = max(len(line) for line in art)
    art_top = (HEIGHT - len(art) * ART_LINE_H) / 2 + ART_FONT

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img" '
        f'aria-label="Farjad - AI Strategist, Startup Mentor, Builder. Profile card with GitHub stats.">',
        "<style>",
        "text { font-family: ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, "
        "'Liberation Mono', 'DejaVu Sans Mono', monospace; white-space: pre; }",
        f".art {{ font-size: {ART_FONT}px; fill: {c['art']}; }}",
        f".info {{ font-size: {INFO_FONT}px; fill: {c['text']}; }}",
        f".key {{ fill: {c['key']}; font-weight: 600; }} .value {{ fill: {c['value']}; }} "
        f".dots {{ fill: {c['dots']}; }} .text {{ fill: {c['text']}; font-weight: 600; }}",
        "</style>",
        f'<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{HEIGHT - 1}" rx="14" '
        f'fill="{c["bg"]}" stroke="{c["border"]}"/>',
    ]
    for i, line in enumerate(art):
        if not line.strip():
            continue
        out.append(
            f'<text class="art" xml:space="preserve" x="{ART_X}" y="{art_top + i * ART_LINE_H:.1f}" '
            f'textLength="{cols * ART_CELL_W:.1f}" lengthAdjust="spacingAndGlyphs">'
            f"{escape(line.ljust(cols))}</text>")
    for i, segments in enumerate(lines):
        if segments is None:
            continue
        chars = sum(len(text) for text, _ in segments)
        spans = "".join(f'<tspan class="{cls}">{escape(text)}</tspan>' for text, cls in segments)
        out.append(
            f'<text class="info" xml:space="preserve" x="{INFO_X}" y="{INFO_TOP + i * INFO_LINE_H:.1f}" '
            f'textLength="{chars * INFO_CELL_W:.1f}" lengthAdjust="spacingAndGlyphs">{spans}</text>')
    out.append("</svg>")
    (ROOT / f"{theme_name}_mode.svg").write_text("\n".join(out) + "\n", encoding="utf-8")


def main():
    stats = load_stats(offline="--offline" in sys.argv)
    lines = build_lines(stats)
    needed = INFO_TOP + len(lines) * INFO_LINE_H
    if needed > HEIGHT:
        raise SystemExit(f"too many lines for the card: need {needed:.0f}px, have {HEIGHT}px")
    for theme in THEMES:
        render(theme, lines)
    print(f"wrote dark_mode.svg and light_mode.svg ({len(lines)} lines) with stats: {stats}")


if __name__ == "__main__":
    main()
