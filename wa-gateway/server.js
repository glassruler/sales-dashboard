// Minimal WhatsApp gateway on Baileys. The Python app calls it over HTTP.
//   GET  /status   -> { connected, state, me }
//   GET  /qr.png   -> QR to link the device (only while not connected)
//   GET  /groups   -> [{ id, subject }]  (find a group JID for WA_TO)
//   POST /send     -> { to: "62812..." | "0812..." | "<id>@g.us", text }
//   POST /logout   -> unlink this number; a new QR appears for another phone
// Every request needs "Authorization: Bearer $WA_GATEWAY_TOKEN".
import fs from 'node:fs'
import path from 'node:path'
import express from 'express'
import pino from 'pino'
import QRCode from 'qrcode'
import makeWASocket, {
  Browsers, DisconnectReason, fetchLatestBaileysVersion, useMultiFileAuthState,
} from '@whiskeysockets/baileys'

const PORT = Number(process.env.PORT || 3000)
const TOKEN = process.env.WA_GATEWAY_TOKEN || ''
const AUTH_DIR = process.env.WA_AUTH_DIR || './auth'
const logger = pino({ level: process.env.LOG_LEVEL || 'info' })

if (!TOKEN) logger.warn('WA_GATEWAY_TOKEN kosong: gateway tidak terlindungi')

let sock = null
let state = 'starting'
let lastQr = null
let me = null

// Never let one bad event kill the gateway (Docker would restart-loop it).
process.on('uncaughtException', e => logger.error(e, 'uncaughtException'))
process.on('unhandledRejection', e => logger.error(e, 'unhandledRejection'))

// AUTH_DIR is a Docker volume mount point: it cannot be removed itself, only emptied.
function clearAuth () {
  try {
    fs.mkdirSync(AUTH_DIR, { recursive: true })
    for (const f of fs.readdirSync(AUTH_DIR)) {
      fs.rmSync(path.join(AUTH_DIR, f), { recursive: true, force: true })
    }
    logger.warn('Sesi WhatsApp dihapus')
  } catch (e) {
    logger.error(e, 'gagal menghapus sesi')
  }
}

function scheduleStart (ms = 3000) {
  setTimeout(() => start().catch(e => { logger.error(e, 'start failed'); scheduleStart(10000) }), ms)
}

async function start () {
  const { state: auth, saveCreds } = await useMultiFileAuthState(AUTH_DIR)
  const { version } = await fetchLatestBaileysVersion().catch(() => ({ version: undefined }))
  const s = makeWASocket({
    auth,
    version,
    logger: logger.child({ mod: 'baileys' }, { level: 'warn' }),
    browser: Browsers.ubuntu('Sales Summary'),
    markOnlineOnConnect: false,
    syncFullHistory: false,
  })
  sock = s
  state = 'starting'
  s.ev.on('creds.update', saveCreds)
  s.ev.on('connection.update', ({ connection, lastDisconnect, qr }) => {
    if (s !== sock) return // events from an old socket after a restart
    if (qr) {
      lastQr = qr
      state = 'waiting_for_qr_scan'
      logger.info('QR baru tersedia di GET /qr.png')
    }
    if (connection === 'open') {
      state = 'connected'
      lastQr = null
      me = s.user?.id || null
      logger.info({ me }, 'WhatsApp tersambung')
    }
    if (connection === 'close') {
      const code = lastDisconnect?.error?.output?.statusCode
      me = null
      lastQr = null
      if (code === DisconnectReason.loggedOut) {
        logger.warn('Perangkat di-logout (dari HP atau tombol Ganti nomor): minta QR baru')
        clearAuth()
      }
      state = 'reconnecting'
      sock = null
      scheduleStart(code === DisconnectReason.loggedOut ? 1000 : 3000)
    }
  })
}

function toJid (to) {
  to = String(to || '').trim()
  if (to.includes('@')) return to
  let d = to.replace(/\D/g, '')
  if (d.startsWith('0')) d = '62' + d.slice(1) // Indonesian local format
  if (d.length < 8) throw new Error('nomor tidak valid')
  return `${d}@s.whatsapp.net`
}

const app = express()
app.use(express.json({ limit: '64kb' }))
app.use((req, res, next) => {
  if (TOKEN && req.get('authorization') !== `Bearer ${TOKEN}`) {
    return res.status(401).json({ error: 'unauthorized' })
  }
  next()
})

app.get('/status', (_req, res) => res.json({ connected: state === 'connected', state, me }))

app.get('/qr.png', async (_req, res) => {
  if (!lastQr) return res.status(404).json({ error: 'tidak ada QR', state })
  res.type('png').send(await QRCode.toBuffer(lastQr, { width: 320, margin: 2 }))
})

app.get('/groups', async (_req, res) => {
  if (state !== 'connected') return res.status(503).json({ error: 'belum tersambung', state })
  try {
    const groups = await sock.groupFetchAllParticipating()
    res.json(Object.values(groups).map(g => ({ id: g.id, subject: g.subject })))
  } catch (e) {
    res.status(500).json({ error: String(e.message || e) })
  }
})

app.post('/logout', async (_req, res) => {
  const s = sock
  try {
    // Normal path: WhatsApp confirms, the 'close' handler clears the session and restarts.
    if (s && state === 'connected') await s.logout()
    else throw new Error('not connected')
  } catch (e) {
    // Not connected / logout refused: clear the session ourselves and restart for a fresh QR.
    logger.warn({ err: String(e.message || e) }, 'logout fallback')
    clearAuth()
    if (s && s === sock) {
      sock = null
      try { s.end(undefined) } catch {}
    }
    state = 'reconnecting'
    me = null
    lastQr = null
    scheduleStart(1000)
  }
  res.json({ ok: true, state: 'reconnecting' })
})

app.post('/send', async (req, res) => {
  if (state !== 'connected') return res.status(503).json({ error: 'belum tersambung', state })
  const { to, text } = req.body || {}
  if (!text || typeof text !== 'string') return res.status(400).json({ error: 'text wajib diisi' })
  try {
    const jid = toJid(to)
    if (jid.endsWith('@s.whatsapp.net')) {
      const [r] = await sock.onWhatsApp(jid)
      if (!r?.exists) return res.status(404).json({ error: `${to} tidak terdaftar di WhatsApp` })
    }
    const sent = await sock.sendMessage(jid, { text })
    res.json({ ok: true, to: jid, id: sent?.key?.id })
  } catch (e) {
    logger.error(e, 'send failed')
    res.status(500).json({ error: String(e.message || e) })
  }
})

app.listen(PORT, () => logger.info(`wa-gateway di port ${PORT}`))
scheduleStart(0)
