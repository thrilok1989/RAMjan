"""📰 Cash Maerket Discord Bot — market event relay + market Q&A chatbot.

Relays the app's Market Event Engine feed (put/call writing, S/R breaks,
CVD reversals, OI walls, ...) into a Discord channel — WARNING/ALERT
severity only, so routine INFO-level events don't spam the channel — and
answers commands with the latest market state. The Streamlit app persists
events to the Supabase `market_events` table and the market picture to
`vob_app_state`; this bot polls both — the two processes never talk
directly, so the bot can run anywhere Python runs (your PC during market
hours is fine).

SETUP (one time)
1. Create the bot:
   https://discord.com/developers/applications → New Application → Bot
   → Reset Token (copy it) → enable "MESSAGE CONTENT INTENT" under
   Privileged Gateway Intents.
2. Invite it to your server:
   OAuth2 → URL Generator → scopes: bot → permissions: Send Messages,
   Read Message History → open the generated URL, pick your server.
3. Get the channel id for alerts:
   Discord Settings → Advanced → Developer Mode ON → right-click the
   channel → Copy Channel ID.
4. Install deps + run:
   pip install -r requirements-bot.txt
   export DISCORD_BOT_TOKEN="..."       # from step 1
   export DISCORD_CHANNEL_ID="..."      # from step 3
   export SUPABASE_URL="https://xxxx.supabase.co"
   export SUPABASE_KEY="anon-key"       # same values as the app's secrets
   python discord_bot.py

COMMANDS (type in any channel the bot can read)
  !picture  — Market Picture: regime, probabilities, levels, playbook
  !bias     — 14-leg tabulation verdict + speed split
  !news     — News Bias verdict + latest headlines
  !help     — this list
"""
import asyncio
import json
import os
import re

import discord
from supabase import create_client

TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
CHANNEL_ID = int(os.environ.get("DISCORD_CHANNEL_ID", "0") or 0)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
POLL_S = 15
STATE_FILE = ".discord_bot_state.json"

if not TOKEN:
    raise SystemExit("Set DISCORD_BOT_TOKEN (see docstring for setup steps).")
if not (SUPABASE_URL and SUPABASE_KEY):
    raise SystemExit("Set SUPABASE_URL and SUPABASE_KEY (same as the app's secrets).")

sb = create_client(SUPABASE_URL, SUPABASE_KEY)


def load_payload():
    """Newest vob_app_state row's payload (the app upserts it every few
    minutes) — used by the !picture/!bias/!news commands."""
    try:
        res = (sb.table("vob_app_state").select("payload,updated_at")
               .order("updated_at", desc=True).limit(1).execute())
        rows = res.data or []
        return (rows[0] or {}).get("payload") or {} if rows else {}
    except Exception as e:
        print(f"supabase read failed: {e}")
        return {}


def _last_posted_id():
    # key is "last_event_id" (not the old outbox's "last_id") so a stale
    # state file from before the market_events migration can't collide
    # with the fresh id space and cause real events to be skipped
    try:
        with open(STATE_FILE) as f:
            return int(json.load(f).get("last_event_id", -1))
    except Exception:
        return -1


def _save_posted_id(i):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({"last_event_id": int(i)}, f)
    except Exception:
        pass


def fmt_picture(p):
    if not p:
        return "🗺️ Market picture not available yet — is the app running?"
    lines = [f"🗺️ **MARKET PICTURE: {p.get('regime', '?')}**",
             f"⬆️ Up {p.get('p_up', 0)}% · ⬇️ Down {p.get('p_down', 0)}% · "
             f"↔️ Sideways {p.get('p_side', 0)}%"]
    res, sup = p.get("res"), p.get("sup")
    if res:
        lines.append(f"🔴 Resistance ₹{res.get('price', 0):.0f} "
                     f"({res.get('src_count', 0)} sources)")
    if p.get("oi_ceiling"):
        lines.append(f"🧱 CE wall ₹{p['oi_ceiling'][0]:.0f} "
                     f"({p['oi_ceiling'][1]:.1f}L OI · resistance)")
    if p.get("oi_floor"):
        lines.append(f"🧱 PE wall ₹{p['oi_floor'][0]:.0f} "
                     f"({p['oi_floor'][1]:.1f}L OI · support)")
    if sup:
        lines.append(f"🟢 Support ₹{sup.get('price', 0):.0f} "
                     f"({sup.get('src_count', 0)} sources)")
    ab = p.get("atm_bias")
    if ab:
        lines.append(f"📊 **ATM Bias** (₹{ab.get('strike', 0):.0f}): {ab.get('verdict', '?')} "
                     f"(Score {ab.get('score', 0):+.0f}) · OI {ab.get('oi', '?')} · "
                     f"ChgOI {ab.get('chgoi', '?')} · Pressure {ab.get('pressure', '?')}")
    db = p.get("doi_bias")
    if db:
        lines.append(f"🔄 **ΔOI Bias (ATM±2)**: {db.get('label', '?')} · "
                     f"CE {db.get('ce_chg', 0) / 1e5:+.1f}L vs PE {db.get('pe_chg', 0) / 1e5:+.1f}L")
    fm = p.get("fut_mfp")
    if fm:
        lines.append(f"💰 **Futures MFP** ({fm.get('symbol', '?')}): {fm.get('bias', '?')} · "
                     f"POC ₹{fm.get('poc', 0):.0f} · VAH ₹{fm.get('vah', 0):.0f} · "
                     f"VAL ₹{fm.get('val', 0):.0f}")
    gb = p.get("global_bias")
    if gb:
        lines.append(f"🌍 **Global Bias**: {gb.get('label', '?')} ({gb.get('score', 0):+.1f})")
    nb = p.get("news_bias")
    if nb:
        lines.append(f"📰 **News Bias**: {nb.get('label', '?')} "
                     f"(net {nb.get('net', 0):+d} / {nb.get('n', 0)} headlines)")
    cb = p.get("commodity_bias")
    if cb:
        lines.append(f"🛢️ **Commodity Regime**: {cb.get('regime', '?')}")
    if p.get("playbook"):
        lines.append(f"🎯 **Playbook:** {p['playbook']}")
    return "\n".join(lines)


