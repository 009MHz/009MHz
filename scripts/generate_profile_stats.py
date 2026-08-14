#!/usr/bin/env python3
"""
Generate self-hosted GitHub profile statistics as SVG files.

No third-party Python packages are required.

Outputs:
  profile/stats.svg
  profile/top-languages.svg
  profile/streak.svg

The script intentionally writes files only after all API requests succeed.
That prevents a temporary GitHub API failure from replacing valid existing
statistics with incomplete data.
"""

from __future__ import annotations

import html
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_URL = "https://api.github.com"
GRAPHQL_URL = f"{API_URL}/graphql"
API_VERSION = "2026-03-10"

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "profile"

BG = "#0d1117"
CARD = "#161b22"
BORDER = "#30363d"
TEXT = "#f0f6fc"
MUTED = "#8b949e"
ACCENT = "#58a6ff"
GREEN = "#3fb950"
PURPLE = "#a371f7"
ORANGE = "#d29922"

WIDTH = 495
HEIGHT = 180


class GitHubAPIError(RuntimeError):
    """Raised when GitHub returns an unexpected API response."""


def github_request(
    url: str,
    *,
    token: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Make an authenticated GitHub API request and return decoded JSON."""
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
    """Execute a GitHub GraphQL query."""
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
    """Fetch profile metadata and a one-year contribution calendar."""
    today = date.today()
    start = today - timedelta(days=365)

    query = """
    query Profile($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        name
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

    contribution_days = [
        day
        for week in calendar["weeks"]
        for day in week["contributionDays"]
    ]

    return {
        "name": user.get("name") or username,
        "login": user["login"],
        "followers": user["followers"]["totalCount"],
        "repositories": user["repositories"]["totalCount"],
        "stars": user["starredRepositories"]["totalCount"],
        "contributions": calendar["totalContributions"],
        "days": contribution_days,
    }


def get_public_repositories(username: str, token: str) -> list[dict[str, Any]]:
    """Fetch all public, non-fork repositories owned by the profile."""
    repositories: list[dict[str, Any]] = []
    page = 1

    while True:
        url = (
            f"{API_URL}/users/{username}/repos"
            f"?per_page=100&page={page}&type=owner&sort=updated"
        )
        batch = github_request(url, token=token)

        if not isinstance(batch, list):
            raise GitHubAPIError("Unexpected repository API response.")

        repositories.extend(
            repo for repo in batch
            if not repo.get("fork", False) and not repo.get("archived", False)
        )

        if len(batch) < 100:
            break

        page += 1

    return repositories


def get_languages(
    username: str,
    repositories: list[dict[str, Any]],
    token: str,
) -> Counter[str]:
    """Aggregate language byte counts across public non-fork repositories."""
    totals: Counter[str] = Counter()

    for repository in repositories:
        full_name = repository.get("full_name")
        if not full_name:
            continue

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
    """
    Calculate current and longest contribution streaks.

    A current streak may include today. If today has no contribution,
    yesterday is used as the first day of the current streak.
    """
    counts = {
        datetime.strptime(day["date"], "%Y-%m-%d").date(): int(
            day["contributionCount"]
        )
        for day in days
    }

    if not counts:
        return 0, 0

    all_dates = sorted(counts)
    longest = 0
    run = 0
    previous: date | None = None

    for current in all_dates:
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

    if counts.get(today, 0) > 0:
        cursor = today
    else:
        cursor = today - timedelta(days=1)

    current = 0

    while counts.get(cursor, 0) > 0:
        current += 1
        cursor -= timedelta(days=1)

    return current, longest


def esc(value: Any) -> str:
    """Escape text for safe SVG/XML output."""
    return html.escape(str(value), quote=True)


def svg_open(width: int, height: int, label: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{esc(label)}">'
    )


def card_background(width: int, height: int) -> str:
    return (
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" '
        f'rx="12" fill="{BG}" stroke="{BORDER}"/>'
    )


def text(
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
        f'<text x="{x}" y="{y}" fill="{fill}" font-family="'
        f'-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif" '
        f'font-size="{size}px" font-weight="{weight}" text-anchor="{anchor}">'
        f'{esc(value)}</text>'
    )


def generate_stats(data: dict[str, Any]) -> str:
    width, height = WIDTH, HEIGHT
    values = [
        ("Contributions", data["contributions"], ACCENT),
        ("Repositories", data["repositories"], GREEN),
        ("Followers", data["followers"], PURPLE),
        ("Stars", data["stars"], ORANGE),
    ]

    parts = [
        svg_open(width, height, "GitHub profile statistics"),
        card_background(width, height),
        text(24, 32, "GitHub Statistics", size=16, weight=600),
        text(
            width - 24,
            32,
            f"@{data['login']}",
            size=12,
            fill=MUTED,
            anchor="end",
        ),
    ]

    positions = [(24, 65), (255, 65), (24, 125), (255, 125)]

    for (label, value, accent), (x, y) in zip(values, positions):
        parts.append(
            f'<circle cx="{x + 5}" cy="{y - 5}" r="4" fill="{accent}"/>'
        )
        parts.append(text(x + 17, y, label, size=12, fill=MUTED))
        parts.append(
            text(x, y + 30, f"{value:,}", size=23, weight=700)
        )

    parts.append("</svg>")
    return "".join(parts)


def generate_languages(languages: Counter[str]) -> str:
    width, height = WIDTH, HEIGHT
    total = sum(languages.values())

    # Keep the card readable. Everything beyond the top five is grouped.
    top = languages.most_common(5)

    if total <= 0:
        top = []
    elif len(languages) > 5:
        remaining = sum(value for _, value in languages.most_common()[5:])
        top.append(("Other", remaining))

    palette = [
        "#58a6ff",
        "#a371f7",
        "#3fb950",
        "#d29922",
        "#f778ba",
        "#8b949e",
    ]

    parts = [
        svg_open(width, height, "Top programming languages"),
        card_background(width, height),
        text(24, 32, "Top Languages", size=16, weight=600),
    ]

    if not top:
        parts.append(text(24, 75, "No language data available", fill=MUTED))
        parts.append("</svg>")
        return "".join(parts)

    bar_x, bar_y = 24, 53
    bar_width, bar_height = width - 48, 10
    cursor = bar_x

    for index, (_, value) in enumerate(top):
        segment_width = bar_width * value / total
        parts.append(
            f'<rect x="{cursor:.2f}" y="{bar_y}" '
            f'width="{max(segment_width, 1):.2f}" height="{bar_height}" '
            f'fill="{palette[index % len(palette)]}"/>'
        )
        cursor += segment_width

    for index, (language, value) in enumerate(top):
        x = 24 + (index % 2) * 230
        y = 92 + (index // 2) * 30
        percentage = value / total * 100
        color = palette[index % len(palette)]

        parts.append(
            f'<circle cx="{x + 5}" cy="{y - 4}" r="4" fill="{color}"/>'
        )
        parts.append(text(x + 17, y, language, size=12))
        parts.append(
            text(
                x + 200,
                y,
                f"{percentage:.1f}%",
                size=12,
                fill=MUTED,
                anchor="end",
            )
        )

    parts.append("</svg>")
    return "".join(parts)


def generate_streak(current: int, longest: int) -> str:
    width, height = WIDTH, HEIGHT

    parts = [
        svg_open(width, height, "GitHub contribution streak"),
        card_background(width, height),
        text(24, 32, "Contribution Streak", size=16, weight=600),
        text(width - 24, 32, "Self-hosted", size=12, fill=MUTED, anchor="end"),
        text(24, 82, "Current", size=12, fill=MUTED),
        text(24, 112, f"{current} days", size=24, weight=700),
        text(255, 82, "Longest", size=12, fill=MUTED),
        text(255, 112, f"{longest} days", size=24, weight=700),
        text(
            24,
            150,
            "Based on the GitHub contribution calendar",
            size=11,
            fill=MUTED,
        ),
        "</svg>",
    ]

    return "".join(parts)


def write_outputs(data: dict[str, Any], languages: Counter[str]) -> None:
    current, longest = calculate_streak(data["days"])

    generated = {
        OUTPUT_DIR / "stats.svg": generate_stats(data),
        OUTPUT_DIR / "top-languages.svg": generate_languages(languages),
        OUTPUT_DIR / "streak.svg": generate_streak(current, longest),
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for path, content in generated.items():
        path.write_text(content, encoding="utf-8")
        print(f"Generated {path.relative_to(ROOT)}")


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN")
    username = os.environ.get("GITHUB_USERNAME", "009MHz")

    if not token:
        print("GITHUB_TOKEN is required.", file=sys.stderr)
        return 1

    try:
        print(f"Fetching GitHub profile data for @{username}...")
        profile = get_profile_data(username, token)

        print("Fetching public repository list...")
        repositories = get_public_repositories(username, token)

        print(f"Aggregating languages from {len(repositories)} repositories...")
        languages = get_languages(username, repositories, token)

        # Only write after every request has succeeded.
        write_outputs(profile, languages)

        print("Profile statistics generated successfully.")
        return 0

    except GitHubAPIError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"UNEXPECTED ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
