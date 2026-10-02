"""Audit supplied Warrior lindwurm ii logs independently."""

import pytest

CASES = [
    ("MLzCvT4VYRP7x6dQ/fight-13/source-30", ("Saaya Irie", 105, "7.5", "relic_7_55", 5)),
    ("DWhvNZr7awAFJVzm/fight-8/source-124", ("Pretty Scars", 105, "7.5", "relic_7_55", 5)),
    ("fB6tX3xAdbmnLWCh/fight-9/source-3", ("Ces Xidronia", 105, "7.5", "savage_7_4", 5)),
]


@pytest.mark.parametrize("prefix,expected", CASES)
def test_warrior_log(tmp_path, audit_war, prefix, expected):
    audit_war(tmp_path, "war_lindwurm_ii.zip", prefix, expected)
