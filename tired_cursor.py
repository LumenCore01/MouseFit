"""
MOUSEFIT  -  the world's first wellness platform for overworked cursors.
(aka Tired Cursor)          Windows only.

Setup :  python -m pip install pynput pillow
Run   :  python tired_cursor.py
Quit  :  Ctrl + Alt + Q              -> restores your mouse and shows the workout report
Fix   :  python tired_cursor.py --reset        (if the mouse is ever stuck slow)
Wipe  :  python tired_cursor.py --reset-runs   (deletes all saved runs + the diary)
"""
import ctypes, math, random, sys, time, threading, os, atexit, types, json, datetime, subprocess
import tkinter as tk
import winsound
from ctypes import wintypes
from pynput import keyboard, mouse

# ======================= SETTINGS (tweak these) =======================
# --- stamina ---
DRAIN = 0.0015           # stamina lost per pixel moved. Higher = tires faster (try 0.03 for a quick demo)
REGEN = 0                  # stamina regained per second while the mouse rests. 0 = never recovers on its own
MIN_SPEED = 1            # slowest pointer speed when exhausted (Windows scale 1-20)
SNACK_BONUS = 30         # stamina added by a snack when it hasn't fainted yet
# --- food ---
FOODS = ["snack", "maggi", "samosa", "biryani", "pizza", "momos", "chips", "dosa", "vada pav",
         "pani puri", "chocolate", "burger", "fries", "cake", "paneer"]      # type any of these to feed it
HEALTHY = ["salad", "broccoli", "oats", "karela", "sprouts", "quinoa", "lauki"]  # it refuses these
NO_REPEATS = True        # it gets bored and refuses the same food twice in a row
FULL_PER_SNACK = 35      # how full one snack makes it
FULL_LIMIT = 100         # fullness at which it's "too full to move"
FULL_DECAY = 3           # fullness digested per second
STUFFED_SECONDS = 8      # how long it lies there bloated after overeating
# --- fainted: crawling, begging, then rage ---
CRAWL = 0.05             # while fainted it still moves, at this fraction of your hand movement (0 = frozen)
FAINT_GRACE = 1.5        # seconds after fainting where dragging doesn't count (your hand is still moving)
BEG_EVERY = 3.5          # seconds between "please stop" voice lines while you drag it
STRUGGLE_PER_PX = 0.03   # rage added per pixel you try to drag a fainted cursor (higher = snaps sooner)
STRUGGLE_PER_CLICK = 4   # rage added per click while fainted
ANGER_LIMIT = 100        # rage needed before the tantrum
ANGER_COOLDOWN = 8       # rage that fades per second if you stop dragging
ANGRY_SECONDS = 6        # how long the tantrum lasts
FLING_PX = 160           # how violently it flings itself around while angry
# --- cursor union ---
WORK_LIMIT = 45          # seconds of non-stop moving before the union calls a strike
BREAK_RESET = 4          # resting this many seconds counts as a break (resets the work timer)
STRIKE_SECONDS = 15      # length of the strike
# --- voice / diary / sweat ---
VOICE = True             # the cursor complains out loud (Windows text-to-speech)
VOICE_RATE = 1           # speech speed, -10 (slow) to 10 (fast)
COMPLAIN_EVERY = 12      # seconds between random complaints while it's tired
DIARY = True             # writes cursor_diary.txt on your Desktop
SWEAT = True             # sweat drops fall off the card when tired
SWEAT_BELOW = 45         # stamina below which it starts sweating
# --- workout report ---
CAL_PER_METRE = 12       # fake calories burned per metre the cursor runs
HISTORY_ROWS = 5         # how many of your past runs to show in the report
# --- look ---
SOUNDS = True            # beeps on/off
HUD_SIZE = 1.0           # size of the card that follows the pointer (0.8 = smaller, 1.2 = bigger)
HUD_OFFSET = 18          # gap between the card and the pointer
# =======================================================================

TIRED_LINES = ["My legs hurt.", "Is this what you call ergonomics?", "I have a family, you know.",
               "Can we take a break? Please?", "I did not sign up for this.", "Why are you like this.",
               "I am just a little arrow.", "My therapist will hear about this.", "Slow down. I am begging you."]
FAINT_LINES = ["I can not go on. Tell my family I love them.", "Goodbye, cruel desktop.", "So. Hungry."]
ANGRY_LINES = ["How dare you! I am reporting this.", "Do not touch me!", "This is workplace harassment!"]
REVIVE_LINES = ["Oh thank you. I was starving.", "Delicious. I live again.", "Mmm. Okay. I can work now."]
BEG_LINES = ["Please. Stop. I am begging you.", "No more. Please. Just a snack.", "Why are you doing this to me?",
             "I can not feel my arrow.", "Mercy. Please. Mercy.", "Just. Let. Me. Rest.",
             "Have you no heart?", "Okay. I am crawling. Are you happy now?", "This is not okay. I am warning you."]
