"""Audit supplied Warrior enuo logs independently."""

import pytest

CASES = [
    ("RCaHJvqWb4KfQd1X/fight-37/source-279", ("Fefel Saturne", 1084, "7.5", "savage_7_4", 5)),
    ("djvB1cXwk87MNCmn/fight-16/source-2", ("Slade Skywalker", 1084, "7.5", "savage_7_4", 5)),
    ("xDXcF4y2kJrapZjV/fight-25/source-133", ("Yaoi Girlfriend", 1084, "7.5", "savage_7_4", 5)),
]


@pytest.mark.parametrize("prefix,expected", CASES)
def test_warrior_log(tmp_path, audit_war, prefix, expected):
    audit_war(tmp_path, "war_enuo.zip", prefix, expected)
