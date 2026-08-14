"""Offline test suite for generate_profile_stats.py."""

from __future__ import annotations

import importlib.util
from collections import Counter
from datetime import date, timedelta
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent / "generate_profile_stats.py"

spec = importlib.util.spec_from_file_location("profile_stats", SCRIPT)
assert spec is not None
assert spec.loader is not None

module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_svg_generation() -> None:
    profile = {
        "login": "009MHz",
        "repositories": 6,
        "followers": 2,
        "stars": 0,
        "contributions": 275,
        "days": [
            {"date": "2026-08-11", "contributionCount": 1},
            {"date": "2026-08-12", "contributionCount": 2},
            {"date": "2026-08-13", "contributionCount": 3},
            {"date": "2026-08-14", "contributionCount": 4},
        ],
    }

    languages = Counter({
        "TypeScript": 800,
        "Python": 150,
        "Gherkin": 50,
    })

    svg = module.generate_activity_svg(profile, languages)

    assert svg.startswith("<svg ")
    assert svg.endswith("</svg>")
    assert 'aria-label="GitHub Activity for @009MHz"' in svg
    assert "GitHub Statistics" in svg
    assert "Top Languages" in svg
    assert "Contribution Streak" in svg
    assert "TypeScript" in svg
    assert "Python" in svg
    assert "<script" not in svg.lower()
    assert "<foreignobject" not in svg.lower()


def test_streak_calculation() -> None:
    today = date.today()

    days = [
        {
            "date": (today - timedelta(days=3)).isoformat(),
            "contributionCount": 1,
        },
        {
            "date": (today - timedelta(days=2)).isoformat(),
            "contributionCount": 2,
        },
        {
            "date": (today - timedelta(days=1)).isoformat(),
            "contributionCount": 3,
        },
        {
            "date": today.isoformat(),
            "contributionCount": 4,
        },
    ]

    current, longest = module.calculate_streak(days)

    assert current == 4
    assert longest == 4


def test_streak_with_gap() -> None:
    today = date.today()

    days = [
        {
            "date": (today - timedelta(days=4)).isoformat(),
            "contributionCount": 1,
        },
        {
            "date": (today - timedelta(days=3)).isoformat(),
            "contributionCount": 1,
        },
        {
            "date": (today - timedelta(days=1)).isoformat(),
            "contributionCount": 1,
        },
        {
            "date": today.isoformat(),
            "contributionCount": 1,
        },
    ]

    current, longest = module.calculate_streak(days)

    assert current == 2
    assert longest == 2


def test_empty_languages() -> None:
    profile = {
        "login": "009MHz",
        "repositories": 0,
        "followers": 0,
        "stars": 0,
        "contributions": 0,
        "days": [],
    }

    svg = module.generate_activity_svg(profile, Counter())

    assert "No language data available" in svg
    assert "0 days" in svg


if __name__ == "__main__":
    tests = [
        test_svg_generation,
        test_streak_calculation,
        test_streak_with_gap,
        test_empty_languages,
    ]

    for test in tests:
        test()
        print(f"{test.__name__}: OK")

    print("All offline tests passed.")
