"""Audit supplied Warrior another merchants tale logs independently."""

import pytest

CASES = [
    ("RzXLJYKqmf7NkPg8/fight-10/source-126", ("Kisei Rie", 4550, "7.4", "savage_7_4", 4)),
    ("Y4JLGvM2QPa7jrNd/fight-2/source-65", ("Oldinho Oldun", 4550, "7.4", "savage_7_4", 4)),
    ("6TwvktDphrMqzcHL/fight-59/source-239", ("Shiinya Mitsuwu", 4550, "7.4", "savage_7_4", 4)),
]


@pytest.mark.parametrize("prefix,expected", CASES)
def test_warrior_log(tmp_path, audit_war, prefix, expected):
    audit_war(tmp_path, "war_another_merchants_tale.zip", prefix, expected)
