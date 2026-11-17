import os, json, hmac, hashlib, logging, sqlite3, time
from urllib.parse import parse_qsl
from flask import Flask, request, jsonify, send_from_directory, abort
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, LabeledPrice
from telegram.ext import Application, CommandHandler, PreCheckoutQueryHandler, MessageHandler, ContextTypes, filters
from threading import Thread

BOT_TOKEN = os.getenv("BOT_TOKEN", "PASTE_BOT_TOKEN")
OWNER_USERNAME = os.getenv("OWNER_USERNAME", "cmeptyug").lstrip("@").lower()
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://YOUR-HTTPS-DOMAIN.example")
DB_PATH = os.getenv("DB_PATH", "cmeptb.sqlite3")
PORT = int(os.getenv("PORT", "8080"))
TITLE = "𒀱ℂ𝕄𝔼ℙ𝕋𝕓𒀱"
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("cmeptb")

app_web = Flask(__name__, static_folder="webapp", static_url_path="")

SERVERS = [
    ("minepe","Mine.pe"),("craftpe","Craft.pe"),("dygers","Dygers.fun"),
    ("inadm","Inadm.ru"),("gamepe","Game.pe"),("modscraft","Modscraft"),
    ("ironmine","IronMine"),("ragemine","RageMine"),("migosmc","MigosMC"),
    ("wmine","WMine"),("mixergrief","MixerGrief"),("raidmine","RaidMine"),
    ("mineore","MineOre"),("inmine","InMine"),("funtime","FunTime"),
    ("lifeboat","Lifeboat"),("hive","The Hive"),("cubecraft","CubeCraft"),
    ("galaxite","Galaxite"),("nethergames","NetherGames"),("zeqa","Zeqa"),
    ("pixelparadise","Pixel Paradise")
]

# These are clearly marked DEMO listings, not verified official server ranks.
# Replace them with real products/prices only after checking each server.
DEMO_PRODUCTS = [
    ("rank","VIP",50,"Пример товара. Замените на настоящий донат сервера."),
    ("rank","Premium",100,"Пример товара. Замените на настоящий донат сервера."),
    ("rank","Legend",180,"Пример товара. Замените на настоящий донат сервера."),
]
# Cases are fixed-content bundles, not paid random-chance gambling.
DEMO_CASES = [
    ("case","Стартовый набор",20,"Фиксированный набор: описание и содержимое задаёт владелец."),
    ("case","Элитный набор",75,"Фиксированный набор: описание и содержимое задаёт владелец."),
]

def conn():
    c=sqlite3.connect(DB_PATH)
    c.row_factory=sqlite3.Row
    return c

