"""Recorded MCH tools and grants for burst and potion packages."""
from ..package_analysis import PackageRules

RULES = PackageRules(
    ('Drill', 'Air Anchor', 'Chain Saw', 'Double Check'),
    (('Excavator Ready', ('Excavator',), 1),
     ('Full Metal Machinist', ('Full Metal Field',), 1),
     ('Overheated', ('Blazing Shot', 'Auto Crossbow'), 5)),
)
