"""Deterministic parsing of saved FFXIV job-guide HTML."""

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from .models import (
    Action,
    AoeFalloff,
    ComboPotency,
    ConditionalPotency,
    DamageOverTime,
    GaugeGain,
    GaugeScaling,
    Potency,
    PotencyModifier,
    StackPotency,
    Trait,
    TriggeredPotency,
)

_LEVEL_PATTERN = re.compile(r"\bLv\.\s*(\d+)\b", re.IGNORECASE)
_ACTION_DAMAGE_TRAIT_PATTERN = re.compile(
    r"^Increases base action damage(?: and autoturret damage)? by (\d+)%\.$",
    re.IGNORECASE,
)
_DAMAGE_POTENCY_PATTERN = re.compile(
    r"^(?:Delivers|Deals|Rushes)\b.*?\bpotency of\s+(\d+)\b", re.IGNORECASE
)
_FALLOFF_PATTERN = re.compile(
    r"\bpotency of\s+\d+\s+for the first enemy,\s+"
    r"and\s+(\d+)% less for all remaining enemies\b",
    re.IGNORECASE,
)
_STACK_FALLOFF_PATTERN = re.compile(
    r"\bfull damage for the first enemy,\s+and\s+(\d+)% less for all remaining enemies\b",
    re.IGNORECASE,
)
_COMBO_POTENCY_PATTERN = re.compile(r"^Combo Potency:\s*(\d+)\s*$", re.IGNORECASE)
_COMBO_ACTION_PATTERN = re.compile(r"^Combo Action:\s*(.+?)\s*$", re.IGNORECASE)
_DOT_MARKERS = {
    "additional effect: damage over time",
    "additional effect: wind damage over time",
    "additional effect: venom",
    "additional effect: poison",
}
_STANDALONE_POTENCY_PATTERN = re.compile(r"^Potency:\s*(\d+)\s*$", re.IGNORECASE)
_DURATION_PATTERN = re.compile(r"^Duration:\s*(\d+)s\s*$", re.IGNORECASE)
_ACTION_START_PATTERN = re.compile(r'<tr\s+id=["\']pve_action__\d+["\']', re.IGNORECASE)
_MCH_PET_ATTACK_PATTERN = re.compile(
    r"attacks using (.+?), dealing damage with a potency of\s+(\d+)\b", re.IGNORECASE
)
_NAMED_POTENCY_PATTERN = re.compile(r"^(.+?) Potency:\s*(\d+)\s*$", re.IGNORECASE)
_MCH_GAUGE_MAX_PATTERN = re.compile(
    r"^Potency increases as (.+?) exceeds required cost at time of deployment, "
    r"up to a maximum of\s+(\d+)\.$",
    re.IGNORECASE,
)
_MCH_GAUGE_ACTION_MAX_PATTERN = re.compile(
    r"^Potency increases up to\s+(\d+) as (.+? Gauge) exceeds minimum cost\.$",
    re.IGNORECASE,
)
_BRD_STACK_POTENCY_PATTERN = re.compile(r"^(\d+) (Repertoire Stacks?|Coda): ([\d,]+)$", re.IGNORECASE)
_BRD_BARRAGE_POTENCY_PATTERN = re.compile(r"^Barrage Potency: (\d+)$", re.IGNORECASE)
_MCH_GAUGE_COST_PATTERN = re.compile(r"^(.+? Gauge) Cost:\s*(\d+)\s*$", re.IGNORECASE)
_MCH_TRIGGER_PATTERN = re.compile(
    r"^Potency is increased by\s+(\d+) for each of your own weaponskills", re.IGNORECASE
)
_MCH_MAX_MCH_STACKS_PATTERN = re.compile(r"^Can be stacked up to\s+(\d+) times\.$", re.IGNORECASE)
_MCH_MODIFIER_PATTERN = re.compile(
    r"^Overheated Effect: Increases the potency of (.+?) by\s+(\d+)\s*$", re.IGNORECASE
)
_MCH_STACKS_PATTERN = re.compile(r"^Grants\s+(\d+) stacks of Overheated", re.IGNORECASE)
_MCH_GENERIC_PET_SCALING_PATTERN = re.compile(
    r"^Potency of .+ actions increases as .+ Gauge exceeds required cost", re.IGNORECASE
)
_TRIGGERS_ACTION_PATTERN = re.compile(r"^Orders .+? to use (.+?)\.$", re.IGNORECASE)
_GAUGE_GAIN_PATTERN = re.compile(
    r"^(Additional Effect|Combo Bonus): Increases (.+? Gauge) by (\d+)$", re.IGNORECASE
)
_MCH_QUEEN_ACTIONS = {"Arm Punch", "Roller Dash", "Pile Bunker", "Crowned Collider"}
_MCH_ROOK_ACTIONS = {"Rook Overload"}


