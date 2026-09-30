import pytest

from ffxiv_potency.fflogs import ReportReference, parse_report_url
from ffxiv_potency.fflogs.reference import (
    ReportSelection,
    parse_report_selection,
    parse_report_selection_url,
    report_code_from_directory,
    report_directory_name,
)


def test_parses_copied_fflogs_url() -> None:
    reference = parse_report_url(
        "https://www.fflogs.com/reports/zYLAW7KTBk8P4XxG?fight=9&type=damage-done&source=18"
    )

    assert reference == ReportReference(
        report_code="zYLAW7KTBk8P4XxG",
        fight_id=9,
        source_id=18,
    )


def test_parses_anonymous_report_link_with_selected_source() -> None:
    assert parse_report_url(
        "https://www.fflogs.com/reports/a:DNaXrgHGZ8PbCkfL?fight=22&source=4"
    ) == ReportReference("a:DNaXrgHGZ8PbCkfL", 22, 4)
    assert report_directory_name("a:DNaXrgHGZ8PbCkfL") == "a-DNaXrgHGZ8PbCkfL"
    assert report_code_from_directory("a-DNaXrgHGZ8PbCkfL") == "a:DNaXrgHGZ8PbCkfL"


def test_parses_unselected_and_partially_selected_report_urls() -> None:
    assert parse_report_selection_url(
        "https://www.fflogs.com/reports/XhcqCfrJzNgZdQxP"
    ) == ReportSelection("XhcqCfrJzNgZdQxP", None, None)
    assert parse_report_selection_url(
        "https://www.fflogs.com/reports/abc123?fight=9"
    ) == ReportSelection("abc123", 9, None)
    assert parse_report_selection_url(
        "https://www.fflogs.com/reports/abc123?source=18"
    ) == ReportSelection("abc123", None, 18)


@pytest.mark.parametrize(
    "url, message",
    [
        ("zYLAW7KTBk8P4XxG", "expected an https"),
        ("https://example.com/reports/code?fight=9&source=18", "expected an https"),
        ("https://www.fflogs.com/character/id/1?fight=9&source=18", "must point to"),
        ("https://www.fflogs.com/reports/code?source=18", "'fight' parameter"),
        ("https://www.fflogs.com/reports/code?fight=9", "'source' parameter"),
        ("https://www.fflogs.com/reports/code?fight=last&source=18", "must be an integer"),
        ("https://www.fflogs.com/reports/a:code:bad?fight=9&source=18", "must point to"),
    ],
)
def test_rejects_incomplete_or_unsupported_reference(url: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_report_url(url)


@pytest.mark.parametrize("code", ["XhcqCfrJzNgZdQxP", "a:DNaXrgHGZ8PbCkfL"])
def test_parses_bare_report_id(code: str) -> None:
    assert parse_report_selection(code) == ReportSelection(code, None, None)
