"""Render query results as Plotly charts (server-emitted spec + tiny script)."""
from __future__ import annotations

import json

from fasthtml.common import Div, Script, NotStr, Table, Thead, Tbody, Tr, Th, Td, P

PALETTE = ["#2563eb", "#16a34a", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#65a30d"]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def plotly_payload(cols, data, chart_type="bar", x_col=None, y_col=None, height=300):
    """Build a JSON-safe Plotly figure shared by pages and streamed chat."""
    if not cols or not data:
        return None
    xi = cols.index(x_col) if x_col in cols else 0
    yi = cols.index(y_col) if y_col in cols else (1 if len(cols) > 1 else 0)
    xs = [r[xi] for r in data]
    ys = [_num(r[yi]) for r in data]

    if chart_type == "line":
        trace = {"type": "scatter", "mode": "lines+markers", "x": xs, "y": ys,
                 "line": {"color": PALETTE[0], "width": 2}, "marker": {"size": 5}}
        traces = [trace]
    elif chart_type == "pie":
        traces = [{"type": "pie", "labels": xs, "values": ys, "hole": 0.45,
                   "marker": {"colors": PALETTE}}]
    elif chart_type == "row":
        traces = [{"type": "bar", "orientation": "h", "y": xs, "x": ys,
                   "marker": {"color": PALETTE[0]}}]
    else:  # bar
        traces = [{"type": "bar", "x": xs, "y": ys,
                   "marker": {"color": [PALETTE[i % len(PALETTE)] for i in range(len(xs))]}}]

    layout = {"margin": {"t": 10, "r": 10, "b": 50, "l": 60}, "height": height,
              "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(0,0,0,0)",
              "font": {"size": 11, "color": "#48526e"},
              "xaxis": {"automargin": True}, "yaxis": {"automargin": True},
              "showlegend": chart_type == "pie"}
    return {"data": traces, "layout": layout}


def plotly(div_id: str, cols, data, chart_type="bar", x_col=None, y_col=None, height=300):
    """Return (Div, Script) that draws a Plotly chart for the given result set."""
    figure = plotly_payload(cols, data, chart_type, x_col, y_col, height)
    if figure is None:
        return Div(P("No data.", style="color:var(--text-mute);"), cls="plot")
    spec = json.dumps(figure)
    return (Div(id=div_id, cls="plot"),
            Script(NotStr(
                f"(function(){{var s={spec};"
                f"Plotly.newPlot('{div_id}',s.data,s.layout,{{displayModeBar:false,responsive:true}});}})();"),
                **{"data-plot": "1"}))


def result_table(cols, data, max_rows=100):
    if not cols:
        return P("No columns.", style="color:var(--text-mute);")
    num_cols = set()
    for ci in range(len(cols)):
        if data and all(isinstance(_num(r[ci]), float) for r in data[:20]):
            num_cols.add(ci)
    head = Tr(*[Th(c, cls="num" if i in num_cols else "") for i, c in enumerate(cols)])
    body = []
    for r in data[:max_rows]:
        body.append(Tr(*[Td(f"{r[i]:,}" if i in num_cols and isinstance(r[i], (int, float)) else str(r[i]),
                            cls="num" if i in num_cols else "") for i in range(len(cols))]))
    extra = P(f"{len(data)} rows (showing {min(len(data),max_rows)})",
              style="color:var(--text-mute);font-size:12px;margin-top:6px;") if len(data) > max_rows else None
    return Div(Table(Thead(head), Tbody(*body), cls="tbl"), extra)
