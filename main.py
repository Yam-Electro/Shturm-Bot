#import pip
#pip.main(['install', 'pytelegrambotapi'])
import telebot
from telebot import types
from background import keep_alive  #импорт функции для поддержки работоспособности

bot = telebot.TeleBot('6324167718:AAGaX3cgGVa8QqhEwW2fJ1ioYxkp9q6W7lk')


def show_map(gmap):
  gmap_width = str(gmap.find(u'█\n') + 1)
  btn = types.InlineKeyboardButton
  markup = types.InlineKeyboardMarkup(row_width=2)
  markup.add(
      btn('', callback_data='0'),
      btn(u'⬆', callback_data='-' + gmap_width),
      btn(u'⬅', callback_data='-1'),
      btn(u'➡', callback_data='1'),
      btn('', callback_data='0'),
      btn(u'⬇', callback_data=gmap_width),
  )
  return {
      'text': '<code>' + gmap + '</code>',
      'parse_mode': 'html',
      'reply_markup': markup
  }


def voice_processing(message):
  file_info = bot.get_file(message.voice.file_id)
  downloaded_file = bot.download_file(file_info.file_path)
  with open('new_file.ogg', 'wb') as new_file:
    new_file.write(downloaded_file)


CONTENT_TYPES = [
    "text", "audio", "document", "photo", "sticker", "video", "video_note",
    "voice", "location", "contact", "new_chat_members", "left_chat_member",
    "new_chat_title", "new_chat_photo", "delete_chat_photo",
    "group_chat_created", "supergroup_chat_created", "channel_chat_created",
    "migrate_to_chat_id", "migrate_from_chat_id", "pinned_message"
]


@bot.message_handler(content_types=CONTENT_TYPES)
def get_text_message(message):
  #bot.send_message(message.from_user.id, message.text)
  if message.text == '123':
    gmap = u"""
        ██████████
        ██████ . █
        █  ◯☿◯ ◯ █
        █     ..██
        ██████████
    """.replace('\n        ', '\n')
    bot.send_message(message.from_user.id, **show_map(gmap))
  elif message.text == '/start':
    bot.send_message(message.from_user.id, 'Извините но 1вы кто такой ваще? ')

  elif message.content_type == 'voice':
    bot.send_message(message.from_user.id, 'обработка')
    #bot.send_message(message.from_user.id, message)
    #bot.send_audio(message.from_user.id, message.voice.file_id)
    voice_processing(message)

  else:
    bot.send_message(message.from_user.id, message.content_type)
  #bot.send_message(message.from_user.id, '123')


# echo-функция, которая отвечает на любое текстовое сообщение таким же текстом

keep_alive()  #запускаем flask-сервер в отдельном потоке. Подробнее ниже...
bot.polling(non_stop=True, interval=0)  #запуск бота
