import telebot
from config import VISITS_BOT_TOKEN

bot = telebot.TeleBot(VISITS_BOT_TOKEN)

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "Привет! Напиши своё имя и телефон для регистрации посещения.")

@bot.message_handler(func=lambda message: True)
def register_visit(message):
    with open("visits.txt", "a", encoding="utf-8") as f:
        f.write(f"{message.from_user.username} | {message.text}\n")
    bot.send_message(message.chat.id, "Посещение зарегистрировано.")

bot.polling()
