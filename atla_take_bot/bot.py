import asyncio
import random
import sqlite3
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)


# =========================================================
# SETTINGS
# =========================================================

TOKEN = "توکن_جدید_بات_خودت"

BOT_NAME = "𝗔𝘁𝗹𝗮Take"

# Auto Spawn:
# 300 seconds = 5 minutes
AUTO_SPAWN_INTERVAL = 300

# Database
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "atla_take.db"

# Images
IMAGE_DIR = BASE_DIR / "images"


# =========================================================
# CHARACTERS
# =========================================================
#
# برای اضافه کردن کاراکتر جدید فقط یک مورد جدید به این لیست اضافه کن.
#
# مثال:
#
# {
#     "name": "catna",
#     "display_name": "Catna",
#     "universe": "Core",
#     "rarity": "Legendary",
#     "image": "images/catna.jpg",
# }
#

CHARACTERS = [
    {
        "name": "thekip",
        "display_name": "Thekip",
        "universe": "Core",
        "rarity": "Mythic",
        "image": "images/thekip.jpg",
    },
]


# =========================================================
# GLOBALS
# =========================================================

# برای جلوگیری از Race Condition هنگام Take
spawn_lock = asyncio.Lock()


# =========================================================
# DATABASE
# =========================================================

def get_db():
    """
    اتصال به دیتابیس SQLite
    """

    conn = sqlite3.connect(DB_PATH)

    conn.row_factory = sqlite3.Row

    return conn


def init_database():
    """
    ساخت جدول‌های مورد نیاز
    """

    conn = get_db()

    cursor = conn.cursor()

    # -----------------------------------------------------
    # Characters
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS characters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            universe TEXT NOT NULL,
            rarity TEXT NOT NULL,
            image TEXT NOT NULL
        )
    """)

    # -----------------------------------------------------
    # Users
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            coins INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # -----------------------------------------------------
    # User Collection
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS collection (
            user_id INTEGER NOT NULL,
            character_id INTEGER NOT NULL,
            quantity INTEGER DEFAULT 0,

            PRIMARY KEY (user_id, character_id),

            FOREIGN KEY (user_id)
                REFERENCES users(user_id),

            FOREIGN KEY (character_id)
                REFERENCES characters(id)
        )
    """)

    # -----------------------------------------------------
    # Chats
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            auto_spawn INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # -----------------------------------------------------
    # Active Spawn
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS active_spawns (
            chat_id INTEGER PRIMARY KEY,
            character_id INTEGER NOT NULL,
            spawned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (character_id)
                REFERENCES characters(id)
        )
    """)

    # -----------------------------------------------------
    # Insert Characters
    # -----------------------------------------------------

    for character in CHARACTERS:

        cursor.execute("""
            INSERT OR IGNORE INTO characters
            (
                name,
                display_name,
                universe,
                rarity,
                image
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            character["name"],
            character["display_name"],
            character["universe"],
            character["rarity"],
            character["image"],
        ))

    conn.commit()
    conn.close()


# =========================================================
# USER DATABASE
# =========================================================

def register_user(user):
    """
    کاربر را در دیتابیس ثبت یا اطلاعاتش را آپدیت می‌کند.
    """

    conn = get_db()

    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO users
        (
            user_id,
            username,
            first_name
        )
        VALUES (?, ?, ?)

        ON CONFLICT(user_id)
        DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name
    """, (
        user.id,
        user.username,
        user.first_name,
    ))

    conn.commit()
    conn.close()


# =========================================================
# CHAT DATABASE
# =========================================================

def register_chat(chat):
    """
    گروه / چت را ثبت می‌کند.
    """

    conn = get_db()

    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO chats
        (
            chat_id,
            title
        )
        VALUES (?, ?)

        ON CONFLICT(chat_id)
        DO UPDATE SET
            title = excluded.title
    """, (
        chat.id,
        chat.title or chat.first_name or "Private Chat",
    ))

    conn.commit()
    conn.close()


def set_auto_spawn(chat_id, enabled):
    """
    فعال یا غیرفعال کردن Auto Spawn
    """

    conn = get_db()

    cursor = conn.cursor()

    cursor.execute("""
        UPDATE chats
        SET auto_spawn = ?
        WHERE chat_id = ?
    """, (
        1 if enabled else 0,
        chat_id,
    ))

    conn.commit()
    conn.close()


# =========================================================
# CHARACTER HELPERS
# =========================================================

