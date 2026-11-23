# Dashboard Penjualan

## Run it in 2 minutes

Needs Python 3.11+. No API keys, database or Docker required.

```powershell
pip install -r requirements.txt
streamlit run app.py
```

Then open http://localhost:8501 in your browser. The sample data is already in `data/sales.csv`; to use your own
copy instead, put it in this folder as `sales.csv` (and delete `data/sales.csv`), or upload it from the sidebar.

What to look at:
- **Region & Brand**: net sales per region and brand, October vs September change, region × brand heatmap
- **⚠️ 5 Outlet Terlemah**: the 5 weakest outlets and why each was flagged
- **📝 Ringkasan & Kirim**: the one-paragraph summary for a sales manager, plain text ready for Telegram
- **Kualitas Data**: what was cleaned in the CSV (duplicates, region spellings, a return invoice, ...)

Without API keys the summary is written from a template. To let AI write it, copy `.env.example` to `.env`
and add a `GEMINI_API_KEY` (or Cloudflare `CF_ACCOUNT_ID` + `CF_API_TOKEN`). Sending to Telegram needs
`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`; WhatsApp needs the gateway (see *Deploy* below).

Tests: `python -m pytest -q`

---

Streamlit app for the Sep–Oct 2026 sales sample (`data/sales.csv`):

- Net sales by **region** and **brand**, month-over-month change, region × brand heatmap
- **5 weakest outlets**, scored fairly (see below)
- A **one-paragraph summary** for a sales manager, written by AI (Gemini Flash or
  Cloudflare Workers AI) from numbers Python computes, with a template fallback
- Send the summary to **Telegram** and **WhatsApp** (Baileys), by button or on a schedule
- "Ask the data" chat, password login, CSV upload for new months

## How it works

```
data/sales.csv ─► salesapp/data.py (clean) ─► salesapp/analytics.py (numbers, weakest outlets, facts)
                                                   │
                       salesapp/ai.py ◄────────────┘  Gemini → Cloudflare → template
                            │                          (output rejected if it adds numbers)
            app.py (Streamlit) / salesapp/scheduler.py
                            │
           Telegram Bot API ┴ wa-gateway (Node + Baileys, internal only)
```

**Data cleaning** (shown in the "Kualitas Data" tab): unwraps rows quoted as one field, strips
the BOM, unifies region spellings (`Jabar`, `JAWA BARAT` → `Jawa Barat`), trims outlet names,
removes 3 exact duplicates, labels 5 blank salesmen, keeps the 1 return invoice (`RTR…`) as a
negative line. Outlet **names are not unique** (three different "Toko Anugerah"), so everything
keys on `outlet_id`.

**Weakest outlets** = lowest score where
60% = net-sales percentile *within the same outlet type* (warung vs warung, grosir vs grosir) and
40% = last-month vs previous-month growth percentile. Outlets whose first order is in the last
month are listed as new, not scored.

## Run locally

```powershell
python -m pip install -r requirements.txt
copy .env.example .env    # then fill in keys
python -m streamlit run app.py
```

```powershell
python -m pytest -q
python -m salesapp.report --dry-run      # print the message without sending
```

WhatsApp gateway locally (optional): `cd wa-gateway; npm install; npm start`, then scan the QR
shown in the app's "Ringkasan & Kirim" tab.

## Configuration (`.env`)

| Variable | What |
|---|---|
| `APP_PASSWORD` | dashboard login |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Google AI Studio key; default `gemini-2.5-flash` |
| `CF_ACCOUNT_ID`, `CF_API_TOKEN`, `CF_MODEL` | Cloudflare Workers AI (token needs *Workers AI: Read*) |
| `AI_PROVIDER` | which to try first: `gemini` or `cloudflare` |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | bot from @BotFather; add the bot to the group, comma-separate several chats |
| `WA_TO` | `0812…`/`62812…` or a group id `…@g.us` (list groups: `GET /groups` on the gateway) |
| `WA_GATEWAY_TOKEN` | shared secret between app and gateway |
| `REPORT_CRON`, `REPORT_CHANNELS` | e.g. `0 8 * * 1` = Monday 08:00 WIB |
| `SITE_ADDRESS` | your domain for automatic HTTPS, or `:80` |

## Deploy to a VPS (Docker)

Services: `app` (Streamlit), `scheduler`, `wa` (Baileys, not exposed), `caddy` (HTTPS).

1. Point your domain's A record at the VPS (optional; without it use `SITE_ADDRESS=:80`).
2. On the VPS, add a read-only **deploy key** for this private repo
   (`ssh-keygen -t ed25519`, paste the `.pub` into GitHub → repo → Settings → Deploy keys).
3. ```bash
   git clone git@github.com:<owner>/<repo>.git sales-dashboard && cd sales-dashboard
   bash deploy/setup-vps.sh   # installs Docker, creates .env, starts everything
   ```
4. Open the site → "Ringkasan & Kirim" → scan the WhatsApp QR once
   (WhatsApp → Linked devices). The session is kept in the `wa_auth` volume.

Update later: upload the new archive to `/tmp`, then `sudo bash /opt/sales-dashboard/deploy/install-update.sh` (keeps `.env`, `data/` and the WhatsApp session, and fixes `data/` ownership). Logs: `docker compose logs -f`.

**Server already running Nginx** (the default now): the app listens on `127.0.0.1:8501` only, `deploy/setup-vps.sh` installs `deploy/nginx-duakelinci.conf`, then run `certbot --nginx -d duakelinci.webbros.my.id`. On a bare server with no web server, use Caddy instead: `docker compose --profile caddy up -d`.

### WhatsApp caveat
Baileys is an unofficial WhatsApp Web client. Use a **dedicated number**, keep volume low
(a few messages a week is fine), and expect to re-scan the QR if WhatsApp logs the device out.
For guaranteed delivery at scale, use the official WhatsApp Business Cloud API instead.
