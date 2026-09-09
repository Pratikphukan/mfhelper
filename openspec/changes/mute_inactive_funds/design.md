# Design: "Mute" Inactive Funds via Configuration

## 1. System Topology & Active Processing Flow

During the daily checking loop, the system evaluates whether a fund is flagged as active before downloading prices or checking triggers:

```
                  ┌───────────────────────────────┐
                  │   Load: config/funds.yaml     │
                  └───────────────┬───────────────┘
                                  │
                                  ▼
                ┌──────────────────────────────────┐
                │     Is fund.active == True?      │
                └──────┬────────────────────┬──────┘
                       │                    │
            ┌──────────┘                    └──────────┐
            ▼ (Yes: Process)                           ▼ (No: Ignore)
┌──────────────────────────────────────┐   ┌────────────────────────────────────┐
│  - Download latest AMFI/mfapi NAV    │   │  - Skip NAV download & API fetches │
│  - Compute 52W, 200D, RSI metrics    │   │  - Skip technical indicator checks │
│  - Check buy/sell triggers           │   │  - Write blank values in daily row │
└──────────────────────────────────────┘   └────────────────────────────────────┘
```

---

## 2. Config & Schema Modifications

### A. YAML Configuration (`config/funds.yaml`)
We add the optional `active:` boolean key to any fund:

```yaml
funds:
  - code: "140196"
    name: "Edelweiss Liquid Fund - Direct Plan - Growth Option"
    category: "debt"
    active: false # Ignored in daily runs, history preserved in sheet
```

### B. Python Configuration Schema (`mfhelper/config.py`)
We update `FundConfig` and `load_funds` to parse the new field:

```python
@dataclass(frozen=True)
class FundConfig:
    code: str
    name: str | None
    expense_ratio_pct: float | None = None
    groww_slug: str | None = None
    category: str | None = None
    weight: float | None = None
    active: bool = True # Defaults to True
```

---

## 3. Daily Execution Logic (`main.py`)

Within `main.py`, if `fund.active` is `False`, we:
1. Skip fetching NAV from AMFI or `mfapi.in` for this fund.
2. Skip calculating trailing returns, RSI, and SMA.
3. Skip checking indicators or confluence dip-buying/trimming alerts.
4. Set its values in `values_by_code` to empty `NavValue(nav=None, ...)` so that it writes clean, blank cells in the newly appended daily row in your Google Sheet, preserving column alignment perfectly!
5. Skip updating `data/last_nav.json` for this fund so that we don't save any fresh NAV dates for it.