def init_db():
    with conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
            country TEXT DEFAULT 'OTHER', language TEXT DEFAULT 'ru',
            currency TEXT DEFAULT 'USD', created INTEGER)""")
        c.execute("""CREATE TABLE IF NOT EXISTS products(
            id INTEGER PRIMARY KEY AUTOINCREMENT, server_key TEXT, kind TEXT,
            title TEXT, price INTEGER, description TEXT, active INTEGER DEFAULT 1)""")
        c.execute("""CREATE TABLE IF NOT EXISTS orders(
            payload TEXT PRIMARY KEY, user_id INTEGER, product_id INTEGER,
            price INTEGER, status TEXT, charge_id TEXT, created INTEGER)""")
        count=c.execute("SELECT COUNT(*) n FROM products").fetchone()["n"]
        if count == 0:
            for key,name in SERVERS:
                for kind,title,price,desc in DEMO_PRODUCTS + DEMO_CASES:
                    c.execute("INSERT INTO products(server_key,kind,title,price,description) VALUES(?,?,?,?,?)",
                              (key,kind,title,price,desc))

def verify_init_data(init_data: str):
    """Verify Telegram WebApp initData using the official HMAC procedure."""
    if not init_data or BOT_TOKEN.startswith("PASTE_"):
        return None
    data=dict(parse_qsl(init_data, keep_blank_values=True))
    received=data.pop("hash", None)
    if not received: return None
    check="\n".join(f"{k}={v}" for k,v in sorted(data.items()))
    secret=hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calculated=hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received): return None
    try:
        auth_date=int(data.get("auth_date","0"))
        if time.time()-auth_date > 86400: return None
        user=json.loads(data.get("user","{}"))
        return user if user.get("id") else None
    except Exception:
        return None

def api_user():
    raw=request.headers.get("X-Telegram-Init-Data","")
    user=verify_init_data(raw)
    if not user:
        abort(401, "Open this Mini App from the Telegram bot.")
    with conn() as c:
        c.execute("""INSERT OR IGNORE INTO users(user_id,username,first_name,created)
                     VALUES(?,?,?,?)""",
                  (user["id"],user.get("username",""),user.get("first_name",""),int(time.time())))
        c.execute("UPDATE users SET username=?, first_name=? WHERE user_id=?",
                  (user.get("username",""),user.get("first_name",""),user["id"]))
    return user

@app_web.get("/")
def index():
    return send_from_directory("webapp","index.html")

@app_web.get("/api/catalog")
def catalog():
    u=api_user()
    with conn() as c:
        rows=c.execute("""SELECT p.id,p.server_key,p.kind,p.title,p.price,p.description
                          FROM products p WHERE p.active=1 ORDER BY p.server_key,p.kind,p.id""").fetchall()
    products=[dict(r) for r in rows]
    with conn() as c:
        profile=c.execute("SELECT country,language,currency FROM users WHERE user_id=?",
                          (u["id"],)).fetchone()
    return jsonify({"title":TITLE,"servers":[{"key":k,"name":n} for k,n in SERVERS],
                    "products":products,"user":{"id":u["id"],"name":u.get("first_name",""),
                    "country":profile["country"],"language":profile["language"],
                    "currency":profile["currency"]}})

@app_web.post("/api/invoice")
def create_invoice():
    u=api_user()
    body=request.get_json(force=True)
    try: pid=int(body.get("product_id"))
    except: abort(400,"Bad product")
    with conn() as c:
        p=c.execute("SELECT * FROM products WHERE id=? AND active=1",(pid,)).fetchone()
    if not p: abort(404,"Product not found")
    payload=f"shop:{u['id']}:{pid}:{int(time.time())}"
    with conn() as c:
        c.execute("INSERT INTO orders(payload,user_id,product_id,price,status,created) VALUES(?,?,?,?,?,?)",
                  (payload,u["id"],pid,p["price"],"pending",int(time.time())))
    # invoice creation is performed by bot application loop via a queue in production.
    # This endpoint uses Telegram Bot API directly using the same token.
    import requests
    data={"chat_id":u["id"],"title":p["title"][:32],
          "description":p["description"][:255],"payload":payload,
          "provider_token":"","currency":"XTR",
          "prices":json.dumps([{"label":p["title"][:32],"amount":int(p["price"])}])}
    resp=requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/createInvoiceLink",data=data,timeout=20)
    result=resp.json()
    if not result.get("ok"):
        with conn() as c: c.execute("UPDATE orders SET status='invoice_error' WHERE payload=?",(payload,))
        return jsonify({"error":"Telegram invoice error","details":result}),502
    return jsonify({"invoice_url":result["result"]})

@app_web.post("/api/profile")
def update_profile():
    u=api_user()
    body=request.get_json(force=True)
    country=str(body.get("country","OTHER"))[:12]
    language=str(body.get("language","ru"))[:12]
    currency=str(body.get("currency","USD"))[:8]
    with conn() as c:
        c.execute("UPDATE users SET country=?,language=?,currency=? WHERE user_id=?",
                  (country,language,currency,u["id"]))
    return jsonify({"ok":True})

# Owner-only product management can be expanded from a private admin page.
@app_web.get("/health")
def health(): return {"ok":True,"title":TITLE}

# ---------------- Telegram bot ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user=update.effective_user
    with conn() as c:
        c.execute("""INSERT OR IGNORE INTO users(user_id,username,first_name,created)
                     VALUES(?,?,?,?)""",(user.id,user.username or "",user.first_name or "",int(time.time())))
    if "YOUR-HTTPS-DOMAIN" in WEBAPP_URL or not WEBAPP_URL.startswith("https://"):
        await update.message.reply_text(
            "Бот запущен, но Mini App ещё не опубликовано.\n"
            "Нужно разместить webapp на HTTPS и задать WEBAPP_URL."
        )
        return
    kb=InlineKeyboardMarkup([[InlineKeyboardButton(
        "🎮 Открыть магазин",web_app=WebAppInfo(url=WEBAPP_URL))]])
    await update.message.reply_text(
        f"🌌 Добро пожаловать в {TITLE}!\nОткрой магазин кнопкой ниже.",
        reply_markup=kb
    )

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.pre_checkout_query
    with conn() as c:
        order=c.execute("SELECT user_id,price,status FROM orders WHERE payload=?",
                        (q.invoice_payload,)).fetchone()
    ok=bool(order and order["user_id"]==q.from_user.id and
            order["price"]==q.total_amount and order["status"]=="pending")
    await q.answer(ok=ok,error_message=None if ok else "Заказ недействителен. Создайте новый.")

async def paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sp=update.effective_message.successful_payment
    with conn() as c:
        order=c.execute("SELECT * FROM orders WHERE payload=?",(sp.invoice_payload,)).fetchone()
        if not order or order["user_id"]!=update.effective_user.id:
            await update.effective_message.reply_text("Платёж получен, но заказ не найден. Напишите владельцу.")
            return
        c.execute("UPDATE orders SET status='paid',charge_id=? WHERE payload=?",
                  (sp.telegram_payment_charge_id,sp.invoice_payload))
        product=c.execute("SELECT title,server_key,kind FROM products WHERE id=?",
                          (order["product_id"],)).fetchone()
    await update.effective_message.reply_text(
        f"✅ Оплата получена!\nТовар: {product['title']}\n"
        f"Сервер: {product['server_key']}\nЗаказ передан владельцу на выдачу."
    )
    try:
        await context.bot.send_message(
            chat_id=f"@{OWNER_USERNAME}",
            text=f"Оплачен заказ: {product['title']}\n"
                 f"Пользователь ID: {update.effective_user.id}\n"
                 f"Сумма: {sp.total_amount} ⭐\n"
                 f"Выдай товар вручную и отметь заказ в базе."
        )
    except Exception: log.exception("Owner notification failed")

def run_web():
    app_web.run(host="0.0.0.0",port=PORT,debug=False,use_reloader=False)

def main():
    if BOT_TOKEN.startswith("PASTE_"):
        raise SystemExit("Set BOT_TOKEN environment variable first.")
    init_db()
    Thread(target=run_web,daemon=True).start()
    import asyncio
    async def runner():
        application=Application.builder().token(BOT_TOKEN).build()
        application.add_handler(CommandHandler("start",start))
        application.add_handler(PreCheckoutQueryHandler(precheckout))
        application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT,paid))
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        log.info("Bot polling started")
        while True: await asyncio.sleep(3600)
    import asyncio
    asyncio.run(runner())

if __name__=="__main__": main()
