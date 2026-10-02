"""Audit supplied Warrior red hot deep blue logs independently."""

import pytest

CASES = [
    ("Ak6wKm1LjcQ42NMP/fight-1/source-11", ("Chad Bradly", 102, "7.5", "savage_7_4", 5)),
    ("WtZvhTL61df7pmyB/fight-1/source-29", ("Mio Ando", 102, "7.5", "relic_7_55", 5)),
    ("129PXtxYGdmRcQgb/fight-2/source-13", ("Slade Skywalker", 102, "7.5", "savage_7_4", 5)),
]


@pytest.mark.parametrize("prefix,expected", CASES)
def test_warrior_log(tmp_path, audit_war, prefix, expected):
    audit_war(tmp_path, "war_red_hot_deep_blue.zip", prefix, expected)
