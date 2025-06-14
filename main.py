#!/usr/bin/env python3
import locale, curses, os, sys, textwrap
from pathlib import Path
try:
    import openai
except ImportError:
    print("pip install --upgrade 'openai>=0.27'", file=sys.stderr)
    sys.exit(1)

# ── locale for unicode ─────────────────────────────────────────────────
locale.setlocale(locale.LC_ALL, "")  # enable full UTF‑8 keyboard input

# ── configuration ───────────────────────────────────────────────────────
MODEL = "gpt-4o"
FILE = Path("answer.txt")
KEY_FILE = Path(".openai_key")
EDIT_WRAP = 50
LEFT_COL = 0
ANN_COL = 60

CATS = ["R", "Gr", "Z", "S", "W", "Ug", "Be", "?"]

PROMPT = (
    "Schreibe jede Zeile des Schülers exakt neu ohne korrektur, gleiche Zeilenumbrüche. "
    "Füge nach jedem fehlerhaften Wort oder Satz ein Tag ein: wort[CAT|Begründung]. "
    "CAT ist der Fehlertyp, Begründung max. 3 Wörter. Versuche alle Fehler zu markieren" 
    f"Verwende diese CATS: {', '.join(CATS)}. Keine zusätzlichen Zeilen."
)

# ── helpers ─────────────────────────────────────────────────────────────
FILE.touch(exist_ok=True)
load = lambda: FILE.read_text("utf-8")
save = lambda t: FILE.write_text(t, "utf-8")

def ensure_key():
    if openai.api_key:
        return
    if KEY_FILE.exists():
        openai.api_key = KEY_FILE.read_text().strip()
    else:
        openai.api_key = input("OpenAI API key: ").strip()
        KEY_FILE.write_text(openai.api_key)

def grade(txt: str) -> str:
    r = openai.ChatCompletion.create(
        model=MODEL,
        temperature=0.2,
        messages=[
            {"role": "system", "content": "You are a strict but kind tutor."},
            {"role": "user", "content": PROMPT + "\n\n" + txt},
        ],
    )
    return r.choices[0].message.content.strip()

# parse line WITHOUT regex

def parse_line(line: str):
    anns = []
    out = []
    i = 0
    n = len(line)
    while i < n:
        if line[i] == "[":
            j = line.find("]", i + 1)
            bar = line.find("|", i + 1, j if j != -1 else n)
            if j != -1 and bar != -1:
                cat = line[i + 1 : bar]
                msg = line[bar + 1 : j]
                if cat in CATS:
                    out.append("*")
                    anns.append((cat, msg))
                    i = j + 1
                    continue
        out.append(line[i])
        i += 1
    return "".join(out), anns

