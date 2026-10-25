# 🏃 MouseFit

**The world's first wellness platform for overworked cursors.**

Your cursor runs about 2 km a day across your screen. No breaks, no lunch, no rights. MouseFit gives it stamina, hunger, feelings, a union and a diary.

It solves no real problem, and it makes your computer harder to use.

Built for **Neura's Got Nothing**, NeuraAI's "most useless project" build event at MAHE Bengaluru (October 2026).

---

## Features

- **Stamina:** moving the mouse drains it, and the real Windows pointer speed drops with it. Sweat drips off the card when it gets tired.
- **It talks:** it complains out loud using Windows text-to-speech ("My legs hurt.", "I have a family, you know.").
- **Fainting:** at 0 stamina it collapses and can only crawl.
- **Begging, then rage:** drag it while it's down and it begs for mercy. Keep going and a rage meter fills until it snaps and flings itself around the screen.
- **Food:** type a food anywhere (`maggi`, `samosa`, `biryani`, `momos`…) to feed it.
  - It refuses healthy food (`salad`, `karela`, `broccoli`…).
  - It gets bored if you feed it the same thing twice in a row.
  - Overfeed it and it's too full to move.
- **Cursor union:** work it too long without a break and it goes on strike. Bribery with food is not accepted.
- **Diary:** it writes `cursor_diary.txt` on your Desktop about everything you put it through.
- **Workout report:** a Strava-style summary showing real distance in metres, calories, pace, faints, strikes, meals refused, abuse incidents and your personal bests.

## Setup (Windows only)

```bash
pip install pynput pillow
python tired_cursor.py
```

| Command | What it does |
|---|---|
| `python tired_cursor.py` | Start a run |
| **Ctrl + Alt + Q** | Finish the run and show the workout report |
| `python tired_cursor.py --reset` | Emergency: restore the normal mouse speed if it's ever stuck slow |
| `python tired_cursor.py --reset-runs` | Delete all saved runs and the diary |

All settings (drain rate, rage limit, foods, strike timer, voice and more) are at the top of `tired_cursor.py`, with a comment explaining each one.

## How it works

- **Pointer speed:** set through the Windows API (`SystemParametersInfo`), scaled to the cursor's stamina.
- **Fainting, crawling and strikes:** the cursor is pinned in place with `SetCursorPos`, with only a fraction of your movement let through.
- **Food detection:** a global keyboard listener (`pynput`) watches for food words.
- **Card and banners:** transparent, click-through, always-on-top Tkinter windows. Colour emoji are rendered with Pillow.
- **Voice:** Windows' built-in speech engine, called through PowerShell.
- **Real distance:** pixels are converted to metres using your screen's physical size.
- **Safety:** your original mouse speed is backed up to a file and always restored on exit or with `--reset`.

---

*MouseFit doesn't make you more productive. It makes you way less productive, but with empathy.*
