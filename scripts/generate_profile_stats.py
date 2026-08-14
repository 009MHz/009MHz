#!/usr/bin/env python3
"""
Generate a self-hosted GitHub activity dashboard as a single SVG.

Outputs:
    profile/activity.svg

Data sources:
    - GitHub GraphQL API for profile metadata and contribution calendar.
    - GitHub REST API for languages in selected featured repositories.

Environment variables:
    GITHUB_TOKEN              Required GitHub Actions token.
    GITHUB_USERNAME           Defaults to 009MHz.
    FEATURED_REPOSITORIES     Comma-separated repository names owned by the
                              profile. Defaults to sportstream,playwright-demo.

The generator writes the output only after all required API calls succeed.
"""

from __future__ import annotations

import html
import json
import os
import sys
from collections import Counter
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
FEATURED_REPOSITORIES = [
    repo.strip()
    for repo in os.getenv(
        "FEATURED_REPOSITORIES", "sportstream,playwright-demo"
    ).split(",")
    if repo.strip()
]

WIDTH = 1000
HEIGHT = 430

BG = "#0d1117"
CARD = "#161b22"
BORDER = "#30363d"
TEXT = "#f0f6fc"
MUTED = "#8b949e"
BLUE = "#58a6ff"
GREEN = "#3fb950"
PURPLE = "#a371f7"
ORANGE = "#d29922"
PINK = "#f778ba"
TRACK = "#21262d"


class GitHubAPIError(RuntimeError):
    """Raised when GitHub returns an unexpected API response."""


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
          first: 1
          ownerAffiliations: OWNER
          privacy: PUBLIC
        ) {
          totalCount
        }
        starredRepositories {
          totalCount
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

    return {
        "login": user["login"],
        "followers": user["followers"]["totalCount"],
        "repositories": user["repositories"]["totalCount"],
        "stars": user["starredRepositories"]["totalCount"],
        "contributions": calendar["totalContributions"],
        "days": days,
    }


def get_languages(
    username: str,
    repositories: list[str],
    token: str,
) -> Counter[str]:
    totals: Counter[str] = Counter()

    for repository in repositories:
        full_name = f"{username}/{repository}"
        url = f"{API_URL}/repos/{full_name}/languages"
        languages = github_request(url, token=token)

        if not isinstance(languages, dict):
            raise GitHubAPIError(
                f"Unexpected language response for {full_name}."
            )

        for language, byte_count in languages.items():
            if isinstance(byte_count, int):
                totals[language] += byte_count

    return totals


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
        f'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif" '
        f'font-size="{size}px" font-weight="{weight}" text-anchor="{anchor}">'
        f'{esc(value)}</text>'
    )


def rounded_card(x: float, y: float, width: float, height: float) -> str:
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" '
        f'rx="12" fill="{CARD}" stroke="{BORDER}"/>'
    )


