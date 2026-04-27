import os
import asyncio
import json
import hashlib
import aiohttp
import aiofiles
import time
from concurrent.futures import ThreadPoolExecutor
from telethon import TelegramClient, events, Button
from PIL import Image
import imagehash
import traceback

upload_semaphore = asyncio.Semaphore(15)

storage_folder = 'media'
if not os.path.exists(storage_folder):
    os.makedirs(storage_folder)

api_id = 21390123
api_hash = '194b2c8f0d8ac59cd757a18d5c59f8e7'
bot_token = '8094452170:AAGRa6SaepH6bqbvdZtNYmjOA4nmydUwl-U'
# Замени на свой реальный ключ
API_KEY = "52d26a78-71b4-4b20-b718-2096f89777f6"

catbox_userhash = ''

client = TelegramClient('bot', api_id, api_hash).start(bot_token=bot_token)

owner_id = 6578711326
whitelist = []
file_hashes = {}
image_hashes = {}
pending_requests = {}
last_request_time = {}

def save_whitelist():
    with open('whitelist.json', 'w') as f:
        json.dump(whitelist, f)

def load_whitelist():
    global whitelist
    try:
        with open('whitelist.json', 'r') as f:
            data = json.load(f)
            whitelist = [int(user_id) for user_id in data]
    except FileNotFoundError:
        whitelist = []

async def save_file_hashes():
    async with aiofiles.open('file_hashes.json', 'w') as f:
        await f.write(json.dumps(file_hashes))

def load_file_hashes():
    global file_hashes
    try:
        with open('file_hashes.json', 'r') as f:
            file_hashes = json.load(f)
    except FileNotFoundError:
        file_hashes = {}

async def save_image_hashes():
    async with aiofiles.open('image_hashes.json', 'w') as f:
        await f.write(json.dumps(image_hashes))

def load_image_hashes():
    global image_hashes
    try:
        with open('image_hashes.json', 'r') as f:
            image_hashes = json.load(f)
    except FileNotFoundError:
        image_hashes = {}

async def calculate_hash(file_path):
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        return await loop.run_in_executor(pool, lambda: hashlib.md5(open(file_path, 'rb').read()).hexdigest())

async def calculate_image_hash(file_path):
    try:
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as pool:
            return await loop.run_in_executor(pool, lambda: str(imagehash.phash(Image.open(file_path))))
    except:
        return None

async def safe_file_delete(file_name):
    for _ in range(5):
        try:
            os.remove(file_name)
            break
        except PermissionError:
            await asyncio.sleep(1)


async def auto_delete_request(user_id, message_id):
    await asyncio.sleep(36000000)
    if user_id in pending_requests:
        try:
            await client.delete_messages(owner_id, message_id)
            del pending_requests[user_id]
        except:
            pass

@client.on(events.NewMessage)
async def handle_media(event):
    if event.sender_id == owner_id or event.sender_id in whitelist:
        # Замени условие на это:
        if not (event.photo or event.video or event.document):
            return

        async with upload_semaphore:
            try:
                file_name = await event.download_media("media/")
                if not file_name:
                    await event.reply("Ошибка обработки")
                    return

                file_hash = await calculate_hash(file_name)

                if file_hash in file_hashes:
                    await safe_file_delete(file_name)
                    await event.reply(file_hashes[file_hash])
                    return

                is_image = event.photo or (event.document and event.document.mime_type and 'image' in event.document.mime_type)
                img_hash = None

                if is_image:
                    img_hash = await calculate_image_hash(file_name)
                    if img_hash and img_hash in image_hashes:
                        await safe_file_delete(file_name)
                        await event.reply(image_hashes[img_hash])
                        return

                # Pixeldrain API endpoint для загрузки
                url = "https://pixeldrain.com/api/file"
                
                # Вместо form_data Catbox, Pixeldrain проще:
                async with aiofiles.open(file_name, "rb") as f:
                    file_data = await f.read()
                
                # Pixeldrain принимает файл в поле "file"
                data = aiohttp.FormData()
                data.add_field('file', file_data, filename=os.path.basename(file_name))
                
                # В блоке загрузки используй auth:
                async with aiohttp.ClientSession(auth=aiohttp.BasicAuth('', API_KEY)) as session:
                    async with session.post(url, data=data) as response:
                        # ... остальной код
                        # Было:
                        # if response.status == 200:
                        
                        # Стало:
                        if response.status in (200, 201):
                            result = await response.json()
                            link = f"https://pixeldrain.com/u/{result['id']}"
                        else:
                            error_text = await response.text()
                            # Обрезаем ошибку до 200 символов, чтобы не упереться в лимит Telegram
                            short_error = (error_text[:200] + '...') if len(error_text) > 200 else error_text
                            await event.reply(f"Ошибка загрузки: {response.status}\n{short_error}")
                            await safe_file_delete(file_name)
                            return
                # Сюда код доходит только если link был успешно создан
                file_hashes[file_hash] = link
                await save_file_hashes()
                # ... дальше остальной код

                if is_image and img_hash:
                    image_hashes[img_hash] = link
                    await save_image_hashes()

                await event.reply(link)
                await safe_file_delete(file_name)

            except Exception as e:
                import traceback
                traceback.print_exc()
                await event.reply(f"Ошибка обработки: {repr(e)}")
        return

    current_time = time.time()
    if event.sender_id in last_request_time:
        time_passed = current_time - last_request_time[event.sender_id]
        if time_passed < 3600:
            return

    if event.sender_id not in pending_requests:
        user = await event.get_sender()

        user_info = (
            f"<b>Запрос на доступ</b>\n\n"
            f"<b>ID:</b> <code>{user.id}</code>\n"
            f"<b>Name:</b> {user.first_name}\n"
            f"<b>Last Name:</b> {user.last_name or 'Нет'}\n"
            f"<b>Username:</b> @{user.username or 'Нет'}\n"
            f"<b>Citation:</b> t.me/{user.username if user.username else f'user?id={user.id}'}"
        )

        msg = await client.send_message(
            owner_id,
            user_info,
            buttons=[Button.inline("Принять", data=f"accept_{user.id}")],
            parse_mode='html'
        )

        pending_requests[user.id] = msg.id
        last_request_time[user.id] = current_time
        asyncio.create_task(auto_delete_request(user.id, msg.id))

        await event.reply("Запрос отправлен администратору, ожидайте обработку")

