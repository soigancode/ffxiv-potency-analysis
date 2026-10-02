"""Audit supplied Warrior lindwurm logs independently."""

import pytest

CASES = [
    ("FycHTxK9W4a6RGwQ/fight-5/source-2", ("Larxy B'lovely", 104, "7.5", "savage_7_4", 5)),
    ("cA1MFwJpLKaBWDgP/fight-2/source-6", ("Viaan Nightsong", 104, "7.5", "savage_7_4", 5)),
    ("6kvVK2mbhxqdjXa1/fight-3/source-11", ("Algo Meshalgo", 104, "7.5", "savage_7_4", 5)),
]


@pytest.mark.parametrize("prefix,expected", CASES)
def test_warrior_log(tmp_path, audit_war, prefix, expected):
    audit_war(tmp_path, "war_lindwurm.zip", prefix, expected)
