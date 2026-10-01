"""Status windows require actual events; damage snapshots provide only observations."""

import pytest

from ffxiv_potency.analysis.auto_attacks import _summarize_auto_attacks
from ffxiv_potency.analysis.brd.dots import brd_dot_potency
from ffxiv_potency.analysis.dots import DotTick
from ffxiv_potency.analysis.penalties import revival_multiplier, summarize_status_windows
from ffxiv_potency.analysis.profiles import _load_combat_profile


def test_death_revival_and_naturally_removed_weakness() -> None:
    debuffs = [
        {"type": "applydebuff", "targetID": 2, "timestamp": 12000,
         "abilityGameID": 1000043},
        {"type": "removedebuff", "targetID": 2, "timestamp": 112000,
         "abilityGameID": 1000043},
        {"type": "applydebuff", "targetID": 3, "timestamp": 13000,
         "abilityGameID": 1000044},
    ]
    life = [
        {"type": "death", "targetID": 2, "timestamp": 5000},
        {"type": "resurrect", "targetID": 2, "timestamp": 12000},
    ]
    windows = summarize_status_windows(
        debuffs, life, {1000043: "Weakness", 1000044: "Brink of Death"},
        2, 0, 140000,
    )
    assert [(w.name, w.start_seconds, w.end_seconds, w.end_reason) for w in windows] == [
        ("Dead", 5, 12, "resurrected"),
        ("Weakness", 12, 112, "expired"),
    ]


def test_damage_down_removed_at_wipe_is_not_natural_expiry() -> None:
    windows = summarize_status_windows(
        [{"type": "applydebuff", "targetID": 2, "timestamp": 500,
          "abilityGameID": 1002911},
         {"type": "refreshdebuff", "targetID": 2, "timestamp": 900,
          "abilityGameID": 1002911},
         {"type": "removedebuff", "targetID": 2, "timestamp": 9950,
          "abilityGameID": 1002911}],
        [], {1002911: "Damage Down"}, 2, 0, 10000,
    )
    assert [(w.name, w.start_seconds, w.end_seconds, w.end_reason) for w in windows] == [
        ("Damage Down", 0.5, 9.95, "fight ended"),
    ]


def test_damage_down_reapplications_extend_one_window_until_natural_expiry() -> None:
    debuffs = [
        {"type": "applydebuff", "targetID": 2, "timestamp": 5_000,
         "abilityGameID": 1002911, "duration": 30_000},
        {"type": "removedebuff", "targetID": 2, "timestamp": 13_000,
         "abilityGameID": 1002911},
        {"type": "applydebuff", "targetID": 2, "timestamp": 13_000,
         "abilityGameID": 1002911, "duration": 30_000},
        {"type": "refreshdebuff", "targetID": 2, "timestamp": 20_000,
         "abilityGameID": 1002911, "duration": 30_000},
        {"type": "removedebuff", "targetID": 2, "timestamp": 50_025,
         "abilityGameID": 1002911},
    ]
    windows = summarize_status_windows(
        debuffs, [], {1002911: "Damage Down"}, 2, 0, 70_000,
    )
    assert len(windows) == 1
    assert windows[0].start_seconds == 5
    assert windows[0].end_seconds == pytest.approx(50.025)
    assert windows[0].refresh_seconds == (13, 20)
    assert windows[0].end_reason == "expired"


def test_early_revival_penalty_removal_is_not_labelled_expired() -> None:
    windows = summarize_status_windows(
        [{"type": "applydebuff", "targetID": 2, "timestamp": 1_000,
          "abilityGameID": 1000043},
         {"type": "removedebuff", "targetID": 2, "timestamp": 51_000,
          "abilityGameID": 1000043}],
        [], {1000043: "Weakness"}, 2, 0, 150_000,
    )
    assert [(w.name, w.end_reason) for w in windows] == [("Weakness", "removed")]


def test_weakness_application_bounds_revival_without_a_resurrect_event() -> None:
    windows = summarize_status_windows(
        [{"type": "applydebuff", "targetID": 2, "timestamp": 12_000,
          "abilityGameID": 1000043}],
        [{"type": "death", "targetID": 2, "timestamp": 5_000},
         {"type": "death", "targetID": 2, "timestamp": 25_000}],
        {1000043: "Weakness"}, 2, 0, 30_000,
    )
    assert [(w.name, w.start_seconds, w.end_seconds, w.end_reason) for w in windows] == [
        ("Dead", 5, 12, "revived: Weakness applied"),
        ("Weakness", 12, 25, "death"),
        ("Dead", 25, 30, "fight ended"),
    ]


def test_player_cast_bounds_revival_when_no_revival_status_is_recorded() -> None:
    windows = summarize_status_windows(
        [], [{"type": "death", "targetID": 2, "timestamp": 5000}], {},
        2, 0, 30000,
        [{"type": "cast", "sourceID": 3, "timestamp": 8000},
         {"type": "cast", "sourceID": 2, "timestamp": 9000},
         {"type": "cast", "sourceID": 2, "timestamp": 12000}],
    )
    assert [(w.name, w.start_seconds, w.end_seconds, w.end_reason) for w in windows] == [
        ("Dead", 5, 9, "revived by next cast; exact time unknown"),
    ]


def test_transcendent_marks_penalty_free_revival_before_next_cast() -> None:
    windows = summarize_status_windows(
        [], [{"type": "death", "targetID": 2, "timestamp": 5000}],
        {1000418: "Transcendent"}, 2, 0, 30000,
        [{"type": "cast", "sourceID": 2, "timestamp": 12000}],
        [{"type": "applybuff", "sourceID": -1, "targetID": 2,
          "abilityGameID": 1000418, "timestamp": 5046},
         {"type": "applybuff", "sourceID": -1, "targetID": 3,
          "abilityGameID": 1000418, "timestamp": 5046}],
    )
    assert [(w.name, w.start_seconds, w.end_seconds, w.end_reason) for w in windows] == [
        ("Dead", 5, 5.046, "revived: Healer LB3"),
    ]


def test_transcendent_does_not_label_a_penalized_revival_as_lb3() -> None:
    windows = summarize_status_windows(
        [{"type": "applydebuff", "targetID": 2, "timestamp": 5100,
          "abilityGameID": 1000043}],
        [{"type": "death", "targetID": 2, "timestamp": 5000}],
        {1000043: "Weakness"}, 2, 0, 30000, None,
        [{"type": "applybuff", "targetID": 2, "timestamp": 5046,
          "abilityGameID": 1000418}],
    )
    assert [(w.name, w.end_reason) for w in windows] == [
        ("Dead", "revived: Weakness applied"), ("Weakness", "fight ended"),
    ]


def test_brink_reapplies_for_a_full_window_after_another_revival() -> None:
    debuffs = [
        {"type": "applydebuff", "targetID": 2, "timestamp": 12_000,
         "abilityGameID": 1000044},
        {"type": "applydebuff", "targetID": 2, "timestamp": 42_000,
         "abilityGameID": 1000044, "duration": 100_000},
        {"type": "removedebuff", "targetID": 2, "timestamp": 142_000,
         "abilityGameID": 1000044},
    ]
    life = [
        {"type": "death", "targetID": 2, "timestamp": 5_000},
        {"type": "death", "targetID": 2, "timestamp": 35_000},
    ]
    windows = summarize_status_windows(debuffs, life, {1000044: "Brink of Death"},
                                      2, 0, 150_000)
    assert [(w.name, w.start_seconds, w.end_seconds, w.end_reason) for w in windows] == [
        ("Dead", 5, 12, "revived: Brink of Death applied"),
        ("Brink of Death", 12, 35, "death"),
        ("Dead", 35, 42, "revived: Brink of Death applied"),
        ("Brink of Death", 42, 142, "expired"),
    ]


def test_global_main_stat_penalties_include_potion_and_do_not_stack() -> None:
    profile = _load_combat_profile("bard")
    normal_dex = 6841
    potted_dex = 7382
    factor = lambda dex: 100 + 237 * (dex - 440) // 440
    for status_id, percentage in ((1000043, 75), (1000044, 50)):
        event = {"buffs": f"{status_id}."}
        assert revival_multiplier(event, profile) == (
            factor(normal_dex * percentage // 100) / factor(normal_dex)
        )
        event["buffs"] += f"{profile.potion_buff_id}."
        assert revival_multiplier(event, profile) == (
            factor(potted_dex * percentage // 100) / factor(potted_dex)
        )
    assert revival_multiplier({"buffs": "1000043.1000044."}, profile) == (
        factor(normal_dex // 2) / factor(normal_dex)
    )
    mch = _load_combat_profile("machinist")
    assert revival_multiplier({"buffs": "1000043."}, mch) == (
        factor(mch.party_main_stat * 75 // 100) / factor(mch.party_main_stat)
    )


def test_potion_gain_during_weakness_uses_the_unpotted_weak_baseline() -> None:
    profile = _load_combat_profile("bard")
    event = {"_resolved_name": "Shot", "buffs": f"1000043.{profile.potion_buff_id}."}
    attacks, unpotted_base, potion_gain = _summarize_auto_attacks(
        [{**event, "timestamp": 0}, {**event, "timestamp": 3040}], "bard", profile,
    )
    potency = attacks[0].potency_per_hit * 2
    expected_base = potency * revival_multiplier(event, profile, potted=False)
    expected_total = (
        potency * revival_multiplier(event, profile, potted=True)
        * profile.player_potion_multiplier
    )
    assert unpotted_base == pytest.approx(expected_base)
    assert attacks[0].total_potency == pytest.approx(expected_total)
    assert potion_gain == pytest.approx(expected_total - expected_base)


def test_dot_uses_application_potion_and_tick_revival_status() -> None:
    profile = _load_combat_profile("bard")
    tick = DotTick(
        "Stormbite", 3_000, 8, 10, "Stormbite", 100,
        f"{profile.potion_buff_id}.", "1000044.", True,
    )
    assert brd_dot_potency(
        tick, 25, potion_multiplier=profile.player_potion_multiplier,
        self_buff_windows={}, combat_profile=profile,
    ) == pytest.approx(
        25 * profile.player_potion_multiplier
        * revival_multiplier({"buffs": "1000044."}, profile, potted=True)
    )
    # A pre-death DoT can continue ticking without the newly applied status.
    no_brink = DotTick("Stormbite", 3_000, 8, 10, "Stormbite", 100,
                       "", "", True)
    assert brd_dot_potency(no_brink, 25, potion_multiplier=1,
                           self_buff_windows={}, combat_profile=profile) == 25