@client.on(events.CallbackQuery(pattern=b'accept_'))
async def accept_request(event):
    if event.sender_id != owner_id:
        return
    
    user_id = int(event.data.decode().split('_')[1])
    
    if user_id not in whitelist:
        whitelist.append(user_id)
        save_whitelist()
    
    if user_id in pending_requests:
        del pending_requests[user_id]
    
    await event.edit(f"<b>Пользователь {user_id} добавлен</b>", parse_mode='html')
    
    try:
        welcome_text = (
            "<b>Привет я:\n"
            "▲▼▲<code>AksiomovUrl</code>▼▲▼\n"
            "<code>>>></code>Созданный с целью\n\n"
            "Выдавать <code>Url</code> ссылки для бота <code>AksiomovHelp</code>\n"
            "Просто скинь мне любой медиа файл\n"
            "Я в свою очередь скину его <code>Url</code> ссылку\n\n"
            "<code>[</code>\n"
            "<code>>>></code>Правило пользования:\n"
            " <code>--></code> Максимальный размер 200мб\n"
            " <code>--></code> Видео и фото без ограничений\n"
            "<code>]</code></b>"
        )
        await client.send_file(
            user_id,
            "https://files.catbox.moe/rhtjww.mp4",
            caption=welcome_text,
            parse_mode='html'
        )
    except:
        pass

@client.on(events.NewMessage(pattern='/delete'))
async def remove_user(event):
    if event.sender_id != owner_id:
        return

    try:
        user_id = int(event.text.split()[1])
        
        if user_id in whitelist:
            whitelist.remove(user_id)
            save_whitelist()
            await event.reply(f"<b>Пользователь {user_id} удалён</b>", parse_mode='html')
        else:
            await event.reply(f"<b>Пользователь {user_id} не в списке</b>", parse_mode='html')
    except:
        await event.reply("<b>Ошибка. Формат: /delete user_id</b>", parse_mode='html')

@client.on(events.NewMessage(pattern='/usersinfo'))
async def users_info(event):
    if event.sender_id != owner_id:
        return

    info = "<b>Белый список:</b>\n\n"
    for user_id in whitelist:
        try:
            user = await client.get_entity(user_id)
            info += f"<b>{user.first_name}</b> [<code>{user_id}</code>]\n"
        except:
            info += f"<b>Неизвестный</b> [<code>{user_id}</code>]\n"
    
    await event.reply(info, parse_mode='html')
@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    if event.sender_id != owner_id and event.sender_id not in whitelist:
        return
    
    welcome_text = (
        "<b>Привет я:\n"
        "▲▼▲<code>AksiomovUrl</code>▼▲▼\n"
        "<code>>>></code>Созданный с целью\n\n"
        "Выдавать <code>Url</code> ссылки для бота <code>AksiomovHelp</code>\n"
        "Просто скинь мне любой медиа файл\n"
        "Я в свою очередь скину его <code>Url</code> ссылку\n\n"
        "<code>[</code>\n"
        "<code>>>></code>Правило пользования:\n"
        " <code>--></code> Максимальный размер 200мб\n"
        " <code>--></code> Видео и фото без ограничений\n"
        "<code>]</code></b>"
    )
    
    await client.send_file(
        event.chat_id,
        "https://files.catbox.moe/rhtjww.mp4",  # Эта ссылка работает (из приветствия)
        caption=welcome_text,
        parse_mode='html'
    )
@client.on(events.NewMessage(pattern='/dateinfo'))
async def date_info(event):
    if event.sender_id != owner_id:
        return
    
    text = """<b>Команды:</b>

<code>/dateinfo</code> - это сообщение
<code>/delete [user_id]</code> - удалить юзера
<code>/usersinfo</code> - список юзеров"""

    await client.send_file(
        event.chat_id,
        "https://files.catbox.moe/rhtjww.mp4",
        caption=text,
        parse_mode='html'
    )

if __name__ == '__main__':
    load_whitelist()
    load_file_hashes()
    load_image_hashes()
    client.run_until_disconnected()