# Design: Tactical "Profit-Taking & Trimming" Assistant

## 1. Logic Flow & Signal Evaluation

During the daily checking loop, the system evaluates both Oversold (Dip Buying) and Overbought (Profit Trimming) confluences:

```
                  ┌───────────────────────────────┐
                  │  Compile Fund Metrics (Daily) │
                  │  - current_rsi                │
                  │  - current_dist_52w_high      │
                  └───────────────┬───────────────┘
                                  │
                                  ▼
                ┌──────────────────────────────────┐
                │   Count Triggers Per Tier        │
                │   - Trim Tier 3 (Extreme Climax) │
                │   - Trim Tier 2 (Moderate Peak)  │
                │   - Trim Tier 1 (Mild Momentum)  │
                └─────────────────┬────────────────┘
                                  │
          ┌───────────────────────┴───────────────────────┐
          ▼ (No or 1 Trigger)                             ▼ (2+ Triggers in any Tier)
┌──────────────────────────────────┐            ┌──────────────────────────────────┐
│        Standard Listing          │            │      Promote to Trimming Card    │
│  - Keep as standard alert list   │            │  - Generate TrimmingSignal       |
│  - No specialized top card       │            │  - Compose action suggestion     │
└──────────────────────────────────┘            │  - Generate direct Groww buy link│
                                                └──────────────────────────────────┘
```

---

## 2. Confluence Classification & Thresholds

We evaluate indicators across three distinct overbought tiers. A `TrimmingSignal` is raised if **at least 2 conditions** are satisfied for a given tier:

### Trim Tier 3 (Extreme Climax Peak - Urgent Action)
* **Conditions (Need $\ge 2$):**
  * `rsi` $\ge 75.0$ (Extreme Overbought)
  * `dist_52w_high` $\ge -1.0\%$ (Trading at or near 52W All-Time High)
* **Actionable Suggestion:** `"Urgent Climax Warning. Fund is trading at extreme peak overbought conditions. Strongly suggesting trimming 5% to 10% of total profits to cash and pausing all SIPs immediately."`
* **Color Accent:** `#F8D7DA` / `#721C24` (Soft warning red)

### Trim Tier 2 (Moderate Overstretch - Trim Zone)
* **Conditions (Need $\ge 2$):**
  * `rsi` $\ge 70.0$ (Standard Overbought)
  * `dist_52w_high` $\ge -3.0\%$ (Near 52W High)
* **Actionable Suggestion:** `"Moderate Overstretch. Strong uptrend momentum, but entering the trim zone. Suggesting pausing manual top-ups and considering locking in partial profits."`
* **Color Accent:** `#FFE8CC` / `#7A3700` (Soft orange)

### Trim Tier 1 (Mild Momentum Run)
* **Conditions (Need $\ge 2$):**
  * `rsi` $\ge 65.0$ (Entering High Momentum)
  * `dist_52w_high` $\ge -5.0\%$ (Trading close to peak)
* **Actionable Suggestion:** `"Mild Momentum Run. Strong trend. Suggesting holding your positions but avoiding any large fresh manual lumpsums."`
* **Color Accent:** `#FFF3CD` / `#856404` (Soft gold/yellow)

---

## 3. Data Schema & Models

Inside `mfhelper/alerts.py`, we define a dataclass:

```python
@dataclass(frozen=True)
class TrimmingSignal:
    scheme_code: str
    fund_name: str
    tier: int               # 1, 2, or 3
    reasons: list[str]      # e.g., ["RSI is 76.5 (Overbought)", "52W drop is -0.5% (Peak)"]
    suggestion: str
    groww_link: str         # Direct search page link
```
