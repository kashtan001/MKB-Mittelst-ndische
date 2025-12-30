 # telegram_document_bot.py — Telegram бот с интеграцией PDF конструктора
# -----------------------------------------------------------------------------
# Генератор PDF-документов Intesa Sanpaolo:
#   /contratto     — кредитный договор
#   /garanzia      — письмо о гарантийном взносе
#   /carta         — письмо о выпуске карты
#   /approvazione  — письмо об одобрении кредита
# -----------------------------------------------------------------------------
# Интеграция с pdf_costructor.py API
# -----------------------------------------------------------------------------
import logging
import os
from io import BytesIO

from telegram import Update, InputFile, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, ConversationHandler, MessageHandler, ContextTypes, filters,
)

# Импортируем API функции из PDF конструктора
from pdf_costructor import (
    generate_contratto_pdf,
    generate_garanzia_pdf, 
    generate_carta_pdf,
    generate_approvazione_pdf,
    monthly_payment,
    format_money
)


# ---------------------- Настройки ------------------------------------------
TOKEN = os.getenv("BOT_TOKEN", "YOUR_TOKEN_HERE")
DEFAULT_TAN = 7.86
DEFAULT_TAEG = 8.30
FIXED_TAN_APPROVAZIONE = 7.15  # Фиксированный TAN для approvazione


logging.basicConfig(format="%(asctime)s — %(levelname)s — %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------ Состояния Conversation -------------------------------
CHOOSING_DOC, ASK_NAME, ASK_AMOUNT, ASK_DURATION, ASK_TAN, ASK_TAEG = range(6)

# ---------------------- PDF-строители через API -------------------------
def build_contratto(data: dict) -> BytesIO:
    """Генерация PDF договора через API pdf_costructor"""
    return generate_contratto_pdf(data)


def build_lettera_garanzia(name: str) -> BytesIO:
    """Генерация PDF гарантийного письма через API pdf_costructor"""
    return generate_garanzia_pdf(name)


def build_lettera_carta(data: dict) -> BytesIO:
    """Генерация PDF письма о карте через API pdf_costructor"""
    return generate_carta_pdf(data)


def build_lettera_approvazione(data: dict) -> BytesIO:
    """Генерация PDF письма об одобрении через API pdf_costructor"""
    return generate_approvazione_pdf(data)


# ------------------------- Handlers -----------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    kb = [["/контракт", "/гарантия"], ["/карта", "/одобрение"]]
    await update.message.reply_text(
        "Выберите документ:",
        reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True)
    )
    return CHOOSING_DOC

async def choose_doc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    doc_type = update.message.text
    context.user_data['doc_type'] = doc_type
    await update.message.reply_text(
        "Введите имя и фамилию клиента:",
        reply_markup=ReplyKeyboardRemove()
    )
    return ASK_NAME

async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    dt = context.user_data['doc_type']
    if dt in ('/garanzia', '/гарантия'):
        try:
            buf = build_lettera_garanzia(name)
            await update.message.reply_document(InputFile(buf, f"Garantie_{name}.pdf"))
        except Exception as e:
            logger.error(f"Ошибка генерации garanzia: {e}")
            await update.message.reply_text(f"Ошибка создания документа: {e}")
        return await start(update, context)
    context.user_data['name'] = name
    await update.message.reply_text("Введите сумму (€):")
    return ASK_AMOUNT

async def ask_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        amt = float(update.message.text.replace('€','').replace(',','.').replace(' ',''))
    except:
        await update.message.reply_text("Неверная сумма, попробуйте снова:")
        return ASK_AMOUNT
    context.user_data['amount'] = round(amt, 2)
    
    # Для всех документов кроме garanzia запрашиваем duration
    await update.message.reply_text("Введите срок (месяцев):")
    return ASK_DURATION

async def ask_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        mn = int(update.message.text)
    except:
        await update.message.reply_text("Неверный срок, попробуйте снова:")
        return ASK_DURATION
    context.user_data['duration'] = mn
    
    dt = context.user_data['doc_type']
    
    # Для approvazione используем фиксированный TAN и сразу генерируем документ
    if dt in ('/approvazione', '/одобрение'):
        d = context.user_data
        d['tan'] = FIXED_TAN_APPROVAZIONE  # Фиксированный TAN 7.15%
        try:
            buf = build_lettera_approvazione(d)
            await update.message.reply_document(InputFile(buf, f"Genehmigung_{d['name']}.pdf"))
        except Exception as e:
            logger.error(f"Ошибка генерации approvazione: {e}")
            await update.message.reply_text(f"Ошибка создания документа: {e}")
        return await start(update, context)
    
    # Для других документов запрашиваем TAN
    await update.message.reply_text(f"Введите TAN (%), Enter для {DEFAULT_TAN}%:")
    return ASK_TAN

async def ask_tan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    txt = update.message.text.strip()
    try:
        context.user_data['tan'] = float(txt.replace(',','.').replace('%','')) if txt else DEFAULT_TAN
    except:
        context.user_data['tan'] = DEFAULT_TAN
    
    # Запрашиваем TAEG для contratto и carta
    await update.message.reply_text(f"Введите TAEG (%), Enter для {DEFAULT_TAEG}%:")
    return ASK_TAEG

async def ask_taeg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    txt = update.message.text.strip()
    try:
        context.user_data['taeg'] = float(txt.replace(',','.')) if txt else DEFAULT_TAEG
    except:
        context.user_data['taeg'] = DEFAULT_TAEG
    
    d = context.user_data
    d['payment'] = monthly_payment(d['amount'], d['duration'], d['tan'])
    dt = d['doc_type']
    
    try:
        if dt in ('/contratto', '/контракт'):
            buf = build_contratto(d)
            filename = f"Vertrag_{d['name']}.pdf"
        else:
            buf = build_lettera_carta(d)
            filename = f"Bankkarte_{d['name']}.pdf"
            
        await update.message.reply_document(InputFile(buf, filename))
    except Exception as e:
        logger.error(f"Ошибка генерации PDF {dt}: {e}")
        await update.message.reply_text(f"Ошибка создания документа: {e}")
    
    return await start(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Операция отменена.")
    return await start(update, context)

# ---------------------------- Main -------------------------------------------
def main():
    app = Application.builder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CHOOSING_DOC: [MessageHandler(filters.Regex(r'^(/contratto|/garanzia|/carta|/approvazione|/контракт|/гарантия|/карта|/одобрение)$'), choose_doc)],
            ASK_NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_AMOUNT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_amount)],
            ASK_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_duration)],
            ASK_TAN:      [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_tan)],
            ASK_TAEG:     [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_taeg)],
        },
        fallbacks=[CommandHandler('cancel', cancel), CommandHandler('start', start)],
    )
    app.add_handler(conv)
    
    print("🤖 Телеграм бот запущен!")
    print("📋 Поддерживаемые документы: /контракт, /гарантия, /карта, /одобрение (итальянские варианты тоже поддерживаются)")
    print("🔧 Использует PDF конструктор из pdf_costructor.py")
    
    app.run_polling()

if __name__ == '__main__':
    main()
