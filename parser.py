import os
import requests
from bs4 import BeautifulSoup
import smtplib
import time
import re
import subprocess
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Настройки из переменных окружения
EMAIL_SENDER = os.environ.get('EMAIL_SENDER')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD')
EMAIL_RECEIVER = os.environ.get('EMAIL_RECEIVER')
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

DB_FILE = "sent_urls.txt"

def load_sent_data(force_pull=False):
    if force_pull:
        try:
            subprocess.run(["git", "pull"], check=False)
        except Exception:
            pass
        
    sent_urls = set()
    sent_titles = set()
    
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                if "||" in line_str:
                    parts = line_str.split("||", 1)
                    url_part = parts[0].strip().rstrip('/').lower()
                    title_part = parts[1].strip().lower()
                    sent_urls.add(url_part)
                    sent_titles.add(title_part)
                else:
                    sent_urls.add(line_str.rstrip('/').lower())
                    
    return sent_urls, sent_titles

def save_sent_data(url, title):
    clean_url = url.strip().rstrip('/').lower()
    clean_title = " ".join(title.split()).strip().lower()
    
    with open(DB_FILE, "a", encoding="utf-8") as f:
        f.write(f"{clean_url}||{clean_title}\n")
    
    try:
        subprocess.run(["git", "config", "--local", "user.email", "github-actions[bot]@users.noreply.github.com"], check=False)
        subprocess.run(["git", "config", "--local", "user.name", "github-actions[bot]"], check=False)
        subprocess.run(["git", "add", DB_FILE], check=False)
        res = subprocess.run(["git", "diff", "--cached", "--quiet"], check=False)
        if res.returncode != 0:
            subprocess.run(["git", "commit", "-m", "Update database [skip ci]"], check=False)
            subprocess.run(["git", "push"], check=False)
    except Exception as e:
        print(f"Ошибка сохранения в Git: {e}")

def send_email(subject, html_content):
    clean_subject = " ".join(subject.split())
    msg = MIMEMultipart()
    msg['From'] = EMAIL_SENDER
    msg['To'] = EMAIL_RECEIVER
    msg['Subject'] = f"Trashbox"
    msg.attach(MIMEText(html_content, 'html'))
    
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"Письмо отправлено: {clean_subject}")
    except Exception as e:
        print(f"Ошибка почты: {e}")

