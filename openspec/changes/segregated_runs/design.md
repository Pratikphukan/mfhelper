# Design: CLI Segregated Runs for Local Testing

## 1. System Topology & Data Flow

```
                     ┌───────────────────────────────┐
                     │     Execute: python main.py   │
                     └───────────────┬───────────────┘
                                     │
                                     ▼
                      ┌─────────────────────────────┐
                      │   Does --dev flag exist?    │
                      └──────┬───────────────┬──────┘
                             │               │
                  ┌──────────┘               └──────────┐
                  ▼ (No: Production)                    ▼ (Yes: Development)
┌─────────────────────────────────────┐   ┌─────────────────────────────────────┐
│    - target: "Daily NAV"            │   │    - target: "Daily NAV (Dev)"      │
│    - email subject: "🚨 MFHelper..."│   │    - email subject: "🚨 [DEV] MFH..."│
└─────────────────────────────────────┘   └─────────────────────────────────────┘
```

---

## 2. Dynamic Worksheet Logic (`main.py`)

Inside `main.py`, we construct the worksheet target name dynamically based on the command line argument parsed:

```python
worksheet_name = settings.google_sheet.worksheet
if args.dev:
    worksheet_name = f"{worksheet_name} (Dev)"
```

This dynamic `worksheet_name` is passed as the target to the `SheetAppender` client instance.

---

## 3. Email Alert Modifications (`mfhelper/alerts.py`)

We modify the `dispatch_alerts_email` function signature to accept a boolean `is_dev` parameter:

```python
def dispatch_alerts_email(
    alerts: list[TriggeredAlert],
    email_config: AlertEmailConfig,
    confluence_signals: list[DipBuyingSignal] | None = None,
    is_dev: bool = False,
) -> bool:
```

Within the function, the Subject header is prefix-molded:
```python
subject_prefix = "🚨 [DEV]" if is_dev else "🚨"
msg["Subject"] = f"{subject_prefix} MFHelper Technical Buy/Sell Alerts: {len(alerts)} Trigger(s)"
```
