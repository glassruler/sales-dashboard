"""Streamlit dashboard: sales by region & brand, 5 weakest outlets, AI summary + send."""
from __future__ import annotations

import hmac
import json
import os
import time
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from salesapp import notify
from salesapp.ai import ask, summarize
from salesapp.analytics import (build_facts, by_dim, fmt_idr, fmt_pct, kpis, month_label,
                                new_outlets, region_brand_matrix, weakest_outlets)
from salesapp.data import load_sales
from salesapp.report import data_path, send

load_dotenv()
st.set_page_config(page_title="Dashboard Penjualan", page_icon="📊", layout="wide")

# Chart tokens (validated reference palette): single series = blue; polarity = blue/red.
BLUE, ORANGE, RED = "#2a78d6", "#eb6834", "#e34948"
SEQ = [[0, "#cde2fb"], [0.35, "#6da7ec"], [0.7, "#256abf"], [1, "#0d366b"]]
INK, MUTED, GRID = "#52514e", "#898781", "#e1e0d9"


# --------------------------------------------------------------------------- auth
def check_password() -> bool:
    pw = os.getenv("APP_PASSWORD")
    if not pw:
        st.sidebar.warning("APP_PASSWORD belum diisi: dashboard terbuka tanpa login.")
        return True
    if st.session_state.get("auth_ok"):
        return True
    st.title("📊 Dashboard Penjualan")
    with st.form("login"):
        entered = st.text_input("Password", type="password")
        if st.form_submit_button("Masuk"):
            if hmac.compare_digest(entered.encode(), pw.encode()):
                st.session_state.auth_ok = True
                st.rerun()
            st.error("Password salah.")
    return False


if not check_password():
    st.stop()


# --------------------------------------------------------------------------- data
@st.cache_data(show_spinner=False)
def load(path: str, mtime: float):
    return load_sales(path)


path = data_path()
if not Path(path).exists():
    st.error(f"File data tidak ditemukan: {path}. Unggah CSV di sidebar.")
df_all, quality = (load(path, Path(path).stat().st_mtime) if Path(path).exists()
                   else (None, None))

with st.sidebar:
    st.header("Filter")
    lang = st.radio("Bahasa ringkasan", ["id", "en"], horizontal=True,
                    format_func=lambda x: "Indonesia" if x == "id" else "English",
                    index=0 if os.getenv("SUMMARY_LANG", "id") == "id" else 1)
    if df_all is not None:
        dmin, dmax = df_all.date.min().date(), df_all.date.max().date()
        dr = st.date_input("Periode", (dmin, dmax), min_value=dmin, max_value=dmax)
        regions = st.multiselect("Region", sorted(df_all.region.unique()))
        brands = st.multiselect("Brand", sorted(df_all.brand.unique()))
        types = st.multiselect("Tipe outlet", sorted(df_all.outlet_type.unique()))
    st.divider()
    with st.expander("Ganti data (CSV)"):
        up = st.file_uploader("Format kolom sama dengan sales.csv", type="csv")
        if up is not None and st.button("Pakai file ini"):
            try:
                new_df, rep = load_sales(up.getvalue())
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_bytes(up.getvalue())
                st.cache_data.clear()
                st.success(f"{rep.clean_rows} baris dimuat.")
                st.rerun()
            except PermissionError:
                st.error("Folder data tidak bisa ditulis. Di server: "
                         "`sudo chown -R 1000:1000 /opt/sales-dashboard/data`")
            except Exception as e:
                st.error(f"File tidak valid: {e}")

if df_all is None:
    st.stop()

df = df_all
if isinstance(dr, tuple) and len(dr) == 2:
    df = df[(df.date.dt.date >= dr[0]) & (df.date.dt.date <= dr[1])]
if regions:
    df = df[df.region.isin(regions)]
if brands:
    df = df[df.brand.isin(brands)]
if types:
    df = df[df.outlet_type.isin(types)]
if df.empty:
    st.warning("Tidak ada data untuk filter ini.")
    st.stop()


