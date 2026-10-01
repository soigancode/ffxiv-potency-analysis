"""Audit supplied Dancer checkpoint pulls and carry-over context."""

import pytest

ADDITIONAL_CASES = [
    (
        "3BVG6fvbQktJjrNK/fight-15/source-6",
        ("Hamu Exacum", "savage_7_4", 238, 161, 2, 23, 41, 22, 22, 13),
        (0,),
    ),
    (
        "3P6vWHcfzb72Cahj/fight-25/source-210",
        ("Felwinter Wright", "savage_7_4", 237, 158, 2, 22, 46, 26, 26, 10),
        (0,),
    ),
    (
        "96PJp3R7YQbK2HDy/fight-10/source-339",
        ("Aki Yuzuka", "savage_7_4", 243, 160, 2, 22, 43, 25, 25, 15),
        (0,),
    ),
    (
        "D7jd4xP9yYCFkWvA/fight-39/source-108",
        ("Gisele Alan", "savage_7_4", 239, 162, 2, 23, 49, 24, 24, 12),
        (0,),
    ),
    (
        "P2x8WQmArqKfycYF/fight-32/source-11",
        ("Yora Sakimuri", "savage_7_4", 243, 161, 2, 22, 48, 27, 27, 11),
        (0,),
    ),
    (
        "aBzTGWJvwx7D2hyt/fight-14/source-9",
        ("Mary Rean", "savage_7_4", 240, 159, 2, 22, 45, 26, 22, 13),
        (0, 1, 2, 3, 4),
    ),
    (
        "bX7C4QfLYcaVGq6j/fight-212/source-1810",
        ("Vuln Collector", "savage_7_4", 238, 158, 2, 22, 45, 22, 18, 13),
        (0, 1, 2, 3, 4),
    ),
    (
        "f3YXkW2FKBPnpHr4/fight-27/source-21",
        ("Hige Chan", "savage_7_4", 238, 159, 2, 22, 46, 23, 19, 12),
        (0, 1, 2, 3, 4),
    ),
    (
        "nPbmkNtrg12CLMYf/fight-43/source-100",
        ("Aela Inanna", "savage_7_4", 251, 161, 2, 22, 43, 31, 31, 17),
        (0,),
    ),
    (
        "qCnc4rYHFTA86QPy/fight-13/source-54",
        ("Xiro Arath", "savage_7_4", 258, 163, 2, 22, 48, 31, 31, 20),
        (0,),
    ),
]


@pytest.mark.parametrize("prefix,expected,starting", ADDITIONAL_CASES)
def test_supplied_dancer_logs(tmp_path, audit_dnc, prefix, expected, starting):
    result = audit_dnc(tmp_path, "dnc_lindwurm_ii.zip", prefix, expected, starting)
    assert result.encounter_id == 105


def test_pre_pull_standard_with_variable_radiant_finale(tmp_path, audit_dnc):
    result = audit_dnc(
        tmp_path,
        "dnc_lindwurm_ii.zip",
        "BNjF2RTJLmGpQbZy/fight-14/source-4",
        ("Pan Pino", "savage_7_4", 251, 166, 2, 22, 46, 23, 23, 18),
        (0,),
    )
    assert result.dnc_initial_buffs == (("Standard Finish", 1.05),)
