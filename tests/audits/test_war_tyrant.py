"""Audit supplied Warrior tyrant logs independently."""

import pytest

CASES = [
    ("86mAWxHcpRBJTKwh/fight-2/source-7", ("Poto Gota", 103, "7.4", "savage_7_4", 5)),
    ("NcbVJykXvjzQKM2n/fight-10/source-6", ("Slade Skywalker", 103, "7.4", "savage_7_4", 5)),
    ("BH8PkdhDqFf17jNg/fight-27/source-26", ("Chad Bradly", 103, "7.4", "savage_7_4", 5)),
]


@pytest.mark.parametrize("prefix,expected", CASES)
def test_warrior_log(tmp_path, audit_war, prefix, expected):
    audit_war(tmp_path, "war_tyrant.zip", prefix, expected)