class JobGuideParseError(ValueError):
    """Raised when guide content cannot be interpreted safely."""


@dataclass(frozen=True, slots=True)
class ParseIssue:
    """One action that could not be interpreted from a complete guide."""

    action_name: str
    message: str


@dataclass(frozen=True, slots=True)
class ParseReport:
    """Successful actions and all issues discovered in a guide snapshot."""

    actions: tuple[Action, ...]
    issues: tuple[ParseIssue, ...]
    source_action_count: int


def _lines(cell: Tag) -> tuple[str, ...]:
    return tuple(cell.stripped_strings)


def _first_match(pattern: re.Pattern[str], lines: tuple[str, ...]) -> re.Match[str] | None:
    return next((match for line in lines if (match := pattern.match(line))), None)


def parse_job_traits(html: str) -> list[Trait]:
    """Capture PvE traits and interpret supported base-action damage bonuses."""
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select('tr[id^="trait_action__"]')
    if not rows:
        raise JobGuideParseError("No PvE trait rows found")
    traits: list[Trait] = []
    for row in rows:
        name_cell = row.select_one("td.skill strong")
        level_cell = row.select_one("td.jobclass")
        if name_cell is None or level_cell is None:
            raise JobGuideParseError(f"Incomplete trait row {row.get('id')!r}")
        name = name_cell.get_text(" ", strip=True)
        match = _LEVEL_PATTERN.search(level_cell.get_text(" ", strip=True))
        if match is None:
            raise JobGuideParseError(f"Could not determine level for trait {name!r}")
        content = row.select_one("td.content")
        description = _lines(content) if content is not None else ()
        multiplier = None
        if name.startswith("Increased Action Damage") and description:
            effect = _first_match(_ACTION_DAMAGE_TRAIT_PATTERN, description)
            if effect is None:
                raise JobGuideParseError(f"Unsupported action damage trait wording for {name!r}")
            multiplier = 1 + int(effect.group(1)) / 100
        traits.append(Trait(name, int(match.group(1)), description, multiplier))
    return traits


def _direct_potency(
    action_name: str, description: tuple[str, ...]
) -> tuple[int | None, AoeFalloff | None]:
    damage_line = next(
        (
            line
            for line in description
            if line.casefold().startswith(("delivers", "deals", "rushes"))
        ),
        None,
    )
    base_match = _DAMAGE_POTENCY_PATTERN.search(damage_line or "")
    base = int(base_match.group(1)) if base_match is not None else None
    if base is None:
        named_match = _first_match(_NAMED_POTENCY_PATTERN, description)
        if named_match is not None:
            base = int(named_match.group(2))
    if falloff_match := (
        _FALLOFF_PATTERN.search(damage_line or "")
        or _STACK_FALLOFF_PATTERN.search(" ".join(description))
    ):
        reduction_percent = int(falloff_match.group(1))
        return base, AoeFalloff(additional_target_multiplier=(100 - reduction_percent) / 100)
    if "first enemy" in (damage_line or "").casefold():
        raise JobGuideParseError(f"Unsupported AoE falloff wording for {action_name!r}")
    return base, None


