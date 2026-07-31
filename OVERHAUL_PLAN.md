# Expense Manager — Fold-Inspired UX Overhaul Plan

Source of inspiration: [fold.money](https://fold.money) (Indian bank-account-aggregator finance app,
package `money.fold.marble`), analyzed via decompiled APK (jadx) — design tokens, screen list, copy
tone, and UX patterns extracted directly from their shipped app, cross-referenced against this repo's
current templates (`dashboard.html`, `manage.html`, `accounts.html`, `themes.css`, `app.py`).

Goal: adopt Fold's **information hierarchy and flow patterns** (big-number-first, donut cash-flow,
consolidated credit card card, overlay transaction detail, Cmd+K search, concentrated personality in
failure states) without abandoning this app's own visual identity
(DM Mono / Syne, terminal-dashboard density, 7-theme system). This is a UX/IA adoption, not a
re-skin — Fold's literal colors/illustrations are not being copied.

---

## Data & Compatibility Guardrails (read before starting any phase)

These apply to every phase below, not just the ones that mention them explicitly:

1. **No schema changes to existing data files.** `data/accounts.json` (list of
   `{id, name, type, balance, ...}`), `data/expenses.xlsx` (openpyxl-driven, no DB), `data/plan.json`,
   `data/categories.json`, `data/networth_history.json` (dict of `"YYYY-MM": value`, net-worth-only,
   **not** per-account) — every one of these keeps its current shape. New data needs a **new file**
   or a new key that old code ignores, never a repurposed/renamed existing field.
2. **Backup-before-migrate stays the convention.** The repo already has a `.bak-<reason>-<date>`
   pattern in `data/` (e.g. `expenses.xlsx.bak-pre-emi-rip`). Any phase that touches persisted data
   follows the same pattern before writing.
3. **Additive routes only.** Every new `/api/*` route is new, not a repurposed existing one. Existing
   routes (`/api/summary`, `/api/accounts/balances`, etc.) keep their current response shape — new
   dashboard widgets consume new endpoints or extend response objects with new keys, never remove/
   rename existing keys those endpoints already return (other code paths may depend on them).
4. **Reuse computed values, don't recompute in parallel.** E.g. the cash-flow donut (Phase 2) must
   read the same income/expense aggregates the existing stat cards use — not a second calculation
   that can drift from the first and show contradictory numbers on the same page.
5. **One phase at a time, smoke-test before the next.** No end-to-end UI test suite exists beyond
   `tests/test_plan.py` (covers `plan.py` bucket math only). After each phase: run `pytest`, then
   manually load `/dashboard`, `/manage`, `/accounts`, `/plan`, `/analytics`, `/settings` and confirm
   no console errors / broken renders before starting the next phase.
6. **Known DOM-ID dependents** (found via grep, current as of this plan) — anything touching these
   IDs must check `interactions.js` / inline `<script>` blocks in the same template for JS that reads
   them: `dashboard.html` → `#stats-row`, `#stat-today`, `#stat-total`, `#stat-avg`, `#stat-count`,
   `#stat-income`, `#stat-net`, `#billing-stats`. Removing/renaming any of these without updating the
   JS that populates them will silently break the dashboard.

---

## Phase 1 — Semantic design-token layer

**What:** Add semantic CSS custom properties (`--fg-default`, `--fg-muted`, `--bg-inset`,
`--border-muted`, `--action-primary-bg`, etc.) in `static/themes.css`, each initially just pointing at
an existing variable (`--fg-default: var(--text)`). Zero visual change on day 1.

**Why:** Every theme currently sets raw values per palette (`--accent`, `--danger`, ...). Fold's
system aliases semantic roles into named color ramps so light/dark is a ramp-swap, not a
per-component rewrite. Adding this layer now means every future component in this plan (credit card
card, analytics donut/insight rows) gets written against semantic names — cheaper to theme correctly
across all 7 palettes, no more raw-hex-in-a-new-component mistakes.

**Compatibility:**
- Purely additive — existing `--accent`, `--text`, `--muted`, etc. are **not removed or renamed**.
  6800+ lines of templates reference them directly; touching those names is the actual risk here,
  not adding new ones alongside.
- No HTML changes, no JS changes. CSS-file-only, all 7 themes × 2 modes get the new block once.

**Effort:** ~1 hour. **Risk:** none if the "don't rename existing vars" rule is followed exactly.

---

## Phase 2 — Dashboard hierarchy rework (`templates/dashboard.html`)

Current: 6-up `.stats-row` grid + separate `.net-worth-hero` + `.acct-balances` cards + `.charts-grid`,
roughly equal visual weight. Fold's pattern: one big number, everything else secondary — validated by
their own redesign case study, which called out "flat numbers" and "redundant elements" as the top
complaints in the pre-redesign version.

### 2.1 — Account mini-trend sparklines

