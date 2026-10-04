"""WAR rules for shared execution reporting."""

from ..diagnostic_types import FollowUpRule

COOLDOWNS = ("Inner Release", "Infuriate", "Upheaval", "Onslaught")
COOLDOWN_GROUPS = {"Upheaval": ("Upheaval", "Orogeny")}
REDUCTIONS = {"Infuriate": (5000, ("Fell Cleave", "Decimate", "Inner Chaos", "Chaotic Cyclone"))}
FIXED = ("Heavy Swing", "Overpower", "Tomahawk", "Fell Cleave", "Decimate")
ALIGNMENT = ()
FOLLOW_UPS = (
    FollowUpRule("Inner Release spenders", "Inner Release", ("Fell Cleave", "Decimate"), 15000, 3),
    FollowUpRule("Primal Rend", "Primal Rend Ready", ("Primal Rend",)),
    FollowUpRule("Primal Ruination", "Primal Ruination Ready", ("Primal Ruination",), 20000),
    FollowUpRule("Primal Wrath", "Wrathful", ("Primal Wrath",)),
    FollowUpRule("Nascent Chaos", "Nascent Chaos", ("Inner Chaos", "Chaotic Cyclone")),
)
