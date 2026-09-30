import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from ffxiv_potency.jobguide import (
    JobGuideParseError,
    inspect_job_actions,
    parse_job_actions,
    parse_job_traits,
)
from ffxiv_potency.jobguide.snapshot import BRD_URL, update_job_guide

FIXTURES = Path(__file__).parents[1] / "fixtures/jobguide"


@pytest.mark.parametrize("job, abbreviation", [("bard", "brd"), ("machinist", "mch")])
def test_full_guide_matches_committed_action_snapshot(job: str, abbreviation: str) -> None:
    html = (FIXTURES / f"{abbreviation}_full_7_5.html").read_text(encoding="utf-8")
    committed = json.loads(
        (Path(__file__).parents[2] / "data" / job / "7.55" / "actions.json").read_text()
    )
    assert [action.to_dict() for action in parse_job_actions(html)] == committed["actions"]
    assert [trait.to_dict() for trait in parse_job_traits(html)] == committed["traits"]


def test_update_downloads_and_exports_versioned_snapshot(tmp_path: Path) -> None:
    mch_url = "https://example.test/jobguide/machinist/"
    source_bytes = (FIXTURES / "mch_full_7_5.html").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == mch_url
        return httpx.Response(200, content=source_bytes)

    result = update_job_guide(
        job="machinist",
        patch="7.55",
        output_root=tmp_path,
        url=mch_url,
        transport=httpx.MockTransport(handler),
        retrieved_at=datetime(2026, 9, 23, 12, 0, tzinfo=UTC),
    )

    assert result.source == tmp_path / "machinist" / "7.55" / "source.html"
    assert result.actions == tmp_path / "machinist" / "7.55" / "actions.json"
    assert result.action_count == 40
    assert result.source.read_bytes() == source_bytes

    document = json.loads(result.actions.read_text(encoding="utf-8"))
    assert document["job"] == "machinist"
    assert document["patch"] == "7.55"
    assert document["source"] == {
        "url": mch_url,
        "retrieved_at": "2026-09-23T12:00:00Z",
        "sha256": hashlib.sha256(source_bytes).hexdigest(),
    }
    assert len(document["actions"]) == 40
    assert document["schema_version"] == 3
    assert document["traits"][0]["name"] == "Increased Action Damage"
    assert document["traits"][0]["description"] == [
        "Increases base action damage and autoturret damage by 10%.",
    ]
    assert document["traits"][0]["action_damage_multiplier"] == 1.1
    assert document["traits"][1]["action_damage_multiplier"] == 1.2


def test_complete_mch_snapshot_has_expected_coverage() -> None:
    html = (FIXTURES / "mch_full_7_5.html").read_text(encoding="utf-8")

    report = inspect_job_actions(html)

    assert report.source_action_count == 39
    assert len(report.actions) == 40
    assert len(report.issues) == 0
    actions = {action.name: action for action in report.actions}
    assert len(actions) == len(report.actions)
    assert actions["Split Shot"].potency is not None
    assert actions["Split Shot"].potency.base == 140
    assert actions["Reassemble"].potency is None


def test_brd_guide_crawls_all_actions_and_special_potencies(tmp_path: Path) -> None:
    html = (FIXTURES / "brd_full_7_5.html").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == BRD_URL
        return httpx.Response(200, content=html)

    result = update_job_guide(
        job="bard",
        patch="7.55",
        output_root=tmp_path,
        transport=httpx.MockTransport(handler),
        retrieved_at=datetime(2026, 9, 27, tzinfo=UTC),
    )
    assert result.action_count == 34
    assert result.source.read_bytes() == html
    document = json.loads(result.actions.read_text(encoding="utf-8"))
    assert document["job"] == "bard"
    assert document["source"]["url"] == BRD_URL
    actions = {row["name"]: row for row in document["actions"]}
    assert len(actions) == 34
    assert actions["Barrage"]["potency"] is None
    assert actions["Caustic Bite"]["potency"]["damage_over_time"] == {
        "potency_per_tick": 20,
        "duration_seconds": 45,
    }
    assert actions["Stormbite"]["potency"]["damage_over_time"]["potency_per_tick"] == 25
    assert actions["Pitch Perfect"]["potency"]["stack_potency"]["by_count"] == {
        "1": 100,
        "2": 220,
        "3": 360,
    }
    assert actions["Radiant Encore"]["potency"]["stack_potency"]["by_count"] == {
        "1": 700,
        "2": 800,
        "3": 1100,
    }
    assert actions["Radiant Encore"]["potency"]["falloff"]["additional_target_multiplier"] == 0.5
    assert actions["Apex Arrow"]["potency"]["gauge_scaling"] == {
        "gauge": "Soul Voice Gauge",
        "maximum_potency": 700,
        "minimum_cost": 20,
    }
    assert actions["Shadowbite"]["potency"]["conditional_potencies"] == {
        "Barrage": 300,
    }
    assert actions["Wide Volley"]["potency"]["conditional_potencies"] == {
        "Barrage": 220,
    }
    assert [
        trait["action_damage_multiplier"] for trait in document["traits"]
        if trait["name"].startswith("Increased Action Damage")
    ] == [1.1, 1.2]