def _combo_potency(action_name: str, description: tuple[str, ...]) -> ComboPotency | None:
    combo_action: str | None = None
    combo_value: int | None = None
    for line in description:
        if match := _COMBO_ACTION_PATTERN.match(line):
            combo_action = match.group(1)
        if match := _COMBO_POTENCY_PATTERN.match(line):
            combo_value = int(match.group(1))

    if (combo_action is None) != (combo_value is None):
        raise JobGuideParseError(f"Incomplete combo potency for {action_name!r}")

    if combo_action is not None and combo_value is not None:
        previous_actions = tuple(
            name.strip() for name in re.split(r"\s+or\s+", combo_action) if name.strip()
        )
        return ComboPotency(potency=combo_value, previous_actions=previous_actions)
    return None


def _damage_over_time(action_name: str, description: tuple[str, ...]) -> DamageOverTime | None:
    dot_markers = [
        index
        for index, line in enumerate(description)
        if line.casefold() in _DOT_MARKERS
        or line.casefold().startswith("delivers damage over time")
    ]
    if len(dot_markers) > 1:
        raise JobGuideParseError(f"Multiple damage-over-time effects for {action_name!r}")
    if not dot_markers:
        return None
    effect_lines = description[dot_markers[0] + 1 :]
    tick_match = _first_match(_STANDALONE_POTENCY_PATTERN, effect_lines)
    duration_match = _first_match(_DURATION_PATTERN, effect_lines)
    if tick_match is None or duration_match is None:
        raise JobGuideParseError(f"Incomplete damage-over-time effect for {action_name!r}")
    return DamageOverTime(
        potency_per_tick=int(tick_match.group(1)),
        duration_seconds=int(duration_match.group(1)),
    )


def _mch_gauge_scaling(description: tuple[str, ...]) -> GaugeScaling | None:
    deployment = _first_match(_MCH_GAUGE_MAX_PATTERN, description)
    action = _first_match(_MCH_GAUGE_ACTION_MAX_PATTERN, description)
    if deployment is None and action is None:
        return None
    if deployment is not None:
        gauge, maximum = deployment.group(1), int(deployment.group(2))
    else:
        assert action is not None
        gauge, maximum = action.group(2), int(action.group(1))
    cost = _first_match(_MCH_GAUGE_COST_PATTERN, description)
    return GaugeScaling(
        gauge=gauge,
        maximum_potency=maximum,
        minimum_cost=int(cost.group(2)) if cost is not None else None,
    )


def _brd_stack_potency(action_name: str, description: tuple[str, ...]) -> StackPotency | None:
    stack_rows = [
        match for line in description if (match := _BRD_STACK_POTENCY_PATTERN.match(line)) is not None
    ]
    if not stack_rows:
        return None
    resource = "Repertoire" if "Repertoire" in stack_rows[0].group(2) else "Coda"
    if len(stack_rows) != 3 or [int(row.group(1)) for row in stack_rows] != [1, 2, 3]:
        raise JobGuideParseError(f"Incomplete stack potency for {action_name!r}")
    return StackPotency(
        resource=resource,
        values=tuple(int(row.group(3).replace(",", "")) for row in stack_rows),
    )


def _brd_barrage_potency(action_name: str, description: tuple[str, ...]) -> int | None:
    barrage_potencies = [
        match for line in description if (match := _BRD_BARRAGE_POTENCY_PATTERN.match(line)) is not None
    ]
    if len(barrage_potencies) > 1:
        raise JobGuideParseError(f"Multiple Barrage potencies for {action_name!r}")
    return int(barrage_potencies[0].group(1)) if barrage_potencies else None


def _mch_triggered_potency(action_name: str, description: tuple[str, ...]) -> TriggeredPotency | None:
    trigger = _first_match(_MCH_TRIGGER_PATTERN, description)
    if trigger is None:
        return None
    stacks = _first_match(_MCH_MAX_MCH_STACKS_PATTERN, description)
    if stacks is None:
        raise JobGuideParseError(f"Incomplete triggered potency for {action_name!r}")
    return TriggeredPotency(
        potency_per_trigger=int(trigger.group(1)),
        maximum_triggers=int(stacks.group(1)),
    )


def _mch_potency_modifier(action_name: str, description: tuple[str, ...]) -> PotencyModifier | None:
    modifier = _first_match(_MCH_MODIFIER_PATTERN, description)
    if modifier is None:
        return None
    stacks = _first_match(_MCH_STACKS_PATTERN, description)
    if stacks is None:
        raise JobGuideParseError(f"Incomplete potency modifier for {action_name!r}")
    return PotencyModifier(
        bonus=int(modifier.group(2)),
        applies_to=modifier.group(1),
        maximum_uses=int(stacks.group(1)),
    )


