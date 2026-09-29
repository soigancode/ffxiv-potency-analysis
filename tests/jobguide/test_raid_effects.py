"""Raid effect data is parsed from each official guide, not fixed in the crawler."""

import json
from pathlib import Path

import httpx
import pytest

from ffxiv_potency.analysis.luck import _load_raid_effects
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
                    "Grants the Wanderer's Minuet, increasing critical hit rate by 4%.",
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
    assert destination == tmp_path / "raid_effects/7.55.json"
    assert [effect["bonus"] for effect in json.loads(destination.read_text())["effects"]] == [
        0.10,
        0.10,
        0.20,
        0.03,
        0.04,
        0.20,
        0.20,
    ]
    assert (tmp_path / "raid_effects/sources/7.55/bard.html").is_file()
    actions = tmp_path / "machinist/7.55/actions.json"
    actions.parent.mkdir(parents=True)
    actions.write_text('{"patch": "7.55"}', encoding="utf-8")
    assert _load_raid_effects(actions) == json.loads(destination.read_text())["effects"]
    with pytest.raises(ValueError, match="one crit/DH rate"):
        parse_raid_effects(pages["dragoon"].replace("10%", "unknown"), "dragoon")
    with pytest.raises(ValueError, match="both crit and DH rates"):
        parse_raid_effects(pages["dancer"].replace("direct hit rate", "accuracy"), "dancer")
