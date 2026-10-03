"""PLD cached models round-trip and unchanged guide refreshes reuse results."""

import json
import shutil
from pathlib import Path
from zipfile import ZipFile

import httpx

from ffxiv_potency.analysis import analyze as analyzer
from ffxiv_potency.analysis.cache import _decode, _encode, cache_path
from ffxiv_potency.analysis.models import AnalysisResult
from ffxiv_potency.analysis.pld.summary import PldSummary
from ffxiv_potency.jobguide.snapshot import update_job_guide

ROOT = Path(__file__).resolve().parents[2]


def test_typed_cache_refresh_reuse_and_semantic_invalidation(tmp_path, monkeypatch):
    root = tmp_path / "data"
    shutil.copytree(ROOT / "data/jobs/pld", root / "jobs/pld")
    logs = root / "logs"
    with ZipFile(ROOT / "tests/fixtures/logs/pld_dancing_mad.zip") as archive:
        archive.extractall(logs)
    directory = logs / "dzyx6FtjcQXMDJP3/fight-13/source-98"
    actions = root / "jobs/pld/7.4/actions.json"
    guide = (ROOT / "tests/fixtures/jobguide/pld_full_7_56.html").read_text()
    monkeypatch.chdir(tmp_path)
    actual = analyzer._analyze_saved_fight
    calls = []

    def calculate(*args, **kwargs):
        calls.append(1)
        return actual(*args, **kwargs)

    monkeypatch.setattr(analyzer, "_analyze_saved_fight", calculate)
    first = analyzer.analyze_saved_fight(directory, actions)
    assert _decode(_encode(first), AnalysisResult) == first
    assert isinstance(first.pld, PldSummary)
    assert isinstance(first.pld.bursts, tuple)
    assert isinstance(first.pld.holy_spirit_casts, tuple)
    assert isinstance(first.pld.cooldown_timing, tuple)
    assert first.pld.combos is not None
    assert isinstance(first.pld.combos.losses, tuple)
    assert len(first.pld.cooldown_timing) == 5
    assert first.pld.cooldown_timing[0].ready_seconds is not None
    assert first.pld.cooldown_timing[-1].minimum
    assert any(kind == "hard cast" for _, kind in first.pld.holy_spirit_casts)
    assert any(kind == "instant" for _, kind in first.pld.holy_spirit_casts)
    assert cache_path(directory).exists()
    assert analyzer.analyze_saved_fight(directory, actions) == first
    assert len(calls) == 1
    update_job_guide(job="paladin", patch="7.56", output_root=root,
                     transport=httpx.MockTransport(lambda _: httpx.Response(200, text=guide)))
    assert analyzer.analyze_saved_fight(directory, actions) == first
    assert len(calls) == 1
    override = analyzer.analyze_saved_fight(directory, actions, gear="relic_7_55")
    assert override.gear_id == "relic_7_55" and override.gear_source == "user-selected"
    assert len(calls) == 2
    # A guide change creates a new action version and invalidates calculations.
    changed = guide.replace("potency of 220.", "potency of 222.")
    assert changed != guide
    new = update_job_guide(job="paladin", patch="7.56", output_root=root,
                           transport=httpx.MockTransport(lambda _: httpx.Response(200, text=changed)))
    assert new.actions != actions
    result = analyzer.analyze_saved_fight(directory, actions)
    assert result.potency_min > first.potency_min and len(calls) == 3
    assert json.loads(actions.read_text())["patch"] == "7.4"
