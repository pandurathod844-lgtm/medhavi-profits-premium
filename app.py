import os
import time
import hmac
import hashlib
import threading
import requests

from flask import Flask, request, jsonify

app = Flask(__name__)

# =========================
# ENVIRONMENT VARIABLES
# =========================

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL_ID = os.environ["TELEGRAM_CHANNEL_ID"]

RAZORPAY_KEY_ID = os.environ["RAZORPAY_KEY_ID"]
RAZORPAY_KEY_SECRET = os.environ["RAZORPAY_KEY_SECRET"]
RAZORPAY_WEBHOOK_SECRET = os.environ["RAZORPAY_WEBHOOK_SECRET"]
RAZORPAY_PLAN_ID = os.environ["RAZORPAY_PLAN_ID"]

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
RAZORPAY_API = "https://api.razorpay.com/v1"


# =========================
# TELEGRAM FUNCTIONS
# =========================

def telegram(method, data=None):
    url = f"{TELEGRAM_API}/{method}"
    r = requests.post(url, data=data or {}, timeout=30)
    return r.json()


def send_message(chat_id, text):
    return telegram(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text
        }
    )


def create_invite_link():
    result = telegram(
        "createChatInviteLink",
        {
            "chat_id": CHANNEL_ID,
            "member_limit": 1
        }
    )

    if result.get("ok"):
        return result["result"]["invite_link"]

    print("Invite error:", result)
    return None


def remove_member(user_id):
    telegram(
        "banChatMember",
        {
            "chat_id": CHANNEL_ID,
            "user_id": user_id
        }
    )

    telegram(
        "unbanChatMember",
        {
            "chat_id": CHANNEL_ID,
            "user_id": user_id,
            "only_if_banned": True
        }
    )


# =========================
# RAZORPAY
# =========================

def create_subscription(telegram_user_id):
    url = f"{RAZORPAY_API}/subscriptions"

    payload = {
        "plan_id": RAZORPAY_PLAN_ID,
        "total_count": 1200,
        "quantity": 1,
        "customer_notify": True,
        "notes": {
            "telegram_user_id": str(telegram_user_id)
        }
    }

    r = requests.post(
        url,
        auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
        json=payload,
        timeout=30
    )

    return r.json()


# =========================
# TELEGRAM POLLING
# =========================

def telegram_polling():
    offset = None

    while True:
        try:
            params = {
                "timeout": 30
            }

            if offset:
                params["offset"] = offset

            r = requests.get(
                f"{TELEGRAM_API}/getUpdates",
                params=params,
                timeout=40
            )

            data = r.json()

            if not data.get("ok"):
                time.sleep(5)
                continue

            for update in data.get("result", []):
                offset = update["update_id"] + 1

                message = update.get("message")

                if not message:
                    continue

                chat_id = message["chat"]["id"]
                text = message.get("text", "").strip()

                if text == "/start":
                    send_message(
                        chat_id,
                        "👋 Welcome to Medhavi Profits Premium!\n\n"
                        "💎 Monthly Membership: ₹1,499\n\n"
                        "Premium membership కోసం /join టైప్ చేయండి."
                    )

                elif text == "/join":
                    send_message(
                        chat_id,
                        "⏳ మీ ₹1,499 monthly subscription payment link create చేస్తున్నాను..."
                    )

                    result = create_subscription(chat_id)

                    if result.get("short_url"):
                        send_message(
                            chat_id,
                            "💎 MEDHAVI PROFITS PREMIUM\n\n"
                            "💰 Monthly: ₹1,499\n"
                            "🔄 Auto-renewal: Monthly\n\n"
                            "👇 Payment complete చేయడానికి ఈ link open చేయండి:\n\n"
                            f"{result['short_url']}\n\n"
                            "Payment successful అయిన తర్వాత premium channel access link మీకు automatically వస్తుంది."
                        )
                    else:
                        print("Subscription creation error:", result)

                        send_message(
                            chat_id,
                            "❌ Payment link create కాలేదు.\n"
                            "కొద్దిసేపటి తర్వాత మళ్లీ /join ప్రయత్నించండి."
                        )

        except Exception as e:
            print("Telegram polling error:", e)
            time.sleep(5)


# =========================
# RAZORPAY WEBHOOK
# =========================

@app.route("/webhook/razorpay", methods=["POST"])
def razorpay_webhook():

    body = request.get_data()

    received_signature = request.headers.get(
        "X-Razorpay-Signature",
        ""
    )

    expected_signature = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(
        received_signature,
        expected_signature
    ):
        return jsonify({"status": "invalid signature"}), 400

    data = request.get_json()

    event = data.get("event", "")

    print("Razorpay Event:", event)

    subscription = (
        data.get("payload", {})
        .get("subscription", {})
        .get("entity", {})
    )

    notes = subscription.get("notes", {})

    telegram_user_id = notes.get("telegram_user_id")

    if not telegram_user_id:
        print("Telegram user ID not found")
        return jsonify({"status": "ok"}), 200

    # =========================
    # PAYMENT SUCCESS
    # =========================

    if event in [
        "subscription.authenticated",
        "subscription.activated",
        "subscription.charged"
    ]:

        invite_link = create_invite_link()

        if invite_link:
            send_message(
                telegram_user_id,
                "✅ PAYMENT SUCCESSFUL!\n\n"
                "🎉 మీ Medhavi Profits Premium membership active అయింది.\n\n"
                "👇 Premium Channel Join Link:\n"
                f"{invite_link}\n\n"
                "⚠️ ఈ linkని ఇతరులతో share చేయకండి."
            )

    # =========================
    # SUBSCRIPTION STOPPED
    # =========================

    elif event in [
        "subscription.halted",
        "subscription.completed"
    ]:

        send_message(
            telegram_user_id,
            "⚠️ మీ Premium subscription ముగిసింది.\n\n"
            "Premium channel access కూడా ముగించబడుతుంది."
        )

        try:
            remove_member(telegram_user_id)
        except Exception as e:
            print("Remove member error:", e)

    return jsonify({"status": "ok"}), 200


# =========================
# HEALTH CHECK
# =========================

@app.route("/", methods=["GET"])
def home():
    return "Medhavi Profits Premium Bot is running!"


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"})


# =========================
# START
# =========================

if __name__ == "__main__":

    threading.Thread(
        target=telegram_polling,
        daemon=True
    ).start()

    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )
