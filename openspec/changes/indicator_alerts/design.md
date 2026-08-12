# Design: Technical Indicator "Buy/Sell Zone" Trigger Alerts

## 1. System Topology & Data Flow

```
┌──────────────────────────────────────────────┐
│                  Daily Run (main.py)         │
│   - Fetches and compiles today's metrics    │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│           Check Rules (mfhelper/alerts.py)   │
│   - Loads rules from config/alerts.yaml      │
│   - Checks RSI-14, 52W Dist, and 200D SMA    │
└──────────────────────┬───────────────────────┘
                       │
                       ▼ (Trigger detected?)
                      Yes
                       │
                       ▼
┌──────────────────────────────────────────────┐
│         Email Dispatcher (MIME & SMTP)       │
│   - Formats a detailed, clean HTML email     │
│   - Resolves SMTP credentials securely       │
│   - Sends email alert to receiver            │
└──────────────────────────────────────────────┘
```

---

## 2. Configuration Schema (`config/alerts.yaml`)

We introduce a new configuration file to isolate rules and credentials:

```yaml
rules:
  rsi_mild_pullback: 50.0    # Tier 1 buy zone (small top-up)
  rsi_moderate_dip: 42.0     # Tier 2 buy zone (moderate lumpsum)
  rsi_deep_oversold: 35.0    # Tier 3 buy zone (aggressive lumpsum)
  rsi_overbought: 70.0
  discount_threshold_pct: -15.0
  enable_sma_crossing: true

email:
  enable: false
  smtp_server: "smtp.gmail.com"
  smtp_port: 587
  use_tls: true
  sender_email: ""
  sender_password: ""        # Replaced by EMAIL_PASSWORD env variable if empty
  receiver_email: ""
```

---

## 3. Trigger Mechanics

For each fund, the system checks today's computed indicators against the boundaries:

1. **RSI Mild Pullback (Tier 1 Buy):** `rsi_value <= rsi_mild_pullback` and `rsi_value > rsi_moderate_dip` (Alert Type: **BUY TIER 1 / MILD PULLBACK - Deploy Smaller Top-ups**).
2. **RSI Moderate Dip (Tier 2 Buy):** `rsi_value <= rsi_moderate_dip` and `rsi_value > rsi_deep_oversold` (Alert Type: **BUY TIER 2 / MODERATE DIP - Deploy Moderate Lumpsum**).
3. **RSI Deep Oversold (Tier 3 Buy):** `rsi_value <= rsi_deep_oversold` (Alert Type: **BUY TIER 3 / DEEP OVERSOLD - Deploy Aggressive Lumpsum**).
4. **RSI Overbought:** `rsi_value >= rsi_overbought` (Alert Type: **MOMENTUM WARNING / TRIM**).
5. **Discount Zone:** `dist_52w_high_pct <= discount_threshold_pct` (Alert Type: **BUY / EXCELLENT MARGIN OF SAFETY**).
4. **200D SMA Crossings:**
   To determine if a trend crossing occurred today, we evaluate today's NAV and yesterday's NAV relative to their respective 200-day Simple Moving Averages:
   * Let $D_{today}$ be the distance % from today's 200D SMA.
   * Let $D_{yesterday}$ be the distance % from yesterday's 200D SMA (computed using `history[1:]`).
   * **Bullish Cross-Above:** $D_{today} \ge 0\%$ and $D_{yesterday} < 0\%$.
   * **Bearish Cross-Below:** $D_{today} \le 0\%$ and $D_{yesterday} > 0\%$.

---

## 4. Email Dispatch Engine
The notification dispatch uses Python's standard `smtplib` and `email.mime` modules for zero-dependency, lightweight execution:
* **Security First:** The sender's SMTP password should never be hardcoded or checked into Git. It will be loaded securely from the `EMAIL_PASSWORD` environment variable (if `sender_password` in YAML is empty).
* **HTML Templates:** Formats alerts as a beautiful, responsive, and color-coded table (Green for BUY zones, Red/Amber for SELL/momentum alerts).