**What:** small trend line on each `.acct-bal-card` (7/30-day balance movement), using Plotly (already
loaded via CDN on this page).

**Compatibility — this needs new data collection, not just a UI change.**
`data/networth_history.json` only stores monthly **total** net worth, not per-account balances — there
is no historical per-account series to backfill from. This phase requires:
- A **new** file, e.g. `data/account_balance_history.json` (e.g. `{account_id: [{date, balance}, ...]}`),
  written to on every balance-affecting mutation going forward.
- `data/accounts.json`'s existing shape (`id/name/type/balance`) is **untouched** — history lives
  alongside it, not inside it.
- Sparklines will show "not enough history yet" for a while after shipping — this is expected, not a
  bug, and should be the empty-state copy (see Phase 7) rather than hiding the widget.

**Effort:** Medium (new tracking hook wherever balance mutations happen in `app.py`/`spreadsheet.py`,
plus the sparkline render). **Risk:** low if the new file is genuinely additive and no existing
balance-write path is modified beyond "also append to the new history file."

### 2.2 — Cash flow as donut, not stat cards

**What:** Replace 2-3 stat cards (whichever currently show income/expense split) with one donut
(income / expense / investment) + numbers as a legend beside it, using data already computed for the
existing stat cards.

**Compatibility:**
- Must consume the **same** aggregate values `#stat-income` / `#stat-net` etc. currently render (check
  `/api/summary` response and the inline `<script>` in `dashboard.html` that populates these IDs) — do
  not write a second computation path.
- If an existing stat card is removed, grep `dashboard.html` and `interactions.js` for its ID first
  (see Guardrails §5) — if any code still targets it, that code needs updating in the same change, not
  left dangling.
