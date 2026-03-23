 # telegram_document_bot.py — Telegram бот с интеграцией PDF конструктора
# -----------------------------------------------------------------------------
# Генератор PDF-документов Intesa Sanpaolo:
#   /contratto     — кредитный договор
#   /garanzia      — письмо о гарантийном взносе
#   /carta         — письмо о выпуске карты
#   /approvazione  — письмо об одобрении кредита
#   /гарантия_de, /garantie — GARANTIE (MKB), DE — файл: Garantie_<safe>.pdf
# -----------------------------------------------------------------------------
# Интеграция с pdf_costructor.py API
# -----------------------------------------------------------------------------
import logging
import os
from io import BytesIO

import telegram
from telegram import Update, InputFile, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, ConversationHandler, MessageHandler, ContextTypes, filters,
)
from telegram.request import HTTPXRequest

# Импортируем API функции из PDF конструктора
from pdf_costructor import (
    generate_contratto_pdf,
    generate_garanzia_pdf, 
    generate_carta_pdf,
    generate_approvazione_pdf,
    generate_garantie_mkb_pdf,
    monthly_payment,
)


# ---------------------- Настройки ------------------------------------------
TOKEN = os.getenv("BOT_TOKEN", "YOUR_TOKEN_HERE")
DEFAULT_TAN = 7.86
DEFAULT_TAEG = 8.30
FIXED_TAN_APPROVAZIONE = 7.15  # Фиксированный TAN для approvazione

# Настройки прокси
PROXY_URL = "http://user351165:35rmsy@185.218.1.162:1479"


logging.basicConfig(format="%(asctime)s — %(levelname)s — %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


def _safe_filename_part(s: str, max_len: int = 80) -> str:
    return s.replace("/", "_").replace("\\", "_")[:max_len]


# ------------------ Состояния Conversation -------------------------------
(
    CHOOSING_DOC, ASK_NAME, ASK_AMOUNT, ASK_DURATION, ASK_TAN, ASK_TAEG,
    ASK_GRTM_VON, ASK_GRTM_BEITRAG, ASK_GRTM_ENTSCH,
) = range(9)

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


def build_garantie_mkb(data: dict) -> BytesIO:
    return generate_garantie_mkb_pdf(data)


# ------------------------- Handlers -----------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    kb = [["/контракт", "/гарантия"], ["/карта", "/одобрение"], ["/гарантия_de", "/garantie"]]
    await update.message.reply_text(
        "Выберите документ:",
        reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True)
    )
    return CHOOSING_DOC

async def choose_doc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    doc_type = update.message.text
    context.user_data['doc_type'] = doc_type
    if doc_type in ('/гарантия_de', '/garantie'):
        await update.message.reply_text(
            "Введите имя для поля Von (отправитель письма):",
            reply_markup=ReplyKeyboardRemove()
        )
        return ASK_GRTM_VON
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

async def ask_grtm_von(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['von'] = update.message.text.strip()
    await update.message.reply_text("Введите сумму обязательного взноса (Beitrag), €:")
    return ASK_GRTM_BEITRAG


async def ask_grtm_beitrag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        amt = float(update.message.text.replace('€', '').replace(',', '.').replace(' ', ''))
    except ValueError:
        await update.message.reply_text("Неверная сумма, введите число (€):")
        return ASK_GRTM_BEITRAG
    context.user_data['beitrag'] = round(amt, 2)
    await update.message.reply_text("Введите сумму компенсации (Entschädigung), €:")
    return ASK_GRTM_ENTSCH


async def ask_grtm_entsch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        amt = float(update.message.text.replace('€', '').replace(',', '.').replace(' ', ''))
    except ValueError:
        await update.message.reply_text("Неверная сумма, введите число (€):")
        return ASK_GRTM_ENTSCH
    context.user_data['entschaedigung'] = round(amt, 2)
    data = {
        'von': context.user_data['von'],
        'beitrag': context.user_data['beitrag'],
        'entschaedigung': context.user_data['entschaedigung'],
    }
    try:
        buf = build_garantie_mkb(data)
        safe = _safe_filename_part(context.user_data['von'])
        await update.message.reply_document(InputFile(buf, f"Garantie_{safe}.pdf"))
    except Exception as e:
        logger.error(f"Ошибка генерации garantie_mkb: {e}")
        await update.message.reply_text(f"Ошибка создания документа: {e}")
    return await start(update, context)


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

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик ошибок"""
    logger.error(f"Exception while handling an update: {context.error}")

    if isinstance(context.error, telegram.error.Conflict):
        logger.error("Конфликт: другая копия бота уже работает! Убедитесь, что запущена только одна инстанс.")
        return

    # Отправляем сообщение об ошибке пользователю, если это возможно
    if update and hasattr(update, 'effective_message'):
        try:
            await update.effective_message.reply_text("❌ Произошла ошибка. Попробуйте позже.")
        except Exception:
            pass

# ---------------------------- Main -------------------------------------------
def main():
    # Использование прокси для обхода блокировок
    t_request = HTTPXRequest(
        proxy_url=PROXY_URL,
        connect_timeout=30,
        read_timeout=30,
        write_timeout=30,
        pool_timeout=30
    )

    app = ApplicationBuilder() \
        .token(TOKEN) \
        .request(t_request) \
        .build()

    # Добавляем обработчик ошибок
    app.add_error_handler(error_handler)

    conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CHOOSING_DOC: [MessageHandler(filters.Regex(r'^(/contratto|/garanzia|/carta|/approvazione|/контракт|/гарантия|/карта|/одобрение|/гарантия_de|/garantie)$'), choose_doc)],
            ASK_NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_AMOUNT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_amount)],
            ASK_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_duration)],
            ASK_TAN:      [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_tan)],
            ASK_TAEG:     [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_taeg)],
            ASK_GRTM_VON:      [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_grtm_von)],
            ASK_GRTM_BEITRAG:  [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_grtm_beitrag)],
            ASK_GRTM_ENTSCH:   [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_grtm_entsch)],
        },
        fallbacks=[CommandHandler('cancel', cancel), CommandHandler('start', start)],
    )
    app.add_handler(conv)

    print("🤖 Телеграм бот запущен!")
    print("📋 Документы: /контракт, /гарантия, /карта, /одобрение, /гарантия_de, /garantie")
    print("🔧 Использует PDF конструктор из pdf_costructor.py")
    print(f"⏱️  Таймауты увеличены до 30 сек для борьбы с TimedOut ошибками")
    print("🌐 Подключен через прокси: 185.218.1.162:1479")
    print("⚠️  Убедитесь, что запущена только одна копия бота!")

    try:
        # Чтобы не обрабатывать накопившийся мусор при запуске
        app.run_polling(drop_pending_updates=True)
    except KeyboardInterrupt:
        print("🛑 Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка при работе бота: {e}")

if __name__ == '__main__':
    main()