# --------------------------------------------------------------------------- charts
def base_layout(fig: go.Figure, height: int = 320) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=8, r=24, t=8, b=28),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=INK, size=13), bargap=0.35,
        hoverlabel=dict(bgcolor="white", font_color="#0b0b0b"),
        legend=dict(orientation="h", y=1.08, x=0),
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=True, zerolinecolor="#c3c2b7", tickfont_color=MUTED)
    fig.update_yaxes(gridcolor=GRID, tickfont_color=INK, automargin=True)
    return fig


def hbar(g: pd.DataFrame, dim: str) -> go.Figure:
    g = g.sort_values("net_sales")
    fig = go.Figure(go.Bar(
        x=g.net_sales, y=g[dim], orientation="h", marker_color=BLUE,
        text=[f"{fmt_idr(v)} · {fmt_pct(s, False)}" for v, s in zip(g.net_sales, g.share)],
        textposition="outside", textfont_color=INK, cliponaxis=False,
        customdata=[fmt_idr(v) for v in g.net_sales],
        hovertemplate="<b>%{y}</b><br>Net sales %{customdata}<extra></extra>",
    ))
    fig = base_layout(fig, 60 + 42 * len(g))
    # headroom on the right so the outside value labels are never clipped
    fig.update_xaxes(showticklabels=False, showgrid=False, range=[0, g.net_sales.max() * 1.75])
    return fig


def mom_bar(g: pd.DataFrame, dim: str, prev_l: str, cur_l: str) -> go.Figure:
    g = g.dropna(subset=["mom"]).sort_values("mom")
    fig = go.Figure(go.Bar(
        x=g.mom, y=g[dim], orientation="h",
        marker_color=[BLUE if v >= 0 else RED for v in g.mom],
        text=[fmt_pct(v) for v in g.mom], textposition="outside", textfont_color=INK,
        cliponaxis=False,
        customdata=list(zip([fmt_idr(v) for v in g.prev], [fmt_idr(v) for v in g.cur])),
        hovertemplate=f"<b>%{{y}}</b><br>{prev_l}: %{{customdata[0]}}<br>{cur_l}: %{{customdata[1]}}<extra></extra>",
    ))
    fig = base_layout(fig, 60 + 42 * len(g))
    lim = max(abs(g.mom.min()), abs(g.mom.max())) * 1.35
    fig.update_xaxes(tickformat="+.0%", showgrid=True, range=[min(-lim, -0.05), max(lim, 0.05)])
    return fig


def heatmap(m: pd.DataFrame) -> go.Figure:
    core = m.drop(index="Total", columns="Total")
    core = core.loc[core.sum(axis=1).sort_values(ascending=False).index,
                    core.sum().sort_values(ascending=False).index]
    txt = [[f"{v / 1e6:.1f} jt".replace(".", ",") for v in row] for row in core.values]
    fig = go.Figure(go.Heatmap(
        z=core.values, x=core.columns, y=core.index, colorscale=SEQ, xgap=2, ygap=2,
        text=txt, texttemplate="%{text}", showscale=False,
        hovertemplate="<b>%{y} · %{x}</b><br>Net sales Rp %{text}<extra></extra>",
    ))
    fig = base_layout(fig, 90 + 46 * len(core))
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(showgrid=False, side="top", tickfont_color=INK, automargin=True, zeroline=False)
    fig.update_layout(margin=dict(t=40))
    return fig


