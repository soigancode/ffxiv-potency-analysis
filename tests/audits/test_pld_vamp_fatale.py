"""Independently audit supplied PLD vamp_fatale logs."""

import pytest

from .pld_audit import audit_pld

CASES = ['ACphXqgKHj1D7LbY/fight-21/source-10', 'YT6mc2XxDBAqadQH/fight-25/source-4', 'dZKyT2HNW19zL6QY/fight-1/source-2']


@pytest.mark.parametrize("prefix", CASES)
def test_paladin_log(tmp_path, prefix):
    audit_pld(tmp_path, "pld_vamp_fatale.zip", prefix)
