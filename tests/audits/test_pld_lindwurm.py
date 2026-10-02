"""Independently audit supplied PLD lindwurm logs."""

import pytest

from .pld_audit import audit_pld

CASES = ['9Kk8D6gW7MwC3Vbh/fight-1/source-29', 'DTVtzXhGqcJFMnmb/fight-1/source-4', 'phja89JyfFQKVz6q/fight-36/source-9']


@pytest.mark.parametrize("prefix", CASES)
def test_paladin_log(tmp_path, prefix):
    audit_pld(tmp_path, "pld_lindwurm.zip", prefix)
