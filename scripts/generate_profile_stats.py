#!/usr/bin/env python3
"""Generate a self-hosted GitHub activity dashboard as a single SVG.

The generator intentionally uses only profile-level data and public repositories
owned by the profile. It does not reference, enumerate, or analyze private or
company repositories.

Output:
    profile/activity.svg

Environment:
    GITHUB_TOKEN       Required GitHub Actions token.
    GITHUB_USERNAME    Defaults to 009MHz.
"""

from __future__ import annotations

import html
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_URL = "https://api.github.com"
GRAPHQL_URL = f"{API_URL}/graphql"
API_VERSION = "2026-03-10"

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "profile" / "activity.svg"

USERNAME = os.getenv("GITHUB_USERNAME", "009MHz")

# Publicly curated profile content. No repository names are needed here.
TECHNOLOGY_FOCUS = (
    ("Playwright", "#45BA4B"),
    ("TypeScript", "#3178C6"),
    ("Python", "#3776AB"),
    ("API Testing", "#FF6C37"),
    ("CI/CD", "#2088FF"),
    ("Selenium", "#43B02A"),
)

WIDTH = 1000
HEIGHT = 360

BG = "#0d1117"
CARD = "#161b22"
BORDER = "#30363d"
TEXT = "#f0f6fc"
MUTED = "#8b949e"
BLUE = "#58a6ff"
GREEN = "#3fb950"
PURPLE = "#a371f7"
ORANGE = "#d29922"


class GitHubAPIError(RuntimeError):
    """Raised for an unexpected GitHub API response."""


def github_request(
    url: str,
    *,
    token: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "009MHz-profile-statistics",
    }

    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url, headers=headers, method=method, data=body)

    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GitHubAPIError(
            f"GitHub API returned HTTP {exc.code}: {detail[:500]}"
        ) from exc
    except URLError as exc:
        raise GitHubAPIError(f"Unable to reach GitHub API: {exc.reason}") from exc

    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise GitHubAPIError("GitHub API returned invalid JSON.") from exc


def graphql(token: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    result = github_request(
        GRAPHQL_URL,
        token=token,
        method="POST",
        payload={"query": query, "variables": variables},
    )

    if result.get("errors"):
        messages = "; ".join(
            str(error.get("message", "Unknown GraphQL error"))
            for error in result["errors"]
        )
        raise GitHubAPIError(f"GitHub GraphQL error: {messages}")

    return result["data"]


def get_profile_data(username: str, token: str) -> dict[str, Any]:
    today = date.today()
    start = today - timedelta(days=365)

    query = """
    query Profile($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        login
        followers {
          totalCount
        }
        repositories(
          first: 100
          ownerAffiliations: OWNER
          privacy: PUBLIC
          isFork: false
        ) {
          totalCount
          nodes {
            stargazerCount
          }
        }
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                date
                contributionCount
              }
            }
          }
        }
      }
    }
    """

    data = graphql(
        token,
        query,
        {
            "login": username,
            "from": f"{start.isoformat()}T00:00:00Z",
            "to": f"{today.isoformat()}T23:59:59Z",
        },
    )

    user = data.get("user")
    if not user:
        raise GitHubAPIError(f"GitHub user '{username}' was not found.")

    calendar = user["contributionsCollection"]["contributionCalendar"]
    days = [
        day
        for week in calendar["weeks"]
        for day in week["contributionDays"]
    ]

    repositories = user["repositories"]
    stars_received = sum(
        int(node.get("stargazerCount", 0))
        for node in repositories.get("nodes", [])
    )

    return {
        "login": user["login"],
        "followers": user["followers"]["totalCount"],
        "repositories": repositories["totalCount"],
        "stars_received": stars_received,
        "contributions": calendar["totalContributions"],
        "days": days,
    }


def calculate_streak(days: list[dict[str, Any]]) -> tuple[int, int]:
    counts = {
        datetime.strptime(day["date"], "%Y-%m-%d").date(): int(
            day["contributionCount"]
        )
        for day in days
    }

    if not counts:
        return 0, 0

    longest = 0
    run = 0
    previous: date | None = None

    for current in sorted(counts):
        if counts[current] > 0:
            if previous is not None and current == previous + timedelta(days=1):
                run += 1
            else:
                run = 1
            longest = max(longest, run)
            previous = current
        else:
            run = 0
            previous = None

    today = date.today()
    cursor = today if counts.get(today, 0) > 0 else today - timedelta(days=1)

    current = 0
    while counts.get(cursor, 0) > 0:
        current += 1
        cursor -= timedelta(days=1)

    return current, longest


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def svg_text(
    x: float,
    y: float,
    value: str,
    *,
    size: int = 14,
    fill: str = TEXT,
    weight: int = 400,
    anchor: str = "start",
) -> str:
    return (
        f'<text x="{x}" y="{y}" fill="{fill}" '
        'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif" '
        f'font-size="{size}px" font-weight="{weight}" text-anchor="{anchor}">'
        f"{esc(value)}</text>"
    )


def rounded_card(x: float, y: float, width: float, height: float) -> str:
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" '
        f'rx="12" fill="{CARD}" stroke="{BORDER}"/>'
    )


