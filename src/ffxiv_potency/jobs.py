"""Combat-job abbreviations and FF Logs names, independent of analyser support."""

JOB_NAMES = {
    "pld": "Paladin", "war": "Warrior", "drk": "DarkKnight", "gnb": "Gunbreaker",
    "whm": "WhiteMage", "sch": "Scholar", "ast": "Astrologian", "sge": "Sage",
    "mnk": "Monk", "drg": "Dragoon", "nin": "Ninja", "sam": "Samurai",
    "rpr": "Reaper", "vpr": "Viper", "brd": "Bard", "mch": "Machinist",
    "dnc": "Dancer", "blm": "BlackMage", "smn": "Summoner", "rdm": "RedMage",
    "pct": "Pictomancer",
}
JOB_CODES = {name.casefold(): code for code, name in JOB_NAMES.items()}


def job_code(job: str) -> str:
    normalized = job.casefold().replace(" ", "")
    return JOB_CODES.get(normalized, normalized)


def job_name(job: str) -> str:
    return JOB_NAMES.get(job_code(job), job.capitalize())