# --------------------------------------------------------------------------- whatsapp
def wa_section() -> None:
    """Linked sender (QR / switch number) and the editable recipient list."""
    if not os.getenv("WA_GATEWAY_URL"):
        return
    st.markdown("**WhatsApp pengirim**")
    stt = notify.whatsapp_status()
    if stt.get("connected"):
        me = str(stt.get("me") or "").split(":")[0].split("@")[0]
        st.success(f"Tersambung sebagai +{me}")
        with st.popover("Ganti nomor pengirim"):
            st.write("Nomor ini akan diputus. Setelah itu QR baru muncul untuk HP lain.")
            if st.button("Ya, putuskan", type="primary"):
                try:
                    notify.whatsapp_logout()
                    st.toast("Diputus. Tunggu QR baru...")
                except Exception as e:
                    st.error(f"Gagal: {e}")
                time.sleep(4)
                st.rerun()
    else:
        st.warning(f"Belum tersambung: {stt.get('error') or stt.get('state', '')}")
        qr = notify.whatsapp_qr_png()
        if qr:
            st.image(qr, caption="Scan dari HP pengirim: WhatsApp > Perangkat tertaut > Tautkan perangkat",
                     width=260)
            st.caption("QR berganti tiap ~20 detik. Kalau gagal, klik Cek lagi.")
        elif stt.get("state") in ("reconnecting", "starting"):
            st.caption("Menyiapkan QR baru, tunggu beberapa detik lalu klik Cek lagi.")
        if st.button("Cek lagi"):
            st.rerun()

    st.markdown("**Penerima WhatsApp**")
    st.caption("Nomor 08xx / 62xx, atau id grup (...@g.us). Centang *Aktif* untuk ikut menerima, "
               "termasuk kiriman otomatis terjadwal.")
    rows = pd.DataFrame(notify.load_recipients(), columns=["name", "number", "active"])
    edited = st.data_editor(
        rows, num_rows="dynamic", hide_index=True, width="stretch", key="wa_recipients",
        column_config={
            "name": st.column_config.TextColumn("Nama"),
            "number": st.column_config.TextColumn("Nomor / id grup", required=True),
            "active": st.column_config.CheckboxColumn("Aktif", default=True),
        },
    )
    c1, c2 = st.columns([1, 1])
    if c1.button("💾 Simpan penerima", width="stretch"):
        try:
            recs = edited.fillna({"name": "", "active": True}).to_dict("records")
            saved = notify.save_recipients(recs)
            st.success(f"Disimpan: {sum(r['active'] for r in saved)} aktif dari {len(saved)}.")
            time.sleep(1)
            st.rerun()
        except ValueError as e:
            st.error(f"Belum disimpan, perbaiki dulu: {e}")
        except PermissionError:
            st.error("Folder data tidak bisa ditulis oleh aplikasi. Jalankan di server: "
                     "`sudo chown -R 1000:1000 /opt/sales-dashboard/data`")
    if stt.get("connected") and c2.button("Lihat grup WhatsApp", width="stretch"):
        try:
            import requests
            r = requests.get(f"{os.getenv('WA_GATEWAY_URL').rstrip('/')}/groups",
                             headers={"Authorization": f"Bearer {os.getenv('WA_GATEWAY_TOKEN', '')}"},
                             timeout=20)
            groups = r.json()
            if groups:
                st.dataframe(pd.DataFrame(groups).rename(columns={"subject": "Grup", "id": "Id (salin ke Nomor)"}),
                             hide_index=True, width="stretch")
            else:
                st.info("Nomor pengirim belum ada di grup mana pun.")
        except Exception as e:
            st.error(f"Gagal mengambil grup: {e}")


# --------------------------------------------------------------------------- page
months = sorted(df.month.unique())
k = kpis(df)
weak = weakest_outlets(df)
facts = build_facts(df, weak)

st.title("📊 Dashboard Penjualan")
st.caption(f"Periode {facts['period']} · {k['outlets']} outlet · sumber: {Path(path).name}")

c = st.columns(5)
mom = facts.get("mom")
c[0].metric("Net sales", fmt_idr(k["net_sales"]))
if mom:
    c[1].metric(f"{mom['cur_label']} vs {mom['prev_label']}", mom["cur"], mom["change"])
else:
    c[1].metric("Bulan", month_label(months[0]))
c[2].metric("Karton", f"{k['cartons']:,}".replace(",", "."))
c[3].metric("Invoice", f"{k['invoices']:,}".replace(",", "."))
c[4].metric("Diskon / gross", fmt_pct(k["discount_rate"], signed=False))

t1, t2, t3, t4, t5 = st.tabs(["Region & Brand", "⚠️ 5 Outlet Terlemah", "📝 Ringkasan & Kirim",
                              "💬 Tanya AI", "Kualitas Data"])

