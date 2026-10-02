"""Independently audit supplied PLD clyteum logs."""

import pytest

from .pld_audit import audit_pld

CASES = ['8LdwxRpHtBT7WgZn/fight-1/source-4', 'Mf9brxJ3LVqPmKXT/fight-1/source-3', 'mHyfD847Yv2RMZtz/fight-1/source-2']


@pytest.mark.parametrize("prefix", CASES)
def test_paladin_log(tmp_path, prefix):
    audit_pld(tmp_path, "pld_clyteum.zip", prefix)
