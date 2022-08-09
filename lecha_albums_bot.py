#!/usr/bin/env python

"""
Bot for storing music albums and releases to the queue
"""
import json
import logging
import os
import re
from io import BytesIO
from pathlib import Path

import requests
import sentry_sdk
import validators
from PIL import Image
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ParseMode
from telegram.ext import CallbackContext, CommandHandler, Updater, MessageHandler, Filters, ConversationHandler, \
    CallbackQueryHandler

sentry_sdk.init(
    dsn="https://4ea25229795440e9a00cdbf9c85c8b26@o1075119.ingest.sentry.io/6522550",

    # Set traces_sample_rate to 1.0 to capture 100%
    # of transactions for performance monitoring.
    # We recommend adjusting this value in production.
    traces_sample_rate=1.0
)

TOKEN = os.environ.get('LECHA_ALBUMS_BOT_TOKEN')
BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILENAME = os.path.join(BASE_DIR, 'lecha_albums_bot.json')
DATA = {}
LINK, GENRES, YEAR, COUNTRY, CAPTURE_EDITS = range(5)

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


def get_song_links(url: str) -> tuple:
    """Get song data from odesli from music service url"""
    logger.info(f"Loading data from `{url}'.")
    answer = requests.get("https://api.song.link/v1-alpha.1/links", params={
        'url': url,
        'userCountry': 'RU'
    })
    if not answer.ok:
        logger.error(f"Error with request to odesli ({answer.status_code}).")
        return None, None
    data = answer.json()
    url = data['pageUrl']
    song_data = None
    for k in data['entitiesByUniqueId'].keys():
        if k.split(':')[0].split('_')[0] == 'ITUNES':
            song_data = data['entitiesByUniqueId'][k]
            break
    return url, song_data


def get_data(filename: str) -> dict:
    """Reads data from json file and returns dict"""
    logger.info(f"Loading data from file `{filename}`...")
    try:
        with open(filename) as f:
            return json.load(f)
    except FileNotFoundError:
        store_data({}, filename)
        return {}


def store_data(data: dict, filename: str):
    """Stores python object serialized to json data to file"""
    logger.info(f"Store data to file `{filename}`...")
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, 'w') as f:
        json.dump(data, f)


def generate_text(data: dict) -> str:
    """Generate album data"""
    return f"""<b>#{data['tag']}</b>
<b>Artist:</b> {data['data']['artistName']}
<b>Album:</b> {data['data']['title']}
<b>Year:</b> {data.get('year', '')}
<b>Genre:</b> {" • ".join(data.get('genres'))}
<b>Country:</b> {data.get('country')}
<b>Link:</b> {data.get('url')}

<i>#{data['data']['artistName'].replace(" ", "")} #{data.get('year', '')[:3] + '0s'} #{data.get('country')} {" ".join(
        ['#' + re.sub('[^A-Za-z0-9]+', '', i) for i in data.get('genres')]
    )}</i>
    """


