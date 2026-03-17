import os
from datetime import datetime
from urllib.parse import urlparse

import requests
import validators
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from psycopg2.extras import DictCursor

from page_analyzer.db import get_conn

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret')


@app.route('/')
def index():
    return render_template('index.html', errors={}, url='')


@app.route('/urls', methods=['POST'])
def create_urls():
    url = request.form.get('url', '').strip()
    errors = {}

    if not url:
        flash('Некорректный URL', 'danger')
        errors['url'] = 'Некорректный URL'
    elif not validators.url(url):
        flash('Некорректный URL', 'danger')
        errors['url'] = 'Некорректный URL'

    if errors:
        return render_template('index.html', errors=errors, url=url), 422
    
    parse = urlparse(url)
    normalized_url = f'{parse.scheme}://{parse.netloc}'
    if len(normalized_url) > 255:
        flash('URL превышает 255 символов', 'danger')
        errors['url'] = 'URL превышает 255 символов'
        return render_template('index.html', errors=errors, url=url), 422

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM urls WHERE name = %s', (normalized_url,))
            existing = cur.fetchone()
            if existing:
                flash('Страница уже существует', 'primary')
                return redirect(url_for('show_url', id=existing[0]))
            cur.execute(
                '''INSERT INTO urls (name, created_at)
                VALUES (%s, %s) RETURNING id''',
                (normalized_url, datetime.utcnow())
            )
            url_id = cur.fetchone()[0]
            conn.commit()
            flash('Страница успешно добавлена', 'success')
            return redirect(url_for('show_url', id=url_id))
        

@app.route('/urls/<int:id>')
def show_url(id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('''SELECT id, name, created_at
                FROM urls WHERE id = %s''', (id,)
            )
            url = cur.fetchone()
            if not url:
                abort(404)
            cur.execute('''SELECT * FROM url_checks
                WHERE url_id = %s ORDER BY id DESC''', (id,)
            )
            checks = cur.fetchall()
            return render_template('urls/show.html', url=url, checks=checks)
        

@app.route('/urls')
def urls_index():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('''SELECT urls.id,
                urls.name,
                urls.created_at,
                MAX(url_checks.created_at) AS last_check,
                MAX(url_checks.status_code) AS status_code
                FROM urls LEFT JOIN url_checks ON urls.id = url_checks.url_id
                GROUP BY urls.id, urls.name, urls.created_at
                ORDER BY urls.id DESC'''
            )
            rows = cur.fetchall()
            return render_template('urls/index.html', urls=rows)
        

MAX_LEN = 200


def normalize_text(text):
    return ' '.join(text.split())


def truncate_if_overflow(raw, max_len=MAX_LEN):
    if raw is None:
        return None
    text = normalize_text(raw)
    if len(text) <= max_len:
        return text
    return f'{text[: max_len - 3]}...'


def extract_text(tag):
    if not tag:
        return None
    return truncate_if_overflow(tag.get_text())


def fetch_url(url_name):
    try:
        r = requests.get(url_name, timeout=5)
    except requests.RequestException:
        return None, 'Произошла ошибка при проверке'
    if r.status_code >= 500:
        return None, 'Произошла ошибка при проверке'
    return r, None


def parse_page_content(html):
    soup = BeautifulSoup(html, 'html.parser')
    h1 = extract_text(soup.h1)
    title = extract_text(soup.title)
    description = None
    meta = soup.find('meta', attrs={'name': 'description'})
    if meta and meta.get('content'):
        description = truncate_if_overflow(meta['content'])
    return h1, title, description


@app.route('/urls/<int:id>/checks', methods=['POST'])
def check_url(id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('SELECT name FROM urls WHERE id = %s', (id,))
            url = cur.fetchone()
            if not url:
                flash('URL не найден', 'danger')
                return redirect(url_for('urls_index'))

            r, error = fetch_url(url['name'])
            if error:
                flash(error, 'danger')
                return redirect(url_for('show_url', id=id))

            h1, title, description = parse_page_content(r.text)
            cur.execute('''INSERT INTO url_checks 
                (url_id, created_at, status_code, h1, title, description) 
                VALUES (%s, %s, %s, %s, %s, %s)''', (
                    id,
                    datetime.utcnow(), 
                    r.status_code, 
                    h1, 
                    title, 
                    description,
                    )
            )
            conn.commit()
            flash('Страница успешно проверена', 'success')
            return redirect(url_for('show_url', id=id))