def _brd_is_non_damage_barrage(action_name: str, description: tuple[str, ...]) -> bool:
    return action_name == "Barrage" and bool(description) and description[0].startswith("Grants Barrage")


def _parse_potency(action_name: str, description: tuple[str, ...]) -> Potency | None:
    if "potency" not in " ".join(description).casefold():
        return None
    if description and description[0].casefold().startswith(("orders ", "deploys ")):
        return None
    if _brd_is_non_damage_barrage(action_name, description):
        # Its buff changes Refulgent Arrow and Shadowbite; Barrage itself deals no damage.
        return None

    base, falloff = _direct_potency(action_name, description)
    combo = _combo_potency(action_name, description)
    damage_over_time = _damage_over_time(action_name, description)
    gauge_scaling = _mch_gauge_scaling(description)
    stack_potency = _brd_stack_potency(action_name, description)
    barrage_potency = _brd_barrage_potency(action_name, description)
    triggered = _mch_triggered_potency(action_name, description)
    modifier = _mch_potency_modifier(action_name, description)

    has_rule = any((base, damage_over_time, triggered, modifier, stack_potency))
    if not has_rule:
        if any(_MCH_GENERIC_PET_SCALING_PATTERN.match(line) for line in description):
            return None
        raise JobGuideParseError(f"Unsupported potency wording for {action_name!r}")

    return Potency(
        base=base,
        combo=combo,
        falloff=falloff,
        damage_over_time=damage_over_time,
        gauge_scaling=gauge_scaling,
        triggered=triggered,
        modifier=modifier,
        stack_potency=stack_potency,
        conditional_potencies=(ConditionalPotency("Barrage", barrage_potency),)
        if barrage_potency is not None else (),
    )


def _parse_relationships(
    action_name: str, description: tuple[str, ...]
) -> tuple[str | None, str | None]:
    triggers_action = next(
        (match.group(1) for line in description if (match := _TRIGGERS_ACTION_PATTERN.match(line))),
        None,
    )
    return triggers_action, _mch_deployed_actor(action_name)


def _mch_deployed_actor(action_name: str) -> str | None:
    return action_name if action_name in {"Rook Autoturret", "Automaton Queen"} else None


def _mch_source_actor(action_name: str) -> str | None:
    if action_name in _MCH_QUEEN_ACTIONS:
        return "Automaton Queen"
    if action_name in _MCH_ROOK_ACTIONS:
        return "Rook Autoturret"
    return None


def _parse_gauge_gains(description: tuple[str, ...]) -> tuple[GaugeGain, ...]:
    gains = []
    for line in description:
        match = _GAUGE_GAIN_PATTERN.match(line)
        if match is not None:
            gains.append(
                GaugeGain(
                    gauge=match.group(2),
                    amount=int(match.group(3)),
                    requires_combo=match.group(1).lower() == "combo bonus",
                )
            )
    return tuple(gains)


def _parse_action_container(container: Tag, row_id: str) -> Action:
    name_cell = container.find("td", class_="skill")
    level_cell = container.find("td", class_="jobclass")
    type_cell = container.find("td", class_="classification")
    content_cell = container.find("td", class_="content")
    if not all(isinstance(cell, Tag) for cell in (name_cell, level_cell, type_cell, content_cell)):
        raise JobGuideParseError(f"Action row {row_id!r} is missing required cells")

    assert isinstance(name_cell, Tag)
    assert isinstance(level_cell, Tag)
    assert isinstance(type_cell, Tag)
    assert isinstance(content_cell, Tag)

    strong = name_cell.find("strong")
    if strong is None:
        raise JobGuideParseError("Action row has no action name")
    name = strong.get_text(" ", strip=True)
    level_text = level_cell.get_text(" ", strip=True)
    level_match = _LEVEL_PATTERN.search(level_text)
    if level_match is None:
        raise JobGuideParseError(f"Could not determine level for {name!r}: {level_text!r}")

    description = _lines(content_cell)
    triggers_action, deploys_actor = _parse_relationships(name, description)

    return Action(
        name=name,
        level=int(level_match.group(1)),
        action_type=type_cell.get_text(" ", strip=True),
        potency=_parse_potency(name, description),
        description=description,
        triggers_action=triggers_action,
        deploys_actor=deploys_actor,
        source_actor=_mch_source_actor(name),
        gauge_gains=_parse_gauge_gains(description),
    )


