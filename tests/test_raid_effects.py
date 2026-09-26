"""Raid effect data is parsed from each official guide, not fixed in the crawler."""

import json
from pathlib import Path

import httpx
import pytest

from ffxiv_potency.fflogs.analyze import _load_combat_profile, _raid_luck_adjustment
from ffxiv_potency.jobguide.raid_buffs import parse_raid_effects, update_raid_effects


def _row(index: int, action: str, description: str) -> str:
    return (
        f'<tr id="pve_action__{index}"><td class="skill"><strong>{action}</strong></td>'
        f'<td class="content">{description}</td></tr>'
    )


def test_crawls_five_raid_rates_from_three_guides(tmp_path: Path) -> None:
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
        "scholar": _row(
            5, "Chain Stratagem", "Increases rate at which target takes critical hits by 10%."
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
        0.10,
    ]
    assert (destination.parent / "bard.html").is_file()
    with pytest.raises(ValueError, match="one crit/DH rate"):
        parse_raid_effects(pages["dragoon"].replace("10%", "unknown"), "dragoon")


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
    }
    assert _raid_luck_adjustment({"buffs": ""}, effects, names, profile) == 0
    assert _raid_luck_adjustment({"buffs": "5."}, effects, names, profile) == pytest.approx(
        0.10 * (profile.critical_damage_multiplier - 1) * (1 + profile.direct_rate * 0.25)
    )
    assert _raid_luck_adjustment({"buffs": "1.2.3.4.5."}, effects, names, profile) > 0.10
