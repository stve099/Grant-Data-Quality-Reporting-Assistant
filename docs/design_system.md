# Design System

The app, charts, and reports share one validated visual language. Values live in
`src/grant_assistant/analytics/charts.py` (chart tokens), `.streamlit/config.toml`
(app theme), and the HTML report stylesheet.

## Principles

1. **Color is assigned by job, never by mood.**
   - *Categorical* (series identity): fixed slot order, never cycled.
   - *Sequential* (magnitude): one blue hue, light→dark.
   - *Status* (state): reserved good/warning/serious/critical steps — never reused
     as series colors, never color-alone (always paired with a label or icon).
2. **One axis per chart.** Two measures of different scale get two charts.
3. **Recessive chrome.** Hairline grid, muted axis ink; the data carries the page.
4. **Text wears ink tokens, not series colors.**
5. **Every chart ships hover tooltips** and sits beside a table or direct labels
   (the "relief rule" for the three light-surface slots below 3:1 contrast).

## Tokens

### Categorical series (fixed order — colorblind-safe, validator-passed)

| Slot | Hue | Hex |
|---|---|---|
| 1 | blue | `#2a78d6` |
| 2 | orange | `#eb6834` |
| 3 | aqua | `#1baf7a` |
| 4 | yellow | `#eda100` |
| 5 | magenta | `#e87ba4` |
| 6 | green | `#008300` |

Validated (light surface `#fcfcfb`): worst adjacent CVD ΔE 9.1, worst adjacent
normal-vision ΔE 19.6 — both pass. Slots 3–5 are sub-3:1 contrast on the light
surface, so charts using them always pair with visible labels or a table.

### Sequential (magnitude)

Blue steps `#cde2fb → #86b6ef → #3987e5 → #2a78d6 → #1c5cab`.

### Status (reserved)

| Role | Hex | Used for |
|---|---|---|
| good | `#0ca30c` | measures met, positive deltas |
| warning | `#fab219` | medium severity |
| serious | `#ec835a` | high severity |
| critical | `#d03b3b` | critical severity, overdue, measures missed |

Severity mapping: critical→critical, high→serious, medium→warning,
low→muted ink `#898781`, informational→baseline `#c3c2b7`.

### Chrome & ink

| Role | Hex |
|---|---|
| Chart surface / app background | `#fcfcfb` |
| Secondary surface | `#f0efec` |
| Primary ink | `#0b0b0b` |
| Secondary ink | `#52514e` |
| Muted (axis labels) | `#898781` |
| Gridline | `#e1e0d9` |
| Baseline / axis | `#c3c2b7` |

### Typography

System sans everywhere: `system-ui, -apple-system, "Segoe UI", sans-serif`.
Tabular numerals (`font-variant-numeric: tabular-nums`) only where columns align.

## Validation

The palette was checked with the dataviz validator (lightness band, chroma floor,
CVD adjacent-pair separation, normal-vision floor, surface contrast):

```
[PASS] Lightness band  [PASS] Chroma floor  [PASS] CVD separation
[PASS] Normal-vision floor  [WARN] Contrast — relief rule applied (labels/tables)
```

If you change any series hue or the slot order, re-validate before shipping.
