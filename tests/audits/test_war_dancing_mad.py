"""Audit supplied Warrior dancing mad logs independently."""

from pathlib import Path

import pytest

from ffxiv_potency.analysis import analyze as analyzer

CASES = [
    ("c8rZPQjqBd9LKGzv/fight-19/source-71", ("Injective Function", 1085, "7.5", "relic_7_55", 5)),
    ("TVGB6LM4FYzmfcdK/fight-6/source-1570", ("Slade Skywalker", 1085, "7.5", "relic_7_55", 5)),
    ("G8NXRVTHjvcAbrM9/fight-4/source-7", ("Esty Meow", 1085, "7.5", "relic_7_55", 5)),
]


@pytest.mark.parametrize("prefix,expected", CASES)
def test_warrior_log(tmp_path, audit_war, prefix, expected, monkeypatch):
    result = audit_war(tmp_path, "war_dancing_mad.zip", prefix, expected)
    seconds = {"Injective Function": 1017.292, "Slade Skywalker": 993.851, "Esty Meow": 996.461}
    assert result.targetable_seconds == pytest.approx(seconds[expected[0]])
    assert result.pps_min == pytest.approx(result.potency_min / seconds[expected[0]])
    if expected[0] == "Injective Function":
        assert result.ghosted == (("Storm's Eye", 1),)
        assert result.ghosted_times == (("Storm's Eye", (382.362,)),)
        assert next(action for action in result.actions if action.name == "Damnation").hits == 15

        actions = Path("data/jobs/war/7.5/actions.json")
        assert analyzer.analyze_saved_fight(tmp_path, actions) == result
        def fail_calculation(*args, **kwargs):
            raise AssertionError("the cached Warrior summary should be reused")
        monkeypatch.setattr(analyzer, "_analyze_saved_fight", fail_calculation)
        cached = analyzer.analyze_saved_fight(tmp_path, actions)
        assert cached == result
        assert cached.war is not None
        assert cached.war.guaranteed_spenders == 57
        assert cached.war.inner_release_uses == 19
