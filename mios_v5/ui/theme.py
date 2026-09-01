"""MIOS V6 — the dashboard palette.

A trading screen is read in a lit room, at a glance, under time pressure. The
original palette leaned on GitHub-dark greys (`#8fa1b3`, `#5d6b7d`) for labels,
engine attributions and every explanatory line — which is most of the words on
the screen. On a `#0d1117` card those sit around 4:1 contrast, fine for prose
and wrong for a panel a trader has to scan in two seconds.

Every muted tone was lifted one band. Nothing structural changed: the accent
colours (bull green, bear red, warning amber) are untouched, so the *meaning*
of a colour is exactly what it was — only the greys got brighter.

    INK        #ffffff   headline values, the number you came for
    BRIGHT     #edf3f9   primary text
    BODY       #dfe7f0   explanatory sentences
    MUTED      #cfd9e6   labels, secondary detail
    LABEL      #c4d0de   inline sub-labels
    MICRO      #b3c2d4   uppercase micro-labels
    ATTRIB     #9fb0c4   engine attributions ("Stage 42 Acceptance")
    FAINT      #93a5ba   the dimmest thing allowed on screen

Semantic accents, unchanged:

    BULL       #00ff88   BULL_SOFT  #17c98b
    BEAR       #ff4444   BEAR_SOFT  #ff6666
    WARN       #ffd000   ALERT      #ff9500   DANGER  #ff2d55
    INFO       #4da6ff   VIOLET     #a78bfa   MINT    #7fe8b0

Surfaces:

    CARD_BG    #0d1117   CARD_BORDER #1e2836
    PANEL_BG   #0f1622   GRID        #161b22

Panels still write hex inline — retrofitting every f-string to constants would
be a large diff for no behavioural gain. This module is the reference: new
panels should use these names, and anything dimmer than `FAINT` does not belong
on a screen someone trades from.
"""

from __future__ import annotations

INK = "#ffffff"
BRIGHT = "#edf3f9"
BODY = "#dfe7f0"
MUTED = "#cfd9e6"
LABEL = "#c4d0de"
MICRO = "#b3c2d4"
ATTRIB = "#9fb0c4"
FAINT = "#93a5ba"

BULL, BULL_SOFT = "#00ff88", "#17c98b"
BEAR, BEAR_SOFT = "#ff4444", "#ff6666"
WARN, ALERT, DANGER = "#ffd000", "#ff9500", "#ff2d55"
INFO, VIOLET, MINT = "#4da6ff", "#a78bfa", "#7fe8b0"

CARD_BG, CARD_BORDER = "#0d1117", "#1e2836"
PANEL_BG, GRID = "#0f1622", "#161b22"

#: the greys this replaced, so a stray one is recognisable in review
RETIRED = ("#4d5b6d", "#5d6b7d", "#66788c", "#7f8ea3", "#8fa1b3", "#aeb9c7")


# ══════════════════════════════════════════════════════════════════════
#  the shared maps — one meaning, one colour
# ══════════════════════════════════════════════════════════════════════
#
# Seven panels defined their own bias map and three defined their own grade
# map. Bull and bear agreed everywhere; **neutral did not** — it was `MUTED`
# grey in `absorption_panel` and `terminal_panel`, and `WARN` amber in the
# other five. Two panels called the same reading "nothing is happening" and
# five called it "be careful", on the same screen.
#
# ⚠️ `NEUTRAL` is `WARN` here because that is what five of the seven maps
#    already used, so unifying costs two panels a colour change rather than
#    five. It is NOT an endorsement: on this repo's own reasoning an *absence*
#    of direction should not wear a caution colour, and `Neutral` elsewhere
#    (Stage 71.85, Stage 71.86) is deliberately treated as an absence. Changing
#    it is one line here — a deliberate decision, not a silent drift.

#: bias → colour. Keys are matched case-insensitively by `bias_tone()`, because
#: half the panels wrote `BULL` and half wrote `bull`, which is how one map
#: became seven.
BIAS_TONE = {"BULL": BULL, "BEAR": BEAR, "NEUTRAL": WARN}

BIAS_EMOJI = {"BULL": "🟢", "BEAR": "🔴", "NEUTRAL": "🟡"}

#: trade quality → colour. `dashboard.py` used `#f0b429`/`#f0455a` for B and C
#: where the other two panels used `WARN`/`ALERT`; the semantic constants win,
#: so a B on one screen is a B on every screen.
GRADE_TONE = {"A+": BULL, "A": BULL_SOFT, "B": WARN, "C": ALERT}


#: Longest key first, so `NEUTRAL` is tested before a shorter key could match
#: inside a longer word. Order is fixed here rather than left to dict iteration
#: because a colour that depends on insertion order is a bug waiting for an
#: alphabetised refactor.
_BIAS_KEYS = ("NEUTRAL", "BEAR", "BULL")


def _bias_key(value) -> str:
    """The map key for a bias label, or `""`.

    ⚠️ Exact lookup was not enough, and this is a bug fix rather than a
    convenience.

    The engines publish `BULLISH`, `STRONG BULLISH`, `BEARISH` — that is what
    Stage 27 and Stage 71 put on screen and into the Telegram message. The maps
    are keyed `BULL` / `BEAR` / `NEUTRAL`, and an exact match means every one of
    those real labels fell through to the default: white text and a ⚪, on a
    reading that was strongly bullish. The colour code silently stopped working
    for the only vocabulary that actually reaches it.

    `BEAR` is tested before `BULL` only for determinism; no real label contains
    both, and a hypothetical one is ambiguous whichever way it is read.
    """
    v = str(value or "").strip().upper()
    if not v:
        return ""
    if v in BIAS_TONE:
        return v
    for key in _BIAS_KEYS:
        if key in v:
            return key
    return ""


def bias_tone(value, default=INK) -> str:
    """A bias's colour, whatever case or wording it arrived in."""
    return BIAS_TONE.get(_bias_key(value), default)


def bias_emoji(value, default="⚪") -> str:
    return BIAS_EMOJI.get(_bias_key(value), default)


def grade_tone(value, default=MUTED) -> str:
    return GRADE_TONE.get(str(value or "").strip().upper(), default)
