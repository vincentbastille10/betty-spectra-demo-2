from flask import Flask, render_template, request, jsonify
import os
import re
import requests
import yaml

# ─── Chemins ───────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")
YAML_PATH = os.path.join(BASE_DIR, "pack", "betty_spectra.yaml")

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)

# Together est appelé en premier dès qu'une clé est configurée.
# Sans clé, ou si l'appel échoue, le script déterministe prend le relais.
TOGETHER_API_KEY = os.environ.get("TOGETHER_API_KEY", "").strip()
TOGETHER_API_URL = "https://api.together.xyz/v1/chat/completions"
LLM_MODEL = os.environ.get(
    "LLM_MODEL", "meta-llama/Llama-3.3-70B-Instruct-Turbo"
)
LEAD_EMAIL = os.environ.get("LEAD_EMAIL", "spectramediabots@gmail.com")
SIGNUP_LINK = os.environ.get("SIGNUP_LINK", "https://mybetty.online/")

DEFAULT_PROMPT = (
    "Tu es Betty, une réceptionniste virtuelle chaleureuse. "
    "Tu qualifies le besoin du visiteur avant de demander son prénom puis "
    "un seul moyen de contact. Une seule question courte à la fois."
)

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", re.I)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\s().-]*){8,15}(?!\w)")
GREETINGS = {
    "bonjour", "bonsoir", "salut", "hello", "hi", "hey", "coucou",
    "bonjour betty", "salut betty",
}


def load_prompt():
    try:
        with open(YAML_PATH, "r", encoding="utf-8") as f:
            return (yaml.safe_load(f) or {}).get("prompt", "").strip() or DEFAULT_PROMPT
    except Exception:
        return DEFAULT_PROMPT


def norm(value):
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def is_greeting(value):
    cleaned = re.sub(r"[!?.…]+", "", norm(value)).strip()
    return cleaned in GREETINGS


def find_email(value):
    match = EMAIL_RE.search(str(value or ""))
    return match.group(0) if match else ""


def find_phone(value):
    for match in PHONE_RE.finditer(str(value or "")):
        candidate = match.group(0).strip()
        digits = re.sub(r"\D", "", candidate)
        if 8 <= len(digits) <= 15:
            return candidate
    return ""


