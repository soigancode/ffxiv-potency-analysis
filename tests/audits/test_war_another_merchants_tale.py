"""Audit supplied Warrior another merchants tale logs independently."""

import pytest

CASES = [
    ("RzXLJYKqmf7NkPg8/fight-10/source-126", ("Kisei Rie", 4550, "7.4", "savage_7_4", 4)),
    ("Y4JLGvM2QPa7jrNd/fight-2/source-65", ("Oldinho Oldun", 4550, "7.4", "savage_7_4", 4)),
    ("6TwvktDphrMqzcHL/fight-59/source-239", ("Shiinya Mitsuwu", 4550, "7.4", "savage_7_4", 4)),
]


@pytest.mark.parametrize("prefix,expected", CASES)
def test_warrior_log(tmp_path, audit_war, prefix, expected, capsys):
    result = audit_war(tmp_path, "war_another_merchants_tale.zip", prefix, expected)
    if expected[0] == "Oldinho Oldun":
        from ffxiv_potency.cli import _print_analysis

        penalty = next(p for p in result.damage_penalties if p.name == "Damage Down")
        windows = [w for w in result.status_windows if w.name == penalty.name]
        by_window = [
            [(lo, hi) for time, lo, hi in penalty.hit_losses
             if w.start_seconds <= time < w.end_seconds]
            for w in windows
        ]
        assert [len(hits) for hits in by_window] == [14, 22]
        assert sum(map(len, by_window)) == penalty.affected_hits
        assert [sum(lo for lo, _ in hits) for hits in by_window] == pytest.approx(
            [698.5323529411767, 984.2735294117649]
        )
        assert sum(lo for _, lo, _ in penalty.hit_losses) == pytest.approx(penalty.lost_potency_min)
        _print_analysis(result, directory=tmp_path)
        output = capsys.readouterr().out
        assert "boss defeated" in output
        assert [w.end_reason for w in windows] == ["boss defeated", "expired"]
        assert "Damage Down total: 49.7s | Damage: -15% | Hits: 36 | Potency lost: 1,683" in output
        assert "all windows" not in output

