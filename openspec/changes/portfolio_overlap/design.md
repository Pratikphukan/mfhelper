# Design: Standalone Mutual Fund Portfolio Overlap Analyzer

## 1. System Topology & Data Flow

```
┌────────────────────────────────────────────────────────┐
│                   Parse local funds                    │
│             - Load: config/funds.yaml                  │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│                   Resolve ISIN Codes                   │
│             - Download AMFI NAVAll.txt                 │
│             - Map AMFI code -> ISIN and Name           │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│              Map ISIN to Tickertape mfId               │
│   - Check data/tickertape_mappings.json cache          │
│   - Cache Miss: Download Tickertape mf sitemap         │
│   - Fuzzy match Name and verify ISIN via /summary API  │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼ (Cache resolved IDs)
┌────────────────────────────────────────────────────────┐
│                Fetch Stock Holdings                    │
│   - GET: api.tickertape.in/mutualfunds/{mfId}/holdings │
│   - Extract currentAllocation: stock title and latest %│
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼ (Intersection calculation)
┌────────────────────────────────────────────────────────┐
│               Pairwise Minimum Intersection            │
│   - Overlap(A, B) = Sum( Min(Alloc_A, Alloc_B) )       │
└───────────────────────────┬────────────────────────────┘
                            │
                            ├──────────────────────────┐
                            ▼                          ▼
              ┌──────────────────────────┐┌─────────────────────────┐
              │    ASCII Overlap Matrix  ││  Detailed Stock Overlap │
              │          Table           ││   Analysis (>10% pairs) │
              └──────────────────────────┘└─────────────────────────┘
```

---

## 2. Mathematical Definition of Overlap

The overlap between Fund $A$ and Fund $B$ is calculated using the **minimum-weight intersection** of their underlying holdings:

$$\text{Overlap}(A, B) = \sum_{s \in A \cap B} \min(W_{A, s}, W_{B, s})$$

Where:
* $s$ represents an underlying holding (matched by unique stock ID `sid`, or company name `title` if `sid` is null).
* $W_{A, s}$ is the percentage allocation of stock $s$ in Fund $A$.
* $W_{B, s}$ is the percentage allocation of stock $s$ in Fund $B$.

---

## 3. Storage & Cache Schema (`data/tickertape_mappings.json`)

To prevent downloading the 5,000+ sitemap XML file on every execution, resolved mappings are cached in a simple flat JSON structure indexed by ISIN:

```json
{
  "INF090I01JR0": "M_FREK",
  "INF192K01CC7": "M_JMUU",
  "INF194KB1AL4": "M_IDFM",
  "INF200K01RP8": "M_SBIGL",
  "INF200K01UJ5": "M_SBRU",
  "INF247L01445": "M_MOLS"
}
```
If a new fund is added to `funds.yaml`, only that specific fund triggers a sitemap resolution, while others load instantly from the cache.
