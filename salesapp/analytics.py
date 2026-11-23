"""Aggregations, weakest-outlet scoring and the fact sheet the summary is written from."""
from __future__ import annotations

import pandas as pd

MONTHS_ID = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "Mei", 6: "Jun",
             7: "Jul", 8: "Agu", 9: "Sep", 10: "Okt", 11: "Nov", 12: "Des"}


def fmt_idr(x: float) -> str:
    """Short Indonesian rupiah format: Rp 1,73 M / Rp 495,2 jt / Rp 594.000."""
    sign = "-" if x < 0 else ""
    a = abs(x)
    if a >= 1e9:
        s = f"{a / 1e9:,.2f} M"
    elif a >= 1e6:
        s = f"{a / 1e6:,.1f} jt"
    else:
        s = f"{a:,.0f}"
        return f"{sign}Rp {s.replace(',', '.')}"
    return f"{sign}Rp {s.replace(',', 'X').replace('.', ',').replace('X', '.')}"


def fmt_pct(x: float | None, signed: bool = True) -> str:
    if x is None or pd.isna(x):
        return "n/a"
    s = f"{x * 100:+.1f}%" if signed else f"{x * 100:.1f}%"
    return s.replace(".", ",")


def month_label(m: str) -> str:
    p = pd.Period(m, "M")
    return f"{MONTHS_ID[p.month]} {p.year}"


def kpis(df: pd.DataFrame) -> dict:
    gross = df.gross_sales_idr.sum()
    return {
        "net_sales": int(df.net_sales_idr.sum()),
        "gross_sales": int(gross),
        "discount": int(df.discount_idr.sum()),
        "discount_rate": float(df.discount_idr.sum() / gross) if gross else 0.0,
        "cartons": int(df.qty_carton.sum()),
        "invoices": int(df.invoice_no.nunique()),
        "outlets": int(df.outlet_id.nunique()),
    }


def by_dim(df: pd.DataFrame, dim: str) -> pd.DataFrame:
    """Net sales by a dimension with share and month-over-month change (last two months)."""
    months = sorted(df.month.unique())
    g = df.groupby(dim).agg(net_sales=("net_sales_idr", "sum"),
                            cartons=("qty_carton", "sum"),
                            invoices=("invoice_no", "nunique"))
    g["share"] = g.net_sales / g.net_sales.sum() if g.net_sales.sum() else 0
    if len(months) >= 2:
        prev, cur = months[-2], months[-1]
        pm = df.pivot_table(index=dim, columns="month", values="net_sales_idr",
                            aggfunc="sum", fill_value=0)
        g["prev"] = pm[prev]
        g["cur"] = pm[cur]
        g["mom"] = (g.cur - g.prev) / g.prev.where(g.prev != 0)
    return g.sort_values("net_sales", ascending=False).reset_index()


def region_brand_matrix(df: pd.DataFrame) -> pd.DataFrame:
    return df.pivot_table(index="region", columns="brand", values="net_sales_idr",
                          aggfunc="sum", fill_value=0, margins=True, margins_name="Total")


