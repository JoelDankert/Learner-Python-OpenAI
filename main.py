#!/usr/bin/env python3
import locale, curses, sys, textwrap, re
from pathlib import Path

try:
    import openai
except ImportError:
    print("pip install --upgrade 'openai>=0.27'", file=sys.stderr)
    sys.exit(1)

# ── Unicode ─────────────────────────────────────────────────────────────
locale.setlocale(locale.LC_ALL, "")

# ── Config ──────────────────────────────────────────────────────────────
MODEL      = "gpt-4o"
KEY_FILE   = Path(".openai_key")
WRAP_COLS  = 50                 # fixe Wrap-Breite

CATS = ["R (Rechtschreibung)","Gr (Grammatik)","Z (Zeichensetzung)","S (Stilvorschlag)","W (Wiederholung)","Ug (Ungenau)","? (Sinnlos)"]
PROMPT = (
    "Schreibe jede Zeile des Schülers exakt neu ohne Korrektur, gleiche Zeilenumbrüche. "
    "Füge nach jedem fehlerhaften Wort oder Satz ein Tag ein: wort[CAT|Begründung]. "
    "CAT ist der Fehlertyp, Begründung max. 1 Satz. Versuche alle Fehler zu markieren "
    f"Verwende diese CATS: {', '.join(CATS)}. Keine zusätzlichen Zeilen."
)

# ── OpenAI-Key ──────────────────────────────────────────────────────────
def ensure_key():
    if openai.api_key:
        return
    if KEY_FILE.exists():
        openai.api_key = KEY_FILE.read_text().strip()
    else:
        openai.api_key = input("OpenAI API key: ").strip()
        KEY_FILE.write_text(openai.api_key)

# ── OpenAI-Calls ────────────────────────────────────────────────────────
def grade_text(txt: str) -> str:
    r = openai.ChatCompletion.create(
        model=MODEL, temperature=0.2,
        messages=[
            {"role":"system","content":"You are a strict but kind tutor."},
            {"role":"user",  "content":PROMPT + "\n\n" + txt}
        ],
    )
    return r.choices[0].message.content.strip()

def rate_paragraphs(txt: str):
    paras = [p.strip() for p in txt.split("\n\n") if p.strip()]
    if not paras:
        return []
    prompt = "Bewerte die folgenden Absätze. Gib für jeden eine kurze Rückmeldung (gut & was fehlt). keine extra sätze direkt anfangen, deine zeilen werden den absätzen zugeordnet, nummeriert:\n"
    for i,p in enumerate(paras,1):
        prompt += f"{i}. {p}\n\n"
    r = openai.ChatCompletion.create(
        model=MODEL, temperature=0.2,
        messages=[
            {"role":"system","content":"You are a strict but kind tutor."},
            {"role":"user",  "content":prompt}
        ],
    )
    fb = []
    for ln in r.choices[0].message.content.strip().splitlines():
        # entferne evtl. vorgesetztes „Absatz n:“ o. Ä.
        ln = re.sub(r"^\\*?\\s*Absatz\\s+\\d+\\s*:?\\s*", "", ln, flags=re.I)
        if ln:
            fb.append(ln.strip())
    return fb

# ── Parsing ─────────────────────────────────────────────────────────────
def parse_line(line: str):
    anns, out = [], []
    i = 0
    while i < len(line):
        if line[i] == '[':
            j   = line.find(']', i)
            bar = line.find('|', i, j)
            if j!=-1 and bar!=-1:
                cat = line[i+1:bar]; msg = line[bar+1:j]
                if cat in CATS:
                    out.append('*'); anns.append((cat,msg)); i = j+1; continue
        out.append(line[i]); i += 1
    return ''.join(out), anns

def get_para_bounds(lines):
    bounds, start = [], None
    for idx, raw in enumerate(lines):
        txt,_ = parse_line(raw)
        if not txt.strip():
            if start is not None:
                bounds.append((start, idx-1)); start=None
        else:
            if start is None: start = idx
    if start is not None:
        bounds.append((start, len(lines)-1))
    return bounds

# ── Renderer ───────────────────────────────────────────────────────────
def render(stdscr, graded: str, para_fb):
    curses.start_color()
    curses.init_pair(1, curses.COLOR_RED,   0)                # * + CAT
    curses.init_pair(2, curses.COLOR_GREEN, 0)                # Absatz-FB
    curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_RED) # selektierter *

    lines       = graded.splitlines()
    para_bounds = get_para_bounds(lines)

    errors = []
    for i,l in enumerate(lines):
        _,anns = parse_line(l)
        for cat,msg in anns:
            errors.append((i,cat,msg))
    sel,total = 0,len(errors)

    while True:
        stdscr.clear()
        stdscr.addstr(0,0, "Keine Fehler" if total==0 else f"{errors[sel][1]}: {errors[sel][2]}", curses.A_REVERSE)

        y       = 2
        err_idx = 0
        cat_ptr = {i:0 for i,_ in enumerate(lines)}  # welchen CAT haben wir pro Zeile schon ausgegeben?

        for li, raw in enumerate(lines):
            txt, anns = parse_line(raw)
            cats_only = [c for c,_ in anns]
            wraps     = textwrap.wrap(txt, WRAP_COLS) or [""]
            for seg in wraps:
                if y >= curses.LINES: break
                x, cats_this_wrap = 0, []
                for ch in seg:
                    if ch == '*':
                        cat = cats_only[cat_ptr[li]]
                        cat_ptr[li] += 1
                        cats_this_wrap.append(cat)
                        style = curses.color_pair(1)
                        if err_idx == sel: style |= curses.color_pair(3)
                        stdscr.addstr(y,x,'*',style)
                        err_idx += 1; x += 1
                    else:
                        stdscr.addstr(y,x,ch); x += 1
                if cats_this_wrap:                                   # Cats direkt hinter dieser Wrap-Zeile
                    stdscr.addstr(y, x+1, " ".join(cats_this_wrap), curses.color_pair(1))
                y += 1
            # Absatz-Feedback – ohne Präfix
            for pidx,(s,e) in enumerate(para_bounds):
                if li == e and pidx < len(para_fb):
                    for seg in textwrap.wrap(para_fb[pidx], WRAP_COLS):
                        if y>=curses.LINES: break
                        stdscr.addstr(y,0,seg,curses.color_pair(2)); y+=1
                    y += 1
            if y>=curses.LINES: break

        stdscr.refresh()
        ch = stdscr.get_wch()
        if ch in (10,13): break
        if total:
            if   ch == curses.KEY_RIGHT: sel = (sel+1) % total
            elif ch == curses.KEY_LEFT:  sel = (sel-1) % total

# ── Main ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 main.py <file>")
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    ensure_key()
    original = path.read_text(encoding="utf-8")
    graded   = grade_text(original)
    para_fb  = rate_paragraphs(original)

    curses.wrapper(render, graded, para_fb)
