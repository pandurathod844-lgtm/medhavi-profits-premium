import os
import time
import hmac
import hashlib
import threading
import requests

from flask import Flask, request, jsonify
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


# =========================
# ENVIRONMENT VARIABLES
# =========================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
RAZORPAY_PLAN_ID = os.getenv("RAZORPAY_PLAN_ID")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET")


# =========================
# FLASK APP
# =========================

app = Flask(__name__)

processed_subscriptions = set()


# =========================
# TELEGRAM API
# =========================

def telegram_api(method, data):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"

    try:
        response = requests.post(
            url,
            json=data,
            timeout=30
        )

        print("Telegram:", method, response.status_code)
        print(response.text)

        return response.json()

    except Exception as e:
        print("Telegram API Error:", e)
        return {}


# =========================
# RAZORPAY SUBSCRIPTION
# =========================

def create_subscription(telegram_user_id):

    url = "https://api.razorpay.com/v1/subscriptions"

    data = {
        "plan_id": RAZORPAY_PLAN_ID,
        "total_count": 12,
        "quantity": 1,
        "customer_notify": True,
        "notes": {
            "telegram_user_id": str(telegram_user_id)
        }
    }

    try:

        response = requests.post(
            url,
            auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
            json=data,
            timeout=30
        )

        print("Razorpay Status:", response.status_code)
        print("Razorpay Response:", response.text)

        result = response.json()

        if response.status_code >= 400:
            return None, result

        return result, None

    except Exception as e:

        print("Razorpay Exception:", e)

        return None, {
            "error": {
                "description": str(e)
            }
        }


# =========================
# /START
# =========================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.effective_message

    await message.reply_text(
        "👋 Medhavi Profits Premium కు స్వాగతం!\n\n"
        "💎 Premium Membership\n"
        "💰 ₹1499 / Month\n\n"
        "Premium membership కోసం /join పంపండి."
    )


# =========================
# /JOIN
# =========================

async def join_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.effective_message
    chat_id = message.chat_id

    print("JOIN REQUEST:", chat_id)

    result, error = create_subscription(chat_id)

    if error:

        error_message = (
            error
            .get("error", {})
            .get("description")
            or str(error)
        )

        await message.reply_text(
            "❌ Razorpay Error:\n\n"
            + error_message
        )

        return

    short_url = result.get("short_url")

    if not short_url:

        await message.reply_text(
            "❌ Payment link create కాలేదు.\n"
            "కొద్దిసేపటి తర్వాత మళ్లీ ప్రయత్నించండి."
        )

        return

    await message.reply_text(
        "💎 Medhavi Profits Premium\n\n"
        "💰 Membership: ₹1499 / Month\n\n"
        "👇 Payment చేయడానికి ఈ link open చేయండి:\n\n"
        + short_url
        + "\n\n"
        "✅ Payment successful అయిన తర్వాత "
        "Premium Channel access కోసం invite link వస్తుంది."
    )


# =========================
# TELEGRAM POLLING
# =========================

def run_telegram():

    try:

        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        telegram_app = (
            Application
            .builder()
            .token(TELEGRAM_BOT_TOKEN)
            .build()
        )

        telegram_app.add_handler(
            CommandHandler("start", start_command)
        )

        telegram_app.add_handler(
            CommandHandler("join", join_command)
        )

        loop.run_until_complete(
            telegram_app.initialize()
        )

        loop.run_until_complete(
            telegram_app.start()
        )

        loop.run_until_complete(
            telegram_app.updater.start_polling()
        )

        print("Telegram Bot Started")

        loop.run_forever()

    except Exception as e:

        print("Telegram error:", e)


# =========================
# RAZORPAY WEBHOOK
# =========================

@app.route("/webhook/razorpay", methods=["POST"])
def razorpay_webhook():

    payload = request.get_data()

    signature = request.headers.get(
        "X-Razorpay-Signature",
        ""
    )

    expected_signature = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(
        signature,
        expected_signature
    ):

        print("Invalid Razorpay webhook signature")

        return jsonify({
            "status": "invalid signature"
        }), 400


    data = request.get_json(silent=True) or {}

    event = data.get("event", "")

    print("Razorpay Event:", event)


    if event == "subscription.charged":

        try:

            subscription = (
                data
                .get("payload", {})
                .get("subscription", {})
                .get("entity", {})
            )

            subscription_id = subscription.get("id")

            notes = subscription.get(
                "notes",
                {}
            )

            telegram_user_id = notes.get(
                "telegram_user_id"
            )

            if (
                subscription_id
                and telegram_user_id
                and subscription_id
                not in processed_subscriptions
            ):

                processed_subscriptions.add(
                    subscription_id
                )

                # Create one-time invite link
                invite_result = telegram_api(
                    "createChatInviteLink",
                    {
                        "chat_id": TELEGRAM_CHANNEL_ID,
                        "member_limit": 1,
                        "expire_date": int(time.time()) + 86400
                    }
                )

                invite_link = (
                    invite_result
                    .get("result", {})
                    .get("invite_link")
                )

                if invite_link:

                    telegram_api(
                        "sendMessage",
                        {
                            "chat_id": telegram_user_id,
                            "text":
                                "🎉 Payment Successful!\n\n"
                                "💎 Medhavi Profits Premium\n\n"
                                "👇 Premium Channel Join Link:\n\n"
                                + invite_link
                                + "\n\n"
                                "⚠️ ఈ link ఒక్కసారి మాత్రమే ఉపయోగించండి."
                        }
                    )

                    print(
                        "Premium invite sent to:",
                        telegram_user_id
                    )

        except Exception as e:

            print(
                "Webhook processing error:",
                e
            )


    return jsonify({
        "status": "ok"
    }), 200


# =========================
# HEALTH CHECK
# =========================

@app.route("/", methods=["GET"])
def home():

    return "Medhavi Profits Premium Bot is Running!"


@app.route("/health", methods=["GET"])
def health():

    return jsonify({
        "status": "ok",
        "bot": "running"
    })


# =========================
# START BOT + SERVER
# =========================

if __name__ == "__main__":

    telegram_thread = threading.Thread(
        target=run_telegram,
        daemon=True
    )

    telegram_thread.start()

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
