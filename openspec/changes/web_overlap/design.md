# Design: Interactive Web-Based Portfolio Overlap Matrix

## 1. System Topology & Data Flow

The dashboard loads the aggregated holdings cache, performs the overlap math in the browser, and renders the interactive UI:

```
┌────────────────────────────────────────────────────────┐
│             Load Consolidated Cache JSON               │
│     - File: data/combined_portfolio_allocation.json    │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼ (Inject into HTML script tag)
┌────────────────────────────────────────────────────────┐
│            Initialize Web Overlay Dataset              │
│   Extracts:                                            │
│   - fund_holdings: { "code_a": [stocks], "code_b": .. }│
│   - dataset: list of funds and display names           │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼ (On Click "View Overlap Matrix")
┌────────────────────────────────────────────────────────┐
│            Pairwise JS Overlap Calculation             │
│   For each pair (A, B):                                │
│     Calculates: Overlap(A, B) = Sum( Min(W_A, W_B) )   │
└───────────────────────────┬────────────────────────────┘
                            │
                            ├──────────────────────────┐
                            ▼                          ▼
              ┌──────────────────────────┐┌─────────────────────────┐
              │    Color Heatmap Grid    ││   Live Stock Inspector  │
              │  - Green: < 10% overlap  ││  - Click cell to see   │
              │  - Amber: 10% - 20%      ││    the exact shared     │
              │  - Red: > 20% overlap    ││    stock list            │
              └──────────────────────────┘└─────────────────────────┘
```

---

## 2. Browser-Side Overlap Algorithm (JavaScript)

We implement the mathematical minimum weight intersection inside the client-side browser logic:

```javascript
function calculatePairwiseOverlap(fundA_holdings, fundB_holdings) {
    let overlap_pct = 0.0;
    const mapB = {};
    
    // Create lookup map for Fund B
    fundB_holdings.forEach(h => {
        const key = h.sid ? h.sid : h.company_name.toLowerCase().trim();
        mapB[key] = h;
    });
    
    const overlappingStocks = [];
    
    // Check intersections
    fundA_holdings.forEach(hA => {
        const keyA = hA.sid ? hA.sid : hA.company_name.toLowerCase().trim();
        if (mapB[keyA]) {
            const hB = mapB[keyA];
            const intersection = Math.min(hA.allocation_pct, hB.allocation_pct);
            overlap_pct += intersection;
            overlappingStocks.push({
                name: hA.company_name,
                alloc_a: hA.allocation_pct,
                alloc_b: hB.allocation_pct,
                intersection: intersection
            });
        }
    });
    
    overlappingStocks.sort((a, b) => b.intersection - a.intersection);
    return {
        total: Math.round(overlap_pct * 100) / 100,
        stocks: overlappingStocks
    };
}
```

---

## 3. Web UI Mockup & Grid Color Accents

The matrix grid utilizes specific background styling classes to indicate overlap health:
* **`< 10.0% Overlap`**: `bg-emerald-50 text-emerald-800` (Excellent diversification)
* **`10.0% to 20.0% Overlap`**: `bg-amber-50 text-amber-800` (Standard overlap)
* **`> 20.0% Overlap`**: `bg-rose-50 text-rose-800` (Redundancy warning)

The grid includes full horizontal and vertical fund name labels. Clicking a cell displays the details panel.
