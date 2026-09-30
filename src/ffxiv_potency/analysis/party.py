"""Determine the main-stat party bonus from fight-specific participants."""

from typing import Any

from .errors import AnalysisError

_ROLES = {
    **dict.fromkeys(("Paladin", "Warrior", "DarkKnight", "Gunbreaker",
                     "Gladiator", "Marauder"), "tank"),
    **dict.fromkeys(("WhiteMage", "Scholar", "Astrologian", "Sage",
                     "Conjurer"), "healer"),
    **dict.fromkeys(("Monk", "Dragoon", "Ninja", "Samurai", "Reaper", "Viper",
                     "Pugilist", "Lancer", "Rogue"), "melee"),
    **dict.fromkeys(("Bard", "Machinist", "Dancer", "Archer"), "physical ranged"),
    **dict.fromkeys(("BlackMage", "Summoner", "RedMage", "Pictomancer",
                     "Thaumaturge", "Arcanist", "BlueMage"), "magical ranged"),
}


def party_bonus_percent(
    fight: dict[str, Any], master_data: dict[str, Any], source_id: int | None,
) -> int | None:
    """Return the unique-role count, or None for old downloads without a roster."""
    ids = fight.get("friendlyPlayers")
    if ids is None:
        return None
    if (not isinstance(ids, list) or not ids or source_id not in ids
            or any(not isinstance(actor_id, int) for actor_id in ids)
            or len(ids) != len(set(ids))):
        raise AnalysisError("fight has incomplete or invalid friendlyPlayers data")
    actors = master_data.get("actors")
    if not isinstance(actors, list):
        raise AnalysisError("master data is missing player jobs for party bonus")
    by_id = {actor.get("id"): actor for actor in actors
             if isinstance(actor, dict) and actor.get("type") == "Player"}
    roles = set()
    participants = 0
    for actor_id in ids:
        actor = by_id.get(actor_id)
        job = actor.get("subType") if isinstance(actor, dict) else None
        # FF Logs includes one or more synthetic LimitBreak "players" in
        # friendlyPlayers, even though their IDs are absent from CombatantInfo.
        if job == "LimitBreak":
            continue
        role = _ROLES.get(job) if isinstance(job, str) else None
        if role is None:
            raise AnalysisError(
                f"cannot determine the party bonus: player {actor_id} has unknown job {job!r}"
            )
        roles.add(role)
        participants += 1
    if participants == 0:
        raise AnalysisError("fight has no identifiable player jobs for party bonus")
    return len(roles)
