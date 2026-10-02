"""Independently audit supplied PLD another_merchants_tale logs."""

import pytest

from .pld_audit import audit_pld

CASES = ['6GXNV2hj4pDBybRd/fight-4/source-36', 'YnJGy1bqjzMDmvZh/fight-24/source-100', 'xRLQdJ2qv7XFT4rA/fight-35/source-478']


@pytest.mark.parametrize("prefix", CASES)
def test_paladin_log(tmp_path, prefix):
    audit_pld(tmp_path, "pld_another_merchants_tale.zip", prefix)
