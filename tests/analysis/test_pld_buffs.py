"""Circle of Scorn snapshots require recorded integer event identifiers."""

from typing import Any

import pytest

from ffxiv_potency.analysis.errors import AnalysisError
from ffxiv_potency.analysis.pld.buffs import circle_snapshots


@pytest.mark.parametrize("ability", [None, "1000248"])
def test_circle_snapshots_ignore_unknown_ability_identifiers(ability):
    damage = [{"type": "damage", "sourceID": 1, "tick": tick,
               "abilityGameID": ability, "amount": 100}
              for tick in (False, True)]
    assert circle_snapshots(damage, [], {1000248: "Circle of Scorn"}, 1) == {}


@pytest.mark.parametrize("field", ["timestamp", "packetID", "targetID"])
@pytest.mark.parametrize("missing", [False, True])
@pytest.mark.parametrize("amount", [0, 100])
def test_circle_tick_with_missing_match_identifier(field, missing, amount):
    tick: dict[str, Any] = {"type": "damage", "sourceID": 1, "tick": True,
                            "abilityGameID": 1000248, "timestamp": 10000,
                            "packetID": 1, "targetID": 2, "amount": amount}
    if missing:
        del tick[field]
    else:
        tick[field] = None
    if amount:
        with pytest.raises(AnalysisError, match="cannot match Circle of Scorn tick"):
            circle_snapshots([tick], [], {1000248: "Circle of Scorn"}, 1)
    else:
        assert circle_snapshots([tick], [], {1000248: "Circle of Scorn"}, 1) == {}
