"""Audit supplied Warrior vamp fatale logs independently."""

import pytest

CASES = [
    ("gLVqJyb1pNw79ZMn/fight-44/source-22", ("Chad Bradly", 101, "7.4", "savage_7_4", 5)),
    ("KWxL9RdgNYjavQXT/fight-6/source-3", ("Poto Gota", 101, "7.4", "savage_7_4", 5)),
    ("w7BdyfL9hRmYW8Hb/fight-22/source-4", ("Slade Skywalker", 101, "7.4", "savage_7_4", 5)),
]


@pytest.mark.parametrize("prefix,expected", CASES)
def test_warrior_log(tmp_path, audit_war, prefix, expected):
    audit_war(tmp_path, "war_vamp_fatale.zip", prefix, expected)