def parse_trashbox():
    url = "https://trashbox.ru/news"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    
    print("Проверка новостей...")
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"Ошибка загрузки сайта: {e}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')
    link_pattern = re.compile(r'/link/\d{4}-\d{2}-\d{2}')
    
    sent_urls, sent_titles = load_sent_data(force_pull=True)
    found_links = []

    for a in soup.find_all('a', href=True):
        href = a['href'].strip().split('?')[0].split('#')[0].rstrip('/')
        
        if link_pattern.search(href):
            full_url = href if href.startswith('http') else "https://trashbox.ru" + href
            full_url = full_url.lower()
            
            if full_url not in sent_urls and full_url not in found_links:
                found_links.append(full_url)

    print(f"К отправке: {len(found_links)} уникальных новостей.")

    new_dispatched = 0
    for news_url in reversed(found_links):
        sent_urls, sent_titles = load_sent_data(force_pull=False)
        if news_url in sent_urls:
            continue

        print(f"Обработка статьи: {news_url}")
        
        try:
            news_res = requests.get(news_url, headers=headers, timeout=15)
            news_res.raise_for_status()
            news_soup = BeautifulSoup(news_res.text, 'html.parser')
            
            # 1. Поиск основного заголовка
            title_tag = news_soup.find('h1', class_=re.compile(r'h_topic_caption', re.I)) or news_soup.find('h1')
            title = title_tag.get_text(strip=True) if title_tag else "Без названия"
            
            clean_title_check = " ".join(title.split()).strip().lower()
            if clean_title_check in sent_titles:
                print(f"Пропуск: статья с заголовком '{title}' уже была отправлена ранее.")
                continue

            # 2. Поиск подзаголовка / описания статьи
            sub_title_tag = news_soup.find('div', class_=re.compile(r'div_topic_circle_descr_top', re.I))
            sub_title_html = f"<p style='font-size: 1.1em; color: #555; font-weight: bold;'>{sub_title_tag.get_text(strip=True)}</p>" if sub_title_tag else ""

            # 3. Поиск даты публикации
            date_tag = news_soup.find('time')
            date_html = f"<p style='color: #888; font-size: 0.85em;'>Дата: {date_tag.get_text(strip=True)}</p>" if date_tag else ""

            # 4. Поиск основного контейнера контента
            content_div = (
                news_soup.find('div', class_=re.compile(r'div_topic_view', re.I)) or 
                news_soup.find('div', id=re.compile(r'div_text_content_', re.I)) or
                news_soup.find('div', id='topic_content') or
                news_soup.find('article')
            )

            # 5. Поиск титульного фото
            title_img = news_soup.find('img', class_=re.compile(r'div_image_news_item', re.I))

            if content_div:
                # Вставка титульного фото в начало контента статьи
                if title_img:
                    # Создаем обертку для оформления титульной картинки
                    img_container = news_soup.new_tag('div', style="text-align: center; margin-bottom: 15px;")
                    img_container.append(title_img)
                    content_div.insert(0, img_container)

                # Вставка подзаголовка над текстом (после титульного фото)
                if sub_title_tag:
                    sub_tag_parsed = BeautifulSoup(sub_title_html, 'html.parser')
                    content_div.insert(1 if title_img else 0, sub_tag_parsed)

                # Очистка от рекламы, промо-блоков, скриптов и стилей
                for trash in content_div.find_all(['div', 'section', 'form', 'script', 'style', 'iframe', 'ins'], 
                                                 id=re.compile(r'comments|comm_cont|reply_form|related|tags|vote|rating|like|dislike|div_anim_rec', re.I),
                                                 class_=re.compile(r'comments|comm_cont|topic_tags|vote|rating|like|dislike|div_anim_rec', re.I)):
                    trash.decompose()
                
                # Удаление элементов авторов и мета-информации внутри текста
                for author_info in content_div.find_all(['div', 'span', 'a'], 
                                                       class_=re.compile(r'author|avatar|topic_author|user|meta', re.I)):
                    author_info.decompose()
                
                for s in content_div(['script', 'style', 'iframe', 'ins', 'form']):
                    s.decompose()

                # Форматирование ВСЕХ картинок внутри письма
                for img in content_div.find_all('img', src=True):
                    src = img['src'].strip()
                    if src.startswith('/') and not src.startswith('//'):
                        img['src'] = "https://trashbox.ru" + src
                    elif src.startswith('//'):
                        img['src'] = "https:" + src
                    
                    if img.has_attr('width'): del img['width']
                    if img.has_attr('height'): del img['height']
                    if img.has_attr('srcset'): del img['srcset']
                    if img.has_attr('sizes'): del img['sizes']
                    
                    img['style'] = "max-width: 100% !important; height: auto !important; display: block !important; margin: 12px auto !important; object-fit: contain;"
                
                # Сброс размеров у контейнеров картинок галереи (.center, .div_gallery_item и т.д.)
                for img_container in content_div.find_all(['div', 'span'], class_=re.compile(r'image|img|gallery|center', re.I)):
                    img_container['style'] = "max-width: 100% !important; width: auto !important; height: auto !important; text-align: center;"

                html_body = f"""
                <html>
                <head>
                    <style>
                        body {{ font-family: sans-serif; line-height: 1.6; color: #333; max-width: 700px; margin: 0 auto; padding: 10px; }}
                        img {{ max-width: 100% !important; height: auto !important; display: block !important; margin: 12px auto !important; }}
                        div.center, span.div_gallery_item {{ max-width: 100% !important; width: auto !important; height: auto !important; text-align: center !important; display: block !important; }}
                    </style>
                </head>
                <body>
                    <h1 style="font-size: 1.5em; line-height: 1.3;">{title}</h1>
                    {date_html}
                    {str(content_div)}
                    <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                    <p><a href="{news_url}">Читать оригинал на Trashbox.ru</a></p>
                </body>
                </html>
                """
            else:
                html_body = f"Контент не найден. <a href='{news_url}'>Перейти на сайт</a>"

            send_email(title, html_body)
            
            save_sent_data(news_url, title)
            new_dispatched += 1
            
            print("Пауза 5 секунд...")
            time.sleep(5)
            
        except Exception as e:
            print(f"Ошибка при обработке {news_url}: {e}")

    if new_dispatched == 0:
        print("Новых новостей нет.")

if __name__ == "__main__":
    parse_trashbox()
