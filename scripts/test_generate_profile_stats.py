"""Offline tests for the self-hosted GitHub profile dashboard."""

from __future__ import annotations

import importlib.util
from datetime import date, timedelta
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent / "generate_profile_stats.py"

spec = importlib.util.spec_from_file_location("profile_stats", SCRIPT)
assert spec is not None and spec.loader is not None

module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def sample_profile() -> dict:
    today = date.today()
    return {
        "login": "009MHz",
        "repositories": 6,
        "followers": 2,
        "stars_received": 3,
        "contributions": 275,
        "days": [
            {"date": (today - timedelta(days=2)).isoformat(), "contributionCount": 1},
            {"date": (today - timedelta(days=1)).isoformat(), "contributionCount": 2},
            {"date": today.isoformat(), "contributionCount": 3},
        ],
    }


def test_svg_has_no_outer_title() -> None:
    svg = module.generate_activity_svg(sample_profile())

    assert svg.startswith("<svg ")
    assert svg.endswith("</svg>")
    assert "GitHub Statistics" in svg
    assert "Technology Focus" in svg
    assert "Contribution Streak" in svg

    # The README owns the section title; the SVG must not duplicate it.
    assert '">GitHub Activity</text>' not in svg
    assert "GitHub Activity</text>" not in svg

    # No repository-specific configuration belongs in the SVG.
    assert "FEATURED_REPOSITORIES" not in svg
    assert "Languages analyzed from" not in svg


def test_svg_has_no_outer_border_rect() -> None:
    svg = module.generate_activity_svg(sample_profile())

    # The first drawable element after <svg> should be a card, not a full-size
    # 1000x360 background container.
    assert '<rect width="1000" height="360"' not in svg


def test_statistics_are_present() -> None:
    svg = module.generate_activity_svg(sample_profile())

    assert ">275</text>" in svg
    assert ">6</text>" in svg
    assert ">2</text>" in svg
    assert ">3</text>" in svg
    assert "Stars received" in svg


def test_streak_calculation() -> None:
    today = date.today()
    days = [
        {"date": (today - timedelta(days=3)).isoformat(), "contributionCount": 1},
        {"date": (today - timedelta(days=2)).isoformat(), "contributionCount": 2},
        {"date": (today - timedelta(days=1)).isoformat(), "contributionCount": 3},
        {"date": today.isoformat(), "contributionCount": 4},
    ]

    current, longest = module.calculate_streak(days)

    assert current == 4
    assert longest == 4


def test_streak_with_gap() -> None:
    today = date.today()
    days = [
        {"date": (today - timedelta(days=4)).isoformat(), "contributionCount": 1},
        {"date": (today - timedelta(days=3)).isoformat(), "contributionCount": 1},
        {"date": (today - timedelta(days=1)).isoformat(), "contributionCount": 1},
        {"date": today.isoformat(), "contributionCount": 1},
    ]

    current, longest = module.calculate_streak(days)

    assert current == 2
    assert longest == 2


if __name__ == "__main__":
    tests = [
        test_svg_has_no_outer_title,
        test_svg_has_no_outer_border_rect,
        test_statistics_are_present,
        test_streak_calculation,
        test_streak_with_gap,
    ]

    for test in tests:
        test()
        print(f"{test.__name__}: OK")

    print("All tests passed.")