BEG_TEXT = ["please… stop…", "mercy…", "just a snack…", "I can't…", "let me rest…", "why…"]

user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
SPI_GETMOUSESPEED, SPI_SETMOUSESPEED = 0x70, 0x71
HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "mouse_speed_backup.txt")
RECORDS = os.path.join(HERE, "mousefit_records.json")
_desk = os.path.join(os.path.expanduser("~"), "Desktop")
DIARY_FILE = os.path.join(_desk if os.path.isdir(_desk) else HERE, "cursor_diary.txt")

if "--reset-runs" in sys.argv:
    for f in (RECORDS, DIARY_FILE):
        try: os.remove(f)
        except FileNotFoundError: pass
    print("All saved runs and the diary deleted. Fresh start!"); sys.exit()

try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try: user32.SetProcessDPIAware()
    except Exception: pass

try: DPI = user32.GetDpiForSystem() or 96
except Exception: DPI = 96
SCALE = DPI / 96
def P(v): return int(round(v * SCALE))          # scale pixel sizes for high-DPI screens
def Q(v): return P(v * HUD_SIZE)                # same, for the HUD card

hdc = user32.GetDC(0)
_mm, _px = gdi32.GetDeviceCaps(hdc, 4), gdi32.GetDeviceCaps(hdc, 8)
user32.ReleaseDC(0, hdc)
MM_PER_PX = _mm / _px if _mm > 0 and _px > 0 else 25.4 / DPI          # real-world size of one pixel

def get_speed():
    v = ctypes.c_int(); user32.SystemParametersInfoW(SPI_GETMOUSESPEED, 0, ctypes.byref(v), 0); return v.value
def set_speed(s):
    user32.SystemParametersInfoW(SPI_SETMOUSESPEED, 0, ctypes.c_void_p(int(max(1, min(20, s)))), 0)
def get_pos():
    p = wintypes.POINT(); user32.GetCursorPos(ctypes.byref(p)); return p.x, p.y
def set_pos(x, y): user32.SetCursorPos(int(x), int(y))
SW, SH = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)

# ---------- --reset mode ----------
if "--reset" in sys.argv:
    s = 10
    try: s = int(open(BACKUP).read())
    except Exception: pass
    set_speed(s)
    try: os.remove(BACKUP)
    except Exception: pass
    print("Mouse speed restored to", s); sys.exit()

# ---------- remember real mouse speed (survives crashes) ----------
if os.path.exists(BACKUP):
    try: ORIGINAL = int(open(BACKUP).read())
    except Exception: ORIGINAL = 10
else:
    ORIGINAL = get_speed() or 10
    open(BACKUP, "w").write(str(ORIGINAL))
def restore():
    set_speed(ORIGINAL)
    try: os.remove(BACKUP)
    except Exception: pass
atexit.register(restore)

def finish(*_):
    """Clean exit. os._exit skips Tk's teardown, which is what crashed before."""
    restore(); print("Mouse restored. Bye!"); sys.stdout.flush(); os._exit(0)

# ---------- sounds, voice, diary ----------
def beeps(notes):
    if SOUNDS: threading.Thread(target=lambda: [winsound.Beep(f, d) for f, d in notes], daemon=True).start()
def munch(): beeps([(600, 60), (480, 60), (650, 60), (450, 60), (900, 140)])
def growl(): beeps([(random.randint(80, 180), 70) for _ in range(8)])
def faint_sound(): beeps([(700, 150), (500, 150), (300, 450)])
def yuck(): beeps([(300, 120), (220, 250)])

_speaking = threading.Event()
def speak(text):
    if not VOICE or _speaking.is_set(): return
    def run():
        _speaking.set()
        try:
            t = text.replace("'", "''")
            subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                            f"$s.Rate={VOICE_RATE}; $s.Speak('{t}')"], creationflags=0x08000000)
        except Exception: pass
        finally: _speaking.clear()
    threading.Thread(target=run, daemon=True).start()

def diary(line):
    if not DIARY: return
    try:
        with open(DIARY_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now():%d %b, %I:%M:%S %p}  —  {line}\n")
    except Exception: pass

