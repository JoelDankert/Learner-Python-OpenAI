import locale
import curses
import sys
import textwrap
import os
from pathlib import Path

try:
    import openai
except ImportError:
    print("pip install --upgrade 'openai>=0.27'", file=sys.stderr)
    sys.exit(1)

# ── Unicode ─────────────────────────────────────────────────────────────
locale.setlocale(locale.LC_ALL, "")

# ── Config ──────────────────────────────────────────────────────────────
MODEL     = "gpt-4o"
KEY_FILE  = Path(".openai_key")

ANSI_RED    = "\033[31m"
ANSI_GREEN  = "\033[32m"
ANSI_RESET  = "\033[0m"
ANSI_BOLD   = "\033[1m"

CATS = [
    "R (Rechtschreibung)", "Gr (Grammatik)", "Z (Zeichensetzung)",
    "S (Stilvorschlag)", "W (Wiederholung)", "Ug (Ungenau)", "? (Sinnlos)"
]
# Kürzel manuell extrahieren
CAT_CODES = []
for c in CATS:
    token = c
    for sep in (" ", "("):
        pos = token.find(sep)
        if pos != -1:
            token = token[:pos]
            break
    CAT_CODES.append(token)

PROMPT = (
    "Schreibe jede Zeile des Schülers exakt neu ohne Korrektur, gleiche "
    "Zeilenumbrüche. Füge nach jedem fehlerhaften Wort oder Satz ein Tag ein: "
    "wort[Kategoriekürzel|Begründung]. Begründung circa 1 Satz erklären was genau falsch ist. "
    "Versuche alle Fehler zu markieren. "
    f"Verwende diese CATS: {', '.join(CATS)}. Keine zusätzlichen Zeilen. "
    "WICHTIG: NICHTS WEITER HINZUFÜGEN! NUR BEWERTEN!"
)

def render_to_stdout(graded: str, wrap_cols: int = 80):
    """
    Gibt den korrigierten Text in der Konsole aus, mit * und Kürzeln wie im curses-Modus.
    """
    lines = graded.splitlines()

    for li, raw in enumerate(lines):
        txt, anns = parse_line(raw)
        cats_only = [c for c, _ in anns]
        wraps     = textwrap.wrap(txt, wrap_cols) or [""]

        cat_ptr = 0
        for seg in wraps:
            line_out = ""
            cat_tags = []
            for ch in seg:
                if ch == "*":
                    if cat_ptr < len(cats_only):
                        line_out += f"{ANSI_RED}*{ANSI_RESET}"
                        cat_tags.append(cats_only[cat_ptr])
                        cat_ptr += 1
                    else:
                        line_out += "*"
                else:
                    line_out += ch
            padding = " " * (wrap_cols - len(seg))
            tag_str = " ".join(cat_tags)
            if tag_str:
                tag_str = f"{ANSI_RED}{tag_str}{ANSI_RESET}"
            print(f"{line_out}{padding}  {tag_str}")
        print()  # Leerzeile zwischen Absätzen (optional)

def clean_graded(text: str, original: str) -> str:
    """
    • entfernt LLM-Vorspann wie "R: …"
    • entfernt führende Zeilennummern
    """
    lines = text.splitlines()

    # LLM-Preambel entfernen
    while lines and any(lines[0].startswith(code + ":") for code in CAT_CODES):
        lines.pop(0)

    cleaned = []
    for ln in lines:
        stripped = ln.lstrip()
        parts = stripped.split(maxsplit=1)
        if parts and parts[0].isdigit():
            ln = parts[1] if len(parts) > 1 else ""
        cleaned.append(ln.rstrip())

    return "\n".join(cleaned)

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
        model=MODEL,
        temperature=0.3,
        messages=[
            {"role": "system", "content": "You are a strict but kind tutor."},
            {"role": "user",   "content": PROMPT + "\n\n" + txt}
        ],
    )
    return r.choices[0].message.content.strip()

