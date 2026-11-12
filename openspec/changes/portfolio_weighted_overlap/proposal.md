# Portfolio-weighted holdings overlap

## Problem

The current `Portfolio Overlap` report compares the underlying stock allocation of each configured fund pair. It does not use the user's actual Groww holdings or the amount invested in each fund. As a result, it cannot show which shared stocks create the most exposure in the user's portfolio.

The script also takes its fund list from `config/funds.yaml`, while the private spreadsheet now has a `Fund Code Map` and a `Current Holdings` tab that should be the source for this analysis.

## Proposal

Update the on-demand overlap report to read the user's actual positions from `Current Holdings` and resolve scheme names/codes from `Fund Code Map`. Aggregate folios by AMFI code, fetch underlying holdings for each identified fund, and weight each stock allocation by the fund's share of the reported portfolio value.

Show the largest estimated stock exposures and data coverage, including the Groww statement date and funds that could not be mapped or fetched. Keep the existing pairwise overlap matrix and detailed fund-pair breakdown as a supporting section.

## Out of Scope

- Changing buy/sell signals or producing an investment amount.
- Inferring transactions made after the uploaded Groww statement.
- Changing the daily alert workflow.
- Replacing the existing pairwise overlap calculation.
