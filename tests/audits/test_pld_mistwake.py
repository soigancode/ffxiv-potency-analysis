"""Independently audit supplied PLD mistwake logs."""

import pytest

from .pld_audit import audit_pld

CASES = ['Cxzw8FXY3dbjJDmB/fight-14/source-2', 'PBjz4WbvGxQ2tKVk/fight-18/source-136', 'dagPQCNrqZzwcx3Y/fight-1/source-2']


@pytest.mark.parametrize("prefix", CASES)
def test_paladin_log(tmp_path, prefix):
    audit_pld(tmp_path, "pld_mistwake.zip", prefix)
