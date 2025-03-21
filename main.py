#!/usr/bin/env python3
import os
import sys
import openai
import readline
from sympy import sympify

#readline.parse_and_bind("tab: complete")
#readline.parse_and_bind("set editing-mode vi")


# ANSI-Farbcodes
RED = "\033[31m"
GREEN = "\033[32m"
BLUE = "\033[34m"
GRAY = "\033[90m"
RESET = "\033[0m"

# -------------------------------
# System-Prompts (siehe unten)
# -------------------------------
SYSTEM_PROMPT_GENERATE_QUESTION = (
    "Du bist ein Tutor und erstellst anhand des folgenden Benutzereingabe-Prompts eine neue, einzigartige Frage."
    "Die Fragen sollten zerlegt gestaltet werden, nicht alle Themen auf einmal."
    "Nutze den Inhalt des Prompts, um eine einzige interessante, lehrreiche Frage zu formulieren."
    "Bitte achte besonders darauf, dass du ausschließlich mit der Frage antwortest, nichts weiter."
    "Für mathe oder ähnliches nutze ausschließlich ascii schrift, kein TeX. sprich sqrt, ^2 _i etc. Gebe außerdem keine Hinweise"
    "\n\nBenutzereingabe-Prompt:\n{user_prompt}"
    "\n\nAlte Fragen (nicht ähnlich wie diese):\n{previous}"
    "\n\nWunsch des Nutzers: {wunsch}"
)

SYSTEM_PROMPT_CHECK_ANSWER = (
    "Du überprüfst nur den letzten Schritt die der nutzer gemacht hat auf die folgende Frage. "
    "Falls die Antwort bis dahin korrekt ist, antworte ausschließlich mit einer kurzen Bestätigung, ende den satz mit einem Punkt (.) am ende deiner nachricht"
    "Falls der Nutzer in dem schritt einen Fehler gemacht hat, antworte ausschließlich mit einer kurzen Erklärung des Fehlers, gefolgt von einem Ausrufezeichen (!) als satzende"
    "Falls der Nutzer eine Frage in seiner letzten nachricht stellt (Signal Fragezeichen), beantworte die Frage einfach. ende dann immer mit Punkt (.) bei jeder frage"
    "Für mathe oder ähnliches nutze ausschließlich ascii schrift, kein TeX. sprich sqrt, ^2 _i etc."
    "Antworte bitte als würdest du mit dem Nutzer sprechen."
    "Nochmal: ende mit . wenn richtig und mit ! wenn falsch, bei fragen immer ."
    "\n\nFrage:\n{question}\n\nChatverlauf:\n{chat_history}"
)


def clear():
    os.system("clear")

# -------------------------------
# Helper: Buffered Print (zur späteren Erweiterung)
# -------------------------------
def buffered_print(text, color=RESET):
    """Gibt den Text in der angegebenen Farbe aus."""
    print(f"{color}{text}{RESET}")

# -------------------------------
# OpenAI-API-Aufrufe
# -------------------------------
def generate_question(user_prompt, previous, wunsch):
    """Erstellt mithilfe von OpenAI eine Frage basierend auf dem übergebenen Benutzereingabe-Prompt."""
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT_GENERATE_QUESTION.format(user_prompt=user_prompt,previous=previous,wunsch=wunsch)
                }
            ]
        )
        question = response.choices[0].message["content"].strip().replace("\\","")
        return question
    except Exception as e:
        return f"Fehler beim Generieren der Frage: {e}"

def check_answer(question, chat_history):
    """Überprüft die Antwort zur Frage und gibt entweder einen Punkt (.) bei Korrektheit oder ein Ausrufezeichen (!) gefolgt von einem Kommentar zurück."""
    
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT_CHECK_ANSWER.format(question=question, chat_history=chat_history)
                }
            ]
        )
        result = response.choices[0].message["content"].strip().replace("\\","")
        return result
    except Exception as e:
        return f"Fehler beim Überprüfen der Antwort: {e}"

# -------------------------------
# Hauptprogramm
# -------------------------------
def main():
    # OpenAI API-Key abfragen
    openai_key = "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"
    openai.api_key = openai_key

    # Prompts-Verzeichnis festlegen (Unterordner "prompts")
    prompts_dir = os.path.join(os.getcwd(), "prompts")
    if not os.path.isdir(prompts_dir):
        buffered_print("Prompts-Verzeichnis nicht gefunden, erstelle es...", color=GRAY)
        os.makedirs(prompts_dir)

    # Liste aller Prompt-Dateien im Unterordner
    prompt_files = [f for f in os.listdir(prompts_dir) if os.path.isfile(os.path.join(prompts_dir, f))]
    if not prompt_files:
        buffered_print("Keine Benutzer-Prompts gefunden im Verzeichnis 'prompts'. Bitte füge eine Prompt-Datei hinzu.", color=RED)
        sys.exit(1)

    buffered_print("Verfügbare Benutzer-Prompts:", color=GREEN)
    for idx, filename in enumerate(prompt_files, start=1):
        buffered_print(f"{idx}. {filename}", color=GREEN)

    choice = input("Wähle eine Prompt (Zahl): ").strip()
    try:
        choice_idx = int(choice) - 1
        selected_prompt_file = os.path.join(prompts_dir, prompt_files[choice_idx])
    except (ValueError, IndexError):
        buffered_print("Ungültige Auswahl.", color=RED)
        sys.exit(1)

    with open(selected_prompt_file, "r", encoding="utf-8") as f:
        user_prompt_content = f.read()

    clear()

    # Erste Frage generieren
    question = generate_question(user_prompt_content,"noch keine", "")
    oldquestions = []
    oldquestions.append(question)
    buffered_print("\n# " + question, color=GREEN)
    # Der Chatverlauf wird als einfacher String geführt (zum Überprüfen)
    chat_history = f"Frage: {question}\n"

    # Interaktive Schleife
    while True:
        user_input = input("> ").strip()
        if user_input.lower() == "exit":
            buffered_print("Sitzung beendet. Du kannst nun eine andere Benutzer-Prompt wählen.", color=GRAY)
            break
        elif user_input.lower().startswith("next"):
            # Generiere eine neue Frage, lösche bisherigen Chatverlauf außer der neuen Fragestellung
            clear()
            question = generate_question(user_prompt_content,"\n\n".join(oldquestions),user_input[4:])
            oldquestions.append(question)
            buffered_print("\nFrage: " + question, color=GREEN)
            chat_history = f"Frage: {question}\n"
        elif user_input.lower().startswith("calc"):
            ask = user_input[4:]
            try:
                expr = sympify(ask, evaluate=True)
                calc = round(float(expr.evalf()),3)
            except:
                calc = "Error"
            chat_history += (f"calculation executed: {ask}={calc}\n")
            buffered_print(f"CALC: {ask}={calc}", color=BLUE)
            
        else:
            # Antwort prüfen
            chat_history += f"User: {user_input}\n"
            result = check_answer(question, chat_history)
            if result.endswith("!"):
                buffered_print(result, color=RED)
                chat_history += f"Tutor: {result}\n"
            elif result.endswith("."):
                buffered_print(result, color=GREEN)
                chat_history += f"Tutor: {result}\n"
            else:
                # Falls das Format unerwartet ist, einfach ausgeben
                buffered_print(result, color=GRAY)

if __name__ == "__main__":
    main()
