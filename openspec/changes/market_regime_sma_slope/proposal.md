# Show the 200-day SMA slope in Market Regime

## Problem

MFHelper classifies a market as BEAR when the NIFTY 500 closes below its 200-day SMA and the 200-day SMA is lower than it was 20 trading sessions earlier. The `Market Regime` sheet currently shows the current 200-day SMA, but not the earlier value used for this comparison. A reader therefore cannot verify the slope condition from the same row.

## Proposal

Add the 200-day SMA value from 20 trading sessions earlier and its difference from the current 200-day SMA to each new `Market Regime` row. Use the existing NIFTY 500 history already fetched and cached by the regime calculation. This makes the BEAR rule easier to inspect without adding another data source or changing classification behavior.

When upgrading the existing sheet, preserve all old rows and leave the two new cells blank for historical rows. Populate the new columns on future runs.

## Out of Scope

- Changing regime thresholds or classification rules.
- Adding market-breadth or other indicators.
- Changing daily alert content or buy/sell behavior.
- Reading historical values back from the Google Sheet to calculate the slope.
