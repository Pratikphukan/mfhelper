# Design: Consolidated Portfolio Allocation Map

## 1. System Topology & Data Flow

The script reads your fund list, fetches portfolios, applies custom weights, and writes the consolidated metrics to Google Sheets and your Web Dashboard:

```
┌────────────────────────────────────────────────────────┐
│             Parse funds & custom weights               │
│             - Load: config/funds.yaml                  │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│                Fetch Portfolios (Live)                 │
│   - GET: api.tickertape.in/mutualfunds/{mfId}/holdings │
│   - Extract stock allocation % and industry sector     │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼ (Aggregation Math)
┌────────────────────────────────────────────────────────┐
│           Consolidated Portfolio Aggregator            │
│   For each stock S:                                    │
│     TotalWeight(S) = Sum( Weight_Fund * StockWeight_Fund)
│   Group by Sectors to get Consolidated Sector weights │
└───────────────────────────┬────────────────────────────┘
                            │
                            ├──────────────────────────┐
                            ▼                          ▼
              ┌──────────────────────────┐┌─────────────────────────┐
              │    Google Sheets Sync    ││    HTML Web Dashboard   │
              │  "Combined Allocation"   ││  - Sector Donut Chart   │
              │       Worksheet          ││  - Top Stocks Bar Chart │
              └──────────────────────────┘└─────────────────────────┘
```

---

## 2. Mathematical Aggregation Algorithm

Let $W_f$ be the percentage weight of Fund $f$ in your total portfolio (where $\sum W_f = 100\%$).
Let $A_{f, s}$ be the percentage allocation of Stock $s$ inside Fund $f$.

The **consolidated portfolio weight** $P_s$ for Stock $s$ across your entire portfolio is calculated as:

$$P_s = \sum_{f} \left( \frac{W_f}{100} \times A_{f, s} \right)$$

### Example:
If you hold:
* 50% Fund A ($W_A = 50\%$), which holds 10% HDFC Bank ($A_{A, \text{HDFC}} = 10\%$).
* 50% Fund B ($W_B = 50\%$), which holds 6% HDFC Bank ($A_{B, \text{HDFC}} = 6\%$).

Your **consolidated exposure to HDFC Bank** is:

$$P_{\text{HDFC}} = \left( \frac{50}{100} \times 10 \right) + \left( \frac{50}{100} \times 6 \right) = 5\% + 3\% = 8\%$$

We apply this exact formula across every stock holding to find your true consolidated top 15 stocks. We then group them by their industry sector (e.g. Financials, Tech, Energy) to compute your true consolidated sector exposure.

---

## 3. Storage & Config Schema (`config/funds.yaml`)

We add an optional `weight:` key (float) to your tracked funds list:

```yaml
funds:
  - code: "127042"
    name: "Motilal Oswal Midcap Fund"
    weight: 20.0 # 20% of your total investments are in this fund
  - code: "120492"
    name: "JM Flexicap Fund"
    weight: 40.0 # 40% of your total investments
```

*Note: If no custom weights are specified, the script will default to **equal weighting** ($\frac{100}{N}\%$ per fund) so it runs seamlessly out-of-the-box!*
