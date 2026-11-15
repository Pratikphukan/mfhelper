# Design: Make market-regime buy advice cautious and clear

## Scope

- Change the wording and labels on buy-side email cards and indicator rows so they agree with the market regime.
- Keep the existing technical calculations and tier detection. This change changes how signals are presented; it does not suppress them.
- Remove suggested size multipliers from all buy signals until a private investment limit exists.
- Leave sell/trim signals unchanged.

## Regime wording

### BEAR

BEAR means the NIFTY 500 is below its 200-day average and that average has fallen over the configured lookback (20 sessions by default). It describes the broad market trend; it is not a forecast for an individual fund.

- If a dip signal does not meet the configured capitulation thresholds, call it **DIP DETECTED — WATCH**. Explain that this is a signal during a broad-market downtrend and does not predict whether the fund will fall further.
- If both configured capitulation conditions are met, call it **CAPITULATION DETECTED — REVIEW BEFORE DECIDING**. State that meeting the thresholds is an extreme-dip signal, not proof the fund has bottomed.
- The current defaults are RSI <= 25 and fund NAV at least 12% below its 200-day average. Use configured values, not hard-coded text.

### CORRECTION

CORRECTION means the five-session average VIX is at or above the configured high band (18 by default), unless the higher-priority BEAR rule matched first.

- Tier 1: **WATCH**; say a stronger signal may be worth reviewing.
- Tier 2 or 3: **REVIEW SIGNAL**; show the evidence, without telling the user to buy.

### UPTREND and NEUTRAL

Show the technical signal as **TECHNICAL DIP TIER N**, with its evidence. Do not suggest an amount or label it as a buy recommendation.

## Buttons and size

- Replace the buy-card **BUY ON GROWW** button label with **REVIEW ON GROWW**, so the link remains available without sounding like an order.
- Remove the multiplier/"normal top-up" size from all buy cards, regardless of regime.
- Keep existing multiplier configuration values accepted but unused for now. Removing them would require a separate config cleanup and could affect a user's private settings.

## Consistency requirement

Apply the same regime wording to both the confluence cards and the indicator rows. Changing only the note beside a card is not enough if a separate row still says BUY or "Deploy". The technical trigger and its values remain visible as evidence.

## Verification

- Cover BEAR with and without capitulation thresholds, CORRECTION at each tier, and UPTREND/NEUTRAL.
- Confirm both cards and indicator rows use consistent wording and no buy-size multiplier appears.
- Confirm trim cards are unchanged.
- Use synthetic tests only; no live Google Sheet or state writes.
- Run `pytest tests/`.

## User decisions

- Use **TECHNICAL DIP TIER** for UPTREND and NEUTRAL signals.
- Use **REVIEW ON GROWW** for buy-signal buttons.
- The user requested both wording changes after reviewing the options; this approves the design for implementation.
