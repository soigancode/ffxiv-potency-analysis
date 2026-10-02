"""Separate phase HP closures from target deaths using encounter evidence."""

from collections import defaultdict


def phase_lock_windows(overkills, casts, damage, actors, targetability, fight_end, encounter_id=None):
    windows = defaultdict(list)
    times_by_target = defaultdict(list)
    for event in overkills:
        target = event.get("targetID")
        time = event.get("timestamp")
        if (
            isinstance(target, int)
            and isinstance(time, (int, float))
            and event.get("overkill", 0) > 0
        ):
            times_by_target[target].append(time)
    for target, times in times_by_target.items():
        if actors.get(target, {}).get("subType") != "Boss":
            continue
        clusters = []
        for time in sorted(set(times)):
            if not clusters or time - clusters[-1][-1] > 5000:
                clusters.append([])
            clusters[-1].append(time)
        for cluster in clusters:
            first, last = cluster[0], cluster[-1]
            disappear = min(
                (
                    e["timestamp"]
                    for e in targetability
                    if e.get("sourceID") == target
                    and e.get("targetable") == 0
                    and last <= e.get("timestamp", -1) < fight_end
                ),
                default=last + 4000,
            )
            if any(
                e.get("type") == "damage"
                and e.get("targetID") == target
                and last < e.get("timestamp", -1) <= disappear
                and e.get("amount", 0) > 1
                and not e.get("overkill")
                for e in damage
            ):
                disappear = last + 4000
            later_casts = [
                e
                for e in casts
                if e.get("targetID") == target
                and first + 1500 <= e.get("timestamp", -1) <= disappear
            ]
            repeated = last - first >= 2000 or (
                len(cluster) >= 3 and last - first >= 1000 and later_casts
            )
            # Some paired bosses have no further DoT ticks. Continued action
            # resolutions without landed damage, followed by a delayed phase
            # disappearance, still support a closure rather than an add death.
            delayed_phase = (
                disappear < fight_end - 5000
                and disappear - first >= 3000
                and len(later_casts) >= 2
                and any(
                    e.get("sourceID") == target
                    and e.get("targetable") == 0
                    and e.get("timestamp") == disappear
                    for e in targetability
                )
                and not any(
                    e.get("type") == "damage"
                    and e.get("targetID") == target
                    and first < e.get("timestamp", -1) <= disappear
                    and e.get("amount", 0) > 1
                    and not e.get("overkill")
                    for e in damage
                )
            )
            if repeated or delayed_phase:
                # Include actions already resolving when the HP threshold was
                # reached, using the same 2.5s resolution allowance as ghosts.
                windows[target].append((first - 2500, disappear))
    if encounter_id == 1085:
        # Chaos and Exdeath close one paired phase. The first boss reaching its
        # threshold starts the closure, even while the other still logs damage.
        # Restrict this to their real boss actors and require both lethal hits
        # and disappearances, so ordinary Kefka untargetability is unaffected.
        pair = {
            a.get("gameID"): actor_id for actor_id, a in actors.items()
            if a.get("subType") == "Boss" and a.get("gameID") in (19508, 19509)
        }
        if len(pair) == 2:
            closures = {}
            for target in pair.values():
                for hit in overkills:
                    time = hit.get("timestamp")
                    if hit.get("targetID") != target or not isinstance(time, (int, float)):
                        continue
                    if hit.get("overkill", 0) <= 0:
                        continue
                    end = next((
                        e["timestamp"] for e in targetability
                        if e.get("sourceID") == target and e.get("targetable") == 0
                        and time <= e.get("timestamp", -1) <= time + 2000
                        and e["timestamp"] < fight_end - 5000
                    ), None)
                    if end is not None:
                        closures[target] = (time, end)
                        break
            if len(closures) == 2:
                first = min(time for time, _ in closures.values())
                last = max(end for _, end in closures.values())
                if last - first <= 30000:
                    for target, (_, end) in closures.items():
                        windows[target].append((first - 2500, end))
    return windows