def generate_message_with_object(update: Update, data: dict) -> None:
    """Send message with audio object"""
    logger.info(f"Generating text with album for user {update.effective_user.full_name}")
    keyboard = [
        [
            InlineKeyboardButton("\uFE0F редактировать️", callback_data="open_edit"),
            InlineKeyboardButton("❌ отменить", callback_data="cancel"),
        ],
        [InlineKeyboardButton("✅ подтвердить", callback_data="done")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    response = requests.get(data['data']['thumbnailUrl'])
    img = Image.open(BytesIO(response.content))

    img_bytes = BytesIO()
    img.save(img_bytes, format="PNG")
    img_bytes.seek(0)

    update.message.reply_photo(
        img_bytes,
        caption=generate_text(data),
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )


def start(update: Update, _: CallbackContext) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    if str(user.id) not in DATA:
        DATA[str(user.id)] = []
        store_data(DATA, CONFIG_FILENAME)
    logger.info("User %s connected.", user.first_name)
    update.message.reply_text(f'Привет {user.full_name}! Чтобы создать новую запись нажми /new')


def help_command(update: Update, _: CallbackContext) -> None:
    """Send a message when the command /help is issued."""
    logger.info(f"User {update.effective_user.full_name} called /help command")
    update.message.reply_text('Чтобы создать новую запись нажми /new')


def new_object(update: Update, _: CallbackContext) -> int:
    """Init create album description script"""
    logger.info(f"User {update.effective_user.full_name} called /new command")
    update.message.reply_text('Введите ссылку:')
    return LINK


def get_link(update: Update, context: CallbackContext) -> int:
    """get link and load all data from odesli"""
    logger.info(f"Getting link from {update.effective_user.full_name} input")
    user = update.effective_user
    if not validators.url(update.message.text):
        logger.warning("Link invalid")
        update.message.reply_text('Ты дебил?! Это не ссылка, давай еще раз.')
        return LINK

    url, data = get_song_links(update.message.text)
    if url is None and data is None:
        logger.warning("Link invalid")
        update.message.reply_text('Не найдена ссылка в odesli.')
        url = update.message.text
        data = {
            'title': 'Обновите название',
            'artistName': 'Обновите исполнителя',
            'thumbnailUrl': 'https://www.generationsforpeace.org/wp-content/uploads/2018/03/empty.jpg',
        }
    if data is None:
        logger.warning("Link invalid")
        update.message.reply_text('Ты дебил?! Это ссылка не из Apple Music, давай еще раз.')
        return LINK
    logger.info(f"Got data from odesli for {update.effective_user.full_name}")
    tag = len(DATA[str(user.id)])
    context.user_data["tag"] = tag

    DATA[str(user.id)].append({
        "url": url,
        "data": data,
        "tag": tag,
    })
    store_data(DATA, CONFIG_FILENAME)
    update.message.reply_text('Отправьте жанры через запятую.')
    return GENRES


def get_genres(update: Update, context: CallbackContext) -> int:
    """Get and process genres"""
    logger.info(f"Get genres from {update.effective_user.full_name}")
    user = update.effective_user
    genres = update.message.text.split(', ')
    tag = context.user_data["tag"]
    DATA[str(user.id)][tag]['genres'] = genres
    store_data(DATA, CONFIG_FILENAME)
    update.message.reply_text('Отправьте год.')
    return YEAR


def get_year(update: Update, context: CallbackContext) -> int:
    """get and process year"""
    logger.info(f"Get year from user {update.effective_user.full_name}")
    user = update.effective_user
    year = update.message.text
    if not year.isdigit():
        update.message.reply_text("Ты совсем дегенерат?! Это даже не число... Давай еще раз.")
        return YEAR
    tag = context.user_data["tag"]
    DATA[str(user.id)][tag]['year'] = year
    store_data(DATA, CONFIG_FILENAME)
    update.message.reply_text('Отправьте страну.')
    return COUNTRY


def get_country(update: Update, context: CallbackContext) -> int:
    """get and process country"""
    logger.info(f"Process country and send album message to user {update.effective_user.full_name}")
    user = update.effective_user
    country = update.message.text
    tag = context.user_data["tag"]
    DATA[str(user.id)][tag]['country'] = country
    store_data(DATA, CONFIG_FILENAME)
    generate_message_with_object(update, DATA[str(user.id)][tag])
    return ConversationHandler.END


def process_edits(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    if query.data == 'edit_tag':
        context.user_data["edit_state"] = 'edit_tag'
        update.effective_user.send_message("Введите тег")
    elif query.data == 'edit_title':
        context.user_data["edit_state"] = 'edit_title'
        update.effective_user.send_message("Введите название")
    elif query.data == 'edit_band':
        context.user_data["edit_state"] = 'edit_band'
        update.effective_user.send_message("Введите группу")
    elif query.data == 'edit_year':
        context.user_data["edit_state"] = 'edit_year'
        update.effective_user.send_message("Введите год")
    elif query.data == 'edit_county':
        context.user_data["edit_state"] = 'edit_county'
        update.effective_user.send_message("Введите страну")
    elif query.data == 'edit_genres':
        context.user_data["edit_state"] = 'edit_genres'
        update.effective_user.send_message("Введите жанры через запятую")
    return CAPTURE_EDITS


def capture_edits(update: Update, context: CallbackContext) -> int:
    user = update.effective_user
    tag = context.user_data["tag"]
    logger.info(f"Saving user edit {user.full_name}")
    if context.user_data["edit_state"] == 'edit_tag':
        DATA[str(user.id)][tag]['tag'] = update.message.text
    elif context.user_data["edit_state"] == 'edit_title':
        DATA[str(user.id)][tag]['data']['title'] = update.message.text
    elif context.user_data["edit_state"] == 'edit_band':
        DATA[str(user.id)][tag]['data']['artistName'] = update.message.text
    elif context.user_data["edit_state"] == 'edit_year':
        DATA[str(user.id)][tag]['year'] = update.message.text
    elif context.user_data["edit_state"] == 'edit_county':
        DATA[str(user.id)][tag]['country'] = update.message.text
    elif context.user_data["edit_state"] == 'edit_genres':
        DATA[str(user.id)][tag]['genres'] = update.message.text.split(', ')

    store_data(DATA, CONFIG_FILENAME)
    generate_message_with_object(update, DATA[str(user.id)][tag])
    return ConversationHandler.END


def button(update: Update, _: CallbackContext) -> None:
    """Parses the CallbackQuery and updates the message text."""

    query = update.callback_query
    query.answer()
    print(query.data)

    if query.data == 'open_edit':
        keyboard = [
            [InlineKeyboardButton("\uFE0F тег", callback_data="edit_tag"), ],
            [InlineKeyboardButton("\uFE0F название", callback_data="edit_title"), ],
            [InlineKeyboardButton("\uFE0F группа", callback_data="edit_band"), ],
            [InlineKeyboardButton("\uFE0F год", callback_data="edit_year"), ],
            [InlineKeyboardButton("\uFE0F страна", callback_data="edit_county"), ],
            [InlineKeyboardButton("\uFE0F жанры", callback_data="edit_genres"), ],
            [InlineKeyboardButton("⬅️ назад", callback_data="back")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_reply_markup(reply_markup=reply_markup)
    elif query.data == 'cancel':
        return
    elif query.data == 'done':
        update.effective_user.send_message("До свидания")
    elif query.data == 'back':
        keyboard = [
            [
                InlineKeyboardButton("\uFE0F редактировать️", callback_data="open_edit"),
                InlineKeyboardButton("❌ отменить", callback_data="cancel"),
            ],
            [InlineKeyboardButton("✅ подтвердить", callback_data="done")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_reply_markup(reply_markup=reply_markup)


def cancel(update: Update, _: CallbackContext) -> None:
    """cancel conversation"""
    logger.info(f"Canceling operation from user {update.effective_user.full_name}")
    update.message.reply_text("Отменено")


def main() -> None:
    """Start the bot."""
    logger.info("Loading bot...")
    global DATA

    if TOKEN is None:
        logger.error("None token exported")
        exit()

    DATA = get_data(CONFIG_FILENAME)
    updater = Updater(TOKEN)

    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(CommandHandler('help', help_command))

    create_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('new', new_object)],
        states={
            LINK: [MessageHandler(Filters.text, get_link)],
            GENRES: [MessageHandler(Filters.text, get_genres)],
            YEAR: [MessageHandler(Filters.text, get_year)],
            COUNTRY: [MessageHandler(Filters.text, get_country)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    dispatcher.add_handler(create_conv_handler)

    edit_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(process_edits, pattern='^edit.*$')],
        states={CAPTURE_EDITS: [MessageHandler(Filters.text, capture_edits)]},
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    dispatcher.add_handler(edit_conv_handler)

    dispatcher.add_handler(CallbackQueryHandler(button))

    try:
        updater.start_polling()
        updater.idle()
    except NetworkError:
        exit(1)


if __name__ == '__main__':
    main()
