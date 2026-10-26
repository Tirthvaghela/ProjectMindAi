"""Guard against hard-coded catalogue sizes in the user interface.

The catalogue grew from 500 to 868 projects and the landing page still said
"850+". Anything the UI says about how many projects exist must come from the
API (frontend/src/hooks/useCatalogueSize.js). Historical measurements may be
quoted only if they name the catalogue they were measured on.
"""

from __future__ import annotations

import re
from pathlib import Path

import config

FRONTEND_SRC = config.BASE_DIR.parent / "frontend" / "src"
SOURCES = [p for ext in ("*.jsx", "*.js") for p in FRONTEND_SRC.rglob(ext) if ".test." not in p.name]

# "868 projects", "850+ projects indexed", "500 project briefs" ...
COUNT_CLAIM = re.compile(r"\b\d[\d,]*\+?\s+(?:projects?|project briefs)\b", re.IGNORECASE)
# { value: '850+', label: 'Projects indexed' }
STAT_TILE = re.compile(r"value:\s*'\d[\d,]*\+?'\s*,\s*label:\s*'[^']*projects?[^']*'", re.IGNORECASE)


def test_the_frontend_sources_were_found():
    assert len(SOURCES) > 20


def test_no_ui_source_hard_codes_how_many_projects_exist():
    offenders = []
    for path in SOURCES:
        text = path.read_text(encoding="utf-8")
        for pattern in (COUNT_CLAIM, STAT_TILE):
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{path.relative_to(FRONTEND_SRC)}:{line}: {match.group(0)!r}")
    assert not offenders, "Hard-coded catalogue size in the UI (use useCatalogueSize): " + "; ".join(offenders)


def test_a_historical_metric_shown_in_the_ui_names_the_catalogue_it_was_measured_on():
    hero = (FRONTEND_SRC / "components" / "landing" / "LandingHero.jsx").read_text(encoding="utf-8")
    for match in re.finditer(r"0\.892[^\n]*", hero):
        assert "500" in match.group(0), match.group(0)