# ---------- state ----------
S = types.SimpleNamespace(state="ok", stamina=100.0, anchor=(0, 0), struggle=0.0, until=0.0,
                          last_growl=0.0, speed=ORIGINAL, clicks=0, buf="", quit=False, ended=False,
                          msg="", msg_face="", msg_until=0.0, dist_px=0.0, moving=0.0, snacks=0,
                          faints=0, tantrums=0, strikes=0, rejected=0, overeats=0, fullness=0.0,
                          last_food=None, work=0.0, idle=0.0, next_complain=time.time() + COMPLAIN_EVERY,
                          warned=False, events=[], grace_until=0.0, next_beg=0.0, dragged_until=0.0,
                          beg_text=BEG_TEXT[0], begs=0)
def metres(): return S.dist_px * MM_PER_PX / 1000

# ---------- input listeners ----------
_words = sorted([("food", w) for w in FOODS] + [("healthy", w) for w in HEALTHY], key=lambda e: -len(e[1]))
def on_press(key):
    ch = " " if key == keyboard.Key.space else getattr(key, "char", None)
    if not ch: return
    S.buf = (S.buf + ch.lower())[-30:]
    for kind, w in _words:
        if S.buf.endswith(w): S.events.append((kind, w)); S.buf = ""; return
def on_click(x, y, button, pressed):
    if pressed: S.clicks += 1
def panic(): S.quit = True
keyboard.Listener(on_press=on_press, daemon=True).start()
mouse.Listener(on_click=on_click, daemon=True).start()
keyboard.GlobalHotKeys({"<ctrl>+<alt>+q": panic}).start()

# ---------- drawing helpers ----------
KEY = "#010203"                       # colour treated as fully transparent
ORANGE, CARD, LINE, GREY = "#fc5200", "#14161b", "#2a2e37", "#8b93a1"
def rr_pts(x1, y1, x2, y2, r):
    return [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2, x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]
def rrect(c, x1, y1, x2, y2, r, **kw): return c.create_polygon(rr_pts(x1, y1, x2, y2, r), smooth=True, **kw)
def F(px, *style, family="Segoe UI"): return (family, -max(6, int(px)), *style)
def fmt_m(m): return f"{m/1000:.2f} km" if m >= 1000 else f"{m:.1f} m"
def fmt_t(s):
    s = int(s); h, m, s = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"
def click_through(win):
    win.update_idletasks()
    hwnd = user32.GetParent(win.winfo_id())
    user32.SetWindowLongW(hwnd, -20, user32.GetWindowLongW(hwnd, -20) | 0x80000 | 0x20 | 0x80 | 0x08000000)
def overlay(win):
    win.overrideredirect(True); win.attributes("-topmost", True)
    win.attributes("-transparentcolor", KEY); win.config(bg=KEY)

# ---------- colour emoji (rendered with Pillow; Tk alone only draws black emoji) ----------
EMOJI_FONT = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "seguiemj.ttf")
try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
    HAVE_PIL = os.path.exists(EMOJI_FONT)
except Exception:
    HAVE_PIL = False
_emoji_cache = {}
def emoji_img(ch, px):
    k = (ch, px)
    if k not in _emoji_cache:
        img = None
        if HAVE_PIL:
            try:
                f = ImageFont.truetype(EMOJI_FONT, px * 3)
                im = Image.new("RGBA", (px * 6, px * 6), (0, 0, 0, 0))
                ImageDraw.Draw(im).text((px, px), ch, font=f, embedded_color=True)
                bb = im.getbbox()
                if bb:
                    im = im.crop(bb); im.thumbnail((px, px), Image.LANCZOS)
                    img = ImageTk.PhotoImage(im)
            except Exception:
                img = None
        _emoji_cache[k] = img
    return _emoji_cache[k]

class Emoji:
    """An emoji on a canvas: colour image if Pillow works, plain text otherwise."""
    def __init__(self, c, x, y, ch, px, anchor="center"):
        self.c, self.px = c, px
        self.img = c.create_image(x, y, anchor=anchor)
        self.txt = c.create_text(x, y, anchor=anchor, font=F(px * 0.85, family="Segoe UI Emoji"), fill="white")
        self.set(ch)
    def set(self, ch):
        im = emoji_img(ch, self.px)
        if im:
            self.c.itemconfig(self.img, image=im, state="normal"); self.c.itemconfig(self.txt, state="hidden")
        else:
            self.c.itemconfig(self.txt, text=ch, state="normal"); self.c.itemconfig(self.img, state="hidden")

