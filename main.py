import os
import re
import sys
import io
import asyncio
import random
import shutil
from pathlib import Path
from aiogram import Bot, Dispatcher, types
from aiogram.types import FSInputFile, Message
from aiogram.filters import CommandStart, Command
import yt_dlp
from yt_dlp.utils import sanitize_filename, DownloadError, ExtractorError
from dotenv import load_dotenv

# --- Настройка UTF-8 вывода ---
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
os.environ["PYTHONUTF8"] = "1"

# --- Проверка наличия ffmpeg ---
if not shutil.which("ffmpeg"):
    print("[ERROR] ⚠️ ffmpeg не найден! Установите его в контейнере.")
else:
    print("[DEBUG] ffmpeg найден ✅")

# --- Загружаем переменные окружения ---
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

if not TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env файле")
if ADMIN_ID == 0:
    raise ValueError("ADMIN_ID не найден в .env файле")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- Папка для сохранения аудио ---
PERSISTENT_DIR = Path(os.getenv("DATA_DIR", "/data"))
AUDIO_DOWNLOAD_DIR = PERSISTENT_DIR / "downloaded_audio"
AUDIO_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
print(f"[DEBUG] Аудио будет сохраняться в: {AUDIO_DOWNLOAD_DIR}")

# --- Регулярное выражение для проверки ссылок YouTube ---
YOUTUBE_REGEX = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+")
 
# --- Загрузка прокси ---
def load_proxies(file_path="proxies.txt"):
    path = Path(file_path)
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

proxies = load_proxies()
USE_PROXY = True

# --- Команда /start ---
@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "<b>Привет 👋</b>\n\n"
        "Я умею скачивать <b>аудио из YouTube</b>. 🎶\n"
        "Просто пришли мне ссылку на видео, и я отправлю тебе MP3.\n"
        "Разработчик: Koora (@xx00xxdanu)\n\n"
        "ℹ️ Используй /info для справки.",
        parse_mode="HTML"
    )

# --- Команда /info ---
@dp.message(Command("info"))
async def info_handler(message: Message):
    await message.answer(
        "🤖 <b>Информация о боте</b>\n\n"
        "🎶 Конвертирует видео YouTube в MP3 (192 kbps)\n"
        "📦 Ограничение Telegram — 50 МБ\n"
        "⚠️ При ошибке «Video unavailable» попробуй включить прокси (/proxy_on)\n\n"
        "👨‍💻 Автор: Koora (@xx00xxdanu)",
        parse_mode="HTML"
    )

# --- Админ команды ---
@dp.message(Command("proxy_on"))
async def proxy_on(message: Message):
    global USE_PROXY
    if message.from_user.id != ADMIN_ID:
        return
    USE_PROXY = True
    await message.answer("✅ Прокси включены")

@dp.message(Command("proxy_off"))
async def proxy_off(message: Message):
    global USE_PROXY
    if message.from_user.id != ADMIN_ID:
        return
    USE_PROXY = False
    await message.answer("✅ Прокси выключены")

@dp.message(Command("ahelp"))
async def help_handler(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(
        "<b>Help admins</b>\n\n"
        "/proxy_on — включить прокси\n"
        "/proxy_off — выключить прокси\n"
        "/restart — перезапустить бота",
        parse_mode="HTML"
    )

@dp.message(Command("restart"))
async def restart_bot(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("♻️ Перезапускаю бота...")
    python = sys.executable
    os.execl(python, python, *sys.argv)

# --- Обработка YouTube ссылок ---
@dp.message()
async def handle_message(message: Message):
    url = message.text.strip()
    if not YOUTUBE_REGEX.match(url):
        await message.answer("❌ Это не ссылка YouTube. Отправь корректную ссылку.")
        return
    url = url.split("?")[0]
    await download_youtube_audio(message, url)

# --- Загрузка и обработка аудио ---
async def download_youtube_audio(message: Message, url: str):
    await message.answer("⏳ Скачиваю аудио...")

    try:
        with yt_dlp.YoutubeDL({"quiet": True, "encoding": "utf-8"}) as ydl:
            info = ydl.extract_info(url, download=False)

        title = sanitize_filename(info.get("title", "audio"))
        title_safe = re.sub(r'[<>:"/\\|?*\x00-\x1F]', '_', title)
        outtmpl = str(AUDIO_DOWNLOAD_DIR / f"{title_safe}.%(ext)s")

        proxy = random.choice(proxies) if proxies and USE_PROXY else None

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "quiet": False,
            "noplaylist": True,
            "nocheckcertificate": True,
            "geo_bypass": True,
            "force_ipv4": True,
            "encoding": "utf-8",
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/123.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }

        if proxy:
            # Автоматически выбираем протокол
            if proxy.endswith(":1080"):
                proxy_url = f"socks5h://{proxy}"   # socks5h прокидывает DNS через прокси
            else:
                proxy_url = f"http://{proxy}"
            ydl_opts["proxy"] = proxy_url
            print(f"[DEBUG] Использую прокси: {proxy_url}")
        else:
            print("[DEBUG] Прокси не используется")


        # --- Скачивание с обработкой ошибок ---
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=True)
                downloaded_file = Path(ydl.prepare_filename(info_dict)).with_suffix(".mp3")

        except DownloadError as e:
            error_text = str(e)
            if "Video unavailable" in error_text or "This content isn’t available" in error_text:
                await message.answer("❌ Видео недоступно в твоём регионе или удалено с YouTube.")
            elif "Private video" in error_text:
                await message.answer("🔒 Это приватное видео. Я не могу его скачать.")
            elif "Sign in to confirm your age" in error_text:
                await message.answer("⚠️ Видео с ограничением по возрасту. YouTube требует авторизацию.")
            else:
                await message.answer(f"❌ Ошибка загрузки: {error_text}")
            return

        except ExtractorError:
            await message.answer("❌ Не удалось обработать видео.")
            return
        except Exception as e:
            await message.answer(f"❌ Неизвестная ошибка: {e}")
            return

        # --- Отправка файла ---
        if downloaded_file.exists():
            try:
                await message.answer_audio(
                    FSInputFile(downloaded_file),
                    caption=f"🎶 {title} @downloadmusic25_bot",
                    title=title
                )
            finally:
                downloaded_file.unlink(missing_ok=True)
        else:
            await message.answer("❌ Ошибка: файл не найден после скачивания.")

    except Exception as e:
        await message.answer(f"❌ Ошибка при загрузке: {e}")
        print(f"[ERROR] {e}")

# --- Запуск бота ---
if __name__ == "__main__":
    async def main():
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            await dp.start_polling(bot)
        except Exception as e:
            print(f"[CRITICAL] Бот упал: {e}", flush=True)
            await asyncio.sleep(5)
            os.execl(sys.executable, sys.executable, *sys.argv)

    asyncio.run(main())
