import json
import os
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
DATA_FILE = "data.json"

# ================= DATA HELPERS =================
def load_data():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_user(data, uid):
    uid = str(uid)
    if uid not in data["users"]:
        data["users"][uid] = {
            "points": 0,
            "number": None,
            "deposit": 0,
            "pending_deposit": 0,
            "referred_by": None
        }
    return data["users"][uid]

# ================= MAIN MENU =================
async def show_main_menu(target, context):
    text = (
        "📲 *Virtual Number OTP Bot*\n\n"
        "This bot provides virtual numbers for OTP verification.\n"
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
        await target.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown"
        )
    else:
        await target.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown"
        )

# ================= START + AUTO REFERRAL =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    uid = str(update.effective_user.id)

    is_new = uid not in data["users"]
    user = get_user(data, uid)

    if is_new and context.args:
        ref_id = context.args[0]
        if ref_id != uid and ref_id in data["users"]:
            user["referred_by"] = ref_id
            data["users"][ref_id]["points"] += 1

    save_data(data)
    await show_main_menu(update, context)

# ================= BACK =================
async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await show_main_menu(q, context)

# ================= PROFILE =================
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = load_data()
    u = get_user(data, q.from_user.id)

    await q.answer()
    await q.edit_message_text(
        f"👤 *Your Profile*\n\n"
        f"🎁 Points: {u['points']}\n"
        f"📱 Active Number: {u['number'] or 'None'}\n"
        f"💳 Total Deposit: ₹{u['deposit']}\n"
        f"👥 Referred By: {u['referred_by'] or 'None'}",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back", callback_data="back")]]
        ),
        parse_mode="Markdown"
    )

# ================= BUY NUMBERS =================
async def buy_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = load_data()
    rows = []

    temp = []
    for c, d in data["numbers"].items():
        flag = "🇮🇳" if c == "IN" else "🇺🇸"
        temp.append(
            InlineKeyboardButton(
                f"{flag} {c} – {d['points']} pts",
                callback_data=f"sel_{c}"
            )
        )
        if len(temp) == 2:
            rows.append(temp)
            temp = []

    if temp:
        rows.append(temp)

    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back")])

    await q.answer()
    await q.edit_message_text(
        "📲 *Select a number*",
        reply_markup=InlineKeyboardMarkup(rows),
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
    data = load_data()
    u = get_user(data, q.from_user.id)
    c = context.user_data["buy"]

    cost = data["numbers"][c]["points"]
    if u["points"] < cost:
        await q.answer("Not enough points", show_alert=True)
        return

    u["points"] -= cost
    u["number"] = data["numbers"][c]["number"]
    save_data(data)

    await q.edit_message_text(
        f"📱 *Number Purchased*\n\n`{u['number']}`",
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
    q = update.callback_query
    otp = random.randint(100000, 999999)

    await q.answer()
    await q.edit_message_text(
        f"📩 *Your OTP*\n\n`{otp}`",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back", callback_data="back")]]
        ),
        parse_mode="Markdown"
    )

# ================= DEPOSIT =================
async def deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    context.user_data["awaiting_amount"] = True

    await q.answer()
    await q.edit_message_text(
        "💰 *Deposit Balance*\n\n"
        "Enter amount (minimum ₹10)",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back", callback_data="back")]]
        ),
        parse_mode="Markdown"
    )

async def deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_amount"):
        return

    try:
        amount = int(update.message.text)
    except ValueError:
        await update.message.reply_text("❌ Enter a valid number")
        return

    if amount < 10:
        await update.message.reply_text("❌ Minimum deposit is ₹10")
        return

    data = load_data()
    u = get_user(data, update.effective_user.id)
    u["pending_deposit"] = amount
    save_data(data)

    context.user_data["awaiting_amount"] = False
    context.user_data["awaiting_ss"] = True

    await update.message.reply_text(
        f"💰 Amount: ₹{amount}\n\n"
        "UPI ID:\n`7309248020@fam`\n\n"
        "Send payment screenshot"
    )

# ================= SCREENSHOT =================
async def screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("awaiting_ss"):
        uid = update.message.from_user.id
        data = load_data()
        amt = data["users"][str(uid)]["pending_deposit"]

        kb = [[
            InlineKeyboardButton("✅ Approve", callback_data=f"ap_{uid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"rej_{uid}")
        ]]

        await context.bot.send_photo(
            ADMIN_ID,
            update.message.photo[-1].file_id,
            caption=f"Deposit request\nUser: {uid}\nAmount: ₹{amt}",
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
    data = load_data()
    u = get_user(data, uid)

    if action == "ap":
        amt = u["pending_deposit"]
        u["deposit"] += amt
        u["pending_deposit"] = 0
        save_data(data)
        await context.bot.send_message(uid, f"✅ Deposit approved\n₹{amt}")
        await q.edit_message_caption("Approved ✅")
    else:
        u["pending_deposit"] = 0
        save_data(data)
        await context.bot.send_message(uid, "❌ Deposit rejected")
        await q.edit_message_caption("Rejected ❌")

# ================= REFER =================
async def refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    link = f"https://t.me/{context.bot.username}?start={uid}"

    await q.answer()
    await q.edit_message_text(
        f"🎁 *Refer & Earn*\n\n"
        f"1 Referral = 1 Point\n\n"
        f"{link}",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back", callback_data="back")]]
        ),
        parse_mode="Markdown"
    )

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(CallbackQueryHandler(profile, pattern="^profile$"))
    app.add_handler(CallbackQueryHandler(buy_menu, pattern="^buy$"))
    app.add_handler(CallbackQueryHandler(confirm_buy, pattern="^sel_"))
    app.add_handler(CallbackQueryHandler(buy_ok, pattern="^buy_ok$"))
    app.add_handler(CallbackQueryHandler(get_otp, pattern="^otp$"))
    app.add_handler(CallbackQueryHandler(deposit, pattern="^deposit$"))
    app.add_handler(CallbackQueryHandler(refer, pattern="^refer$"))
    app.add_handler(CallbackQueryHandler(admin_action, pattern="^(ap_|rej_)"))
    app.add_handler(CallbackQueryHandler(back, pattern="^back$"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_amount))
    app.add_handler(MessageHandler(filters.PHOTO, screenshot))

    app.run_polling()

if __name__ == "__main__":
    main()
