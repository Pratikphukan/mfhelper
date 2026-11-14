from pathlib import Path

import pytest

from mfhelper.groww_links import (
    GROWW_MUTUAL_FUNDS_URL,
    GrowwUrlMapError,
    parse_groww_url_map_rows,
    read_groww_url_map,
    validate_groww_url,
)


def test_map_rows_return_valid_urls_keyed_by_amfi_code():
    rows = [
        ["Scheme Name", "AMFI Scheme Code", "Groww URL"],
        ["Fund A Direct Growth", 119788.0, "https://groww.in/mutual-funds/fund-a-direct-growth"],
        ["Gold ETF", "113076", "https://groww.in/etfs/gold-etf"],
    ]

    assert parse_groww_url_map_rows(rows) == {
        "119788": "https://groww.in/mutual-funds/fund-a-direct-growth",
        "113076": "https://groww.in/etfs/gold-etf",
    }


def test_missing_individual_url_is_left_for_general_page_fallback():
    rows = [["Scheme Name", "AMFI Scheme Code", "Groww URL"], ["Fund A", 12345, ""]]
    assert parse_groww_url_map_rows(rows) == {}
    assert GROWW_MUTUAL_FUNDS_URL == "https://groww.in/mutual-funds"


@pytest.mark.parametrize(
    "url",
    [
        "http://groww.in/mutual-funds/fund-a",
        "https://groww.in.evil.example/mutual-funds/fund-a",
        "https://example.com/mutual-funds/fund-a",
        "https://groww.in/stocks/fund-a",
        "https://groww.in/mutual-funds/",
        "https://groww.in/mutual-funds/fund-a?redirect=example.com",
        "https://groww.in/mutual-funds/fund-a#details",
        "https://user@groww.in/mutual-funds/fund-a",
    ],
)
def test_only_https_groww_fund_or_etf_pages_are_accepted(url):
    with pytest.raises(ValueError):
        validate_groww_url(url)


def test_map_rejects_wrong_headers_and_conflicting_urls():
    with pytest.raises(GrowwUrlMapError, match="headers"):
        parse_groww_url_map_rows([["Scheme Name", "AMFI Scheme Code"]])

    with pytest.raises(GrowwUrlMapError, match="conflicting"):
        parse_groww_url_map_rows([
            ["Scheme Name", "AMFI Scheme Code", "Groww URL"],
            ["Fund A", 12345, "https://groww.in/mutual-funds/fund-a"],
            ["Fund A duplicate", 12345, "https://groww.in/mutual-funds/another-fund"],
        ])


def test_invalid_nonblank_url_rejects_map():
    with pytest.raises(GrowwUrlMapError, match="invalid Groww URL"):
        parse_groww_url_map_rows([
            ["Scheme Name", "AMFI Scheme Code", "Groww URL"],
            ["Fund A", 12345, "https://example.com/fund-a"],
        ])


def test_reader_loads_the_fund_code_map_through_fake_sheets_client():
    calls = []

    class Worksheet:
        def get(self, range_name, value_render_option=None):
            calls.append((range_name, value_render_option))
            return [
                ["Scheme Name", "AMFI Scheme Code", "Groww URL"],
                ["Fund A", 12345, "https://groww.in/mutual-funds/fund-a"],
            ]

    class Spreadsheet:
        def worksheet(self, name):
            assert name == "Fund Code Map"
            return Worksheet()

    class Client:
        def open_by_key(self, spreadsheet_id):
            assert spreadsheet_id == "sheet-id"
            return Spreadsheet()

    def client_factory(credentials_path, token_path):
        assert credentials_path == Path("credentials.json")
        assert token_path == Path("token.json")
        return Client()

    result = read_groww_url_map(
        spreadsheet_id="sheet-id",
        credentials_path=Path("credentials.json"),
        token_path=Path("token.json"),
        client_factory=client_factory,
    )

    assert result == {"12345": "https://groww.in/mutual-funds/fund-a"}
    assert calls == [("A:C", "UNFORMATTED_VALUE")]
