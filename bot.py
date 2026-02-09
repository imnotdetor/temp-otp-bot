import os
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
    kb = []

    for n in numbers_col.find():
        kb.append([
            InlineKeyboardButton(
                f"{n['country']} – {n['points']} pts",
                callback_data=f"sel_{n['country']}"
            )
        ])

    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="back")])

    await q.answer()
    await q.edit_message_text(
        "📲 *Select a number*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

async def confirm_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    context.user_data["buy"] = q.data.split("_")[1]

    await q.answer()
    await q.edit_message_text(
        "Confirm purchase?",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Buy", callback_data="buy_ok"),
                InlineKeyboardButton("⬅️ Back", callback_data="back")
            ]
        ])
    )

async def buy_ok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user = get_user(q.from_user.id)
    country = context.user_data["buy"]

    num = numbers_col.find_one({"country": country})
    if not num:
        await q.answer("Number not available", show_alert=True)
        return

    if user["points"] < num["points"]:
        await q.answer("Not enough points", show_alert=True)
        return

    user["points"] -= num["points"]
    user["number"] = num.get("number", "+0000000000")
    save_user(user)

    await q.edit_message_text(
        f"📱 *Number Purchased*\n\n`{user['number']}`",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📩 Get OTP", callback_data="otp"),
                InlineKeyboardButton("⬅️ Back", callback_data="back")
            ]
        ]),
        parse_mode="Markdown"
    )

# ================= OTP =================
async def get_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    otp = random.randint(100000, 999999)
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        f"📩 *Your OTP*\n\n`{otp}`",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]]),
        parse_mode="Markdown"
    )

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

    country, points, number = context.args
    numbers_col.update_one(
        {"country": country},
        {"$set": {"country": country, "points": int(points), "number": number}},
        upsert=True
    )
    await update.message.reply_text("✅ Number added/updated")

# ================= REFER =================
async def refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    link = f"https://t.me/{context.bot.username}?start={uid}"

    await q.answer()
    await q.edit_message_text(
        f"🎁 *Refer & Earn*\n\n1 Referral = 1 Point\n\n{link}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]]),
        parse_mode="Markdown"
    )

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addpoints", addpoints))
    app.add_handler(CommandHandler("addnumber", addnumber))

    app.add_handler(CallbackQueryHandler(profile, "^profile$"))
    app.add_handler(CallbackQueryHandler(buy_menu, "^buy$"))
    app.add_handler(CallbackQueryHandler(confirm_buy, "^sel_"))
    app.add_handler(CallbackQueryHandler(buy_ok, "^buy_ok$"))
    app.add_handler(CallbackQueryHandler(get_otp, "^otp$"))
    app.add_handler(CallbackQueryHandler(deposit, "^deposit$"))
    app.add_handler(CallbackQueryHandler(refer, "^refer$"))
    app.add_handler(CallbackQueryHandler(admin_action, "^(ap_|rej_)"))
    app.add_handler(CallbackQueryHandler(back, "^back$"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_amount))
    app.add_handler(MessageHandler(filters.PHOTO, screenshot))

    app.run_polling()

if __name__ == "__main__":
    main()
