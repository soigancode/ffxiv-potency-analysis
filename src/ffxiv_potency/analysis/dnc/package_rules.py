"""Recorded DNC grants and witnessed gauge spends for burst packages."""
from ..package_analysis import PackageRules

RULES = PackageRules((), (
    ('Flourishing Starfall', ('Starfall Dance',), 1),
    ('Flourishing Finish', ('Tillana',), 1),
    ('Dance of the Dawn Ready', ('Dance of the Dawn',), 1),
    ('Finishing Move Ready', ('Finishing Move',), 1),
    ('Last Dance Ready', ('Last Dance',), 1),
    ('Threefold Fan Dance', ('Fan Dance III',), 1),
    ('Fourfold Fan Dance', ('Fan Dance IV',), 1),
), witnessed=('Saber Dance', 'Fan Dance', 'Fan Dance II'))


def rules_for_actions(actions):
    import re
    from dataclasses import replace

    generation = re.search(r'Increases Esprit Gauge by (\d+)',
                          ' '.join(actions.get('Tillana', {}).get('description', ())))
    cost = re.search(r'Esprit Gauge Cost: (\d+)',
                    ' '.join(actions.get('Saber Dance', {}).get('description', ())))
    count = int(generation[1]) // int(cost[1]) if generation and cost and int(cost[1]) else 0
    return replace(RULES, earned=(('Tillana', 'Saber Dance', count),) if count else ())
