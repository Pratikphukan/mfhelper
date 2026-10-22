# Design: Gold ETF Analytics Tracker & Google Sheet Writer

## 1. System Topology & Data Flow

The script reads the Gold ETF configuration, fetches NAV histories from `mfapi.in`, computes analytics, and writes to Google Sheets:

```
┌────────────────────────────────────────────────────────┐
│            Load: config/gold_etfs.yaml                 │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│             Fetch Full History & Meta                  │
│       - GET: api.mfapi.in/mf/{etf_code}                │
│       - Scrape expense ratios & AUM from Groww         │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼ (Compute Performance & Risk)
┌────────────────────────────────────────────────────────┐
│               Gold ETF Analytics Engine                │
│   - 1Y Abs %, 3Y CAGR %, 5Y CAGR %                     │
│   - Ann. SD %, Sharpe (3Y), Sortino (3Y), Calmar (3Y)  │
│   - Max Drawdown (3Y) %                                │
└───────────────────────────┬────────────────────────────┘
                            │
                            ├──────────────────────────┐
                            ▼                          ▼
              ┌──────────────────────────┐┌─────────────────────────┐
              │    Google Sheets Sync    ││    Terminal Table       │
              │  "Gold ETFs Analytics"   ││   Performance Output    │
              │       Worksheet          ││         Console         │
              └──────────────────────────┘└─────────────────────────┘
```

---

## 2. Configuration Schema (`config/gold_etfs.yaml`)

We define a dedicated configuration file listing the top Indian Gold ETFs:

```yaml
etfs:
  - code: "140088"
    ticker: "GOLDBEES"
    name: "Nippon India ETF Gold BeES"
  - code: "105463"
    ticker: "HDFCGOLD"
    name: "HDFC Gold ETF"
  - code: "105462"
    ticker: "ICICIGOLD"
    name: "ICICI Prudential Gold ETF"
  - code: "119789"
    ticker: "SETFGOLD"
    name: "SBI Gold ETF"
  - code: "120472"
    ticker: "AXISGOLD"
    name: "Axis Gold ETF"
  - code: "118778"
    ticker: "KOTAKGOLD"
    name: "Kotak Gold ETF"
  - code: "105463"
    ticker: "UTIGOLD"
    name: "UTI Gold ETF"
```

---

## 3. Worksheet Table Layout (`Gold ETFs Analytics`)

The table is written starting at row 1 of the new **`Gold ETFs Analytics`** worksheet tab:

| ETF Name | Ticker | AMFI Code | 1Y % | 3Y CAGR % | 5Y CAGR % | Ann. SD % | Sharpe (3Y) | Sortino (3Y) | Calmar (3Y) | Max DD (3Y) % | TER % | Last Updated |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