def generate_activity_svg(
    profile: dict[str, Any],
    languages: Counter[str],
) -> str:
    current, longest = calculate_streak(profile["days"])

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'role="img" aria-label="GitHub Activity for @{esc(profile["login"])}">',
        f'<rect width="{WIDTH}" height="{HEIGHT}" rx="14" fill="{BG}" '
        f'stroke="{BORDER}"/>',
        svg_text(28, 38, "GitHub Activity", size=18, weight=600),
        svg_text(
            WIDTH - 28,
            38,
            f"@{profile['login']}",
            size=12,
            fill=MUTED,
            anchor="end",
        ),
    ]

    # Top cards
    card_y = 58
    card_h = 170
    gap = 18
    card_w = (WIDTH - 56 - gap) / 2
    left_x = 28
    right_x = left_x + card_w + gap

    parts.extend([
        rounded_card(left_x, card_y, card_w, card_h),
        rounded_card(right_x, card_y, card_w, card_h),
        svg_text(left_x + 22, card_y + 32, "GitHub Statistics", size=15, weight=600),
        svg_text(right_x + 22, card_y + 32, "Top Languages", size=15, weight=600),
    ])

    stats = [
        ("Contributions", profile["contributions"], BLUE),
        ("Repositories", profile["repositories"], GREEN),
        ("Followers", profile["followers"], PURPLE),
        ("Stars", profile["stars"], ORANGE),
    ]

    positions = [
        (left_x + 22, card_y + 70),
        (left_x + 235, card_y + 70),
        (left_x + 22, card_y + 135),
        (left_x + 235, card_y + 135),
    ]

    for (label, value, accent), (x, y) in zip(stats, positions):
        parts.append(f'<circle cx="{x + 4}" cy="{y - 5}" r="4" fill="{accent}"/>')
        parts.append(svg_text(x + 16, y, label, size=11, fill=MUTED))
        parts.append(svg_text(x, y + 29, f"{value:,}", size=22, weight=700))

    # Language distribution, selected repositories only.
    language_items = languages.most_common(5)
    total = sum(languages.values())

    if total:
        bar_x = right_x + 22
        bar_y = card_y + 52
        bar_w = card_w - 44
        bar_h = 10
        palette = [BLUE, PURPLE, GREEN, ORANGE, PINK]
        cursor = bar_x

        for index, (_, value) in enumerate(language_items):
            segment = bar_w * value / total
            parts.append(
                f'<rect x="{cursor:.2f}" y="{bar_y}" '
                f'width="{max(segment, 1):.2f}" height="{bar_h}" '
                f'fill="{palette[index % len(palette)]}"/>'
            )
            cursor += segment

        for index, (language, value) in enumerate(language_items):
            x = right_x + 22 + (index % 2) * 205
            y = card_y + 92 + (index // 2) * 32
            percentage = value / total * 100
            color = palette[index % len(palette)]

            parts.append(f'<circle cx="{x + 4}" cy="{y - 4}" r="4" fill="{color}"/>')
            parts.append(svg_text(x + 16, y, language, size=11))
            parts.append(
                svg_text(
                    x + 190,
                    y,
                    f"{percentage:.1f}%",
                    size=11,
                    fill=MUTED,
                    anchor="end",
                )
            )
    else:
        parts.append(
            svg_text(
                right_x + 22,
                card_y + 90,
                "No language data available",
                size=12,
                fill=MUTED,
            )
        )

    # Streak card
    streak_y = 246
    streak_h = 150

    parts.extend([
        rounded_card(28, streak_y, WIDTH - 56, streak_h),
        svg_text(50, streak_y + 32, "Contribution Streak", size=15, weight=600),
        svg_text(
            WIDTH - 50,
            streak_y + 32,
            "Based on the GitHub contribution calendar",
            size=11,
            fill=MUTED,
            anchor="end",
        ),
        svg_text(50, streak_y + 74, "Current", size=11, fill=MUTED),
        svg_text(50, streak_y + 108, f"{current} days", size=24, weight=700),
        svg_text(500, streak_y + 74, "Longest", size=11, fill=MUTED),
        svg_text(500, streak_y + 108, f"{longest} days", size=24, weight=700),
    ])

    if FEATURED_REPOSITORIES:
        featured = ", ".join(FEATURED_REPOSITORIES)
        parts.append(
            svg_text(
                50,
                streak_y + 132,
                f"Languages analyzed from: {featured}",
                size=10,
                fill=MUTED,
            )
        )

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
        print(f"Fetching profile data for @{USERNAME}...")
        profile = get_profile_data(USERNAME, token)

        print(
            "Analyzing languages from featured repositories: "
            + ", ".join(FEATURED_REPOSITORIES)
        )
        languages = get_languages(
            USERNAME,
            FEATURED_REPOSITORIES,
            token,
        )

        svg = generate_activity_svg(profile, languages)

        if not svg.startswith("<svg ") or not svg.endswith("</svg>"):
            raise RuntimeError("Generated SVG failed basic validation.")

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
