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


def test_recipients_roundtrip(tmp_path, monkeypatch):
    from salesapp import notify
    monkeypatch.setenv("RECIPIENTS_PATH", str(tmp_path / "r.json"))
    monkeypatch.setenv("WA_TO", "0812-3456-7890")
    assert notify.load_recipients() == [{"name": "", "number": "6281234567890", "active": True}]
    saved = notify.save_recipients([
        {"name": "Andi", "number": "+62 812 3456 7890", "active": True},
        {"name": "dup", "number": "081234567890", "active": True},       # same number -> dropped
        {"name": "Grup", "number": "120363012345678901@g.us", "active": False},
        {"name": "", "number": "", "active": True},                       # empty row -> ignored
    ])
    assert [r["number"] for r in saved] == ["6281234567890", "120363012345678901@g.us"]
    assert notify.active_wa_recipients() == ["6281234567890"]
    with pytest.raises(ValueError):
        notify.save_recipients([{"name": "x", "number": "12", "active": True}])


def test_data_path_falls_back_to_root_sales_csv(tmp_path, monkeypatch):
    from salesapp import report
    monkeypatch.delenv("DATA_PATH", raising=False)
    monkeypatch.setattr(report, "ROOT", tmp_path)
    (tmp_path / "sales.csv").write_text("x")
    assert report.data_path() == str(tmp_path / "sales.csv")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "sales.csv").write_text("x")
    assert report.data_path() == str(tmp_path / "data" / "sales.csv")
