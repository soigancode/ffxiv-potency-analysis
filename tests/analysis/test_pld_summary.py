"""Ranged chains, opening exemptions and delayed burst attribution."""

from test_pld_state import buff

from ffxiv_potency.analysis.pld.state import replay_spells
from ffxiv_potency.analysis.pld.summary import PldDotSummary, summarize_pld

NAMES = {1: "Holy Spirit", 2: "Fast Blade", 3: "Shield Lob", 4: "Atonement",
         5: "Imperator", 6: "Confiteor", 7: "Blade of Faith", 8: "Blade of Truth",
         9: "Blade of Valor", 10: "Blade of Honor"}
ACTIONS = {n: {"type": "Spell" if n in {"Holy Spirit", "Confiteor"} or n.startswith("Blade of")
              else "Weaponskill", "potency": {"base": 100}} for n in NAMES.values()}
ACTIONS["Imperator"]["type"] = ACTIONS["Blade of Honor"]["type"] = "Ability"


def cast(time, ability, **fields):
    return {"type": "cast", "timestamp": time, "sourceID": 1,
            "abilityGameID": ability, "packetID": time, **fields}


def summary(casts, buffs=(), end=60000, landed=()):
    state = replay_spells(casts, list(buffs), [], [], NAMES, 1, 0, end)
    return summarize_pld(casts, buffs, [], [], NAMES, ACTIONS, 1, 0, end, state,
                         landed, PldDotSummary(0, 0, 0, 0))


def test_chain_begins_at_first_ranged_gcd_and_shows_every_gap():
    casts = [cast(t, a) for t, a in [(0, 2), (2500, 3), (3000, 5), (3500, 1),
                                    (5000, 1), (7500, 3), (10000, 4)]]
    casts[3]["type"] = "begincast"
    result = summary(casts)
    assert result.holy_spirit_casts == ((5.0, "hard cast"),)
    c = result.ranged[0]
    assert c.seconds == 2.5
    assert c.actions == ("Shield Lob", "Holy Spirit", "Shield Lob")
    assert c.gaps == (2.5, 2.5)
    assert (c.previous, c.previous_gap, c.following, c.following_gap) == ("Fast Blade", 2.5, "Atonement", 2.5)


def test_opening_holy_spirit_and_instant_and_unconfirmed_uses_are_excluded():
    casts = [cast(-1500, 1, type="begincast"), cast(0, 1), cast(2500, 2),
             cast(5000, 1), cast(7500, 1), cast(10000, 1)]
    result = summary(casts, [buff(4000, 1002673)])
    assert result.ranged == ()


def test_delayed_unenhanced_valor_keeps_burst_attribution_and_landed_potency():
    casts = [cast(t, a) for t, a in [(0, 5), (2500, 6), (5000, 7), (7500, 8),
                                    (34000, 9), (55000, 10)]]
    r = summary(casts, [buff(0, 1001368)], landed=[((34000, 9), "Blade of Valor", 500)])
    assert len(r.bursts) == 1
    b = r.bursts[0]
    assert [f.casts for f in b.follow_ups] == [1, 1, 1, 1, 1]
    assert b.follow_ups[3].potency == 500
    assert "Blade of Valor: unenhanced" in b.notes
    assert "Blade of Valor: delayed 34.00s after burst start" in b.notes
    assert "Blade of Honor: delayed 55.00s after burst start" in b.notes
