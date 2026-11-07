# Design: Use only live NSE P/E data

## Agreed behavior

1. Request Nifty 50 P/E from NSE during a run.
2. Accept a value only if the response contains a valid, plausible P/E.
3. If the request fails or the response is invalid, set valuation to unknown for that run.
4. Write a blank P/E and blank source to the Market Regime tab when valuation is unknown.
5. Do not use cached or manually configured P/E values for suggested sizing or trim thresholds.
6. Continue recording available NIFTY 500 and VIX data.

## Compatibility

Old `nifty50_pe`, `nifty50_pe_as_of`, and `stale_days` YAML keys are ignored by the regime parser. This avoids breaking existing alert configuration while removing their effect.
