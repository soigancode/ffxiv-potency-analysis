import pytest

from ffxiv_potency.fflogs import ReportReference, parse_report_url


def test_parses_copied_fflogs_url() -> None:
    reference = parse_report_url(
        "https://www.fflogs.com/reports/zYLAW7KTBk8P4XxG?fight=9&type=damage-done&source=18"
    )

    assert reference == ReportReference(
        report_code="zYLAW7KTBk8P4XxG",
        fight_id=9,
        source_id=18,
    )


@pytest.mark.parametrize(
    "url, message",
    [
        ("zYLAW7KTBk8P4XxG", "expected an https"),
        ("https://example.com/reports/code?fight=9&source=18", "expected an https"),
        ("https://www.fflogs.com/character/id/1?fight=9&source=18", "must point to"),
        ("https://www.fflogs.com/reports/code?source=18", "'fight' parameter"),
        ("https://www.fflogs.com/reports/code?fight=9", "'source' parameter"),
        ("https://www.fflogs.com/reports/code?fight=last&source=18", "must be an integer"),
    ],
)
def test_rejects_incomplete_or_unsupported_reference(url: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_report_url(url)
