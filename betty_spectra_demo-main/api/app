from flask import Flask, render_template, request, jsonify, send_from_directory
import requests
import yaml
import os

# ─── Chemins absolus ───────────────────────────────────────────────
# api/app.py est dans /api/ — templates/ et static/ sont à la RACINE
BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR   = os.path.join(BASE_DIR, "static")

app = Flask(
    __name__,
    template_folder=TEMPLATE_DIR,
    static_folder=STATIC_DIR,
)

# ─── Config LLM ────────────────────────────────────────────────────
TOGETHER_API_KEY = os.environ.get("TOGETHER_API_KEY", "").strip()
TOGETHER_API_URL = "https://api.together.xyz/v1/chat/completions"
LLM_MODEL        = "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"

# ─── Chargement YAML ───────────────────────────────────────────────
YAML_PATH = os.path.join(BASE_DIR, "pack", "betty_spectra.yaml")
with open(YAML_PATH, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

SYSTEM_PROMPT = config["prompt"]

# ─── Historique en mémoire (simple, par session) ───────────────────
# Vercel est stateless — l'historique sera perdu entre les requêtes froides.
# Pour un vrai historique persistant, utilise une DB.
CONV_HISTORY: list[dict] = []

# ─── Routes ────────────────────────────────────────────────────────

@app.route("/")
def home():
    return render_template("chat.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    data         = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()

    if not user_message:
        return jsonify({"response": "Je vous écoute 🙂"})

    if not TOGETHER_API_KEY:
        return jsonify({"response": "Erreur serveur : TOGETHER_API_KEY manquant."}), 500

    # Garde les 8 derniers échanges
    CONV_HISTORY.append({"role": "user", "content": user_message})
    history = CONV_HISTORY[-8:]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

    try:
        response = requests.post(
            TOGETHER_API_URL,
            headers={
                "Authorization": f"Bearer {TOGETHER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model":       LLM_MODEL,
                "messages":    messages,
                "temperature": 0.7,
                "max_tokens":  220,
            },
            timeout=30,
        )
        response.raise_for_status()
        reply = response.json()["choices"][0]["message"]["content"].strip()

    except requests.exceptions.HTTPError as e:
        print("ERREUR TOGETHER HTTP :", e, response.text[:300])
        reply = "Petit souci côté IA. Réessayez dans un instant 🙂"

    except Exception as e:
        print("ERREUR LLM :", e)
        reply = "Petit souci technique… pouvez-vous reformuler ? 🙂"

    CONV_HISTORY.append({"role": "assistant", "content": reply})

    return jsonify({"response": reply})


@app.route("/healthz")
def healthz():
    return "ok", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
