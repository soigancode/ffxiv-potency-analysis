"""Raid effect data is parsed from each official guide, not fixed in the crawler."""

import json
from pathlib import Path

import httpx
import pytest

from ffxiv_potency.fflogs.analyze import (
    _load_combat_profile,
    _load_raid_effects,
    _raid_luck_adjustment,
)
from ffxiv_potency.jobguide.raid_buffs import parse_raid_effects, update_raid_effects


def _row(index: int, action: str, description: str) -> str:
    return (
        f'<tr id="pve_action__{index}"><td class="skill"><strong>{action}</strong></td>'
        f'<td class="content">{description}</td></tr>'
    )


def test_crawls_seven_raid_rates_from_four_guides(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="only patch 7.55"):
        update_raid_effects(tmp_path, "7.5")
    pages = {
        "dragoon": _row(
            1,
            "Battle Litany",
            "Increases critical hit rate of self and nearby party members by 10%.",
        ),
        "bard": "".join(
            [
                _row(
                    2,
                    "Battle Voice",
                    "Increases direct hit rate of self and all nearby party members by 20%.",
                ),
                _row(3, "Army's Paeon", "Grants Army's Paeon, increasing direct hit rate by 3%."),
                _row(
                    4,
                    "The Wanderer's Minuet",
                    "Grants the Wanderer's Minuet, increasing critical hit rate by 2%.",
                ),
            ]
        ),
        "dancer": _row(
            5,
            "Devilment",
            "Increases critical hit rate and direct hit rate by 20%. "
            "Party member designated as your Dance Partner will also receive the effect.",
        ),
        "scholar": _row(
            6, "Chain Stratagem", "Increases rate at which target takes critical hits by 10%."
        ),
    }

    def respond(request: httpx.Request) -> httpx.Response:
        job = request.url.path.rstrip("/").split("/")[-1]
        return httpx.Response(200, text=pages[job])

    destination = update_raid_effects(tmp_path, "7.55", transport=httpx.MockTransport(respond))
    assert [effect["bonus"] for effect in json.loads(destination.read_text())["effects"]] == [
        0.10,
        0.20,
        0.03,
        0.02,
        0.20,
        0.20,
        0.10,
    ]
    assert (destination.parent / "bard.html").is_file()
    with pytest.raises(ValueError, match="one crit/DH rate"):
        parse_raid_effects(pages["dragoon"].replace("10%", "unknown"), "dragoon")
    with pytest.raises(ValueError, match="both crit and DH rates"):
        parse_raid_effects(pages["dancer"].replace("direct hit rate", "accuracy"), "dancer")


def test_target_debuff_and_player_buffs_adjust_expected_luck() -> None:
    profile = _load_combat_profile("machinist")
    effects = json.loads(
        (Path(__file__).parents[1] / "src/ffxiv_potency/data/raid_effects.json").read_text()
    )["effects"]
    names = {
        1: "Battle Litany",
        2: "Battle Voice",
        3: "Army's Paeon",
        4: "The Wanderer's Minuet",
        5: "Chain Stratagem",
        6: "Devilment",
    }
    assert _raid_luck_adjustment({"buffs": ""}, effects, names, profile) == 0
    assert _raid_luck_adjustment({"buffs": "5."}, effects, names, profile) == pytest.approx(
        0.10 * (profile.critical_damage_multiplier - 1) * (1 + profile.direct_rate * 0.25)
    )
    assert _raid_luck_adjustment({"buffs": "1.2.3.4.5."}, effects, names, profile) > 0.10
    crit_strength = profile.critical_damage_multiplier - 1
    buffed = _raid_luck_adjustment({"buffs": "6."}, effects, names, profile)
    expected = (
        (1 + (profile.critical_rate + 0.20) * crit_strength)
        * (1 + (profile.direct_rate + 0.20) * 0.25)
        - (1 + profile.critical_rate * crit_strength) * (1 + profile.direct_rate * 0.25)
    )
    assert buffed == pytest.approx(expected)


def test_old_local_effects_fall_back_to_complete_bundled_data(tmp_path: Path) -> None:
    actions = tmp_path / "data/machinist/7.55/actions.json"
    actions.parent.mkdir(parents=True)
    actions.write_text('{"patch": "7.55"}', encoding="utf-8")
    existing = tmp_path / "data/raid_buffs/7.55/effects.json"
    existing.parent.mkdir(parents=True)
    bundled = json.loads(
        (Path(__file__).parents[1] / "src/ffxiv_potency/data/raid_effects.json").read_text()
    )
    existing.write_text(
        json.dumps({"patch": "7.55", "effects": bundled["effects"][:4] + bundled["effects"][6:]}),
        encoding="utf-8",
    )
    assert _load_raid_effects(actions) == bundled["effects"]
