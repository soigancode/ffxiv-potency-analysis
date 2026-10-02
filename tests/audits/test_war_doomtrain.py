"""Audit supplied Warrior doomtrain logs independently."""

import pytest

CASES = [
    ("cJGNQTHpDfKky6vL/fight-16/source-14", ("Phosy Yu", 1083, "7.5", "savage_7_4", 5)),
    ("CdYQVbxTn9DjgtZF/fight-13/source-264", ("Ahri Kagerou", 1083, "7.5", "savage_7_4", 5)),
    ("GRVC1r2Haw8cZKNz/fight-11/source-5", ("Cyclist Dude", 1083, "7.5", "relic_7_55", 5)),
]


@pytest.mark.parametrize("prefix,expected", CASES)
def test_warrior_log(tmp_path, audit_war, prefix, expected):
    audit_war(tmp_path, "war_doomtrain.zip", prefix, expected)