def fmt_bias(b):
    if not b:
        return "🧮 14-leg bias not available yet — is the app running?"
    sp = b.get("speed") or {}
    def _s(k, name):
        d = sp.get(k) or {}
        return f"{name}: {d.get('label', '—')} (net {d.get('net', 0):+d})"
    return ("🧮 **14-LEG TABULATION** · "
            f"**{b.get('label', '?')}** · {b.get('bull', 0)}↑ / {b.get('bear', 0)}↓ "
            f"(net {b.get('net', 0):+d}) · spot ₹{b.get('spot', 0):.1f} "
            f"· as of {b.get('as_of', '?')} IST\n"
            f"{_s('fast', '🚀 Fast')} · {_s('lag', '🐢 Lagging')} · "
            f"{_s('mis', '🌫️ Misguiding')}")


def fmt_news(n):
    if not n:
        return "📰 News bias not available yet — is the app running?"
    out = [f"📰 **NEWS BIAS: {n.get('label', '?')}** · net {n.get('net', 0):+d} "
           f"across {n.get('n', 0)} headlines · as of {n.get('as_of', '?')} IST"]
    for r in (n.get("rows") or [])[:6]:
        age = r.get("age_min")
        age_s = (f"{age}m" if isinstance(age, int) and age < 120
                 else (f"{age // 60}h" if isinstance(age, int) else "—"))
        out.append(f"{r.get('em', '⚪')} [{age_s}] {r.get('title', '')[:150]}")
    return "\n".join(out)


HELP = ("**Cash Maerket bot commands**\n"
        "`!picture` — market regime, probabilities, levels, playbook\n"
        "`!bias` — 14-leg tabulation verdict + speed split\n"
        "`!news` — news bias + latest headlines\n"
        "Market events (put/call writing, S/R breaks, CVD reversals, OI "
        "walls, ...) post here automatically while the app is running — "
        "WARNING/ALERT severity only.")

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


_SEVERITY_EMOJI = {"info": "🟢", "warning": "🟡", "alert": "🔴"}


def _format_event(item):
    """Mirror mios_v5.market_events.format_discord_message()'s format
    without importing the app package — this bot is meant to run
    standalone, possibly outside the repo checkout."""
    color = _SEVERITY_EMOJI.get(item.get("severity"), "🟡")
    ts = item.get("event_time") or ""
    time_str = ts[11:16] if len(ts) >= 16 else ""
    return f"{color} {time_str}  {item.get('headline', '')}\n└─ {item.get('detail', '')}"


def _fetch_new_events(last_id, limit=50):
    """New market_events rows (id > last_id), WARNING/ALERT severity only —
    routine INFO events (volume spikes, OI-wall proximity, ...) stay in the
    app/Supabase but don't reach Discord. Oldest first, chronological post
    order."""
    try:
        res = (sb.table("market_events")
               .select("id,event_time,event_type,severity,headline,detail")
               .gt("id", last_id).in_("severity", ["warning", "alert"])
               .order("id").limit(limit).execute())
        return res.data or []
    except Exception as e:
        print(f"market_events read failed: {e}")
        return []


async def relay_alerts():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID) if CHANNEL_ID else None
    if channel is None:
        print("DISCORD_CHANNEL_ID not set/found — alert relay off, commands still work.")
        return
    last_id = _last_posted_id()
    if last_id < 0:
        # first run: skip the backlog, only post events from now on
        try:
            res = sb.table("market_events").select("id").order("id", desc=True).limit(1).execute()
            rows = res.data or []
            last_id = int(rows[0]["id"]) if rows else 0
        except Exception as e:
            print(f"market_events read failed: {e}")
            last_id = 0
        _save_posted_id(last_id)
    while not client.is_closed():
        try:
            for item in _fetch_new_events(last_id):
                iid = int(item["id"])
                await channel.send(_format_event(item)[:1900])
                last_id = iid
                _save_posted_id(last_id)
                await asyncio.sleep(1)
        except Exception as e:
            print(f"relay error: {e}")
        await asyncio.sleep(POLL_S)


@client.event
async def on_ready():
    print(f"logged in as {client.user} · relay channel: {CHANNEL_ID or 'OFF'}")
    client.loop.create_task(relay_alerts())


@client.event
async def on_message(message):
    if message.author.bot:
        return
    cmd = re.split(r"\s+", message.content.strip().lower() or "")[0]
    if cmd not in ("!picture", "!bias", "!news", "!help"):
        return
    if cmd == "!help":
        await message.channel.send(HELP)
        return
    payload = await asyncio.to_thread(load_payload)
    if cmd == "!picture":
        await message.channel.send(fmt_picture(payload.get("_market_picture"))[:1900])
    elif cmd == "!bias":
        await message.channel.send(fmt_bias(payload.get("_leg_bias_summary"))[:1900])
    elif cmd == "!news":
        await message.channel.send(fmt_news(payload.get("_news_bias"))[:1900])


client.run(TOKEN)
