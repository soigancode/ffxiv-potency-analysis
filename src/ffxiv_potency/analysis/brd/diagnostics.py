"""BRD rules for shared execution reporting."""

from ..diagnostic_types import AlignmentRule, FollowUpRule

COOLDOWNS = ("Raging Strikes", "Battle Voice", "Radiant Finale", "Barrage", "Empyreal Arrow", "Sidewinder")
REDUCTIONS = {}
FIXED = ()
ALIGNMENT = (AlignmentRule("Raging Strikes", "Raging Strikes", ("Apex Arrow", "Blast Arrow", "Radiant Encore", "Pitch Perfect", "Empyreal Arrow", "Sidewinder", "Refulgent Arrow", "Shadowbite", "Caustic Bite", "Stormbite", "Iron Jaws"), strength=1.15),)
FOLLOW_UPS = (FollowUpRule("Radiant Encore", "Radiant Encore Ready", ("Radiant Encore",)),)
