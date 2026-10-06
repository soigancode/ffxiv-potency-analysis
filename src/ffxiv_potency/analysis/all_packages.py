"""Select job-specific burst packages for the shared report layout."""
from importlib import import_module
from statistics import median

from .diagnostics import buff_intervals, rules_for
from .package_analysis import summarize_packages
from .pld.buffs import FIGHT_OR_FLIGHT

JOBS = {'paladin': 'pld', 'bard': 'brd', 'machinist': 'mch', 'dancer': 'dnc'}


def summarize_job_packages(job, result, casts, damage, buffs, life, names, actions,
                           source, start, end, targetable, damage_windows, estimates=None,
                           spell_potencies=None, primary_hits=None, potion_buff_id=None, combatants=(),
                           periodic_target_windows=None, potency_rows=(), potion_multiplier=None):
    if job not in JOBS:
        return ()
    module = import_module(f'.{JOBS[job]}.package_rules', __package__)
    rules = module.rules_for_actions(actions) if hasattr(module, 'rules_for_actions') else module.RULES
    groups = []
    if job == 'paladin':
        groups.append(('Fight or Flight', tuple((a, b) for a, b, _ in damage_windows.get(FIGHT_OR_FLIGHT, ()))))
    elif job != 'machinist':
        for rule in rules_for(job).ALIGNMENT:
            groups.append((rule.name, tuple((a, b) for a, b, _ in
                buff_intervals(rule, buffs, names, source, end, damage_windows))))
    if job == 'machinist':
        groups.append(('Wildfire', tuple((start + w.applied_seconds * 1000,
            min(end, start + w.applied_seconds * 1000 + 10000)) for w in result.mch_wildfires)))
    if result.potion is not None:
        groups.append(('Potion', tuple((start + w.start_seconds * 1000,
            min(end, start + w.end_seconds * 1000)) for w in result.potion.windows
            if w.start_seconds is not None and w.end_seconds is not None)))
    resource_model = None
    if job == 'paladin':
        from .pld.package_resources import requiescat_model
        resource_model = requiescat_model(casts, buffs, life, combatants, names, actions, source, start, end)
    output = []
    package_cache = {}
    for label, windows in groups:
        packages = []
        for begin, finish in windows:
            if (begin, finish) in package_cache:
                packages.extend(package_cache[begin, finish])
                continue
            values = {}
            enhancements = {}
            packet_values = {}
            uncertain_values = set()
            if job == 'paladin':
                for event in casts:
                    key = event.get('packetID'), event.get('abilityGameID')
                    if spell_potencies is not None and key in spell_potencies:
                        name = names.get(event.get('abilityGameID'))
                        packet_values[key] = (spell_potencies[key] if spell_potencies[key] is not None
                            else (actions.get(name, {}).get('potency') or {}).get('base', 0))
                for name, action in actions.items():
                    enhanced = (action.get('potency') or {}).get('conditional_potencies', {}).get('Requiescat')
                    if enhanced is not None:
                        enhancements[name] = tuple((e['timestamp'], min(
                            e['timestamp'] + e.get('duration', 0),
                            min((r['timestamp'] + 1 for r in buffs
                                if r.get('abilityGameID') == 1001368 and r.get('targetID') == source
                                and r.get('type') == 'removebuff' and r['timestamp'] >= e['timestamp']), default=end)), enhanced)
                            for e in buffs if e.get('abilityGameID') == 1001368
                            and e.get('targetID') == source and e.get('type') in {'applybuff', 'refreshbuff'})
            if job == 'bard':
                for name in ('Apex Arrow', 'Pitch Perfect', 'Radiant Encore'):
                    evidence = [estimates[id(e)][0] for e in damage if estimates and id(e) in estimates
                        and names.get(e.get('abilityGameID')) == name and begin <= e['timestamp'] < finish]
                    if evidence:
                        values[name] = median(evidence)
                    for e in damage:
                        if estimates and id(e) in estimates and names.get(e.get('abilityGameID')) == name:
                            key = e.get('packetID'), e.get('abilityGameID')
                            packet_values[key] = max(packet_values.get(key, 0), estimates[id(e)][0])
                            if estimates[id(e)][1] and begin <= e['timestamp'] < finish:
                                uncertain_values.add(name)
                previous = [f for f in result.brd_finales if start + f.timestamp_seconds * 1000 < finish]
                if previous:
                    spec = actions.get('Radiant Encore', {}).get('potency') or {}
                    values['Radiant Encore'] = spec.get('stack_potency', {}).get('by_count', {}).get(str(previous[-1].coda), 0)
            package = summarize_packages(casts, damage, buffs, life, names, actions,
                source, start, end, ((begin, finish),), targetable, rules, values=values, enhancements=enhancements,
                packet_values=packet_values, uncertain_values=uncertain_values, primary_hits=primary_hits,
                resource_model=resource_model, periodic_target_windows=periodic_target_windows)
            package_cache[begin, finish] = package
            packages.extend(package)
        if packages and job == 'paladin' and label == 'Potion' and potion_buff_id is not None:
            from .pld.potion_alignment import annotate_potion_alignment
            packages = [annotate_potion_alignment(w, casts, damage, names, source, start, end,
                        damage_windows.get(FIGHT_OR_FLIGHT, ()), potion_buff_id, buffs, life,
                        potency_rows, potion_multiplier)
                        for w in packages]
        if packages:
            output.append((label, tuple(packages)))
    return tuple(output)
