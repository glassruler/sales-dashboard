"""Load and clean the raw sales CSV.

The export has quirks that a plain ``pd.read_csv`` mishandles:
- a UTF-8 BOM and every whole row wrapped in one pair of double quotes
- region spelled several ways (``Jabar``, ``JAWA BARAT``, ``JABODETABEK``)
- trailing spaces in some outlet names
- exact duplicate lines
- blank salesman
- return invoices (``RTR...``) with negative quantities (kept: they reduce net sales)
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

REGION_ALIASES = {
    "JABAR": "Jawa Barat",
    "JATENG": "Jawa Tengah",
    "JATIM": "Jawa Timur",
    "JABODETABEK": "Jabodetabek",
    "JAWA BARAT": "Jawa Barat",
    "JAWA TENGAH": "Jawa Tengah",
    "JAWA TIMUR": "Jawa Timur",
    "SUMATERA": "Sumatera",
    "SUMATRA": "Sumatera",
    "KALIMANTAN": "Kalimantan",
}

TEXT_COLS = ["invoice_no", "region", "branch", "outlet_id", "outlet_name",
             "outlet_type", "salesman", "brand", "sku"]
NUM_COLS = ["qty_carton", "price_per_carton_idr", "gross_sales_idr",
            "discount_idr", "net_sales_idr"]
UNKNOWN_SALESMAN = "(Tidak diketahui)"


@dataclass
class QualityReport:
    raw_rows: int = 0
    clean_rows: int = 0
    duplicates_removed: int = 0
    region_values_fixed: int = 0
    outlet_names_trimmed: int = 0
    missing_salesman: int = 0
    return_lines: int = 0
    return_value_idr: int = 0
    math_mismatches: int = 0
    notes: list[str] = field(default_factory=list)


def _read_raw(source: str | Path | bytes) -> pd.DataFrame:
    if isinstance(source, (bytes, bytearray)):
        text = source.decode("utf-8-sig")
    else:
        text = Path(source).read_text(encoding="utf-8-sig")
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Each row may be wrapped in one pair of quotes: unwrap it, then parse normally.
        if line.startswith('"') and line.endswith('"') and line.count('"') == 2:
            line = line[1:-1]
        rows.append(line)
    reader = csv.reader(io.StringIO("\n".join(rows)))
    header, *body = list(reader)
    header = [h.strip().lower() for h in header]
    return pd.DataFrame(body, columns=header)


def load_sales(source: str | Path | bytes) -> tuple[pd.DataFrame, QualityReport]:
    df = _read_raw(source)
    rep = QualityReport(raw_rows=len(df))

    raw_outlet = df["outlet_name"].astype("string")
    for c in TEXT_COLS:
        df[c] = df[c].astype("string").str.strip().replace("", pd.NA)
    trimmed = int((raw_outlet != df["outlet_name"]).fillna(False).sum())
    for c in NUM_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype("int64")
    df["date"] = pd.to_datetime(df["date"].str.strip(), errors="coerce")
    bad_dates = int(df["date"].isna().sum())
    if bad_dates:
        rep.notes.append(f"{bad_dates} baris dengan tanggal tidak valid dibuang.")
        df = df.dropna(subset=["date"])

    # Region: canonical names
    before = df["region"].copy()
    df["region"] = df["region"].map(lambda r: REGION_ALIASES.get(str(r).upper(), str(r).title()))
    rep.region_values_fixed = int((before != df["region"]).sum())

    # Outlet name: one canonical name per outlet_id (most frequent, already stripped)
    canon = df.groupby("outlet_id")["outlet_name"].agg(lambda s: s.mode().iat[0])
    rep.outlet_names_trimmed = trimmed + int((df["outlet_name"] != df["outlet_id"].map(canon)).sum())
    df["outlet_name"] = df["outlet_id"].map(canon)

    rep.missing_salesman = int(df["salesman"].isna().sum())
    df["salesman"] = df["salesman"].fillna(UNKNOWN_SALESMAN)

    dup = df.duplicated(keep="first")
    rep.duplicates_removed = int(dup.sum())
    df = df[~dup].copy()

    rep.math_mismatches = int(
        ((df.qty_carton * df.price_per_carton_idr) != df.gross_sales_idr).sum()
        + ((df.gross_sales_idr - df.discount_idr) != df.net_sales_idr).sum()
    )

    df["is_return"] = df["invoice_no"].str.upper().str.startswith("RTR") | (df["qty_carton"] < 0)
    rep.return_lines = int(df["is_return"].sum())
    rep.return_value_idr = int(df.loc[df["is_return"], "net_sales_idr"].sum())

    df["month"] = df["date"].dt.to_period("M").astype(str)
    rep.clean_rows = len(df)
    return df.reset_index(drop=True), rep
