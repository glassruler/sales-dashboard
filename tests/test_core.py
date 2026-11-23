from pathlib import Path

import pytest

from salesapp.ai import template_summary, unknown_numbers
from salesapp.analytics import build_facts, fmt_idr, weakest_outlets
from salesapp.data import load_sales

DATA = Path(__file__).resolve().parents[1] / "data" / "sales.csv"


@pytest.fixture(scope="module")
def loaded():
    return load_sales(DATA)


def test_cleaning(loaded):
    df, rep = loaded
    assert rep.raw_rows == 1891
    assert rep.duplicates_removed == 3
    assert set(df.region) == {"Jabodetabek", "Jawa Barat", "Jawa Tengah", "Jawa Timur",
                              "Sumatera", "Kalimantan"}
    assert df.groupby("outlet_id").outlet_name.nunique().max() == 1
    assert rep.return_lines == 1 and rep.return_value_idr < 0
    assert rep.math_mismatches == 0


def test_weakest_excludes_new_outlets(loaded):
    df, _ = loaded
    w = weakest_outlets(df)
    assert len(w) == 5
    assert "Warung Sumber Makmur" not in set(w.outlet_name)  # first order in October
    assert w.score.is_monotonic_increasing
    assert w.outlet_id.is_unique  # names repeat across outlets ("Toko Anugerah" x3); ids must not


def test_summary_has_no_invented_numbers(loaded):
    df, _ = loaded
    f = build_facts(df)
    for lang in ("id", "en"):
        assert unknown_numbers(template_summary(f, lang), f) == []
    assert unknown_numbers("naik 99,9% ke Rp 9,9 M", f)


def test_fmt_idr():
    assert fmt_idr(1_727_965_000) == "Rp 1,73 M"
    assert fmt_idr(495_827_800) == "Rp 495,8 jt"
    assert fmt_idr(594_000) == "Rp 594.000"
    assert fmt_idr(-528_000) == "-Rp 528.000"