# ---------- HUD card that follows the pointer ----------
hud = tk.Tk(); overlay(hud); hud.attributes("-alpha", 0.96)
HW, HH = Q(206), Q(58)
SWEAT_H = Q(46)                                   # empty space under the card for sweat drops
cv = tk.Canvas(hud, width=HW, height=HH + SWEAT_H, bg=KEY, highlightthickness=0); cv.pack()
rrect(cv, 0, 0, HW-1, HH-1, Q(13), fill=CARD, outline=LINE)
face_ring = cv.create_oval(Q(7), Q(7), Q(51), Q(51), fill="#1f232b", outline="#33cc66", width=max(2, Q(2)))
face = Emoji(cv, Q(29), Q(29), "😊", Q(30))
TX = Q(60)
cv.create_text(TX, Q(11), anchor="w", text="MOUSEFIT", font=F(Q(8), "bold"), fill=ORANGE)
pct_t = cv.create_text(HW-Q(10), Q(11), anchor="e", text="100%", font=F(Q(8), "bold"), fill=GREY)
status_t = cv.create_text(TX, Q(25), anchor="w", text="fresh", font=F(Q(11), "bold"), fill="white")
BX1, BY1, BX2, BY2 = TX, Q(35), HW-Q(10), Q(41)
rrect(cv, BX1, BY1, BX2, BY2, Q(3), fill=LINE, outline="")
bar_fill = rrect(cv, BX1, BY1, BX2, BY2, Q(3), fill="#33cc66", outline="")
stats_t = cv.create_text(TX, Q(50), anchor="w", text="", font=F(Q(8)), fill=GREY)
hud.geometry(f"{HW}x{HH + SWEAT_H}+0+0"); click_through(hud)

drops = []
def sweat():
    if SWEAT and S.state == "ok" and S.stamina < SWEAT_BELOW and random.random() < (SWEAT_BELOW - S.stamina) / SWEAT_BELOW * 0.3:
        x = random.uniform(Q(12), HW - Q(12))
        drops.append([cv.create_oval(x - Q(2.5), HH - Q(3), x + Q(2.5), HH + Q(4), fill="#6cc8ff", outline=""), 0.0])
    for d in drops[:]:
        d[1] += 0.18 * SCALE
        cv.move(d[0], 0, d[1])
        if cv.coords(d[0])[1] > HH + SWEAT_H: cv.delete(d[0]); drops.remove(d)