def rate_paragraphs(txt: str):
    paras = [p.strip() for p in txt.split("\n\n") if p.strip()]
    if not paras:
        return []
    prompt = (
        "Bewerte die folgenden Absätze (alles wo eine leere zeile dazwischen ist). "
        "Gib für jeden Absatz eine kleine Rückmeldung, was man besser machen kann. Achte nur auf Inhalt"
        "NICHT auf Rechtschreibung oder Grammatik"
        "Keine Zusatzsätze – beginne sofort mit der bewertung des ersten absatzes..\n"
        "WICHTIG: NICHTS WEITER HINZUFÜGEN! NUR BEWERTEN!"
    )
    for i, p in enumerate(paras, 1):
        prompt += f"{i}. {p}\n\n"
    r = openai.ChatCompletion.create(
        model=MODEL,
        temperature=0.3,
        messages=[
            {"role": "system", "content": "Du bist ein genauer Lehrer, der versucht den Schülertext zu verbessern"},
            {"role": "user",   "content": prompt}
        ],
    )
    raw = [ln.strip() for ln in r.choices[0].message.content.splitlines() if ln.strip()]
    return raw

# ── Parsing ohne Regex ──────────────────────────────────────────────────
def parse_line(line: str):
    anns, out = [], []
    i = 0
    while i < len(line):
        if line[i] == "[":
            close = line.find("]", i + 1)
            bar   = line.find("|", i + 1, close if close != -1 else None)
            if close != -1 and bar != -1:
                cat = line[i + 1:bar].strip()
                if cat in CAT_CODES:
                    msg = line[bar + 1:close].strip()
                    out.append("*")
                    anns.append((cat, msg))
                    i = close + 1
                    continue
        out.append(line[i])
        i += 1
    return "".join(out), anns

# ── Kleine Änderung: Absatzgrenzen robuster bestimmen ───────────────
# ── 2. Absatzgrenzen nur an leeren Zeilen ────────────────────────────
def get_para_bounds(lines):
    """
    Absatz = Block ohne *leere* Zeile dazwischen.
    Nur echte Leerzeilen zählen als Trenner – keine Sonderbehandlung
    von Ziffern mehr.  Dadurch erscheint der Arbeitsauftrag (1. Absatz)
    wieder korrekt.
    """
    bounds, start = [], None
    for idx, raw in enumerate(lines):
        txt, _ = parse_line(raw)
        if txt.strip() == "":
            if start is not None:
                bounds.append((start, idx - 1))
                start = None
        else:
            if start is None:
                start = idx
    if start is not None:
        bounds.append((start, len(lines) - 1))
    return bounds

