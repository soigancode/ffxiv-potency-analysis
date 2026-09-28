"""Errors raised when saved FF Logs data cannot be analyzed safely."""


class AnalysisError(ValueError):
    """A saved log or its reference data is incomplete or inconsistent."""
