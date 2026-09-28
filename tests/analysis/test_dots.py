"""Shared application matching also works for a DoT without a refresh action."""

from ffxiv_potency.analysis.dots import DotRules, reconstruct_dot_ticks


def test_bioblaster_ticks_keep_target_and_application_snapshots() -> None:
    def hit(time: int, packet: int, target: int, ability: int, *, tick: bool = False, buffs: str = ""):
        return {
            "type": "damage", "sourceID": 2, "targetID": target,
            "timestamp": time, "packetID": packet, "abilityGameID": ability,
            "tick": tick, "amount": 100, "buffs": buffs,
        }

    events = [
        hit(100, 11, 10, 1, buffs="49."),
        hit(150, 21, 20, 1, buffs=""),
        hit(3000, 11, 10, 1, tick=True),
        hit(3400, 99, 10, 2),  # An unrelated action cannot refresh Bioblaster.
        hit(6000, 11, 10, 1, tick=True),
        hit(6100, 21, 20, 1, tick=True),
        hit(8000, 12, 10, 1, buffs="new."),
        hit(9000, 11, 10, 1, tick=True),  # The replaced application is no longer live.
        hit(11000, 12, 10, 1, tick=True),
        hit(20000, 21, 20, 1, tick=True),  # The other target's application expired.
    ]

    ticks = reconstruct_dot_ticks(
        events, {1: "Bioblaster", 2: "Drill"}, 2,
        DotRules(frozenset({"Bioblaster"}), duration_ms=15_000),
    )

    assert [tick.matched for tick in ticks] == [True, True, True, False, True, False]
    assert [tick.snapshot_buffs for tick in ticks] == ["49.", "49.", "", "", "new.", ""]
    assert [tick.target_id for tick in ticks] == [10, 10, 20, 10, 10, 20]
