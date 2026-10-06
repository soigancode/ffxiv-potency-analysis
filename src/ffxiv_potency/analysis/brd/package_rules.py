"""Recorded BRD resources for personal burst and potion packages."""
import re
from dataclasses import replace

from ..package_analysis import PackageRules

RULES = PackageRules(
    ('Empyreal Arrow', 'Sidewinder', 'Barrage'),
    (('Barrage', ('Refulgent Arrow',), 1),
     ('Resonant Arrow Ready', ('Resonant Arrow',), 1),
     ('Blast Arrow Ready', ('Blast Arrow',), 1),
     ('Radiant Encore Ready', ('Radiant Encore',), 1)),
    witnessed=('Apex Arrow', 'Pitch Perfect'),
)


def rules_for_actions(actions):
    description = ' '.join(actions.get('Barrage', {}).get('description', ()))
    match = re.search(r'Refulgent Arrow will strike .*? (\w+) times', description)
    words = {'two': 2, 'three': 3, 'four': 4, 'five': 5}
    count = (int(match[1]) if match and match[1].isdigit() else
             words.get(match[1], 1) if match else 1)
    return replace(RULES, multipliers=(('Barrage', 'Refulgent Arrow', count),))