def get_random_character():
    """
    انتخاب تصادفی کاراکتر
    """

    conn = get_db()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM characters
        ORDER BY RANDOM()
        LIMIT 1
    """)

    character = cursor.fetchone()

    conn.close()

    return character


def get_character_by_name(name):
    """
    پیدا کردن کاراکتر با اسم
    """

    conn = get_db()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM characters
        WHERE LOWER(name) = LOWER(?)
    """, (
        name,
    ))

    character = cursor.fetchone()

    conn.close()

    return character


# =========================================================
# SPAWN HELPERS
# =========================================================

def get_active_spawn(chat_id):
    """
    گرفتن Spawn فعلی یک چت
    """

    conn = get_db()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            active_spawns.chat_id,
            active_spawns.spawned_at,

            characters.id,
            characters.name,
            characters.display_name,
            characters.universe,
            characters.rarity,
            characters.image

        FROM active_spawns

        JOIN characters
            ON characters.id = active_spawns.character_id

        WHERE active_spawns.chat_id = ?
    """, (
        chat_id,
    ))

    spawn = cursor.fetchone()

    conn.close()

    return spawn


def create_spawn(chat_id):
    """
    ایجاد یک Spawn جدید.
    اگر قبلاً Spawn فعال وجود داشته باشد، None برمی‌گرداند.
    """

    conn = get_db()

    cursor = conn.cursor()

    # بررسی Spawn قبلی
    cursor.execute("""
        SELECT *
        FROM active_spawns
        WHERE chat_id = ?
    """, (
        chat_id,
    ))

    existing = cursor.fetchone()

    if existing:
        conn.close()
        return None

    # انتخاب کاراکتر
    character = get_random_character()

    if character is None:
        conn.close()
        return None

    # ساخت Spawn
    cursor.execute("""
        INSERT INTO active_spawns
        (
            chat_id,
            character_id
        )
        VALUES (?, ?)
    """, (
        chat_id,
        character["id"],
    ))

    conn.commit()
    conn.close()

    return character


# =========================================================
# SPAWN CAPTION
# =========================================================

def get_hidden_name(character):
    """
    اسم مخفی کاراکتر
    """

    name = character["name"]

    # فعلاً سیستم ساده
    if name.lower() == "thekip":
        return "t _ _ k _ p"

    # برای بقیه کاراکترها
    if len(name) <= 2:
        return "??"

    hidden = ""

    for index, char in enumerate(name):

        if index == 0 or index == len(name) - 1:
            hidden += char

        else:
            hidden += "_"

        hidden += " "

    return hidden.strip()


def build_spawn_caption(character):
    """
    متن کارت Spawn
    """

    hidden_name = get_hidden_name(character)

    return (
        "🃏 A CHARACTER APPEARED!\n\n"

        f"🌍 Universe: {character['universe']}\n"
        f"⭐ Rarity: {character['rarity']}\n"
        f"🔤 Name: {hidden_name}\n\n"

        "🎯 اولین نفری که اسم درست رو بفرسته برنده میشه!\n\n"

        "مثال:\n"
        "/take thekip"
    )


# =========================================================
# SEND SPAWN
# =========================================================

async def send_spawn(bot, chat_id, character):

    image_path = BASE_DIR / character["image"]

    caption = build_spawn_caption(character)

    # اگر عکس وجود داشت
    if image_path.exists():

        with open(image_path, "rb") as photo:

            await bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption,
            )

    else:

        # اگر عکس پیدا نشد، بات از کار نمی‌افتد
        await bot.send_message(
            chat_id=chat_id,
            text=caption
            + "\n\n⚠️ تصویر این کاراکتر پیدا نشد.",
        )


# =========================================================
# /START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user
    chat = update.effective_chat

    if user:
        register_user(user)

    if chat:
        register_chat(chat)

    await update.message.reply_text(
        f"🎴 {BOT_NAME}\n\n"

        "به AtlaTake خوش اومدی! 🔥\n\n"

        "🎲 /spawn — اسپاون کاراکتر\n"
        "🎯 /take <name> — گرفتن کاراکتر\n"
        "🎴 /collection — کلکسیون تو\n"
        "👤 /profile — پروفایل\n"
        "⚡ /autospawn on/off — کنترل اسپاون خودکار\n\n"

        "مثال:\n"
        "/take thekip"
    )


# =========================================================
# /SPAWN
# =========================================================

async def spawn(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id

    register_chat(update.effective_chat)

    async with spawn_lock:

        existing = get_active_spawn(chat_id)

        if existing:

            await update.message.reply_text(
                "⚠️ هنوز یک کاراکتر برای گرفتن وجود داره!\n\n"

                "🎯 اولین نفری که اسم درست رو بفرسته، "
                "کاراکتر رو می‌گیره."
            )

            return

        character = create_spawn(chat_id)

    if character is None:

        await update.message.reply_text(
            "❌ فعلاً امکان Spawn کردن کاراکتر وجود نداره."
        )

        return

    await send_spawn(
        context.bot,
        chat_id,
        character,
    )


# =========================================================
# AUTO SPAWN
# =========================================================

async def auto_spawn(context: ContextTypes.DEFAULT_TYPE):

    conn = get_db()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT chat_id
        FROM chats
        WHERE auto_spawn = 1
    """)

    chats = cursor.fetchall()

    conn.close()

    for row in chats:

        chat_id = row["chat_id"]

        try:

            async with spawn_lock:

                existing = get_active_spawn(chat_id)

                if existing:
                    continue

                character = create_spawn(chat_id)

            if character is None:
                continue

            await send_spawn(
                context.bot,
                chat_id,
                character,
            )

        except Exception as error:

            print(
                f"[AUTO SPAWN ERROR] "
                f"{chat_id}: {error}"
            )


