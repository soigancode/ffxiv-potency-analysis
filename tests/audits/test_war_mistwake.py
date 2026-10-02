"""Audit supplied Warrior mistwake logs independently."""

import pytest

CASES = [
    ("dT8F9CYwQN2yr6L3/fight-2/source-14", ("Kakuruma Ad-stella", 4549, "7.5", "relic_7_55", 4)),
    ("M2mYJD8qG93w6TFp/fight-1/source-4", ("Hirona Larfie", 4549, "7.5", "relic_7_55", 4)),
    ("hWnAXRVZfg8tLCH4/fight-1/source-4", ("Kei Hiwatari", 4549, "7.5", "relic_7_55", 4)),
]


@pytest.mark.parametrize("prefix,expected", CASES)
def test_warrior_log(tmp_path, audit_war, prefix, expected):
    audit_war(tmp_path, "war_mistwake.zip", prefix, expected)
