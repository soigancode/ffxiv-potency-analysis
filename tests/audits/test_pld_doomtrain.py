"""Independently audit supplied PLD doomtrain logs."""

import pytest

from .pld_audit import audit_pld

CASES = ['A2fyzv348WqpTnbD/fight-15/source-271', 'B8CWz2HPJgcwmZYF/fight-4/source-6', 'XF4agMxAcQbhY1kB/fight-11/source-374']


@pytest.mark.parametrize("prefix", CASES)
def test_paladin_log(tmp_path, prefix):
    audit_pld(tmp_path, "pld_doomtrain.zip", prefix)
