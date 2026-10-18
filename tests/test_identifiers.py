"""Checks on the identifier rules that Dataform must reproduce.

tests/data/identifier_cases.json lists awkward organisation names with
the key and employer_id each must get. The same file can test the
Dataform model (docs/identifiers.md).
"""

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from hww_dashboard import wrangle

CASES = Path(__file__).resolve().parent / "data" / "identifier_cases.json"


def cases() -> list[dict[str, Any]]:
    """Read the awkward names.

    Returns:
        One dict per name: raw, why, cleaned, key and employer_id.
    """
    entries: list[dict[str, Any]] = json.loads(CASES.read_text("utf-8"))
    return entries


class TestNameKey:
    """``name_key``: the form names are compared and hashed in."""

    @pytest.mark.parametrize("case", cases(), ids=lambda c: c["why"])
    def test_awkward_names(self, case: dict[str, Any]) -> None:
        """Each name gets its listed key, cleaned text and id.

        Args:
            case: One entry of identifier_cases.json.
        """
        cleaned = wrangle.clean_text(case["raw"])
        assert cleaned == case["cleaned"]
        assert wrangle.name_key(cleaned) == case["key"]
        assert wrangle.employer_id_for(cleaned) == case["employer_id"]

    def test_the_rule_is_stable_under_repeats(self) -> None:
        """A key is its own key, so applying the rule twice changes nothing."""
        for case in cases():
            assert wrangle.name_key(case["key"]) == case["key"]


class TestBuildDimEmployer:
    """``build_dim_employer``: one employer per key."""

    def test_look_alike_spellings_merge(self) -> None:
        """Spellings that differ only invisibly are one organisation."""
        names = ["Org 11", "ORG 11", "Org 11", "Org 12"]
        rows = pd.DataFrame(
            {
                "org": names,
                "sector": ["Public"] * 4,
                "industry": ["Unknown"] * 4,
                "size_band": ["Unknown"] * 4,
                "sites_band": ["Unknown"] * 4,
                "source": ["signups"] * 4,
                "position": range(4),
            }
        )
        dim = wrangle.build_dim_employer(
            rows, list(wrangle.SOURCES), wrangle.Report()
        )
        assert sorted(dim["employer_id"]) == sorted(
            {wrangle.employer_id_for(n) for n in names}
        )
        assert len(dim) == 2

    def test_a_collision_asks_for_a_longer_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two names with one id stop the run, and say what to do.

        Args:
            monkeypatch: Gives every name the same id.
        """
        rows = pd.DataFrame(
            {
                "org": ["Org 1", "Org 2"],
                "sector": ["Public"] * 2,
                "industry": ["Unknown"] * 2,
                "size_band": ["Unknown"] * 2,
                "sites_band": ["Unknown"] * 2,
                "source": ["signups"] * 2,
                "position": range(2),
            }
        )
        monkeypatch.setattr(wrangle, "employer_id_for", lambda name: "E1")
        with pytest.raises(wrangle.InputError, match="lengthen the id"):
            wrangle.build_dim_employer(
                rows, list(wrangle.SOURCES), wrangle.Report()
            )


class TestLoadMappings:
    """``load_mappings``: overrides are keyed the same way as names."""

    def test_override_matches_a_look_alike_name(
        self, project_folder: Path, tmp_path: Path
    ) -> None:
        """An override written with plain spaces catches a pasted name.

        Args:
            project_folder: Holds the live mappings, copied.
            tmp_path: Holds the copy.
        """
        maps = tmp_path / "maps"
        maps.mkdir()
        for path in (project_folder / "mappings").glob("*.csv"):
            (maps / path.name).write_bytes(path.read_bytes())
        (maps / "org_overrides.csv").write_text(
            "raw_name,canonical_name\nOrg Eleven,Org 11\n", "utf-8"
        )
        _lookups, overrides = wrangle.load_mappings(maps)
        assert wrangle.org_name("ORG ELEVEN", overrides) == "Org 11"

    def test_look_alike_raw_names_must_agree(
        self, project_folder: Path, tmp_path: Path
    ) -> None:
        """Two raw names with one key can't point different ways.

        Args:
            project_folder: Holds the live mappings, copied.
            tmp_path: Holds the copy.
        """
        maps = tmp_path / "maps"
        maps.mkdir()
        for path in (project_folder / "mappings").glob("*.csv"):
            (maps / path.name).write_bytes(path.read_bytes())
        (maps / "org_overrides.csv").write_text(
            "raw_name,canonical_name\nOrg A,Org 1\nOrg A,Org 2\n",
            "utf-8",
        )
        with pytest.raises(wrangle.InputError, match="one target"):
            wrangle.load_mappings(maps)