def weakest_outlets(df: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """Score each outlet on two things, lower = weaker:

    - 60%: net sales percentile *within its own outlet type* (a warung is compared with
      warungs, not with grosir), so small formats are not flagged just for being small.
    - 40%: month-over-month growth percentile across all outlets (last two months).
    If only one month is in view, the score is the peer percentile alone.
    """
    months = sorted(df.month.unique())
    o = df.groupby(["outlet_id", "outlet_name", "outlet_type", "region", "branch"]).agg(
        net_sales=("net_sales_idr", "sum"),
        invoices=("invoice_no", "nunique"),
        cartons=("qty_carton", "sum"),
        last_order=("date", "max"),
    ).reset_index()
    if len(months) >= 2:
        prev, cur = months[-2], months[-1]
        pm = df.pivot_table(index="outlet_id", columns="month", values="net_sales_idr",
                            aggfunc="sum", fill_value=0)
        o["prev"] = o.outlet_id.map(pm[prev])
        o["cur"] = o.outlet_id.map(pm[cur])
        first_month = df.groupby("outlet_id").month.min()
        # Outlets that first ordered in the latest month have no fair comparison yet.
        o = o[o.outlet_id.map(first_month) != cur].copy()

    o["peer_pct"] = o.groupby("outlet_type").net_sales.rank(pct=True)
    o["peer_rank"] = o.groupby("outlet_type").net_sales.rank(method="min").astype(int)
    o["peer_count"] = o.groupby("outlet_type").outlet_id.transform("count")

    if len(months) >= 2:
        o["mom"] = (o.cur - o.prev) / o.prev.where(o.prev != 0)
        o["growth_pct"] = o.mom.fillna(-1).rank(pct=True)
        o["score"] = 0.6 * o.peer_pct + 0.4 * o.growth_pct
        prev_l, cur_l = month_label(prev), month_label(cur)
    else:
        o["mom"] = pd.NA
        o["score"] = o.peer_pct
        prev_l = cur_l = None

    o = o.sort_values(["score", "net_sales"]).head(n).reset_index(drop=True)

    def reason(r) -> str:
        parts = [f"peringkat {r.peer_rank} dari {r.peer_count} {r.outlet_type}"]
        if prev_l and pd.notna(r.mom):
            parts.append(f"{cur_l} vs {prev_l} {fmt_pct(r.mom)}")
        parts.append(f"{r.invoices} invoice")
        return "; ".join(parts)

    o["reason"] = o.apply(reason, axis=1)
    return o


def new_outlets(df: pd.DataFrame) -> pd.DataFrame:
    """Outlets whose first order falls in the latest month in view (excluded from scoring)."""
    months = sorted(df.month.unique())
    if len(months) < 2:
        return df.iloc[0:0][["outlet_id", "outlet_name"]]
    first = df.groupby(["outlet_id", "outlet_name", "outlet_type", "branch"]).agg(
        first_order=("date", "min"), net_sales=("net_sales_idr", "sum")).reset_index()
    return first[first.first_order.dt.to_period("M").astype(str) == months[-1]]


def build_facts(df: pd.DataFrame, weak: pd.DataFrame | None = None) -> dict:
    """Plain numbers the summary (template or AI) is written from. The AI never computes."""
    k = kpis(df)
    months = sorted(df.month.unique())
    reg = by_dim(df, "region")
    br = by_dim(df, "brand")
    weak = weakest_outlets(df) if weak is None else weak
    f: dict = {
        "period": f"{df.date.min():%d/%m/%Y} - {df.date.max():%d/%m/%Y}",
        "net_sales": fmt_idr(k["net_sales"]),
        "cartons": f"{k['cartons']:,}".replace(",", "."),
        "invoices": k["invoices"],
        "outlets": k["outlets"],
        "discount_rate": fmt_pct(k["discount_rate"], signed=False),
        "top_region": {"name": reg.iloc[0].region, "net": fmt_idr(reg.iloc[0].net_sales),
                       "share": fmt_pct(reg.iloc[0].share, signed=False)},
        "bottom_region": {"name": reg.iloc[-1].region, "net": fmt_idr(reg.iloc[-1].net_sales),
                          "share": fmt_pct(reg.iloc[-1].share, signed=False)},
        "top_brand": {"name": br.iloc[0].brand, "net": fmt_idr(br.iloc[0].net_sales),
                      "share": fmt_pct(br.iloc[0].share, signed=False)},
        "bottom_brand": {"name": br.iloc[-1].brand, "net": fmt_idr(br.iloc[-1].net_sales),
                         "share": fmt_pct(br.iloc[-1].share, signed=False)},
        "weak_outlets": [
            {"name": r.outlet_name, "type": r.outlet_type, "branch": r.branch,
             "net": fmt_idr(r.net_sales), "mom": fmt_pct(r.mom) if pd.notna(r.mom) else "n/a"}
            for r in weak.itertuples()
        ],
    }
    if len(months) >= 2:
        prev, cur = months[-2], months[-1]
        pv = df[df.month == prev].net_sales_idr.sum()
        cv = df[df.month == cur].net_sales_idr.sum()
        f["mom"] = {"prev_label": month_label(prev), "cur_label": month_label(cur),
                    "prev": fmt_idr(pv), "cur": fmt_idr(cv),
                    "change": fmt_pct((cv - pv) / pv if pv else None)}
        rg = reg.dropna(subset=["mom"]).sort_values("mom")
        bg = br.dropna(subset=["mom"]).sort_values("mom")
        f["region_worst_mom"] = {"name": rg.iloc[0].region, "mom": fmt_pct(rg.iloc[0].mom)}
        f["region_best_mom"] = {"name": rg.iloc[-1].region, "mom": fmt_pct(rg.iloc[-1].mom)}
        f["brand_worst_mom"] = {"name": bg.iloc[0].brand, "mom": fmt_pct(bg.iloc[0].mom)}
        f["brand_best_mom"] = {"name": bg.iloc[-1].brand, "mom": fmt_pct(bg.iloc[-1].mom)}
    return f
