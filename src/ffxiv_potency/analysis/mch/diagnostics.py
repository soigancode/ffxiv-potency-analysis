"""MCH rules for shared execution reporting."""

from ..diagnostic_types import AlignmentRule, FollowUpRule

COOLDOWNS = ("Reassemble", "Drill", "Air Anchor", "Chain Saw", "Wildfire", "Double Check", "Checkmate")
REDUCTIONS = {name: (15000, ("Blazing Shot",)) for name in ("Double Check", "Checkmate")}
FIXED = ("Heated Split Shot", "Split Shot", "Drill", "Air Anchor", "Chain Saw", "Excavator", "Blazing Shot", "Scattergun", "Auto Crossbow")
ALIGNMENT = (AlignmentRule("Reassemble", "Reassembled", ("Drill", "Air Anchor", "Chain Saw", "Excavator"), "guaranteed", duration_ms=5000),)
FOLLOW_UPS = (
    FollowUpRule("Excavator", "Excavator Ready", ("Excavator",)),
    FollowUpRule("Full Metal Field", "Full Metal Machinist", ("Full Metal Field",)),
    FollowUpRule("Hypercharge GCDs", "Overheated", ("Blazing Shot", "Auto Crossbow"), 10000, 5),
)


def sequence_context(result, life, source, start, end, targetable):
    """Explain incomplete Wildfire windows and missing Queen finishers."""
    from ..diagnostic_types import FollowUpContext
    from ..diagnostics import omission_reason

    rows = []
    for window in result.mch_wildfires:
        if window.landed_weaponskills >= 6:
            continue
        begin = start + window.applied_seconds * 1000
        deadline = begin + 10000
        progress = max([begin, *(start + t * 1000 for t in window.contributing_times)])
        reason = ("detonated early" if window.detonated_early else
                  omission_reason(progress, deadline, end, life, source, targetable))
        rows.append(FollowUpContext(window.applied_seconds,
            (f"Wildfire: {window.landed_weaponskills}/6 landed GCDs",), "incomplete", reason))
    for index, queen in enumerate(result.pet_deployments):
        if not queen.mch_missing_finishers:
            continue
        begin = start + queen.timestamp_seconds * 1000
        # A pet can outlive its owner. Use established finisher classifications
        # instead of attributing a missing pet attack to the player's death.
        next_deployment = (result.pet_deployments[index + 1].timestamp_seconds
                           if index + 1 < len(result.pet_deployments) else (end - start) / 1000)
        recorded = {reason for name, losses in result.ghosted_ending_times
                    if name in queen.mch_missing_finishers
                    for seconds, reason in losses
                    if queen.timestamp_seconds <= seconds < next_deployment}
        reason = next(iter(recorded)) if len(recorded) == 1 else "reason unconfirmed"
        if reason == "reason unconfirmed":
            reason = omission_reason(begin, begin + 12000, end, [], source, targetable)
            reason = reason.replace("during sequence", "during deployment")
        if queen.mch_prepull:
            reason = "deployment began before saved interval"
        elif queen.mch_overdrive_seconds is not None and reason == "reason unconfirmed":
            reason = "Queen Overdrive recorded; reason unconfirmed"
        rows.append(FollowUpContext(queen.timestamp_seconds, queen.mch_missing_finishers,
                                   "no landed hit", reason))
    return tuple(rows)
