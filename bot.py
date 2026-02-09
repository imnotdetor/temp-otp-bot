import os
import asyncio
import requests
import time
from bson import ObjectId
import random
from pymongo import MongoClient
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
MONGO_URI = os.getenv("MONGO_URI")

FIVESIM_API = "https://5sim.net/v1"
FIVESIM_KEY = os.getenv("FIVESIM_API_KEY")

HEADERS = {
    "Authorization": f"Bearer {FIVESIM_KEY}",
    "Accept": "application/json"
}
# ================= MONGO =================
client = MongoClient(MONGO_URI)
db = client["otpbot"]
users_col = db["users"]
numbers_col = db["numbers"]

# ================= DATA HELPERS =================
def get_user(uid):
    uid = str(uid)
    user = users_col.find_one({"_id": uid})
    if not user:
        user = {
            "_id": uid,
            "points": 0,
            "number": None,
            "deposit": 0,
            "pending_deposit": 0,
            "referred_by": None
        }
        users_col.insert_one(user)
    return user

def save_user(user):
    users_col.update_one({"_id": user["_id"]}, {"$set": user})

def buy_5sim_number(country="poland", operator="any", service="telegram"):
    url = f"{FIVESIM_API}/user/buy/activation/{country}/{operator}/{service}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    print(r.text)  # DEBUG
    if r.status_code != 200:
        return None
    return r.json()


def check_5sim_sms(order_id):
    url = f"{FIVESIM_API}/user/check/{order_id}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    if r.status_code != 200:
        return None
    return r.json()


def finish_5sim(order_id):
    url = f"{FIVESIM_API}/user/finish/{order_id}"
    requests.get(url, headers=HEADERS)
# ================= MAIN MENU =================
async def show_main_menu(target, context):
    text = (
        "📲 *Virtual Number OTP Bot*\n\n"
        "Buy numbers, receive OTPs, deposit balance & earn via referrals."
    )

    kb = [
        [
            InlineKeyboardButton("👤 Profile", callback_data="profile"),
            InlineKeyboardButton("📲 Buy Numbers", callback_data="buy")
        ],
        [
            InlineKeyboardButton("💰 Deposit", callback_data="deposit"),
            InlineKeyboardButton("🎁 Refer & Earn", callback_data="refer")
        ]
    ]

    if isinstance(target, Update):
        await target.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await target.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

# ================= START + REFERRAL =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    user = get_user(uid)

    if user["referred_by"] is None and context.args:
        ref = context.args[0]
        if ref != uid and users_col.find_one({"_id": ref}):
            user["referred_by"] = ref
            users_col.update_one({"_id": ref}, {"$inc": {"points": 1}})
            save_user(user)

    await show_main_menu(update, context)

# ================= BACK =================
async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await show_main_menu(update.callback_query, context)

# ================= PROFILE =================
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user = get_user(q.from_user.id)

    await q.answer()
    await q.edit_message_text(
        f"👤 *Your Profile*\n\n"
        f"🎁 Points: {user['points']}\n"
        f"📱 Active Number: {user['number'] or 'None'}\n"
        f"💳 Total Deposit: ₹{user['deposit']}\n"
        f"👥 Referred By: {user['referred_by'] or 'None'}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]]),
        parse_mode="Markdown"
    )

# ================= BUY NUMBERS =================
async def buy_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    kb = [
        [InlineKeyboardButton("🇵🇱 Poland | OTP | 1 Point", callback_data="buy_ok")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back")]
    ]

    await q.edit_message_text(
        "📲 *Buy Virtual Number*\n\n"
        "• Country: Poland\n"
        "• Service: Low-strict websites\n"
        "• Price: 1 Point\n\n"
        "👇 Buy now:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def buy_ok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Buying number...")

    user = get_user(q.from_user.id)
    PRICE = 1

    if user["points"] < PRICE:
        await q.edit_message_text("❌ Not enough points")
        return

    data = buy_5sim_number(
    country="poland",
    operator="any",
    service="telegram"
    )

    if not data or "phone" not in data:
        await q.edit_message_text("❌ Number not available, try later")
        return

    # save session
    context.user_data["five_sim"] = {
        "order_id": data["id"],
        "phone": data["phone"]
    }

    user["points"] -= PRICE
    user["number"] = data["phone"]
    save_user(user)

    await q.edit_message_text(
        f"📱 *Number Purchased*\n\n"
        f"{data['phone']}\n\n"
        "Use this number on website, then click *Get OTP*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📩 Get OTP", callback_data="otp")],
            [InlineKeyboardButton("⬅️ Back", callback_data="back")]
        ])
    )
# ================= OTP =================
async def get_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Waiting for OTP...")

    info = context.user_data.get("five_sim")
    if not info:
        await q.edit_message_text("❌ No active number")
        return

    order_id = info["order_id"]

    for _ in range(10):
        data = check_5sim_sms(order_id)

        if data and data.get("sms"):
            code = data["sms"][0]["code"]
            finish_5sim(order_id)

            await q.edit_message_text(
                f"📩 *OTP Received*\n\n`{code}`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back", callback_data="back")]
                ])
            )
            return

        await asyncio.sleep(5)

    await q.edit_message_text("⌛ OTP not received. Try again later.")