# ── Renderer ────────────────────────────────────────────────────────────
def render(stdscr, graded: str, para_fb):
    curses.curs_set(0)
    curses.start_color()
    curses.init_pair(1, curses.COLOR_RED,   0)                # Sterne + Tags
    curses.init_pair(2, curses.COLOR_GREEN, 0)                # Absatz-FB
    curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_RED) # selektierter *

    WRAP_COLS = max(20, curses.COLS - 15)

    lines       = graded.splitlines()
    para_bounds = get_para_bounds(lines)

    # Fehlerliste ermitteln
    errors = []
    for i, l in enumerate(lines):
        _, anns = parse_line(l)
        for cat, msg in anns:
            errors.append((i, cat, msg))
    sel, total = 0, len(errors)

    scroll   = 0      # ⬅ Neue Scroll-Position (Zeilen-Offset)
    show_fb  = False  # ⬅ p toggelt Absatz-Feedback
    max_scrl = 0      # ⬅ wird pro Frame berechnet

    if curses.COLS < 30 or curses.LINES < 10:
        stdscr.addstr(0, 0, "Terminal zu klein.", curses.A_REVERSE)
        stdscr.refresh(); stdscr.getch(); return

    while True:
        stdscr.clear()
        header = "Keine Fehler" if total == 0 else f"{errors[sel][1]}: {errors[sel][2]}"
        stdscr.addstr(0, 0, header, curses.A_REVERSE)

        y          = 2         # Bildschirmzeile, auf der gezeichnet wird
        line_no    = 0         # Logische Dokumentzeile (inkl. Wraps)
        err_idx    = 0
        cat_ptr    = {idx: 0 for idx in range(len(lines))}

        # Gesamthöhe dynamisch berechnen, während wir zeichnen
        for li, raw in enumerate(lines):
            txt, anns = parse_line(raw)
            cats_only = [c for c, _ in anns]
            wraps     = textwrap.wrap(txt, WRAP_COLS) or [""]

            # ── Inhalt anzeigen ───────────────────────────────────────
            for seg in wraps:
                start_ptr = cat_ptr[li]             # ⬅ Merke Start-Index
                # sichtbare Zeile?
                if line_no >= scroll and y < curses.LINES:
                    x = 0
                    for ch in seg:
                        if ch == "*":
                            cat = cats_only[cat_ptr[li]]
                            cat_ptr[li] += 1
                            style = curses.color_pair(1)
                            if err_idx == sel:
                                style |= curses.color_pair(3)
                            stdscr.addstr(y, x, "*", style)
                            err_idx += 1
                        else:
                            stdscr.addstr(y, x, ch)
                        x += 1
                    # Zeilen-Tags (nur NEUE dieses Wraps) an den Rand schreiben
                    cats_this_wrap = cats_only[start_ptr:cat_ptr[li]]
                    if cats_this_wrap:
                        stdscr.addstr(
                            y, WRAP_COLS + 2,
                            " ".join(cats_this_wrap),
                            curses.color_pair(1)
                        )
                    y += 1
                else:
                    # nichts zeichnen, Fehlerindex trotzdem hochzählen
                    for ch in seg:
                        if ch == "*":
                            cat_ptr[li] += 1
                            err_idx += 1
                line_no += 1  # Eine Wrap-Zeile gezählt

            # ── Absatzfeedback ────────────────────────────────────────
            if show_fb:
                for pidx, (s, e) in enumerate(para_bounds):
                    if li == e and pidx < len(para_fb):
                        for seg in textwrap.wrap(para_fb[pidx], WRAP_COLS):
                            if line_no >= scroll and y < curses.LINES:
                                stdscr.addstr(y, 0, seg, curses.color_pair(2))
                                y += 1
                            line_no += 1
                        line_no += 1  # Leerzeile nach Feedback
                        if line_no >= scroll and y < curses.LINES:
                            y += 1

        # Maximal mögliche Scroll-Position neu setzen
        max_scrl = max(0, line_no - (curses.LINES - 2))

        stdscr.refresh()
        ch = stdscr.get_wch()

        # ── Tastatur-Handling ────────────────────────────────────────
        if ch == 'q':          # normales Beenden
            break
        if ch == 'c':          # Beenden & Inhalt in Zwischenablage
            os.system(f"cat {path} | termux-clipboard-set")
            break

        if total:
            if ch == curses.KEY_RIGHT:
                sel = (sel + 1) % total
            elif ch == curses.KEY_LEFT:
                sel = (sel - 1) % total

        if ch == curses.KEY_UP:                         # Scroll ↑
            scroll = max(0, scroll - 1)
        elif ch == curses.KEY_DOWN:                     # Scroll ↓
            scroll = min(max_scrl, scroll + 1)
        elif ch == 'p':                                 # Toggle Absatz-Feedback
            show_fb = not show_fb


# ── Main ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 main.py <file>", file=sys.stderr)
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    ensure_key()
    original = path.read_text(encoding="utf-8")
    original = '\n'.join(
        line for line in original.splitlines()
        if not line.lstrip().startswith('#')
    )
    graded_raw = grade_text(original)
    graded = clean_graded(graded_raw, original)
    para_fb = rate_paragraphs(original)

    try:
        curses.wrapper(render, graded, para_fb)
    finally:
      print("\n\nOUTPUT\n")
      render_to_stdout(graded, wrap_cols=60)
