import os
from dotenv import load_dotenv
from urllib.parse import urlparse
from datetime import datetime
from psycopg2.extras import DictCursor
from bs4 import BeautifulSoup

from flask import (
    Flask,
    flash,
    get_flashed_messages,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
    abort
)
import requests
from page_analyzer.db import get_conn
import validators


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
        errors['url'] = "Can't be blank"
    elif len(url) > 255:
        errors['url'] = 'URL is too long'
    elif not validators.url(url):
        errors['url'] = 'Invalid URL'

    if errors:
        return render_template('index.html', errors=errors, url=url), 422
    
    parse = urlparse(url)
    normalized_url = f'{parse.scheme}://{parse.netloc}'

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM urls WHERE name = %s', (normalized_url,))
            existing = cur.fetchone()
            if existing:
                flash('URL is already exist', 'warning')
                return redirect(url_for('show_url', id=existing[0]))
            cur.execute(
                'INSERT INTO urls (name, created_at) VALUES (%s, %s) RETURNING id',
                (normalized_url, datetime.utcnow()))
            url_id = cur.fetchone()[0]
            flash('Страница успешно добавлена', 'succes')
            return redirect(url_for('show_url', id=url_id))
        

@app.route('/urls/<id>')
def show_url(id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('SELECT id, name, created_at FROM urls WHERE id = %s', (id,))
            url = cur.fetchone()
            if not url:
                abort(404)
            cur.execute('SELECT * FROM url_checks WHERE url_id = %s ORDER BY id DESC', (id,))
            checks = cur.fetchall()
            return render_template('urls/show.html', url={
                'id': url[0],
                'name': url[1],
                'created_at': url[2]
            }, checks=checks)
        

@app.route('/urls')
def urls_index():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('SELECT urls.id, urls.name, urls.created_at, MAX(url_checks.created_at) AS last_check, MAX(url_checks.status_code) AS status_code FROM urls LEFT JOIN url_checks ON urls.id = url_checks.url_id GROUP BY urls.id ORDER BY urls.id DESC')
            rows = cur.fetchall()
            return render_template('urls/index.html', urls=rows)
        

@app.route('/urls/<id>/checks', methods=['POST'])
def check_url(id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('SELECT name FROM urls WHERE id = %s', (id,))
            url = cur.fetchone()
            if not url:
                flash('URL не найден', 'danger')
                return redirect(url_for('urls_index'))
            try:
                r = requests.get(url['name'], timeout=5)
                if r.status_code >= 500:
                    flash('Произошла ошибка при проверке', 'danger')
                    return redirect(url_for('urls_show', id=id))
                soup = BeautifulSoup(r.text, 'html.parser')
                h1 = soup.h1.get_text(strip=True) if soup.h1 else None
                title = soup.title.get_text(strip=True) if soup.title else None
                description = None
                meta = soup.find('meta', attrs={'name': 'description'})
                if meta and meta.get('content'):
                    description = meta['content'].strip()
                cur.execute('INSERT INTO url_checks (url_id, created_at, status_code, h1, title, description) VALUES (%s, %s, %s, %s, %s, %s)', (id, datetime.now(), r.status_code, h1, title, description))
                conn.commit()
                flash('Страница успешно проверена', 'success')
            except requests.RequestException:
                flash('Ошибка при проверке', 'danger')
            return redirect(url_for('show_url', id=id))