def _mch_derive_volley_fire(actions: list[Action]) -> Action | None:
    if any(action.name == "Volley Fire" for action in actions):
        return None
    deployment = next((action for action in actions if action.name == "Rook Autoturret"), None)
    if deployment is None:
        return None

    attack_match = next(
        (match for line in deployment.description if (match := _MCH_PET_ATTACK_PATTERN.search(line))),
        None,
    )
    maximum_match = next(
        (match for line in deployment.description if (match := _MCH_GAUGE_MAX_PATTERN.match(line))),
        None,
    )
    cost_match = next(
        (match for line in deployment.description if (match := _MCH_GAUGE_COST_PATTERN.match(line))),
        None,
    )
    if attack_match is None or maximum_match is None:
        raise JobGuideParseError("Could not derive Volley Fire from 'Rook Autoturret'")

    relevant_description = tuple(
        line
        for line in deployment.description
        if _MCH_PET_ATTACK_PATTERN.search(line) or _MCH_GAUGE_MAX_PATTERN.match(line)
    )
    return Action(
        name=attack_match.group(1),
        level=deployment.level,
        action_type="Pet Action",
        potency=Potency(
            base=int(attack_match.group(2)),
            gauge_scaling=GaugeScaling(
                gauge=maximum_match.group(1),
                maximum_potency=int(maximum_match.group(2)),
                minimum_cost=int(cost_match.group(2)) if cost_match is not None else None,
            ),
        ),
        description=relevant_description,
        source_actor="Rook Autoturret",
        derived_from="Rook Autoturret",
    )


def _action_blocks(html: str) -> list[str]:
    starts = list(_ACTION_START_PATTERN.finditer(html))
    return [
        html[match.start() : starts[index + 1].start() if index + 1 < len(starts) else len(html)]
        for index, match in enumerate(starts)
    ]


def _action_name(container: Tag) -> str:
    strong = container.select_one("td.skill strong")
    return strong.get_text(" ", strip=True) if strong is not None else "<unknown>"


def inspect_job_actions(html: str) -> ParseReport:
    """Parse every action possible and collect every unsupported action."""

    actions: list[Action] = []
    issues: list[ParseIssue] = []
    blocks = _action_blocks(html)
    if not blocks:
        raise JobGuideParseError("No job-action rows found")

    for block in blocks:
        container = BeautifulSoup(block, "html.parser")
        row = container.select_one('tr[id^="pve_action__"]')
        row_id = row.get("id", "<unknown>") if row is not None else "<unknown>"
        name = _action_name(row) if row is not None else "<unknown>"
        try:
            if row is None:
                raise JobGuideParseError("Action block has no PvE action row")
            actions.append(_parse_action_container(row, str(row_id)))
        except JobGuideParseError as exc:
            issues.append(ParseIssue(action_name=name, message=str(exc)))

    try:
        volley_fire = _mch_derive_volley_fire(actions)
        if volley_fire is not None:
            actions.append(volley_fire)
    except JobGuideParseError as exc:
        issues.append(ParseIssue(action_name="Volley Fire", message=str(exc)))

    return ParseReport(
        actions=tuple(actions),
        issues=tuple(issues),
        source_action_count=len(blocks),
    )


def parse_job_actions(html: str) -> list[Action]:
    """Parse supported rows marked as job actions.

    The selector mirrors the IDs used by the live PvE action table. Unsupported
    potency wording raises an error instead of being silently approximated.
    """

    report = inspect_job_actions(html)
    if report.issues:
        details = "; ".join(f"{issue.action_name}: {issue.message}" for issue in report.issues)
        raise JobGuideParseError(f"Could not parse all job actions: {details}")
    return list(report.actions)
