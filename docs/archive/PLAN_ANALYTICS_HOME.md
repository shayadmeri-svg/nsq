# Analytics Home Page — anime.js User Journey Plan

> **Goal:** Replace the analytics app's current entry with a scroll-driven, anime.js-animated landing experience that surfaces NSQ risk as a political heat map of India, then transitions into the existing dashboard. bhak

---

## 1. What we are building

A single-page, scroll-animated **Analytics Home** that sits in front of the existing analytics dashboard:

1. **Hero section** — product selector (default `Paracetamol`), headline, scroll cue.
2. **Political map of India** — heat map of NSQ alert density by manufacturing state/region.
   - Filters: product name, time window, failure type, form type.
   - Complete Indian map: India states colored by alert count; **Gilgit-Baltistan, Pakistan, Aksai Chin** shown as grey, non-selectable disputed/foreign territories with dotted outlines.
3. **Correlation explorer** — scroll-animated table comparing two selected dimensions from:
   - Issue / Failure category
   - Dosage form
   - Testing lab
   - Default pair: `Issue` vs `Form` for the selected product.
4. **Product risk card** — for the selected product (default `Paracetamol`):
   - probable causes list,
   - potential solutions list rendered **blurred** until the user clicks "Reveal" or signs in.
5. **Contact pill** — sticky, rounded pill button floating in the analytics area that opens a simple contact form.
6. **Dashboard gateway** — at the bottom, a CTA that takes the user into the existing analytics dashboard.

---

## 2. Approach: Streamlit-hosted, anime.js inside `components.html`

Streamlit is the existing deployment target (`analytics/app.py`, port 8501). Rather than add a separate server, we will embed the animated home page as a tall HTML island using `streamlit.components.v1.html`.

### Why this approach

- **Fits current stack:** no new container, no new port, no reverse-proxy changes.
- ** anime.js works:** the HTML island loads anime.js from CDN and runs IntersectionObserver-driven scroll animations inside its own scrollable container.
- **Data is live:** Python prepares the aggregated JSON, passes it into the HTML/JS via a `window.NSQ_DATA` injection, so the heat map and correlation table reflect the current Redis/CDSCO snapshot.
- **Backwards compatible:** the existing dashboard tabs remain untouched; the home page is a new top-level view you can toggle to/from.

### Alternative considered

Create a separate FastAPI/Flask static site (`analytics-site/`). Rejected because it needs a new service, port, and compose entry; the requested "home page for analytics" should live inside the existing analytics app.

---

## 3. Files to create / modify

### New files

| Path | Purpose |
|------|---------|
| `analytics/landing.py` | Streamlit module that renders the home page: loads data, builds the JSON payload, embeds the anime.js HTML island, and exposes the contact form. |
| `analytics/static/home.html` | The full HTML/CSS/JS landing page. Self-contained, reads `window.NSQ_DATA`, drives anime.js scroll animations, renders the D3/Leaflet/Plotly map and correlation table. |
| `analytics/static/india_complete.geojson` | Combined GeoJSON: existing Indian states + Pakistan + Gilgit-Baltistan + Aksai Chin polygons (simplified, greyed out). |
| `analytics/static/home.css` | Optional stylesheet referenced by `home.html`. |
| `analytics/shared/geo_data.py` | Helper to load/combine GeoJSON and attach NSQ alert counts per region. |

### Modified files

| Path | Change |
|------|--------|
| `analytics/app.py` | Add a view switcher at the top: default to **Home** landing, with a nav button/tab to enter the existing dashboard. Existing tabs stay as-is. |
| `analytics/Dockerfile` | Copy the new `static/` folder and `landing.py` into the image. |
| `analytics/requirements.txt` | No new Python deps if we use D3/Plotly via CDN; optional `jinja2` if we prefer templating the HTML. |

---

## 4. UI/UX design

### Section 1 — Hero

- Full-width, dark gradient background.
- Title: "NSQ Risk Intelligence for Indian Manufacturing".
- Product search pill: default value `Paracetamol`; fuzzy-matches against product ontology.
- Animated subtitle cycles through: region, time, product name, type.
- Scroll-down chevron with anime.js pulse animation.

### Section 2 — Political heat map

- Left 25%: filter panel.
  - Product selector (linked to hero).
  - Time slider/period picker (`Reporting Month & Year`).
  - Failure type multi-select (`Failure_Category_Primary`).
  - Form type multi-select.
  - Drug type multi-select.
  - "Reset" and "Enter Dashboard" buttons.
