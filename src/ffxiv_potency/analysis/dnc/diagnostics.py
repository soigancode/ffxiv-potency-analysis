"""DNC rules for shared execution reporting."""

from ..diagnostic_types import AlignmentRule, FollowUpRule

COOLDOWNS = ("Devilment", "Flourish", "Technical Step")
REDUCTIONS = {}
FIXED = ("Cascade", "Windmill", "Reverse Cascade", "Fountainfall", "Rising Windmill", "Bloodshower", "Saber Dance", "Last Dance", "Starfall Dance", "Tillana", "Dance of the Dawn", "Fan Dance", "Fan Dance II", "Fan Dance III", "Fan Dance IV")
BURST_ACTIONS = ("Saber Dance", "Dance of the Dawn", "Starfall Dance", "Tillana", "Last Dance", "Fan Dance III", "Fan Dance IV", "Finishing Move")
ALIGNMENT = (
    AlignmentRule("Technical Finish", "Technical Finish", BURST_ACTIONS, strength=1.05),
    AlignmentRule("Devilment", "Devilment", BURST_ACTIONS, "rate", strength=.20),
)
FOLLOW_UPS = (
    FollowUpRule("Last Dance", "Last Dance Ready", ("Last Dance",)),
    FollowUpRule("Tillana", "Flourishing Finish", ("Tillana",)),
    FollowUpRule("Starfall Dance", "Flourishing Starfall", ("Starfall Dance",), 20000),
    FollowUpRule("Dance of the Dawn", "Dance of the Dawn Ready", ("Dance of the Dawn",)),
)
