"""Independently audit supplied PLD lindwurm_ii logs."""

import pytest

from .pld_audit import audit_pld

CASES = ['HBhFGqTCDy9L2rf1/fight-10/source-10', 'VZtKzbPGAy6NMFqr/fight-11/source-148', 'dXrZC6F4mNgDyYVG/fight-4/source-7']


@pytest.mark.parametrize("prefix", CASES)
def test_paladin_log(tmp_path, prefix):
    audit_pld(tmp_path, "pld_lindwurm_ii.zip", prefix)