- Right 75%: interactive SVG/Leaflet map.
  - Indian states colored on a red heat scale by alert count.
  - **Gilgit-Baltistan, Pakistan, Aksai Chin**: filled `#e5e7eb`, stroke `#9ca3af` dashed, no hover tooltip, labelled as "Disputed / Other".
  - Hover tooltip: state name, alert count, top 3 products, top failure category.
  - Click a state: scrolls to Section 3 pre-filtered by that state.

### Section 3 — Correlation explorer

- Two dropdowns:
  - Dimension A: `Issue`, `Form`, `Testing Lab`.
  - Dimension B: `Issue`, `Form`, `Testing Lab`.
  - Default A=`Issue`, B=`Form`.
- Animated table/matrix:
  - Rows = Dimension A values.
  - Columns = Dimension B values.
  - Cells = NSQ alert count, color-coded (heat scale).
- Product badge at top: "Showing correlations for **Paracetamol**".
- Clicking a cell expands a small panel with representative records.

### Section 4 — Product risk card

- Header: "Paracetamol — probable causes & potential solutions".
- Left: probable causes (visible).
  - e.g. "Dissolution failure dominates", "High-temperature compression", "Wet granulation variability".
- Right: potential solutions list rendered with `filter: blur(6px)` and a "Reveal solutions" CTA.
  - On click, anime.js fades blur to 0 and unlocks the list.

### Section 5 — Contact & dashboard gateway

- Sticky pill "Contact us" fixed bottom-right inside the HTML island.
  - Opens a modal: name, email, company, message, submit.
- Final CTA: "Open full analytics dashboard" → switches Streamlit view to the existing dashboard.

---

## 5. Animation strategy with anime.js

All animations are triggered by an `IntersectionObserver` watching sections as they enter the viewport of the tall HTML island.

| Trigger | Animation |
|---------|-----------|
| Hero load | Title fade-in + translateY, chevron infinite bounce. |
| Map section enters | Map container fade/scale in; state polygons stagger-fill from left to right. |
| Filter change | Map colors animate with anime.js color transition. |
| Correlation section enters | Table rows/cells stagger-slide up; cell heat colors pulse once. |
| Reveal solutions | Blur filter animates from 8px to 0px over 600 ms. |
| Contact pill hover | Scale 1.05 + shadow lift. |

The HTML island is `height=3500px` (configurable) and scrollable, giving anime.js full control of scroll events.

---

## 6. Map data strategy

### Existing asset

`analytics/india_states_slim.geojson` already has Indian state polygons keyed by `properties.NAME_1`.

### New asset

Create `analytics/static/india_complete.geojson` by combining:

1. The existing Indian states (keep `type: "india_state"`, name from `NAME_1`).
2. **Pakistan** (simplified admin-0 polygon, `type: "neighbour", name: "Pakistan"`).
3. **Gilgit-Baltistan** (simplified polygon clipped to the disputed area, `type: "disputed", name: "Gilgit-Baltistan"`).
4. **Aksai Chin** (simplified disputed-area polygon, `type: "disputed", name: "Aksai Chin"`).

Source: Natural Earth 1:110m admin-0 and admin-1 (public domain), simplified with `mapshaper`/geojson tools. We will not claim boundaries; we only visually grey them out.

### Coloring rules

- `type == "india_state"` → heat scale by alert count.
- `type in ("neighbour", "disputed")` → fill `#e5e7eb`, stroke `#9ca3af`, dashed.

---

## 7. Data aggregation backend (`landing.py`)

`landing.py` will:

1. Call `load_and_preprocess_data()` from `app.py` (or refactor the loader into `shared/data_loader.py` so both modules import it cleanly).
2. Aggregate by:
   - `Mfg_State` → alert count, top products, top failure category.
   - Product → counts by state, form, issue, lab, month.
3. Build `NSQ_DATA` JSON:
   - `state_counts`, `product_list`, `time_options`, `failure_options`, `form_options`, `lab_options`, `drug_type_options`.
   - `default_product`: `"Paracetamol"`.
   - `product_correlations[product_key]`: pre-computed cross-tabs for issue×form, issue×lab, form×lab.
   - `risk_cards[product_key]`: probable causes + potential solutions (rules-based from top failure categories and research profiles).
