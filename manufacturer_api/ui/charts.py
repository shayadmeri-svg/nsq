"""Plotly chart builders for the manufacturer dashboard.

Dashboard charts, all styled to the scientific tone: Okabe-Ito colorway,
white background, thin muted axes, no chartchrome.

- ``donut_issue_by_type``  — Figma 'Issue by type' pie/donut.
- ``line_over_time``        — Figma 'Issue over time' monthly line.
- ``bar_by_form``           — Figma dosage-form bar (Tablet/Capsule/Syrup/
  Suspension/Other buckets).
- ``heatmap_form_vs_issue`` — form × failure-category count matrix.

All compute live from the scoped tenant frame; no hardcoded counts.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from ui.palette import (
    BORDER,
    CHART_COLORWAY,
    HEATMAP_SCALE,
    PALE_GREY,
    TEXT,
    TEXT_MUTED,
    WHITE,
    failure_category_color,
    form_color,
)


def _base_layout(fig: go.Figure, height: int = 320) -> go.Figure:
    """Apply the shared scientific styling (white surface, muted axes)."""
    fig.update_layout(
        height=height,
        margin=dict(l=24, r=16, t=16, b=24),
        paper_bgcolor=WHITE,
        plot_bgcolor=WHITE,
        font=dict(color=TEXT, family="Inter, system-ui, sans-serif", size=12),
        showlegend=False,
    )
    return fig


def donut_issue_by_type(df: pd.DataFrame) -> go.Figure | None:
    """Donut of NSQ failure categories (``Failure_Category``)."""
    if df.empty or "Failure_Category" not in df.columns:
        return None
    counts = df["Failure_Category"].fillna("Unknown").value_counts()
    if counts.empty:
        return None
    labels = list(counts.index)
    values = list(counts.values)
    colors = [failure_category_color(l) for l in labels]
    fig = go.Figure(go.Pie(
        labels=labels, values=values,
        hole=0.55,
        marker=dict(colors=colors, line=dict(color=WHITE, width=2)),
        textinfo="label+percent",
        textposition="outside",
        sort=False,
    ))
    fig = _base_layout(fig, height=340)
    return fig


def line_over_time(df: pd.DataFrame) -> go.Figure | None:
    """Monthly NSQ alert volume line from ``Parsed_Date``."""
    if df.empty or "Parsed_Date" not in df.columns:
        return None
    dates = df["Parsed_Date"].dropna()
    if dates.empty:
        return None
    monthly = (dates.dt.to_period("M").value_counts()
               .sort_index())
    x = [str(p) for p in monthly.index]
    y = list(monthly.values)
    fig = go.Figure(go.Scatter(
        x=x, y=y, mode="lines+markers",
        line=dict(color=CHART_COLORWAY[0], width=2.5),
        marker=dict(color=CHART_COLORWAY[0], size=7,
                    line=dict(color=WHITE, width=1.5)),
        hovertemplate=" %{x}: %{y} alerts<extra></extra>",
    ))
    fig.update_yaxes(
        tickmode="linear", dtick=1,
        gridcolor=PALE_GREY, zerolinecolor=PALE_GREY,
        tickfont=dict(color=TEXT_MUTED),
    )
    fig.update_xaxes(
        gridcolor=PALE_GREY, tickfont=dict(color=TEXT_MUTED),
        tickangle=-30,
    )
    fig = _base_layout(fig, height=300)
    return fig


# Map raw ``Form type`` values onto the Figma's dosage-form buckets.
# The Figma lists Tablet / Capsule / Syrup / Suspension / Other. The
# enriched frame's Form type collapses Syrup+Suspension into one value
# ("Syrup/Suspension"), so we keep that as a single bucket rather than
# arbitrarily splitting it; Ointment/Cream and anything unmapped → Other.
_FORM_BUCKET = {
    "Tablet": "Tablet",
    "Capsule": "Capsule",
    "Syrup/Suspension": "Syrup/Suspension",
    "Ointment/Cream": "Other",
}


def _bucket_form(value: str) -> str:
    if not isinstance(value, str):
        return "Other"
    return _FORM_BUCKET.get(value.strip(), "Other")


def bar_by_form(df: pd.DataFrame) -> go.Figure | None:
    """Bar of NSQ alerts by dosage form bucket."""
    if df.empty or "Form type" not in df.columns:
        return None
    buckets = df["Form type"].apply(_bucket_form).value_counts()
    if buckets.empty:
        return None
    # Stable Figma order, only buckets that are present.
    order = ["Tablet", "Capsule", "Syrup/Suspension", "Suspension", "Other"]
    labels = [b for b in order if b in buckets.index] + [
        b for b in buckets.index if b not in order]
    values = [int(buckets[b]) for b in labels]
    colors = [form_color(b) for b in labels]
    fig = go.Figure(go.Bar(
        x=labels, y=values,
        marker_color=colors,
        marker_line=dict(color=WHITE, width=1.5),
        hovertemplate=" %{x}: %{y} alerts<extra></extra>",
        width=0.6,
    ))
    fig.update_yaxes(
        tickmode="linear", dtick=1,
        gridcolor=PALE_GREY, zerolinecolor=PALE_GREY,
        tickfont=dict(color=TEXT_MUTED),
    )
    fig.update_xaxes(
        gridcolor=PALE_GREY, tickfont=dict(color=TEXT_MUTED),
    )
    fig = _base_layout(fig, height=300)
    return fig


def heatmap_form_vs_issue(df: pd.DataFrame) -> go.Figure | None:
    """Count matrix of dosage-form bucket (rows) × failure category (cols).

    Cell value = number of NSQ alerts for that form/issue combination.
    Useful for spotting whether a failure mode concentrates in one
    dosage form. Sequential white→blue scale (scientific, single-hue).
    """
    if df.empty or "Form type" not in df.columns or "Failure_Category" not in df.columns:
        return None
    form = df["Form type"].apply(_bucket_form)
    issue = df["Failure_Category"].fillna("Unknown")
    matrix = pd.crosstab(form, issue)
    if matrix.empty:
        return None

    # Stable row order (Figma form buckets first), keep only present rows.
    row_order = ["Tablet", "Capsule", "Syrup/Suspension", "Suspension", "Other"]
    rows = [r for r in row_order if r in matrix.index] + [
        r for r in matrix.index if r not in row_order]
    # Columns sorted by total alerts descending (dominant failure modes left).
    cols = list(matrix.sum(axis=0).sort_values(ascending=False).index)
    matrix = matrix.loc[rows, cols]

    z = matrix.values
    fig = go.Figure(go.Heatmap(
        z=z,
        x=[str(c) for c in matrix.columns],
        y=[str(r) for r in matrix.index],
        zmin=0,
        colorscale=HEATMAP_SCALE,
        showscale=False,
        text=z,
        texttemplate="%{text}",
        textfont=dict(color=TEXT),
        hovertemplate="%{y} × %{x}: %{z} alerts<extra></extra>",
        xgap=2, ygap=2,
    ))
    fig.update_xaxes(
        side="top",
        tickfont=dict(color=TEXT_MUTED, size=11),
        gridcolor=WHITE, linecolor=BORDER,
    )
    fig.update_yaxes(
        tickfont=dict(color=TEXT_MUTED, size=11),
        gridcolor=WHITE, linecolor=BORDER,
        autorange="reversed",
    )
    fig = _base_layout(fig, height=300)
    # Heatmaps read better with a touch more height for axis labels.
    fig.update_layout(margin=dict(l=24, r=16, t=48, b=16))
    return fig