with t1:
    reg, br = by_dim(df, "region"), by_dim(df, "brand")
    a, b = st.columns(2)
    with a:
        st.subheader("Net sales per region")
        st.plotly_chart(hbar(reg, "region"), width="stretch", theme=None)
    with b:
        st.subheader("Net sales per brand")
        st.plotly_chart(hbar(br, "brand"), width="stretch", theme=None)
    if len(months) >= 2:
        pl, cl = month_label(months[-2]), month_label(months[-1])
        a, b = st.columns(2)
        with a:
            st.subheader(f"Perubahan region, {cl} vs {pl}")
            st.plotly_chart(mom_bar(reg, "region", pl, cl), width="stretch", theme=None)
        with b:
            st.subheader(f"Perubahan brand, {cl} vs {pl}")
            st.plotly_chart(mom_bar(br, "brand", pl, cl), width="stretch", theme=None)
    st.subheader("Region × brand (net sales)")
    m = region_brand_matrix(df)
    st.plotly_chart(heatmap(m), width="stretch", theme=None)
    with st.expander("Lihat sebagai tabel"):
        st.dataframe(m.map(lambda v: f"{v:,.0f}".replace(",", ".")), width="stretch")

with t2:
    st.subheader("5 outlet terlemah")
    st.caption("Skor = 60% posisi net sales dibanding outlet sejenis (warung vs warung, grosir vs "
               "grosir) + 40% pertumbuhan bulan terakhir vs bulan sebelumnya. Outlet yang baru "
               "mulai order di bulan terakhir tidak dinilai.")
    show = weak.assign(
        **{"Net sales": weak.net_sales.map(fmt_idr),
           "Perubahan": weak.mom.map(lambda v: fmt_pct(v) if pd.notna(v) else "n/a"),
           "Order terakhir": weak.last_order.dt.strftime("%d/%m/%Y")}
    ).rename(columns={"outlet_id": "ID", "outlet_name": "Outlet", "outlet_type": "Tipe",
                      "region": "Region", "branch": "Cabang", "reason": "Alasan"})
    st.dataframe(show[["ID", "Outlet", "Tipe", "Region", "Cabang", "Net sales", "Perubahan",
                       "Order terakhir", "Alasan"]], hide_index=True, width="stretch")
    # Outlet names are not unique (e.g. three different "Toko Anugerah"): always key on outlet_id.
    labels = {r.outlet_id: f"{r.outlet_name} · {r.branch} ({r.outlet_id})" for r in weak.itertuples()}
    sel = st.selectbox("Detail outlet", list(labels), format_func=labels.get)
    od = df[df.outlet_id == sel]
    a, b = st.columns(2)
    a.dataframe(od.groupby("brand").net_sales_idr.sum().sort_values(ascending=False)
                .map(fmt_idr).rename("Net sales"), width="stretch")
    b.dataframe(od.groupby(["month", "salesman"]).agg(invoice=("invoice_no", "nunique"),
                net=("net_sales_idr", "sum")).assign(net=lambda x: x.net.map(fmt_idr)),
                width="stretch")
    nw = new_outlets(df)
    if len(nw):
        st.info("Outlet baru (tidak dinilai): " + ", ".join(
            f"{r.outlet_name} ({r.branch}, mulai {r.first_order:%d/%m})" for r in nw.itertuples()))

