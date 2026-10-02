"""Independently audit supplied PLD enuo logs."""

import pytest

from .pld_audit import audit_pld

CASES = ['6n2JyQvfxmgB9ztp/fight-13/source-2', 'a-mgtzdRcrYZByP397/fight-8/source-59', 'ahFnXrBtxN46DjwJ/fight-17/source-42']


@pytest.mark.parametrize("prefix", CASES)
def test_paladin_log(tmp_path, prefix):
    audit_pld(tmp_path, "pld_enuo.zip", prefix)
