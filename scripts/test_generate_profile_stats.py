"""Offline smoke test for the SVG generators."""

import importlib.util
from collections import Counter
from pathlib import Path

script = Path(__file__).resolve().parent / "generate_profile_stats.py"

spec = importlib.util.spec_from_file_location("profile_stats", script)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

sample_profile = {
    "login": "009MHz",
    "repositories": 20,
    "followers": 2,
    "stars": 1,
    "contributions": 251,
    "days": [
        {"date": "2026-08-13", "contributionCount": 7},
        {"date": "2026-08-14", "contributionCount": 3},
    ],
}

stats = module.generate_stats(sample_profile)
languages = module.generate_languages(
    Counter({"TypeScript": 700, "Python": 200, "HTML": 100})
)
streak = module.generate_streak(2, 7)

for name, svg in {
    "stats": stats,
    "languages": languages,
    "streak": streak,
}.items():
    assert svg.startswith("<svg ")
    assert svg.endswith("</svg>")
    assert "<script" not in svg.lower()
    assert "<foreignobject" not in svg.lower()
    print(f"{name}: OK")

current, longest = module.calculate_streak(sample_profile["days"])
assert current == 2
assert longest == 2

print("All offline checks passed.")