# ── tiny editor ─────────────────────────────────────────────────────────
class Editor:
    def __init__(self, scr, txt):
        self.scr, self.lines = scr, txt.split("\n")
        self.y = self.x = 0

    def wrap(self, l):
        return textwrap.wrap(l, EDIT_WRAP) or [""]

    def run(self):
        curses.curs_set(1)
        while True:
            self.draw()
            ch = self.scr.get_wch()  # wide‑char aware input
            # ---- immediate commands ----
            if ch == "\t":  # TAB = grade
                return "\n".join(self.lines).strip()
            if ch == '\x1b':
                save("\n".join(self.lines).strip())  # save before quitting
                return None
            # ---- delegate rest ----
            self.key(ch)

    def draw(self):
        st = self.scr
        st.clear()
        st.addstr(0, 0, "TAB=grade  Esc=quit", curses.A_BOLD)
        y = 2
        for ln in self.lines:
            for seg in self.wrap(ln):
                st.addstr(y, LEFT_COL, seg[: curses.COLS - 1])
                y += 1
        st.move(self.y + 2, min(self.x, curses.COLS - 2))
        st.refresh()

    # minimal cursor/typing
    def key(self, ch):
        L = self.lines

        # --- convert str control to int for easier matching ---
        if isinstance(ch, str):
            if ch == "\x17":  # Ctrl‑W / Ctrl‑Backspace by many terminals
                ch = 23  # euse integer 23 for unified handling below
            elif ch in ("\b", "\x7f", "\x08"):  # backspace varieties
                ch = curses.KEY_BACKSPACE
            elif ch in ("\n", "\r"):  # newline
                ch = 10
            elif len(ch) == 1 and ch.isprintable():  # printable unicode, incl. umlauts
                if len(L[self.y]) < EDIT_WRAP:
                    ln = L[self.y]
                    L[self.y] = ln[: self.x] + ch + ln[self.x :]
                    self.x += 1
                return
            else:
                return  # ignore non‑printables we don't handle

        # --- special / cursor keys ---
        if ch == curses.KEY_UP and self.y:
            self.y -= 1
            self.x = min(self.x, len(L[self.y]))
        elif ch == curses.KEY_DOWN and self.y < len(L) - 1:
            self.y += 1
            self.x = min(self.x, len(L[self.y]))
        elif ch == curses.KEY_LEFT:
            if self.x:
                self.x -= 1
            elif self.y:
                self.y -= 1
                self.x = len(L[self.y])
        elif ch == curses.KEY_RIGHT:
            if self.x < len(L[self.y]):
                self.x += 1
            elif self.y < len(L) - 1:
                self.y += 1
                self.x = 0
        elif ch in (curses.KEY_HOME,):
            self.x = 0
        elif ch in (curses.KEY_END,):
            self.x = len(L[self.y])

        # --- deletions ---
        elif ch in (curses.KEY_BACKSPACE, 127, 8):  # standard backspace
            if self.x:
                ln = L[self.y]
                L[self.y] = ln[: self.x - 1] + ln[self.x :]
                self.x -= 1
            elif self.y:
                self.x = len(L[self.y - 1])
                L[self.y - 1] += L[self.y]
                L.pop(self.y)
                self.y -= 1
        elif ch == 23:  # Ctrl‑Backspace / Ctrl‑W : delete previous word
            if self.x:
                ln = L[self.y]
                pos = self.x-1
                while pos and not ln[pos - 1].isspace():
                    pos -= 1
                L[self.y] = ln[:pos] + ln[self.x :]
                self.x = pos
            elif self.y:  # at start of line – join with previous and continue deletion
                self.x = len(L[self.y - 1])
                L[self.y - 1] += L[self.y]
                L.pop(self.y)
                self.y -= 1
                # recursive call handles remaining word chars on prev line
                self.key(23)

        # --- newline / enter ---
        elif ch in (10, 13):
            ln = L[self.y]
            L[self.y] = ln[: self.x]
            L.insert(self.y + 1, ln[self.x :])
            self.y += 1
            self.x = 0

    # end class Editor

# ── renderer ─────────────────────────────────────────────────────────────

def render(scr, graded: str):
    curses.start_color()
    curses.init_pair(1, curses.COLOR_RED, 0)
    max_y, max_x = curses.LINES - 1, curses.COLS - 1
    scr.clear()
    scr.addstr(0, 0, "Graded result – press any key", curses.A_REVERSE)

    y = 2
    for raw in graded.splitlines():
        clean, anns = parse_line(raw)
        # wrap left text so it never overruns annotation col
        left_chunks = textwrap.wrap(clean, ANN_COL - 2) or [""]
        base_y = y
        for chunk in left_chunks:
            if y >= max_y:
                break
            x = LEFT_COL
            for ch in chunk:
                attr = curses.color_pair(1) | curses.A_BOLD if ch == "*" else 0
                scr.addstr(y, x, ch, attr)
                x += 1
            y += 1
        # annotations
        row = base_y
        for cat, msg in anns:
            for seg in textwrap.wrap(f"*{cat} - {msg}", max_x - ANN_COL):
                if row >= max_y:
                    break
                scr.addstr(row, ANN_COL, seg, curses.color_pair(1))
                row += 1
            y = max(y, row)
        if y >= max_y:
            break
    scr.refresh()
    scr.getch()

# ── main loop ───────────────────────────────────────────────────────────

def main(stdscr):
    txt = load()
    while True:
        edited = Editor(stdscr, txt).run()
        if edited is None:
            break
        txt = edited
        save(txt)
        stdscr.clear()
        stdscr.addstr(0, 0, "Grading…", curses.A_BOLD)
        stdscr.refresh()
        try:
            graded = grade(txt)
        except Exception as e:
            graded = str(e)
        render(stdscr, graded)


if __name__ == "__main__":
    ensure_key()
    curses.wrapper(main)