with t3:
    st.subheader("Ringkasan untuk sales manager")
    use_ai = st.toggle("Pakai AI (Gemini / Cloudflare)", value=True)
    key = json.dumps([facts, lang, use_ai], sort_keys=True, default=str)
    if st.button("🔄 Buat ulang") or st.session_state.get("summary_key") != key:
        with st.spinner("Menulis ringkasan..."):
            text, src = summarize(facts, lang=lang, use_ai=use_ai)
        st.session_state.update(summary_key=key, summary=text, summary_src=src)
    header = "📊 Ringkasan Penjualan" if lang == "id" else "📊 Sales Summary"
    msg = st.text_area("Pesan (bisa diedit sebelum dikirim)",
                       f"{header}\n\n{st.session_state.summary}", height=230)
    st.caption(f"Sumber teks: {st.session_state.summary_src}. Semua angka dihitung oleh Python; "
               "AI hanya merangkai kalimat dan dicek agar tidak menambah angka sendiri.")

    st.markdown("**Kirim sekarang**")
    a, b = st.columns(2)
    with a:
        tg_ok = notify.telegram_configured()
        if st.button("Kirim ke Telegram", disabled=not tg_ok, width="stretch"):
            st.write(send(msg, ["telegram"]))
        if not tg_ok:
            st.caption("Isi TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID di .env")
    with b:
        stt = notify.whatsapp_status() if os.getenv("WA_GATEWAY_URL") else {"connected": False}
        n_active = len(notify.active_wa_recipients())
        wa_ok = bool(stt.get("connected")) and n_active > 0
        if st.button(f"Kirim ke WhatsApp ({n_active} penerima)", disabled=not wa_ok, width="stretch"):
            with st.spinner("Mengirim..."):
                st.write(send(msg, ["whatsapp"]))
        if stt.get("connected") and not n_active:
            st.caption("Tambahkan penerima di bagian **Penerima WhatsApp** di bawah.")
    wa_section()
    cron = os.getenv("REPORT_CRON", "0 8 * * 1")
    st.caption(f"Kirim otomatis: jadwal cron `{cron}` (WIB) ke {os.getenv('REPORT_CHANNELS', 'telegram,whatsapp')}. "
               "Pengiriman otomatis selalu memakai seluruh data, bukan filter di layar.")

with t4:
    st.subheader("Tanya data")
    st.caption("Jawaban hanya berdasarkan tabel ringkas di bawah (sesuai filter aktif).")
    ctx = "\n\n".join([
        "FAKTA:\n" + json.dumps(facts, ensure_ascii=False),
        "REGION:\n" + by_dim(df, "region").round(3).to_csv(index=False),
        "BRAND:\n" + by_dim(df, "brand").round(3).to_csv(index=False),
        "OUTLET_TYPE:\n" + by_dim(df, "outlet_type").round(3).to_csv(index=False),
        "SALESMAN:\n" + by_dim(df, "salesman").round(3).to_csv(index=False),
        "REGION_X_BRAND:\n" + region_brand_matrix(df).to_csv(),
        "OUTLET:\n" + df.groupby(["outlet_id", "outlet_name", "outlet_type", "branch"]).net_sales_idr.sum()
        .reset_index().to_csv(index=False),
    ])
    q = st.chat_input("Contoh: brand apa yang turun paling dalam di Jawa Barat?")
    for role, content in st.session_state.get("chat", []):
        st.chat_message(role).write(content)
    if q:
        st.chat_message("user").write(q)
        with st.spinner("..."):
            ans, src = ask(q, ctx, lang)
        st.chat_message("assistant").write(ans)
        st.caption(f"via {src}")
        st.session_state.setdefault("chat", []).extend([("user", q), ("assistant", ans)])

with t5:
    st.subheader("Pembersihan data otomatis")
    q_ = quality
    st.markdown(f"""
- Baris mentah: **{q_.raw_rows}**, setelah dibersihkan: **{q_.clean_rows}**
- Duplikat persis dibuang: **{q_.duplicates_removed}**
- Nama region diseragamkan (mis. `Jabar`, `JAWA BARAT` → `Jawa Barat`): **{q_.region_values_fixed}** baris
- Nama outlet dirapikan (spasi berlebih): **{q_.outlet_names_trimmed}** baris
- Salesman kosong (diisi "(Tidak diketahui)"): **{q_.missing_salesman}** baris
- Baris retur (qty negatif, tetap dihitung mengurangi net sales): **{q_.return_lines}** ({fmt_idr(q_.return_value_idr)})
- Selisih hitungan qty×harga / gross−diskon: **{q_.math_mismatches}**
""")
    for n in q_.notes:
        st.write("• " + n)
