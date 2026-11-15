# Design: Use Fund Code Map links in alert emails

## Data source

Extend the existing `Fund Code Map` tab with a third column named `Groww URL`:

| Scheme Name | AMFI Scheme Code | Groww URL |
| --- | --- | --- |

The daily alert run will read this tab using the Google Sheets credentials it already uses. It will match URLs by AMFI scheme code, not by fund-name text. This avoids name spelling differences and keeps each URL tied to the exact scheme.

Accept only HTTPS links on `groww.in` under `/mutual-funds/` or `/etfs/`. The current map contains mutual-fund pages and an ETF page, so both paths are needed. This prevents a cell edit from redirecting the alert button to an unrelated site.

## Email behavior

- Use the saved URL for both the buy-confluence and trim cards.
- Keep the existing buy and trim button labels and appearance; this change only replaces their targets.
- If an individual fund has no valid URL, use Groww's general mutual-funds page for that button.
- If the sheet cannot be read or validated, continue sending the alert email with the buttons linking to Groww's general mutual-funds page, and log a warning. The link lookup must not suppress otherwise valid alerts.
- Remove generation of the obsolete `/mutual-funds/search?q=...` path.

## Verification

- Test the URL parser and code-based lookup with synthetic sheet rows.
- Test both email card types with valid and missing links.
- Use fake Sheets clients; do not write to the live spreadsheet.
- Run `pytest tests/` before completion.

## User decision recorded

- Keep Groww buttons present if the map or an individual URL is unavailable; link those buttons to Groww's general mutual-funds page.
- Accept `groww.in/mutual-funds/` and `groww.in/etfs/` paths. The map includes both regular mutual-fund scheme pages and an ETF page.
- Preserve the current button labels and appearance.

The user approved this design before implementation.