def find_name(value):
    text = str(value or "").strip()
    patterns = (
        r"(?:je m'appelle|moi c'est|mon prénom est)\s+([A-Za-zÀ-ÿ'’-]{2,})",
        r"(?:i am|i'm|my name is)\s+([A-Za-zÀ-ÿ'’-]{2,})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(1).capitalize()
    return ""


def bare_name(value):
    if find_email(value) or find_phone(value):
        return ""
    words = re.findall(r"[A-Za-zÀ-ÿ'’-]+", str(value or ""))
    if 1 <= len(words) <= 2:
        candidate = words[0]
        if norm(candidate) not in GREETINGS and len(candidate) >= 2:
            return candidate.capitalize()
    return ""


def detect_ask(value):
    text = norm(value)
    if "prénom" in text or "comment vous appelez" in text:
        return "name"
    if ("email" in text and "mobile" in text) or "moyen de contact" in text:
        return "contact"
    if "métier" in text or "votre activité" in text or "secteur d'activité" in text:
        return "activity"
    if (
        "aimeriez-vous que betty" in text
        or "que doit betty qualifier" in text
        or "qualifier ou récupérer" in text
        or "qualifier ou capturer" in text
    ):
        return "need"
    if "quel critère" in text or "détail le plus utile" in text:
        return "qualifier"
    return None


def rebuild_state(history, message):
    state = {
        "activity": "",
        "need": "",
        "qualifier": "",
        "name": "",
        "email": "",
        "phone": "",
    }
    sequence = [
        (item.get("role"), item.get("content", "") or "")
        for item in history
        if isinstance(item, dict) and item.get("role") in ("user", "assistant")
    ]
    if message:
        sequence.append(("user", message))

    last_ask = None
    for role, content in sequence:
        if role == "assistant":
            last_ask = detect_ask(content)
            continue

        if not state["email"]:
            state["email"] = find_email(content)
        if not state["phone"]:
            state["phone"] = find_phone(content)
        if not state["name"]:
            state["name"] = find_name(content)

        if last_ask and not is_greeting(content):
            value = str(content or "").strip()
            if last_ask == "activity" and not state["activity"]:
                state["activity"] = value[:100]
            elif last_ask == "need" and not state["need"]:
                state["need"] = value[:160]
            elif last_ask == "qualifier" and not state["qualifier"]:
                state["qualifier"] = value[:160]
            elif last_ask == "name" and not state["name"]:
                state["name"] = bare_name(value)
        last_ask = None

    return state


def fallback_reply(state):
    if not state["activity"]:
        return "Bonjour 🙂 Pour rendre cette démonstration utile, quel est votre métier ou votre activité ?"
    if not state["need"]:
        return (
            "Très bien. Qu’aimeriez-vous que Betty qualifie ou récupère sur votre site : "
            "demandes de devis, rendez-vous, inscriptions, ventes ou autre chose ?"
        )
    if not state["qualifier"]:
        return (
            "Quel critère serait le plus utile pour qualifier ces demandes : "
            "la ville, la prestation, le budget, le délai ou l’urgence ?"
        )
    if not state["name"]:
        return (
            "Parfait — j’ai maintenant assez de contexte pour montrer la valeur de Betty. "
            "Quel est votre prénom ?"
        )
    if not state["email"] and not state["phone"]:
        return (
            f"Merci, {state['name']}. Quel moyen préférez-vous pour recevoir les "
            "informations d’activation : votre email ou votre mobile ?"
        )

    contact = state["email"] or state["phone"]
    return (
        f"Parfait, {state['name']} ! Voici le résumé qualifié que le professionnel recevrait :\n"
        f"• Activité : {state['activity']}\n"
        f"• Besoin : {state['need']}\n"
        f"• Critère utile : {state['qualifier']}\n"
        f"• Contact : {contact}\n\n"
        "C’est ainsi que Betty transforme un visiteur anonyme en prospect prêt à rappeler, 24 h/24.\n"
        f"{SIGNUP_LINK}"
    )


def call_together(history, message):
    if not TOGETHER_API_KEY:
        return None

    messages = [{"role": "system", "content": load_prompt()}]
    for item in history[-12:]:
        if (
            isinstance(item, dict)
            and item.get("role") in ("user", "assistant")
            and item.get("content")
        ):
            messages.append({
                "role": item["role"],
                "content": str(item["content"])[:1500],
            })
    messages.append({"role": "user", "content": message})

    try:
        response = requests.post(
            TOGETHER_API_URL,
            headers={
                "Authorization": f"Bearer {TOGETHER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": LLM_MODEL,
                "messages": messages,
                "temperature": 0.55,
                "max_tokens": 220,
            },
            timeout=15,
        )
        if not response.ok:
            app.logger.warning("Together HTTP %s", response.status_code)
            return None
        reply = (
            (response.json().get("choices") or [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        if reply and not re.search(
            r"erreur|error|together|api key|crédit|credit|traceback|exception",
            reply,
            re.I,
        ):
            return reply
    except Exception as exc:
        app.logger.warning("Together indisponible: %s", type(exc).__name__)
    return None


def send_lead_email(state):
    public_key = os.environ.get("MJ_APIKEY_PUBLIC", "")
    private_key = os.environ.get("MJ_APIKEY_PRIVATE", "")
    if not public_key or not private_key:
        return False

    body = (
        "🎯 Nouveau prospect Betty (démo FR)\n\n"
        f"Prénom   : {state.get('name') or '-'}\n"
        f"Email    : {state.get('email') or '-'}\n"
        f"Mobile   : {state.get('phone') or '-'}\n"
        f"Activité : {state.get('activity') or '-'}\n"
        f"Besoin   : {state.get('need') or '-'}\n"
        f"Critère  : {state.get('qualifier') or '-'}\n"
    )
    try:
        response = requests.post(
            "https://api.mailjet.com/v3.1/send",
            auth=(public_key, private_key),
            json={"Messages": [{
                "From": {"Email": LEAD_EMAIL, "Name": "Betty Démo FR"},
                "To": [{"Email": LEAD_EMAIL}],
                "Subject": f"🎯 Prospect Betty FR : {state.get('name') or 'nouveau contact'}",
                "TextPart": body,
            }]},
            timeout=10,
        )
        return bool(response.ok)
    except Exception:
        return False


@app.route("/")
def home():
    return render_template("chat.html")


@app.route("/healthz")
def healthz():
    return "ok", 200


@app.route("/api/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json(silent=True) or {}
        message = str(data.get("message") or "").strip()
        history = data.get("history") or []
        if not isinstance(history, list):
            history = []

        if not message:
            return jsonify({
                "response": "Bonjour 🙂 Pour rendre cette démonstration utile, quel est votre métier ou votre activité ?",
                "lead_captured": False,
            })

        before = rebuild_state(history, "")
        state = rebuild_state(history, message)
        reply = call_together(history, message) or fallback_reply(state)

        had_contact = bool(before["email"] or before["phone"])
        has_contact = bool(state["email"] or state["phone"])
        lead_captured = send_lead_email(state) if has_contact and not had_contact else False

        return jsonify({
            "response": reply,
            "lead_captured": lead_captured,
            "qualified": has_contact,
        })
    except Exception as exc:
        app.logger.warning("Erreur chat: %s", type(exc).__name__)
        return jsonify({
            "response": "Bonjour 🙂 Pour commencer, quel est votre métier ou votre activité ?",
            "lead_captured": False,
        })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