def test_unrecognized_action_damage_trait_does_not_replace_snapshot(tmp_path: Path) -> None:
    destination = tmp_path / "bard/7.55/actions.json"
    destination.parent.mkdir(parents=True)
    destination.write_text('{"previous": true}\n', encoding="utf-8")
    html = (FIXTURES / "brd_full_7_5.html").read_text(encoding="utf-8")
    changed = html.replace("Increases base action damage by 20%.", "Makes attacks stronger.", 1)
    assert changed != html

    with pytest.raises(JobGuideParseError, match="Unsupported action damage trait wording"):
        update_job_guide(
            job="bard", patch="7.55", output_root=tmp_path,
            transport=httpx.MockTransport(lambda request: httpx.Response(200, text=changed)),
        )
    assert destination.read_text(encoding="utf-8") == '{"previous": true}\n'


@pytest.mark.parametrize("patch", ["", "latest", "7", "../7.5", "7.5/other", "7.5"])
def test_update_rejects_unsafe_or_ambiguous_patch(patch: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="only patch 7.55"):
        update_job_guide(job="machinist", patch=patch, output_root=tmp_path)


def test_unrecognized_guide_wording_does_not_replace_existing_actions(tmp_path: Path) -> None:
    actions = tmp_path / "machinist/7.55/actions.json"
    actions.parent.mkdir(parents=True)
    actions.write_text('{"previous": true}\n', encoding="utf-8")
    html = (FIXTURES / "mch_full_7_5.html").read_text(encoding="utf-8")
    original = "Delivers an attack with a potency of 660.<br>Maximum Charges: 2"
    assert original in html
    changed = html.replace(original, "Unrecognized potency wording.<br>Maximum Charges: 2", 1)

    with pytest.raises(JobGuideParseError, match="Unsupported potency wording for 'Drill'"):
        update_job_guide(
            job="machinist",
            patch="7.55",
            output_root=tmp_path,
            transport=httpx.MockTransport(lambda request: httpx.Response(200, text=changed)),
        )

    assert actions.read_text(encoding="utf-8") == '{"previous": true}\n'


def test_brd_heavier_shot_description_survives_malformed_official_html() -> None:
    html = (FIXTURES / "brd_malformed_heavier_shot.html").read_text()
    traits = parse_job_traits(html)
    assert traits[0].name == "Heavier Shot"
    assert traits[0].level == 2
    assert traits[0].description == (
        "Adds to Heavy Shot a 20% chance to grant Hawk's Eye.", "Duration: 30s",
    )
    expected = json.loads(
        (Path(__file__).parents[2] / "data/bard/7.55/actions.json").read_text()
    )
    assert [t.to_dict() for t in traits] == expected["traits"]
    assert [a.to_dict() for a in parse_job_actions(html)] == expected["actions"]


def test_trait_missing_content_does_not_borrow_next_trait_description() -> None:
    html = '''<table>
    <tr id="trait_action__01"><td class="skill"><strong>First</strong></td>
    <td class="jobclass"><div>Lv. 2</div></div></td></tr>
    <tr id="trait_action__02"><td class="skill"><strong>Second</strong></td>
    <td class="jobclass">Lv. 20</td><td class="content">Second effect.</td></tr>
    </table>'''
    traits = parse_job_traits(html)
    assert traits[0].description == ()
    assert traits[1].description == ("Second effect.",)