4. Render `components.html` with the JSON injected.

---

## 8. Additional fields and filters proposed for the graphs

Based on the existing derived columns, we will add these filters to the map and correlation sections:

| Field | Filter type | Why useful |
|-------|-------------|------------|
| `Reporting Month & Year` | Time range slider / multi-select | Temporal trend and seasonality. |
| `Failure_Category_Primary` | Multi-select | Focus on dissolution, sterility, assay, etc. |
| `Form` / `Form type` | Multi-select | Link dosage form to defect type. |
| `Drug type` | Multi-select | Therapeutic-category risk profiling. |
| `Indication` | Multi-select | Disease-area concentration. |
| `Mfg_State` | Multi-select / map click | Regional manufacturing risk. |
| `Mfg_Company_Canonical` | Search / multi-select | Manufacturer-level accountability. |
| `Reporting by Lab/State` | Multi-select | Testing-lab reporting bias. |
| `Recall Class` | Placeholder toggle | Future recall-class overlay once data is available. |
| `Is_Dissolution` | Toggle | Quick focus on dissolution failures. |

For the graphs we will also expose:

- **Alert density per million population** (optional, if state population data is added).
- **Alert rate by company** (alerts / distinct products per company).
- **Month-over-month trend** for the selected product.
- **Top co-occurring failure categories** for the selected product.

---

## 9. Implementation sequence

### Step A — Refactor shared loader
1. Move `load_and_preprocess_data()` and helpers from `app.py` to `analytics/shared/data_loader.py`.
2. Update `app.py` to import from the shared module.
3. Verify the existing dashboard still works (syntax check + manual smoke test).

### Step B — GeoJSON for complete map
4. Generate/download simplified polygons for Pakistan, Gilgit-Baltiland, and Aksai Chin.
5. Merge them with the existing India GeoJSON into `analytics/static/india_complete.geojson`.
6. Validate the combined GeoJSON renders in a standalone HTML snippet.

### Step C — Landing HTML/JS
7. Build `analytics/static/home.html` with:
   - anime.js CDN, D3.js or Leaflet CDN for the map, simple vanilla JS for the correlation table.
   - All sections and animations described above.
   - Blurred-solutions interaction.
8. Build `analytics/static/home.css` for layout and the contact pill.

### Step D — Streamlit landing module
9. Implement `analytics/landing.py`:
   - Load and aggregate data.
   - Render `components.html` with `NSQ_DATA`.
   - Handle contact-form submission (write to session state or a simple log).
10. Add the home/dashboard view switcher to `app.py`.

### Step E — Packaging & deployment
11. Update `analytics/Dockerfile` to copy `static/` and `landing.py`.
12. Run syntax checks and a local Streamlit smoke test.
13. Update `justfile` with a `run-analytics` recipe if not present.

---

## 10. Open questions / decisions for you

1. **Map library:** Should the map be **D3.js** (full custom SVG, easier to anime.js-fill) or **Leaflet** (familiar tile-based, but animation is harder)? I recommend **D3.js** for the anime.js integration.
2. **Disputed territories:** Do you want labels inside the grey areas (e.g. "Gilgit-Baltistan", "Aksai Chin", "Pakistan") or just grey shapes with a legend? I recommend labels + legend.
3. **Solutions blur:** Should revealing solutions require any action (click), or should they auto-reveal when the section scrolls into view? I recommend click-to-reveal for a premium/exclusive feel.
4. **Contact form destination:** Where should the contact form submit? Options:
   - Write to a Redis key (`nsq:contact:<timestamp>`).
   - Send email via a configurable SMTP/`mailto:`.
   - Just log to Streamlit session state / console.
   I recommend **Redis key** for persistence, with a fallback to console log.
5. **Default product:** `Paracetamol` as requested — confirm or change?

---

## 11. Definition of done

- `app.py` opens on the animated home page by default.
- Map shows Indian states with heat colors and GB/PAK/Aksai Chin greyed out.
- Default product is Paracetamol; product selector updates map + correlation table + risk card.
- Correlation table supports Issue / Form / Testing Lab selections with scroll animation.
- Probable causes visible; potential solutions start blurred and reveal on click.
- Sticky "Contact us" pill is present and functional.
- Existing dashboard remains reachable and intact.
- Docker image builds and serves the new static assets.

---

*Plan version 1.0 — 2026-07-30*