# =========================================================
# /TAKE
# =========================================================

async def take(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user
    chat_id = update.effective_chat.id

    register_user(user)

    if not context.args:

        await update.message.reply_text(
            "❌ اسم کاراکتر رو وارد کن.\n\n"

            "مثال:\n"
            "/take thekip"
        )

        return

    answer = " ".join(
        context.args
    ).strip().lower()

    # -----------------------------------------------------
    # Race Condition Protection
    # -----------------------------------------------------

    async with spawn_lock:

        spawn = get_active_spawn(chat_id)

        if spawn is None:

            await update.message.reply_text(
                "❌ در حال حاضر هیچ کاراکتری "
                "برای گرفتن وجود نداره."
            )

            return

        correct_name = spawn["name"].lower()

        # جواب اشتباه
        if answer != correct_name:

            await update.message.reply_text(
                "❌ Wrong character!"
            )

            return

        conn = get_db()

        cursor = conn.cursor()

        # -------------------------------------------------
        # حذف Spawn
        # -------------------------------------------------

        cursor.execute("""
            DELETE FROM active_spawns
            WHERE chat_id = ?
        """, (
            chat_id,
        ))

        deleted = cursor.rowcount

        if deleted == 0:

            conn.close()

            await update.message.reply_text(
                "❌ این کاراکتر قبلاً گرفته شده."
            )

            return

        # -------------------------------------------------
        # اضافه کردن به Collection
        # -------------------------------------------------

        cursor.execute("""
            INSERT INTO collection
            (
                user_id,
                character_id,
                quantity
            )
            VALUES (?, ?, 1)

            ON CONFLICT(user_id, character_id)
            DO UPDATE SET
                quantity = quantity + 1
        """, (
            user.id,
            spawn["id"],
        ))

        conn.commit()
        conn.close()

    # -----------------------------------------------------
    # Result
    # -----------------------------------------------------

    username = user.first_name or "Player"

    await update.message.reply_text(
        "🎉 CHARACTER CLAIMED!\n\n"

        f"👤 {username}\n"
        f"🎴 {spawn['display_name']}\n"
        f"🌍 {spawn['universe']}\n"
        f"⭐ {spawn['rarity']}\n\n"

        "این کاراکتر با موفقیت به Collection تو اضافه شد! 🎴"
    )


# =========================================================
# /COLLECTION
# =========================================================

async def collection(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    register_user(update.effective_user)

    conn = get_db()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            characters.display_name,
            characters.universe,
            characters.rarity,
            collection.quantity

        FROM collection

        JOIN characters
            ON characters.id = collection.character_id

        WHERE collection.user_id = ?

        ORDER BY characters.rarity DESC
    """, (
        user_id,
    ))

    items = cursor.fetchall()

    conn.close()

    if not items:

        await update.message.reply_text(
            "🎴 Collection تو هنوز خالیه!\n\n"
            "برای گرفتن اولین کاراکتر منتظر Spawn باش."
        )

        return

    text = "🎴 YOUR COLLECTION\n\n"

    total = 0

    for item in items:

        quantity = item["quantity"]

        total += quantity

        text += (
            f"🎴 {item['display_name']}\n"
            f"🌍 {item['universe']}\n"
            f"⭐ {item['rarity']}\n"
            f"🔢 x{quantity}\n\n"
        )

    text += f"━━━━━━━━━━━━\n"
    text += f"🎴 Total Characters: {total}"

    await update.message.reply_text(text)


# =========================================================
# /PROFILE
# =========================================================

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    register_user(user)

    conn = get_db()

    cursor = conn.cursor()

    # -----------------------------------------------------
    # User
    # -----------------------------------------------------

    cursor.execute("""
        SELECT *
        FROM users
        WHERE user_id = ?
    """, (
        user.id,
    ))

    user_data = cursor.fetchone()

    # -----------------------------------------------------
    # Collection Stats
    # -----------------------------------------------------

    cursor.execute("""
        SELECT
            COALESCE(SUM(quantity), 0) AS total,
            COUNT(*) AS unique_count

        FROM collection

        WHERE user_id = ?
    """, (
        user.id,
    ))

    stats = cursor.fetchone()

    conn.close()

    name = user_data["first_name"] or "Player"

    username = (
        f"@{user_data['username']}"
        if user_data["username"]
        else "No username"
    )

    await update.message.reply_text(
        "👤 PROFILE\n\n"

        f"🧑 Name: {name}\n"
        f"🔗 Username: {username}\n\n"

        f"🎴 Characters: {stats['total']}\n"
        f"📚 Unique: {stats['unique_count']}\n"
        f"🪙 Coins: {user_data['coins']}\n\n"

        "━━━━━━━━━━━━\n"
        f"🎴 {BOT_NAME}"
    )


# =========================================================
# /AUTOSPAWN
# =========================================================

async def autospawn(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat = update.effective_chat

    # فقط گروه‌ها
    if chat.type not in ["group", "supergroup"]:

        await update.message.reply_text(
            "❌ این دستور برای گروه استفاده میشه."
        )

        return

    # -----------------------------------------------------
    # بررسی Admin
    # -----------------------------------------------------

    member = await context.bot.get_chat_member(
        chat.id,
        update.effective_user.id,
    )

    if member.status not in ["administrator", "creator"]:

        await update.message.reply_text(
            "🛡️ فقط ادمین‌های گروه می‌تونن "
            "Auto Spawn رو تغییر بدن."
        )

        return

    if not context.args:

        await update.message.reply_text(
            "⚙️ استفاده:\n\n"
            "/autospawn on\n"
            "/autospawn off"
        )

        return

    option = context.args[0].lower()

    register_chat(chat)
    if option == "on":

        set_auto_spawn(chat.id, True)

        await update.message.reply_text(
            "⚡ Auto Spawn فعال شد!\n\n"
            "هر ۵ دقیقه بررسی می‌کنم که آیا "
            "کاراکتر جدیدی باید Spawn بشه یا نه."
        )

    elif option == "off":

        set_auto_spawn(chat.id, False)

        await update.message.reply_text(
            "🛑 Auto Spawn غیرفعال شد."
        )

    else:

        await update.message.reply_text(
            "❌ گزینه نامعتبره.\n\n"

            "/autospawn on\n"
            "/autospawn off"
        )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    print(
        f"[ERROR] {context.error}"
    )


# =========================================================
# MAIN
# =========================================================

def main():

    # ساخت دیتابیس
    init_database()

    # ساخت Bot
    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    # -----------------------------------------------------
    # Commands
    # -----------------------------------------------------

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "spawn",
            spawn
        )
    )

    app.add_handler(
        CommandHandler(
            "take",
            take
        )
    )

    app.add_handler(
        CommandHandler(
            "collection",
            collection
        )
    )

    app.add_handler(
        CommandHandler(
            "profile",
            profile
        )
    )

    app.add_handler(
        CommandHandler(
            "autospawn",
            autospawn
        )
    )

    # -----------------------------------------------------
    # Error Handler
    # -----------------------------------------------------

    app.add_error_handler(
        error_handler
    )

    # -----------------------------------------------------
    # Auto Spawn
    # -----------------------------------------------------

    app.job_queue.run_repeating(
        auto_spawn,
        interval=AUTO_SPAWN_INTERVAL,
        first=AUTO_SPAWN_INTERVAL,
    )

    # -----------------------------------------------------
    # Start
    # -----------------------------------------------------

    print(
        f"{BOT_NAME} Started..."
    )

    print(
        "Auto Spawn: Every 5 minutes"
    )

    app.run_polling()


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()