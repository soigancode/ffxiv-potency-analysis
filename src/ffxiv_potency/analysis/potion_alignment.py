"""Potion boundary diagnostics follow damage snapshots rather than hit delays."""

from .events import _has_buff


class PotionAlignment:
    """Recorded direct hits establish coverage, including applications of DoTs.

    Ticks keep their application's snapshot. Ghosts do not lose potion potency.
    Cast timing remains a fallback when damage evidence is unavailable.
    """

    def __init__(self, damage, source, potion_id, begin, finish, rows=(), multiplier=None):
        self.begin, self.finish = begin, finish
        self.available = bool(damage)
        self.hits = {}
        self.covered = set()
        self.unpotted = set()
        for hit in damage:
            if (hit.get('sourceID') != source or hit.get('type') != 'damage'
                    or hit.get('tick') or hit.get('amount', 0) <= 0
                    or hit.get('packetID') is None):
                continue
            key = hit['packetID'], hit.get('abilityGameID')
            self.hits.setdefault(key, []).append(hit)
            if _has_buff(hit, potion_id) and hit['timestamp'] >= begin:
                self.covered.add(key)
            else:
                self.unpotted.add(key)
        self.gains = {}
        if multiplier is not None and multiplier > 1:
            for hit, _, _, potency in rows:
                key = hit.get('packetID'), hit.get('abilityGameID')
                if (hit.get('sourceID') == source and not hit.get('tick')
                        and key in self.unpotted and not _has_buff(hit, potion_id)):
                    self.gains[key] = self.gains.get(key, 0) + potency * (multiplier - 1)

    def inside(self, event, fallback=False):
        key = event.get('packetID'), event.get('abilityGameID')
        if key in self.hits:
            return key in self.covered and key not in self.unpotted
        return fallback or self.begin <= event['timestamp'] < self.finish

    def outside(self, event, fallback=False):
        key = event.get('packetID'), event.get('abilityGameID')
        if self.available and event.get('packetID') is not None:
            return key in self.unpotted
        return not self.inside(event, fallback)

    def side(self, event):
        time = event['timestamp']
        if time < self.begin:
            return 'before'
        if time >= self.finish:
            return 'after'
        # A cast within the recorded bounds can still lack the snapshot.
        # Group that evidence at the closer boundary without a timing tolerance.
        return 'before' if time - self.begin <= self.finish - time else 'after'

    def gain_note(self, events):
        keys = {(e.get('packetID'), e.get('abilityGameID')) for e in events}
        if not keys or not keys <= self.gains.keys():
            return ''
        gain = sum(self.gains[k] for k in keys)
        return f' Estimated potion gain missed: {gain:,.1f} potency (direct hits).'
