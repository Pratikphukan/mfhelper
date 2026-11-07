# Proposal: Use only live NSE P/E data

## Problem

When NSE cannot be reached, MFHelper can currently use a cached or manually configured Nifty 50 P/E. That may put an old or user-entered value in the Market Regime sheet or let it affect future advice.

## Proposed change

Use a P/E only when a valid value is fetched live from NSE. If NSE is unavailable or returns an invalid value, show P/E as unavailable, leave the sheet cell blank, and skip all P/E-based advice adjustments. Continue recording available index and VIX data.

## Decision

The user confirmed live-only behavior applies to both the sheet and future advice.