def generate_activity_svg(profile: dict[str, Any]) -> str:
    current, longest = calculate_streak(profile["days"])

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'role="img" aria-label="GitHub activity statistics for @{esc(profile["login"])}">',
    ]

    # Profile statistics card
    stats_x = 0
    stats_y = 8
    card_h = 150
    gap = 18
    card_w = (WIDTH - gap) / 2
    right_x = card_w + gap

    parts.extend([
        rounded_card(stats_x, stats_y, card_w, card_h),
        rounded_card(right_x, stats_y, card_w, card_h),
        svg_text(24, stats_y + 32, "GitHub Statistics", size=15, weight=600),
        svg_text(right_x + 24, stats_y + 32, "Technology Focus", size=15, weight=600),
    ])

    stats = [
        ("Contributions", profile["contributions"], BLUE),
        ("Repositories", profile["repositories"], GREEN),
        ("Followers", profile["followers"], PURPLE),
        ("Stars received", profile["stars_received"], ORANGE),
    ]

    positions = [
        (24, stats_y + 70),
        (238, stats_y + 70),
        (24, stats_y + 128),
        (238, stats_y + 128),
    ]

    for (label, value, accent), (x, y) in zip(stats, positions):
        parts.append(f'<circle cx="{x + 4}" cy="{y - 5}" r="4" fill="{accent}"/>')
        parts.append(svg_text(x + 16, y, label, size=11, fill=MUTED))
        parts.append(svg_text(x, y + 27, f"{value:,}", size=21, weight=700))

    # Technology focus card.
    focus_x = right_x + 24
    focus_y = stats_y + 62
    columns = 2

    for index, (name, accent) in enumerate(TECHNOLOGY_FOCUS):
        column = index % columns
        row = index // columns
        x = focus_x + column * 225
        y = focus_y + row * 28

        parts.append(f'<circle cx="{x + 4}" cy="{y - 4}" r="4" fill="{accent}"/>')
        parts.append(svg_text(x + 16, y, name, size=11))

    # Contribution streak card.
    streak_y = 174
    streak_h = 150

    parts.extend([
        rounded_card(0, streak_y, WIDTH, streak_h),
        svg_text(24, streak_y + 32, "Contribution Streak", size=15, weight=600),
        svg_text(
            WIDTH - 24,
            streak_y + 32,
            "Based on the GitHub contribution calendar",
            size=11,
            fill=MUTED,
            anchor="end",
        ),
        svg_text(24, streak_y + 76, "Current", size=11, fill=MUTED),
        svg_text(24, streak_y + 110, f"{current} days", size=24, weight=700),
        svg_text(500, streak_y + 76, "Longest", size=11, fill=MUTED),
        svg_text(500, streak_y + 110, f"{longest} days", size=24, weight=700),
    ])

    parts.append("</svg>")
    return "".join(parts)


def write_output(svg: str) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(svg, encoding="utf-8")
    print(f"Generated {OUTPUT.relative_to(ROOT)}")


def main() -> int:
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN is required.", file=sys.stderr)
        return 1

    try:
        print(f"Fetching public profile data for @{USERNAME}...")
        profile = get_profile_data(USERNAME, token)

        svg = generate_activity_svg(profile)

        if not svg.startswith("<svg ") or not svg.endswith("</svg>"):
            raise RuntimeError("Generated SVG failed basic validation.")

        if "FEATURED_REPOSITORIES" in svg:
            raise RuntimeError("Generated SVG contains forbidden repository configuration.")

        write_output(svg)
        print("Profile activity dashboard generated successfully.")
        return 0

    except (GitHubAPIError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"UNEXPECTED ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