- Keep the raw numbers visible next to the donut (as a legend), not donut-only — screen-reader/
  "view as table" fallback pattern this app already uses elsewhere (per README's accessibility pass)
  should extend here, not regress.

**Effort:** Medium. **Risk:** low-medium — the main failure mode is removing a stat card whose ID is
still read by JS elsewhere; mitigated by the grep-first step above.

---

## Phase 3 — Credit card summary card (new component)

**What:** One consolidated card — due date, utilization % (bar, color-shifts amber→red past
70%/90%), upcoming payment amount, current cycle spend — instead of this data being spread across
existing CC stat cards / accounts page.

**Compatibility:**
- This app already computes CC billing-cycle data (per README: "current cycle spend, projected bill,
  previous cycle bill, cycle-over-cycle comparison") — **reuse that existing computation**, don't
  reimplement it. Locate the current function (`app.py`/`spreadsheet.py`, whatever backs
  `#billing-stats`) and feed the new card from it.
- Purely additive UI — no data model changes required, this data already exists.
- Existing `#billing-stats` consumers stay working; the new card is an additional rendering of the
  same underlying numbers, not a replacement of the API response shape.

**Effort:** Medium. **Risk:** low — additive-only, all inputs already exist.

---

## Phase 4 — Transaction detail overlay (verification, not a rewrite)

**What:** Confirm the existing `#edit-modal` / `#sub-modal` / `#delete-modal` in `manage.html` keep
the underlying transaction list visible (dimmed backdrop) behind the modal rather than navigating away
— this is what Fold's redesign added; this app's architecture (modal-overlay pattern already present
in `manage.html`) suggests it may already behave this way.

**Compatibility:** No changes anticipated. If verification shows the modal already preserves list
context, **skip this phase** — nothing to do. If it doesn't, treat as a small CSS/JS fix scoped to the
existing modal, not a new component.

**Effort:** Low (verification) / Low (fix, if needed). **Risk:** none — read-only check first.

---

## Phase 5 — Analytics page overhaul (`templates/analytics.html`)

**Current state:** 4 flat stat cards (This Week / This Month / Last Month / Daily Avg, each with an
up/down comparison) + 4 Plotly charts (category trends line chart, day-of-week bar, top-10-merchants
bar, spending velocity). Functionally complete but reads as a wall of generic charts — exactly the
"flat data presentation" and "low visual clarity" Fold's own redesign case study called out as its
top pre-redesign complaint. This is the page you flagged as "useless now" — it's not missing data, the
data just isn't telling a story.

**What, applying Fold's actual fixes:**
1. **Category breakdown as donut, with the numbers as a legend beside it** — not a replacement for the
   category-trends line chart (that shows change-over-time, keep it), an *addition* showing
   this-period share at a glance. This is Fold's single most-repeated pattern across every screen: big
   number/shape first, supporting detail secondary.
2. **Insight sentences above the charts, not just numbers.** Fold frames stats as short actionable
   lines ("daily trend analysis... savings opportunity identification") rather than bare deltas. E.g.
   turn the existing `#stat-this-month-cmp` up/down indicator into a one-line insight: *"₹X more than
   last month, mostly [top category]"* — reuses data already computed for the stat card and the
   category chart, just narrates it instead of leaving the user to connect the dots.
3. **Top merchants as a list with visual weight per row (bar-in-row, like a mini progress bar behind
   the merchant name), not a separate bar chart.** Matches Fold's transaction-list treatment — visual
   pattern recognition without a context-switch to a different chart type.
4. **Trend indicator consistency.** You already color-code up/down on stat cards (`.up`/`.down`/
   `.neutral` classes exist) — extend that same treatment (colored arrow + %) into the merchants list
   and category rows, so "did this go up or down" reads the same way everywhere on the page.

**Compatibility:**
- **Every number above is already computed** — this phase re-presents existing aggregates, it does
  not introduce new backend calculations. Confirm each new visual pulls from the same source the
  current chart/stat already uses (same rule as Phase 2.2 — no parallel computation path).
- Existing chart IDs (`#chart-cat-trends`, `#chart-dow`, `#chart-merchants`, `#chart-velocity`) and
  stat IDs (`#stat-this-week`, `#stat-this-month`, etc.) — if any are removed/replaced rather than
  supplemented, grep `interactions.js` first per Guardrails §5's pattern (this page wasn't in the
  original grep list — repeat that check here before removing any existing element).
- Keep the "view as table" screen-reader fallback this app already uses elsewhere (per README) for
  any new donut/visual — don't regress accessibility while improving visual hierarchy.

**Effort:** Medium — mostly re-layout and re-presentation of data this page already has, not new
computation. **Risk:** low — additive/re-presentation, same "don't silently remove an ID something
depends on" risk as Phase 2.2, no data-model involvement at all.

---

## Phase 6 — Cmd+K global search

**What:** Lightweight overlay, summonable from any page (not just `/manage`), reusing the filter logic
that already exists behind `#search` in `manage.html`.

**Compatibility:**
- **Extract the existing filter/search logic into `interactions.js`** (shared across pages) rather than
  copy-pasting it into a new overlay — two independent copies of search logic will drift the moment
  one gets a bugfix the other doesn't.
- The existing `#search` input in `manage.html` keeps working as-is; the overlay is a new, additional
  entry point calling the same underlying function, not a replacement.
- Keyboard listener (`keydown` for Cmd/Ctrl+K) needs a check against existing global key handlers (if
  any) in `interactions.js` to avoid stealing a shortcut something else already uses.

**Effort:** Medium. **Risk:** low if the shared-function extraction happens first (avoids the drift
failure mode above).

---

## Phase 7 — Copy / microcopy pass

**What:** Rewrite ~5-8 strings in empty/failure states specifically (first-run dashboard banner,
no-transactions-this-month, no-search-results, draft-parsing failure) with personality — concentrated
there, not spread across labels/buttons/nav (Fold's actual pattern per the teardown, not "voice
everywhere").

**Compatibility:**
- **Text-only changes.** Do not alter the element IDs/classes any JS hooks toggle visibility on — e.g.
  if an empty-state `<div>` is shown/hidden via a class toggle in `interactions.js`, change only the
  text node inside it, not the class name or structure.
- No data/route changes at all. Lowest-risk phase in this entire plan.

**Effort:** Low. **Risk:** near-zero.

---

## Phase 8 — Typography scale formalization (optional)

**What:** Formalize this app's own type scale as named CSS classes (`.text-heading-lg`,
`.text-body-md`, `.text-label-sm`) instead of ad-hoc `font-size` declarations per component — same
discipline as Fold's "Aurora" system (Heading/Body/Label × size × weight), but this app's own two-font
identity (Syne/DM Mono), not a copy of Fold's fonts.

**Compatibility:**
- **Do not do a blanket find-replace of every existing `font-size` in one pass** — with 6800+ lines
  across templates, a mass replace risks subtle spacing/line-height regressions in components that
  were tuned individually. Adopt the new classes incrementally, only in components already being
  touched by other phases (natural opportunity, not a dedicated sweep).

**Effort:** Low, spread over time. **Risk:** low if adopted incrementally as stated, medium if done as
one large mechanical pass.

---

## Priority order (impact vs. effort vs. risk)

| # | Phase | Effort | Risk |
|---|-------|--------|------|
| 1 | Semantic token layer | Low | None |
| 2 | Copy pass, empty/error states | Low | Near-zero |
| 3 | Credit card summary card | Medium | Low |
| 4 | Cash-flow donut | Medium | Low-medium |
| 5 | Analytics page overhaul | Medium | Low |
| 6 | Account mini-trends | Medium | Low |
| 7 | Cmd+K global search | Medium | Low |
| 8 | Typography scale | Low (incremental) | Low |

Ship in roughly this order — each phase is additive on top of the last, and every phase above is
independently revertable (new CSS vars, new files, new routes) without touching what came before it.

Recurring expense tracker (previously Phase 5) — dropped per explicit request, not part of scope.
