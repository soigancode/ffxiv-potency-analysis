"""Spell-state precedence, recorded charges, expiry and cast evidence."""

import pytest

from ffxiv_potency.analysis.pld.state import DIVINE_MIGHT, REQUIESCAT, replay_spells

NAMES = {1: "Holy Spirit", 2: "Confiteor", 3: "Blade of Faith", 4: "Blade of Truth",
         5: "Blade of Valor", 6: "Holy Circle", 7: "Clemency"}


def cast(time, ability, **fields):
    return {"timestamp": time, "type": "cast", "sourceID": 1,
            "abilityGameID": ability, "packetID": time, **fields}


def buff(time, status, kind="applybuff", **fields):
    return {"timestamp": time, "type": kind, "sourceID": 1, "targetID": 1,
            "abilityGameID": status, "duration": 30000, **fields}


def replay(casts, buffs=(), initial=(), life=(), end=20000):
    return replay_spells(casts, list(buffs), list(life),
                         [{"sourceID": 1, "auras": list(initial)}], NAMES, 1, 0, end)


def test_divine_might_priority_does_not_spend_requiescat():
    state = replay([cast(1000, 1), cast(2000, 2), cast(3000, 3), cast(4000, 4), cast(5000, 5)],
                   [buff(0, REQUIESCAT), buff(0, DIVINE_MIGHT),
                    buff(1000, DIVINE_MIGHT, "removebuff"),
                    buff(2000, REQUIESCAT, "removebuffstack", stack=3)])
    assert [s.enhancement for s in state.spells] == ["Divine Might"] + ["Requiescat"] * 4
    assert [r.uses for r in state.ready] == [1, 4]
    assert state.ready[1].remaining == 0


@pytest.mark.parametrize("charges", [1, 2, 4])
def test_recorded_initial_charges_are_respected(charges):
    state = replay([cast(1000 * i, 1) for i in range(1, 6)],
                   initial=[{"ability": REQUIESCAT, "stacks": charges}])
    assert [s.enhancement for s in state.spells] == ["Requiescat"] * charges + ["None"] * (5 - charges)
    assert state.ready[1].grants == charges


@pytest.mark.parametrize("duration", [None, 1000])
@pytest.mark.parametrize("cast_time", [None, 2000])
def test_initial_expiry_with_and_without_later_events(duration, cast_time):
    state = replay([] if cast_time is None else [cast(cast_time, 2)],
                   initial=[{"ability": REQUIESCAT, "stacks": 4, "duration": duration}])
    ready = state.ready[1]
    assert ready.expired == (4 if duration is not None else 0)
    assert ready.uses == int(duration is None and cast_time is not None)
    assert ready.remaining == (0 if duration is not None else 4 - ready.uses)
    if duration is not None:
        assert ready.losses == ((1.0, "4 expired"),)


def test_removal_at_same_timestamp_follows_the_cast_snapshot():
    state = replay([cast(1000, 2), cast(2000, 3)],
                   [buff(0, REQUIESCAT, stack=1), buff(1000, REQUIESCAT, "removebuff")])
    assert [s.enhancement for s in state.spells] == ["Requiescat", "None"]


def test_expired_delayed_blade_and_death_clear_charges():
    state = replay([cast(34000, 5)], [buff(0, REQUIESCAT)], end=35000)
    assert state.spells[0].enhancement == "None"
    assert state.spells[0].cast_kind == "instant"
    assert state.ready[1].expired == 4
    death = {"timestamp": 1000, "type": "death", "targetID": 1}
    state = replay([cast(2000, 1)], [buff(0, REQUIESCAT), buff(0, DIVINE_MIGHT)], life=[death])
    assert state.spells[0].enhancement == "None"
    assert [r.death_lost for r in state.ready] == [1, 4]


def test_initial_stack_grant_echo_and_remaining_are_not_losses():
    state = replay([cast(1000, 2)], [buff(0, REQUIESCAT),
                   buff(0, REQUIESCAT, "applybuffstack", stack=4)])
    assert (state.ready[1].grants, state.ready[1].uses, state.ready[1].remaining) == (4, 1, 3)
    assert state.ready[1].expired == state.ready[1].overwritten == state.ready[1].death_lost == 0


def test_hard_cast_evidence_fake_casts_and_unconfirmed_instant_uses():
    state = replay([cast(1000, 1, type="begincast"), cast(2500, 1), cast(5000, 1),
                    cast(6000, 1, fake=True), cast(7000, 6)], [buff(6500, DIVINE_MIGHT)])
    assert [s.cast_kind for s in state.spells] == ["hard cast", "unconfirmed", "instant"]
    assert state.ready[0].uses == 1


def test_clemency_spends_a_charge_without_creating_a_damage_spell():
    state = replay([cast(1000, 7), cast(2000, 2)], [buff(0, REQUIESCAT, stack=1)])
    assert len(state.spells) == 1 and state.spells[0].enhancement == "None"
    assert state.ready[1].uses == 1


def test_stack_echo_order_and_recorded_partial_grant():
    state = replay([cast(1000, 2), cast(2000, 3)],
                   [buff(0, REQUIESCAT, "applybuffstack", stack=1), buff(0, REQUIESCAT)])
    assert [s.enhancement for s in state.spells] == ["Requiescat", "None"]
    assert (state.ready[1].grants, state.ready[1].uses, state.ready[1].overwritten) == (1, 1, 0)


def test_abandoned_begin_cast_does_not_label_a_later_instant_use():
    state = replay([cast(0, 1, type="begincast", duration=1500), cast(1000, 2),
                    cast(1400, 1), cast(3000, 1)])
    assert [s.cast_kind for s in state.spells] == ["instant", "unconfirmed", "unconfirmed"]
