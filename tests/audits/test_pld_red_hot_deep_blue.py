"""Independently audit supplied PLD red_hot_deep_blue logs."""

import pytest

from .pld_audit import audit_pld

CASES = ['9xmAtQ6rDjPR82aC/fight-1/source-3', 'HLFK1Zn326mbwzpX/fight-2/source-37', 'pqft2WXmCVKrJNRa/fight-15/source-122']


@pytest.mark.parametrize("prefix", CASES)
def test_paladin_log(tmp_path, prefix):
    audit_pld(tmp_path, "pld_red_hot_deep_blue.zip", prefix)