# ================= DEPOSIT =================
async def deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    context.user_data["awaiting_amount"] = True

    await q.answer()
    await q.edit_message_text(
        "💰 *Deposit Balance*\n\nEnter amount (minimum ₹10)",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]]),
        parse_mode="Markdown"
    )

async def deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_amount"):
        return

    try:
        amount = int(update.message.text)
    except ValueError:
        await update.message.reply_text("❌ Enter a valid amount")
        return

    if amount < 10:
        await update.message.reply_text("❌ Minimum deposit is ₹10")
        return

    user = get_user(update.effective_user.id)
    user["pending_deposit"] = amount
    save_user(user)

    context.user_data["awaiting_amount"] = False
    context.user_data["awaiting_ss"] = True

    await update.message.reply_text(
        f"💰 Amount: ₹{amount}\n\nUPI ID:\n`7309248020@fam`\n\nSend payment screenshot",
        parse_mode="Markdown"
    )

async def screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("awaiting_ss"):
        uid = update.message.from_user.id
        user = get_user(uid)

        kb = [[
            InlineKeyboardButton("✅ Approve", callback_data=f"ap_{uid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"rej_{uid}")
        ]]

        await context.bot.send_photo(
            ADMIN_ID,
            update.message.photo[-1].file_id,
            caption=f"Deposit Request\nUser: {uid}\nAmount: ₹{user['pending_deposit']}",
            reply_markup=InlineKeyboardMarkup(kb)
        )

        await update.message.reply_text("⏳ Waiting for admin approval")
        context.user_data["awaiting_ss"] = False

# ================= REFER =================
async def refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    link = f"https://t.me/{context.bot.username}?start={uid}"

    text = (
        "🎁 Refer & Earn Points\n\n"
        "1 Successful Referral = 1 Point ✅\n\n"
        "Share this link with friends:\n\n"
        f"{link}\n\n"
        "⚠️ Friend must start the bot using this link"
    )

    # ✅ SAFE: reply_text + NO Markdown
    await q.message.reply_text(text)
# ================= ADMIN APPROVE / REJECT =================
async def admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        return

    action, uid = q.data.split("_")
    user = get_user(uid)

    if action == "ap":
        amt = user["pending_deposit"]
        user["deposit"] += amt
        user["pending_deposit"] = 0
        save_user(user)
        await context.bot.send_message(uid, f"✅ Deposit approved\n₹{amt}")
        await q.edit_message_caption("Approved ✅")
    else:
        user["pending_deposit"] = 0
        save_user(user)
        await context.bot.send_message(uid, "❌ Deposit rejected")
        await q.edit_message_caption("Rejected ❌")

# ================= ADMIN COMMANDS =================
async def addpoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    uid, pts = context.args
    user = get_user(uid)
    user["points"] += int(pts)
    save_user(user)

    await update.message.reply_text(f"✅ Added {pts} points to {uid}")

async def addnumber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if len(context.args) < 3:
        await update.message.reply_text(
            "Usage: /addnumber COUNTRY POINTS NUMBER"
        )
        return

    country, points, number = context.args

    numbers_col.insert_one({
        "country": country,
        "points": int(points),
        "number": number
    })

    await update.message.reply_text(
        f"✅ Number added\n{country} | {number} | {points} pts"
    )


async def delnumber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /delnumber NUMBER_ID"
        )
        return

    try:
        num_id = ObjectId(context.args[0])
    except:
        await update.message.reply_text("❌ Invalid number ID")
        return

    res = numbers_col.delete_one({"_id": num_id})

    if res.deleted_count == 0:
        await update.message.reply_text("❌ Number not found")
    else:
        await update.message.reply_text("✅ Number deleted")

async def listnumbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    text = "📋 *Available Numbers*\n\n"
    for n in numbers_col.find():
        text += (
            f"ID: `{n['_id']}`\n"
            f"Country: {n['country']}\n"
            f"Number: {n['number']}\n"
            f"Points: {n['points']} pts\n\n"
        )

    await update.message.reply_text(text, parse_mode="Markdown")
# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addpoints", addpoints))
    app.add_handler(CommandHandler("addnumber", addnumber))
    app.add_handler(CommandHandler("delnumber", delnumber))
    app.add_handler(CommandHandler("listnumbers", listnumbers))

    # ---- CALLBACK QUERY HANDLERS (ORDER MATTERS) ----
    app.add_handler(CallbackQueryHandler(profile, "^profile$"))
    app.add_handler(CallbackQueryHandler(buy_menu, "^buy$"))

    # buy flow
    app.add_handler(CallbackQueryHandler(buy_ok, "^buy_ok$"))
    app.add_handler(CallbackQueryHandler(get_otp, "^otp$"))

    # deposit
    app.add_handler(CallbackQueryHandler(deposit, "^deposit$"))

    # 🔥 REFER MUST COME BEFORE BACK
    app.add_handler(CallbackQueryHandler(refer, "^refer$"))

    # admin approve/reject
    app.add_handler(CallbackQueryHandler(admin_action, "^(ap_|rej_)"))

    # 🔥 BACK ALWAYS LAST
    app.add_handler(CallbackQueryHandler(back, "^back$"))

    # message handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_amount))
    app.add_handler(MessageHandler(filters.PHOTO, screenshot))

    app.run_polling()

if __name__ == "__main__":
    main()
