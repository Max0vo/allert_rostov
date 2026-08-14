import time
import json
import os
import re
import requests
import urllib.parse

# ================= НАСТРОЙКИ (БЕЗОПАСНЫЕ) =================
# Берём секреты из переменных окружения GitHub Actions
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
IOS_WEBHOOK_URL = os.getenv('IOS_WEBHOOK_URL')

CHANNELS = [
    'radar_rvk',
    'locatorru',
    'lpr1_Rostov_alarm',
    'nebo_rostova'
]

GEO_KEYWORDS = ['ростов', 'ростов-на-дону', 'батайск', 'аксай', 'таганрог']
DANGER_KEYWORDS = ['бпла', 'опасность', 'ракетная', 'в укрытие', 'ракета', 'мрш']
CANCEL_KEYWORD = 'отбой'

COOLDOWN_PERIOD = 420  # Кулдаун 7 минут

# В GitHub Actions состояние будем хранить в локальном файле текущей директории
STATE_FILE = 'monitor_state.json'
# ==============================================

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'last_alert': 0, 'processed_posts': {}}

def save_state(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def check_text_conditions(text: str):
    if not text:
        return False, None, [], []

    sentences = re.split(r'(?<=[.!?\n])\s+', text)

    for sentence in sentences:
        sentence_clean = sentence.strip()
        if not sentence_clean:
            continue

        sentence_lower = sentence_clean.lower()

        if CANCEL_KEYWORD in sentence_lower:
            continue

        matched_geo = []
        for geo in GEO_KEYWORDS:
            pattern = r'\b' + re.escape(geo) + r'\b'
            if re.search(pattern, sentence_lower):
                matched_geo.append(geo)

        matched_danger = [danger for danger in DANGER_KEYWORDS if danger in sentence_lower]

        if matched_geo and matched_danger:
            return True, sentence_clean, matched_geo, matched_danger

    return False, None, [], []

def send_ios_alert(state, channel_username, trigger_sentence, geo_match, danger_match, full_text):
    current_time = int(time.time())
    last_alert = state.get('last_alert', 0)

    print(f"\n🚨 [СРАБАТЫВАНИЕ] Канал: @{channel_username}")
    print(f"🎯 Найдена геопозиция: {geo_match}")
    print(f"⚠️ Найдена угроза: {danger_match}")
    print(f"💬 Предложение-триггер: «{trigger_sentence}»")
    print(f"📄 Полный текст поста:\n{full_text.strip()}\n")

    if (current_time - last_alert < COOLDOWN_PERIOD):
        print("⏳ Опасность найдена, но действует общий кулдаун.")
        return state

    try:
        # Кодируем текст, чтобы его можно было передать в ссылке
        # Передаем именно trigger_sentence (саму суть), так как длинный пост может не влезть в лимит URL
        safe_text = urllib.parse.quote(trigger_sentence)
        
        # Добавляем параметр &text= в конец URL
        payload_url = f"{IOS_WEBHOOK_URL}?tag=script_alert&alert=true&time={current_time}&channel={channel_username}&text={safe_text}"
        
        response = requests.get(payload_url, timeout=10)

        if response.status_code in [200, 204]:
            print("🔥 ОПАСНОСТЬ! Сигнал отправлен на Hookdeck.")
            state['last_alert'] = current_time
        else:
            print(f"❌ Ошибка вебхука: Код {response.status_code}")
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")

    return state

def get_last_channel_post(channel_username):
    try:
        url = f"https://t.me/s/{channel_username}"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')
            messages = soup.find_all('div', class_='tgme_widget_message_text')
            if messages:
                return messages[-1].get_text()
    except Exception as e:
        print(f"Ошибка парсинга @{channel_username}: {e}")
    return None

def main():
    state = load_state()
    if 'processed_posts' not in state:
        state['processed_posts'] = {}

    print("🛰️ Разовый проход мониторинга запущен.")

    # Проходим по всем каналам один раз за запуск
    for channel in CHANNELS:
        text = get_last_channel_post(channel)
        if text:
            first_line = text.split('\n')[0]
            print(f"Канал @{channel}: {first_line}")

            is_triggered, sentence, geo, danger = check_text_conditions(text)
            last_seen_post = state['processed_posts'].get(channel)

            if is_triggered:
                if last_seen_post != text:
                    state = send_ios_alert(state, channel, sentence, geo, danger, text)
                    state['processed_posts'][channel] = text
                else:
                    print(f"ℹ️ Пост в @{channel} уже обрабатывался ранее. Пропускаем.")
            else:
                if last_seen_post != text:
                    state['processed_posts'][channel] = text

    save_state(state)

if __name__ == '__main__':
    main()
