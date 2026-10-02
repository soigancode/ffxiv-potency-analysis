"""Audit supplied Warrior clyteum logs independently."""

import pytest

CASES = [
    ("DHKQP4GRzFqw9ZLx/fight-1/source-2", ("Parth Unaax", 4551, "7.5", "savage_7_4", 4)),
    ("D2d91zkj6AaP7BhR/fight-1/source-13", ("The Rizzler", 4551, "7.5", "savage_7_4", 4)),
    ("VpDTCafgvzjhJKyB/fight-1/source-2", ("Fraig Rihll", 4551, "7.5", "savage_7_4", 3)),
]


@pytest.mark.parametrize("prefix,expected", CASES)
def test_warrior_log(tmp_path, audit_war, prefix, expected):
    audit_war(tmp_path, "war_clyteum.zip", prefix, expected)
