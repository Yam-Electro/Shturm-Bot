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


@bot.message_handler(content_types=['text'])
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
    bot.send_message(message.from_user.id, 'Извините но вы кто такой ваще? ')

  else:
    bot.send_message(message.from_user.id, message)
  #bot.send_message(message.from_user.id, '123')


# echo-функция, которая отвечает на любое текстовое сообщение таким же текстом

keep_alive()  #запускаем flask-сервер в отдельном потоке. Подробнее ниже...
bot.polling(non_stop=True, interval=0)  #запуск бота
