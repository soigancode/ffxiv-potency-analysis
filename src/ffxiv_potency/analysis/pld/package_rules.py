"""PLD cooldowns and deterministic spell follow-ups for burst packages."""
from ..package_analysis import PackageRules
from ..targetability import package_targetable_time, targetable_intervals

RULES = PackageRules(
    ('Imperator', 'Circle of Scorn', 'Expiacion', 'Intervene'),
    (('Goring Blade Ready', ('Goring Blade',), 1),
     ('Confiteor Ready', ('Confiteor',), 1),
     ('Blade of Honor Ready', ('Blade of Honor',), 1)),
    status_ids=(('Goring Blade Ready', 1003847), ('Confiteor Ready', 1003019),
                ('Blade of Honor Ready', 1003831)),
    chains=(('Confiteor', 'Blade of Faith', 'Blade of Truth', 'Blade of Valor'),),
    periodic=('Circle of Scorn',),
    earned=(('Blade of Valor', 'Blade of Honor', 1),),
)


def scorn_target_windows(damage, encounter_damage, names, source, actors, updates,
                         overkills, locks, targetable, start, end):
    """Keep each Scorn target's damageability boundary separate for expected ticks."""
    targets = {(e.get('targetID'), e.get('targetInstance', 1)) for e in damage
               if e.get('sourceID') == source and names.get(e.get('abilityGameID')) == 'Circle of Scorn'}
    windows = {}
    for target in targets:
        actor_id, instance = target
        if actor_id is None:
            continue
        actor = actors.get(actor_id)
        if actor is None:
            continue
        hits = [e for e in encounter_damage if e.get('targetID') == actor_id
                and e.get('targetInstance', 1) == instance]
        transitions = [e for e in updates if e.get('sourceID') == actor_id
                       and e.get('sourceInstance', 1) == instance]
        endings = [e for e in overkills if e.get('targetID') == actor_id
                   and e.get('targetInstance', 1) == instance]
        if locks:
            individual = package_targetable_time(targetable, {actor_id: actor},
                hits, transitions, endings, locks, start, end)
            windows[target] = individual.intervals
        else:
            windows[target] = targetable_intervals(transitions, hits, endings,
                                                   {actor_id: actor}, start, end)
    return windows
