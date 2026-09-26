"""FF Logs URL parsing, API access, and fixture downloads."""

from .analyze import AnalysisError, analyze_saved_fight
from .client import FFLogsClient, FFLogsError
from .download import DownloadResult, download_report_events, refresh_report_rankings
from .models import (
    ActionSummary,
    AnalysisResult,
    AutoAttackSummary,
    HitOutcomeSummary,
    PetDeploymentSummary,
    PotionSummary,
    PotionWindow,
    WildfireSummary,
)
from .rankings import top_ranked_sources
from .reference import ReportReference, parse_report_url

__all__ = [
    "ActionSummary",
    "AnalysisError",
    "AnalysisResult",
    "AutoAttackSummary",
    "DownloadResult",
    "FFLogsClient",
    "FFLogsError",
    "HitOutcomeSummary",
    "PetDeploymentSummary",
    "PotionSummary",
    "PotionWindow",
    "ReportReference",
    "WildfireSummary",
    "analyze_saved_fight",
    "download_report_events",
    "parse_report_url",
    "refresh_report_rankings",
    "top_ranked_sources",
]