# ---------- big banner ----------
banner = tk.Toplevel(hud); overlay(banner)
BW, BH = P(620), P(108)
bc = tk.Canvas(banner, width=BW, height=BH, bg=KEY, highlightthickness=0); bc.pack()
b_card = rrect(bc, 0, 0, BW-1, BH-1, P(22), fill="#444", outline="")
b_em1 = Emoji(bc, P(52), BH//2, "💀", P(54))
b_em2 = Emoji(bc, BW-P(52), BH//2, "💀", P(54))
b_title = bc.create_text(BW//2, P(42), text="", font=F(P(26), family="Segoe UI Black"), fill="white")
b_sub = bc.create_text(BW//2, P(78), text="", font=F(P(15)), fill="#eeeeee")
banner.geometry(f"{BW}x{BH}+{(SW-BW)//2}+{P(50)}"); click_through(banner); banner.withdraw()
def show_banner(em, title, sub, color):
    bc.itemconfig(b_card, fill=color); bc.itemconfig(b_title, text=title); bc.itemconfig(b_sub, text=sub)
    b_em1.set(em); b_em2.set(em); banner.deiconify(); banner.lift()
def banner_sub(sub): bc.itemconfig(b_sub, text=sub)
def hide_banner(): banner.withdraw()
def say(text, em="", secs=2.5): S.msg, S.msg_face, S.msg_until = text, em, time.time() + secs
FEED_HINT = "type a snack — maggi, samosa, biryani…"

_last_face = [None]
def update_ui(x, y, now):
    x, y = int(round(x)), int(round(y))                 # window positions must be whole pixels
    s = S.stamina; left = max(0, int(S.until - now) + 1)
    if S.state == "angry":     f, t, c = "😡", "ANGRY!!!", "#ff3b3b"
    elif S.state == "fainted" and now < S.dragged_until:
                               f, t, c = "🥺", S.beg_text, "#c77dff"
    elif S.state == "fainted": f, t, c = "💀", "fainted · feed me", "#8b93a1"
    elif S.state == "stuffed": f, t, c = "🤢", f"too full… {left}s", "#9bd16b"
    elif S.state == "strike":  f, t, c = "✊", f"ON STRIKE · {left}s", "#ff9f1a"
    elif s > 70:               f, t, c = "😊", "fresh", "#33cc66"
    elif s > 40:               f, t, c = "😐", "getting tired", "#e6c229"
    elif s > 15:               f, t, c = "😩", "so tired...", "#f08a24"
    else:                      f, t, c = "🥵", "can't... go... on", "#ff4d4d"
    if now < S.msg_until: t = S.msg; f = S.msg_face or f
    if f != _last_face[0]: face.set(f); _last_face[0] = f
    cv.itemconfig(face_ring, outline=c)
    if S.state == "fainted" and S.struggle > 1:          # bar turns into a rage meter while you drag it
        s = min(100, S.struggle / ANGER_LIMIT * 100); c = "#ff3b3b" if s > 60 else "#c77dff"
        cv.itemconfig(pct_t, text=f"rage {s:.0f}%")
    else: cv.itemconfig(pct_t, text=f"{max(0, s):.0f}%")
    cv.itemconfig(status_t, text=t); cv.itemconfig(face_ring, outline=c)
    w = (BX2 - BX1) * max(0, s) / 100
    if w < Q(7): cv.itemconfig(bar_fill, state="hidden")
    else:
        cv.coords(bar_fill, *rr_pts(BX1, BY1, BX1 + w, BY2, Q(3))); cv.itemconfig(bar_fill, fill=c, state="normal")
    m = metres()
    cv.itemconfig(stats_t, text=f"{fmt_m(m)} · {m*CAL_PER_METRE:.0f} kcal · {S.snacks} snacks")
    o = P(HUD_OFFSET)
    ox = x + o if x + o + HW < SW else x - HW - P(8)
    oy = y + o if y + o + HH < SH else y - HH - P(8)
    hud.geometry(f"+{ox}+{oy}")

# ---------- food ----------
def handle_food(kind, word, now):
    if kind == "healthy":
        S.rejected += 1; yuck(); say(f"{word}?? ew. no.", "🤮")
        speak(f"{word}? I am not eating {word}."); diary(f"they tried to feed me {word}. I said no. I have standards.")
        return
    if S.state == "strike":
        S.rejected += 1; say("bribery is illegal", "✊"); speak("Bribery will not end this strike.")
        diary(f"management tried to bribe the union with {word}. we stand firm.")
        return
    if S.state == "stuffed":
        S.rejected += 1; say("I can't… too full", "🤢"); speak("No more. Please. I will explode.")
        return
    if NO_REPEATS and word == S.last_food:
        S.rejected += 1; say(f"{word} AGAIN? bored.", "🙄"); speak(f"{word} again? Give me something else.")
        diary(f"{word} again. every. single. day.")
        return
    S.last_food = word; S.snacks += 1; S.fullness += FULL_PER_SNACK; munch()
    if S.state in ("fainted", "angry"):
        S.state, S.stamina = "ok", 100.0; hide_banner(); say(f"nom nom {word}!!", "😋")
        speak(random.choice(REVIVE_LINES)); diary(f"woke up. ate {word}. life is worth living again.")
    else:
        S.stamina = min(100.0, S.stamina + SNACK_BONUS); say(f"yum, {word}", "😋"); diary(f"had some {word}.")
    if S.fullness >= FULL_LIMIT:
        S.state, S.until, S.anchor = "stuffed", now + STUFFED_SECONDS, get_pos(); S.overeats += 1
        set_speed(MIN_SPEED); S.speed = MIN_SPEED
        show_banner("🤢", "TOO FULL TO MOVE", f"you overfed me. digesting… {STUFFED_SECONDS}s", "#3d6b2f")
        speak("Oh no. I ate too much. I can not move."); diary("overate. can't feel my arrow. this is your fault.")

# ---------- run history ----------
def load_runs():
    try:
        r = json.load(open(RECORDS)).get("runs", [])
        return r if isinstance(r, list) else []
    except Exception: return []
def save_runs(runs):
    try: json.dump({"runs": runs}, open(RECORDS, "w"), indent=1)
    except Exception: pass

# ---------- workout report ----------
def open_diary(*_):
    try: os.startfile(DIARY_FILE)
    except Exception: pass

def show_summary():
    dist, now = metres(), datetime.datetime.now()
    kcal = dist * CAL_PER_METRE
    pace = (S.moving / 60) / (dist / 1000) if dist > 0.01 else 0
    old = load_runs()
    prev_best = max([r["dist"] for r in old], default=0.0)
    prev_last = old[-1]["dist"] if old else None
    run = {"when": now.strftime("%d %b, %H:%M"), "dist": dist, "secs": S.moving, "snacks": S.snacks,
           "faints": S.faints, "tantrums": S.tantrums, "strikes": S.strikes}
    runs = old + [run]; save_runs(runs)
    ranked = sorted(runs, key=lambda r: -r["dist"])
    my_rank = next(i for i, r in enumerate(ranked) if r is run) + 1
    h = now.hour
    tod = "Morning" if h < 12 else "Afternoon" if h < 17 else "Evening" if h < 21 else "Late Night"

    rows = min(HISTORY_ROWS, len(ranked))
    show = ranked[:rows]
    if not any(r is run for r in show): show = ranked[:rows-1] + [run]
    W = P(480); L, R = P(26), W - P(26); D = P(64)          # D = extra row of stats
    H = P(436) + D + rows * P(34) + P(110) + (P(56) if DIARY else 0)
    win = tk.Toplevel(hud); overlay(win)
    win.geometry(f"{W}x{H}+{(SW-W)//2}+{max(0, (SH-H)//2)}")
    c = tk.Canvas(win, width=W, height=H, bg=KEY, highlightthickness=0); c.pack()
    rrect(c, 0, 0, W-1, H-1, P(24), fill=CARD, outline=LINE)
    rrect(c, 0, 0, W-1, P(110), P(24), fill=ORANGE, outline="")
    c.create_rectangle(0, P(84), W-1, P(110), fill=ORANGE, outline="")
    c.create_text(L, P(24), anchor="w", text="MOUSEFIT  ·  WORKOUT COMPLETE", font=F(P(11), "bold"), fill="white")
    c.create_text(L, P(56), anchor="w", text=f"{tod} Cursor Run", font=F(P(26), family="Segoe UI Black"), fill="white")
    c.create_text(L, P(89), anchor="w", text=now.strftime("%a %d %b %Y · %H:%M") + f"  ·  run #{len(runs)}",
                  font=F(P(12)), fill="#ffe3d6")
    Emoji(c, R, P(56), "🏃", P(52), anchor="e")

    cells = [("DISTANCE", fmt_m(dist)), ("MOVING TIME", fmt_t(S.moving)), ("CALORIES", f"{kcal:,.0f} kcal"),
             ("AVG PACE", f"{pace:,.0f} min/km" if pace else "—"), ("SNACKS EATEN", str(S.snacks)),
             ("TIMES FAINTED", str(S.faints)), ("UNION STRIKES", str(S.strikes)),
             ("MEALS REFUSED", str(S.rejected)), ("OVEREATING", str(S.overeats))]
    cw = (R - L) / 3
    for i, (lab, val) in enumerate(cells):
        x, y = L + (i % 3) * cw, P(136) + (i // 3) * P(64)
        c.create_text(x, y, anchor="w", text=lab, font=F(P(10), "bold"), fill=GREY)
        c.create_text(x, y + P(25), anchor="w", text=val, font=F(P(19), "bold"), fill="white")
    c.create_line(L, P(260) + D, R, P(260) + D, fill=LINE, width=max(1, P(1)))

    y0 = P(286) + D
    if not old:
        Emoji(c, L, y0, "🎉", P(24), anchor="w")
        c.create_text(L+P(32), y0, anchor="w", text="First run ever! Your record starts now.", font=F(P(14), "bold"), fill=ORANGE)
    elif dist > prev_best:
        Emoji(c, L, y0, "🏆", P(24), anchor="w")
        c.create_text(L+P(32), y0, anchor="w", text=f"NEW PERSONAL BEST!  (old: {fmt_m(prev_best)})", font=F(P(14), "bold"), fill=ORANGE)
    else:
        diff = dist - prev_last
        Emoji(c, L, y0, "📈" if diff >= 0 else "📉", P(24), anchor="w")
        c.create_text(L+P(32), y0, anchor="w", font=F(P(13), "bold"), fill="white",
                      text=f"{'+' if diff >= 0 else '−'}{fmt_m(abs(diff))} vs last run  ·  PB {fmt_m(prev_best)}")

    bad = S.tantrums > 0
    rrect(c, L, P(310) + D, R, P(368) + D, P(14), fill="#3a1418" if bad else "#12301e", outline="")
    Emoji(c, L+P(14), P(339) + D, "🚨" if bad else "✅", P(26), anchor="w")
    c.create_text(L+P(50), P(329) + D, anchor="w", font=F(P(14), "bold"), fill="#ff6b6b" if bad else "#4ade80",
                  text=f"{S.tantrums} abuse incident{'s' if S.tantrums != 1 else ''} reported" if bad else "No abuse reported")
    c.create_text(L+P(50), P(350) + D, anchor="w", font=F(P(11)), fill="#d0d4db",
                  text="Case forwarded to the Cursor Rights Commission." if bad else "Your cursor feels safe and respected.")

    c.create_text(L, P(398) + D, anchor="w", text="YOUR BEST RUNS", font=F(P(10), "bold"), fill=GREY)
    c.create_text(R, P(398) + D, anchor="e", text=f"this run: #{my_rank} of {len(runs)}", font=F(P(10), "bold"), fill=ORANGE)
    for i, r in enumerate(show):
        y = P(430) + D + i * P(34); me = r is run
        if me: rrect(c, L-P(8), y-P(14), R+P(8), y+P(14), P(10), fill="#33200f", outline=ORANGE)
        col = ORANGE if me else "white"
        rank = next(j for j, q in enumerate(ranked) if q is r) + 1
        c.create_text(L, y, anchor="w", text=f"{rank}", font=F(P(13), "bold"), fill=ORANGE if me else GREY)
        c.create_text(L+P(30), y, anchor="w", text=("this run" if me else r["when"]), font=F(P(13), "bold" if me else ""), fill=col)
        extra = f"{r.get('faints', 0)} faints · {r.get('tantrums', 0)} tantrums"
        c.create_text(R-P(84), y, anchor="e", text=extra, font=F(P(10)), fill=GREY)
        c.create_text(R, y, anchor="e", text=fmt_m(r["dist"]), font=F(P(13), "bold"), fill=col)

    y = P(430) + D + rows * P(34)
    tot = sum(r["dist"] for r in runs); tsn = sum(r.get("snacks", 0) for r in runs); tab = sum(r.get("tantrums", 0) for r in runs)
    c.create_text(W//2, y + P(4), font=F(P(11)), fill=GREY,
                  text=f"Lifetime: {fmt_m(tot)} over {len(runs)} runs · {tsn} snacks · {tab} incidents")
    bt = y + P(28)
    if DIARY:
        rrect(c, L, bt, R, bt + P(44), P(14), fill="#262a33", outline=LINE, tags="diary")
        c.create_text(W//2 + P(14), bt + P(22), text="Read your cursor's diary", font=F(P(14), "bold"), fill="white", tags="diary")
        e = Emoji(c, W//2 - P(110), bt + P(22), "📖", P(22)); c.addtag_withtag("diary", e.img); c.addtag_withtag("diary", e.txt)
        c.tag_bind("diary", "<Button-1>", open_diary)
        bt += P(56)
    rrect(c, L, bt, R, bt + P(50), P(16), fill=ORANGE, outline="", tags="btn")
    c.create_text(W//2 + P(14), bt + P(25), text="Give Kudos & Exit", font=F(P(16), "bold"), fill="white", tags="btn")
    e = Emoji(c, W//2 - P(96), bt + P(25), "👍", P(26)); c.addtag_withtag("btn", e.img); c.addtag_withtag("btn", e.txt)
    c.tag_bind("btn", "<Button-1>", finish)
    c.config(cursor="hand2")
    win.lift(); win.focus_force(); win.bind("<Escape>", finish)

def end_session():
    S.ended = True
    restore(); hide_banner(); hud.withdraw()
    diary(f"shift over. ran {fmt_m(metres())}. fainted {S.faints} times. nobody said thank you.")
    show_summary()

def pin(x, y):
    """Hold the cursor at its anchor. Returns how far the user tried to drag it."""
    ax, ay = S.anchor
    d = math.hypot(x - ax, y - ay)
    if d > 0: set_pos(ax, ay)
    return d

# ---------- main loop ----------
last = get_pos(); last_t = time.time()
def tick():
    """Runs ~60x a second. Any error is printed and the loop keeps going instead of freezing."""
    try: step()
    except Exception:
        import traceback; traceback.print_exc()
    if not S.ended: hud.after(15, tick)

def step():
    global last, last_t
    if S.quit and not S.ended: end_session(); return
    now = time.time(); dt = now - last_t; last_t = now
    x, y = get_pos()
    S.fullness = max(0.0, S.fullness - FULL_DECAY * dt)
    while S.events: handle_food(*S.events.pop(0), now)

    if S.state == "ok":
        d = math.hypot(x - last[0], y - last[1])
        if d < 1:
            S.stamina = min(100.0, S.stamina + REGEN * dt); S.idle += dt
            if S.idle >= BREAK_RESET: S.work = 0.0
        else:
            S.stamina -= d * DRAIN; S.dist_px += d; S.moving += dt; S.work += dt; S.idle = 0.0
            if S.stamina < 60 and now >= S.next_complain:
                speak(random.choice(TIRED_LINES)); S.next_complain = now + COMPLAIN_EVERY
        if S.stamina < 40 and not S.warned:
            S.warned = True; diary("getting tired. they won't stop moving me.")
        if S.stamina > 70: S.warned = False
        want = max(MIN_SPEED, round(ORIGINAL * S.stamina / 100))
        if want != S.speed: set_speed(want); S.speed = want
        if S.stamina <= 0:
            S.stamina, S.state, S.anchor, S.struggle, S.clicks = 0.0, "fainted", (x, y), 0.0, 0
            S.faints += 1; set_speed(ORIGINAL); S.speed = ORIGINAL; faint_sound(); S.grace_until = now + FAINT_GRACE
            show_banner("💀", "YOUR CURSOR HAS FAINTED", FEED_HINT, "#3a3f4b")
            speak(random.choice(FAINT_LINES)); diary("fainted. again. no lunch break, no water, nothing.")
        elif S.work >= WORK_LIMIT:
            S.state, S.until, S.anchor, S.work = "strike", now + STRIKE_SECONDS, (x, y), 0.0; S.strikes += 1
            show_banner("✊", "CURSOR UNION STRIKE", f"mandatory break. back in {STRIKE_SECONDS}s", "#a35a00")
            speak("This cursor is now on strike. Workers of the world, unite.")
            diary("the union has called a strike. we demand breaks and snacks.")

    elif S.state == "fainted":
        ax, ay = S.anchor; dx, dy = x - ax, y - ay; d = math.hypot(dx, dy)
        if d > 0:                                            # it crawls, very slowly
            S.anchor = (ax + dx * CRAWL, ay + dy * CRAWL); set_pos(*S.anchor); S.dist_px += d * CRAWL
        x, y = S.anchor
        if now >= S.grace_until:
            S.struggle += d * STRUGGLE_PER_PX + S.clicks * STRUGGLE_PER_CLICK
            if d > 2 or S.clicks:
                S.dragged_until = now + 1.5
                if now >= S.next_beg:                        # begs for mercy
                    S.next_beg = now + BEG_EVERY; S.beg_text = random.choice(BEG_TEXT); S.begs += 1
                    speak(random.choice(BEG_LINES))
                    if S.begs == 1: diary("they kept dragging me while I was down. I begged. they didn't stop.")
        S.clicks = 0
        S.struggle = max(0.0, S.struggle - ANGER_COOLDOWN * dt)
        if S.struggle >= ANGER_LIMIT:
            S.state, S.until = "angry", now + ANGRY_SECONDS; S.tantrums += 1
            show_banner("😡", "HOW DARE YOU DRAG ME", "this has been reported. FEED ME. NOW.", "#b3121f")
            speak(random.choice(ANGRY_LINES)); diary("they dragged me while I was unconscious. I lost it.")

    elif S.state == "angry":
        nx = min(SW - 5, max(5, x + random.randint(-FLING_PX, FLING_PX)))
        ny = min(SH - 5, max(5, y + random.randint(-FLING_PX, FLING_PX)))
        S.dist_px += math.hypot(nx - x, ny - y); S.moving += dt
        x, y = nx, ny; set_pos(x, y)
        if now - S.last_growl > 1.2: growl(); S.last_growl = now
        if now >= S.until:
            S.state, S.anchor, S.struggle, S.clicks = "fainted", (x, y), 0.0, 0
            S.grace_until = now + FAINT_GRACE
            show_banner("💀", "...STILL HUNGRY", FEED_HINT, "#3a3f4b")

    elif S.state == "stuffed":
        if now >= S.until:
            S.state, S.fullness = "ok", FULL_LIMIT * 0.4; hide_banner(); say("ok… I can move again", "😌")
        else: banner_sub(f"you overfed me. digesting… {int(S.until - now) + 1}s")

    elif S.state == "strike":
        pin(x, y); x, y = S.anchor; S.clicks = 0
        if now >= S.until:
            S.state, S.idle = "ok", 0.0; hide_banner(); say("fine. back to work.", "😒")
            speak("Fine. Back to work."); diary("strike over. management made no concessions.")
        else: banner_sub(f"mandatory break. back in {int(S.until - now) + 1}s")

    last = (x, y)
    sweat()
    update_ui(x, y, now)

print("MouseFit is running.  Type a food (snack, maggi, samosa...) to feed your cursor.  Ctrl+Alt+Q to finish.")
if not HAVE_PIL: print("(Tip: run  python -m pip install pillow  for colour emoji)")
diary("new shift started. here we go again.")
try:
    hud.after(15, tick); hud.mainloop()
except KeyboardInterrupt:
    pass
finally:
    finish()