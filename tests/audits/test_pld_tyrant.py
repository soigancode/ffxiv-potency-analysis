"""Independently audit supplied PLD tyrant logs."""

import pytest

from .pld_audit import audit_pld

CASES = ['9FJgCWnP82kV61Th/fight-5/source-28', 'F1xadAwMnKQm4tgR/fight-44/source-10', 'vLm7VgGdxhQ19yHj/fight-44/source-690']


@pytest.mark.parametrize("prefix", CASES)
def test_paladin_log(tmp_path, prefix):
    audit_pld(tmp_path, "pld_tyrant.zip", prefix)
