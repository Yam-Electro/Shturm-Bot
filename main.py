#import pip
#pip.main(['install', 'pytelegrambotapi'])
import telebot
from telebot import types
from background import keep_alive  #импорт функции для поддержки работоспособности
import ml as m
import torch

bot = telebot.TeleBot('6324167718:AAGaX3cgGVa8QqhEwW2fJ1ioYxkp9q6W7lk')

device = "cuda:0" if torch.cuda.is_available() else "cpu"


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
    bot.send_message(message.from_user.id, '321')

  elif message.text == 'device':
    bot.send_message(message.from_user.id, device)

  elif message.text == '/start':
    bot.send_message(message.from_user.id, 'Извините но вы кто такой ваще? ')

  elif message.content_type == 'voice':
    bot.send_message(message.from_user.id, 'обработка')
    #bot.send_message(message.from_user.id, message)
    #bot.send_audio(message.from_user.id, message.voice.file_id)
    voice_processing(message)
    audio_frame = m.audioframe('new_file.ogg')
    text = m.audio_to_text(audio_frame)
    bot.send_message(message.from_user.id, audio_frame[:10])
    bot.send_message(message.from_user.id,
                     text if len(text) > 0 else 'нет текста')
  else:
    bot.send_message(message.from_user.id, message.content_type)


keep_alive()  #запускаем flask-сервер в отдельном потоке. Подробнее ниже...
bot.polling(non_stop=True, interval=0)  #запуск бота
