# Design: Tactical "Dip Buying" Assistant in Email Alerts

## 1. Logic Flow & Signal Evaluation

Every daily run evaluated by `main.py` compiles the fund's current technical metrics: `rsi`, `dist_200d_sma`, and `dist_52w_high`. 

For each fund, the system runs the **Confluence Algorithm**:

```
                  ┌───────────────────────────────┐
                  │  Compile Fund Metrics (Daily) │
                  │  - current_rsi                │
                  │  - current_dist_200d_sma      │
                  │  - current_dist_52w           │
                  └───────────────┬───────────────┘
                                  │
                                  ▼
                ┌──────────────────────────────────┐
                │   Count Triggers Per Tier        │
                │   - Tier 3 check (Deep drops)    │
                │   - Tier 2 check (Moderate drops)│
                │   - Tier 1 check (Mild drops)    │
                └─────────────────┬────────────────┘
                                  │
          ┌───────────────────────┴───────────────────────┐
          ▼ (No or 1 Trigger)                             ▼ (2+ Triggers in any Tier)
┌──────────────────────────────────┐            ┌──────────────────────────────────┐
│        Standard Listing          │            │     Promote to Tactical Card     │
│  - Keep as standard alert list   │            │  - Generate DipBuyingSignal      |
│  - No specialized top card       │            │  - Compose action suggestion     │
└──────────────────────────────────┘            │  - Generate direct Groww buy link│
                                                └──────────────────────────────────┘
```

---

## 2. Confluence Classification & Thresholds

We evaluate indicators across three distinct tiers. A `DipBuyingSignal` is raised if **at least 2 conditions** are satisfied for a given tier:

### Tier 3 (Strong Confluence Buy)
* **Conditions (Need $\ge 2$):**
  * `rsi` $\le 35.0$ (Deeply Oversold)
  * `dist_200d_sma` $\le -10.0\%$ (Capitulation)
  * `dist_52w_high` $\le -20.0\%$ (Deep Peak Discount)
* **Actionable Suggestion:** `"Strong Confluence Buy. Fund is highly oversold and deeply discounted from peak. Suggesting aggressive lumpsum top-up."`
* **Color Accent:** `#D4EDDA` / `#155724` (Deep emerald green)

### Tier 2 (Moderate Confluence Buy)
* **Conditions (Need $\ge 2$):**
  * `rsi` $\le 45.0$ (Moderate Oversold)
  * `dist_200d_sma` $\le -2.0\%$ (Support Discount)
  * `dist_52w_high` $\le -10.0\%$ (Moderate Peak Discount)
* **Actionable Suggestion:** `"Moderate Confluence Buy. Solid support dip. Suggesting moderate lumpsum or increased SIP multiplier."`
* **Color Accent:** `#FFF3CD` / `#856404` (Warm support gold/yellow)

### Tier 1 (Mild Confluence Pullback)
* **Conditions (Need $\ge 2$):**
  * `rsi` $\le 55.0$ (Mild Pullback)
  * `dist_200d_sma` $\le 2.0\%$ (Trend Support)
  * `dist_52w_high` $\le -5.0\%$ (Mild Peak Discount)
* **Actionable Suggestion:** `"Mild Confluence Pullback. Healthy consolidation. Suggesting standard top-up."`
* **Color Accent:** `#EBF2FF` / `#004085` (Soft blue support)

---

## 3. Data Schema & Models

Inside `mfhelper/alerts.py`, we define a dataclass:

```python
@dataclass(frozen=True)
class DipBuyingSignal:
    scheme_code: str
    fund_name: str
    tier: int               # 1, 2, or 3
    reasons: list[str]      # e.g., ["RSI is 32.5 (Oversold)", "52W drop is -22.4% (Deep)"]
    suggestion: str
    groww_link: str         # Direct buy button link
```

### Deep-linked Transaction URL:
The Groww buy link is formatted as a URL-encoded query pointing to Groww's mutual fund search page:
`https://groww.in/mutual-funds/search?q={url_encoded_fund_name}`
This provides a seamless, one-click transition from your inbox directly to the transaction page!
