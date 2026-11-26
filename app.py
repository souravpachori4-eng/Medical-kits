import os, sqlite3, secrets, json, io
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from functools import wraps

BASE_DIR = Path(__file__).resolve().parent

import pandas as pd
import numpy as np
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
load_dotenv(BASE_DIR / '.env')
DB_PATH = Path(os.getenv(
    'DATABASE_PATH',
    str(BASE_DIR / 'meddata.db')
))

UPLOAD_DIR = Path(os.getenv(
    'UPLOAD_DIR',
    str(BASE_DIR / 'private_uploads')
))

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_EXTENSIONS = {'csv', 'xlsx', 'xls'}
MAX_UPLOAD_MB = int(os.getenv('MAX_UPLOAD_MB', '20'))

app = Flask(__name__)
SECRET_KEY = os.getenv('SECRET_KEY')

if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY is missing from environment variables")

app.secret_key = SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_MB * 1024 * 1024
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.getenv('COOKIE_SECURE', '0') == '1'
FREE_ANALYSES = int(os.getenv('FREE_ANALYSES', '2'))
ANALYSIS_PRICE_INR = 15



@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()




def init_db():
    with db() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            analyses_used INTEGER NOT NULL DEFAULT 0,
            paid_credits INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS datasets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            original_name TEXT NOT NULL,
            stored_name TEXT NOT NULL,
            row_count INTEGER DEFAULT 0,
            col_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            analysis_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(dataset_id) REFERENCES datasets(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount_paise INTEGER NOT NULL,
            provider_order_id TEXT,
            provider_payment_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        );
        ''')
        # Lightweight schema migration for databases created by earlier MVP versions.
        cols = [r['name'] for r in conn.execute('PRAGMA table_info(users)').fetchall()]
        if 'paid_credits' not in cols:
            conn.execute('ALTER TABLE users ADD COLUMN paid_credits INTEGER NOT NULL DEFAULT 0')
        admin_email = os.getenv('ADMIN_EMAIL', '').strip().lower()
        admin_password = os.getenv('ADMIN_PASSWORD', '')
        if admin_email and admin_password:
            existing = conn.execute('SELECT id FROM users WHERE email=?', (admin_email,)).fetchone()
            if existing:
                conn.execute("UPDATE users SET role='admin' WHERE email=?", (admin_email,))
            else:
                conn.execute('INSERT INTO users(email,password_hash,role,created_at) VALUES(?,?,?,?)',
                            (admin_email, generate_password_hash(admin_password), 'admin', now()))


def now():
    return datetime.utcnow().isoformat(timespec='seconds')


def csrf_token():
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_urlsafe(24)
    return session['_csrf']
app.jinja_env.globals['csrf_token'] = csrf_token


@app.before_request
def check_csrf():
    if request.method == 'POST':
        submitted = request.form.get('_csrf', '')
        if not submitted or not secrets.compare_digest(submitted, session.get('_csrf', '')):
            abort(400, 'CSRF validation failed. Refresh and try again.')


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS



def load_dataset(path):
    ext = path.suffix.lower()
    if ext == '.csv':
        try:
            return pd.read_csv(path)
        except UnicodeDecodeError:
            return pd.read_csv(path, encoding='latin-1')
    return pd.read_excel(path)



def get_user():
    if not session.get('user_id'):
        return None
    with db() as conn:
        return conn.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()



def user_projects(user_id):
    with db() as conn:
        return conn.execute('''SELECT p.*, COUNT(d.id) AS dataset_count
          FROM projects p LEFT JOIN datasets d ON d.project_id=p.id
          WHERE p.user_id=? GROUP BY p.id ORDER BY p.id DESC''', (user_id,)).fetchall()


@app.route('/')
def index():
    if session.get('user_id'):
        return redirect(url_for('dashboard'))
    return render_template('landing.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        if not email or len(password) < 8:
            flash('Enter a valid email and a password of at least 8 characters.', 'error')
        elif password != confirm_password:
            flash('Passwords do not match.', 'error')
        else:
            try:
                with db() as conn:
                    conn.execute('INSERT INTO users(email,password_hash,created_at) VALUES(?,?,?)',
                                (email, generate_password_hash(password), now()))
                flash('Account created. Please sign in.', 'success')
                return redirect(url_for('login'))
            except sqlite3.IntegrityError:
                flash('That email is already registered.', 'error')
    return render_template('auth.html', mode='register')



@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        with db() as conn:
            user = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        if user and check_password_hash(user['password_hash'], password):
            session.clear()
            session['user_id'] = user['id']
            session['email'] = user['email']
            session['role'] = user['role']
            return redirect(url_for('dashboard'))
        flash('Email or password is incorrect.', 'error')
    return render_template('auth.html', mode='login')


@app.route('/logout', methods=['POST'])
@login_required
def logout():
    session.clear()
    return redirect(url_for('index'))


@app.route('/dashboard')
@login_required
def dashboard():
    user = get_user()
    projects = user_projects(user['id'])
    with db() as conn:
        datasets = conn.execute('''SELECT d.*, p.title AS project_title FROM datasets d
            JOIN projects p ON p.id=d.project_id WHERE d.user_id=? ORDER BY d.id DESC LIMIT 10''', (user['id'],)).fetchall()
    return render_template('dashboard.html', user=user, projects=projects, datasets=datasets,
                         free_limit=FREE_ANALYSES, price=ANALYSIS_PRICE_INR)


@app.route('/projects/create', methods=['POST'])
@login_required
def create_project():
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    if not title:
        flash('Project title is required.', 'error')
    else:
        with db() as conn:
            conn.execute('INSERT INTO projects(user_id,title,description,created_at) VALUES(?,?,?,?)',
                        (session['user_id'], title[:120], description[:1000], now()))
        flash('Research project created.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/project/<int:project_id>')
@login_required
def project(project_id):
    with db() as conn:
        p = conn.execute('SELECT * FROM projects WHERE id=? AND user_id=?',
                       (project_id, session['user_id'])).fetchone()
        if not p:
            abort(404)
        ds = conn.execute('SELECT * FROM datasets WHERE project_id=? ORDER BY id DESC', (project_id,)).fetchall()
    return render_template('project.html', project=p, datasets=ds)


@app.route('/project/<int:project_id>/upload', methods=['POST'])
@login_required
def upload_dataset(project_id):
    file = request.files.get('file')
    with db() as conn:
        project = conn.execute('SELECT * FROM projects WHERE id=? AND user_id=?',
                              (project_id, session['user_id'])).fetchone()
    if not project:
        abort(404)
    if not file or not file.filename or not allowed_file(file.filename):
        flash('Choose a CSV or Excel file.', 'error')
        return redirect(url_for('project', project_id=project_id))
    safe_name = secure_filename(file.filename)
    unique_name = f"u{session['user_id']}_{secrets.token_hex(12)}_{safe_name}"
    destination = UPLOAD_DIR / unique_name
    file.save(destination)
    try:
        df = load_dataset(destination)
        if len(df.columns) == 0:
            raise ValueError('Dataset has no columns')
    except Exception as e:
        destination.unlink(missing_ok=True)
        flash(f'Could not read the dataset: {e}', 'error')
        return redirect(url_for('project', project_id=project_id))
    with db() as conn:
        conn.execute('''INSERT INTO datasets(project_id,user_id,original_name,stored_name,row_count,col_count,created_at)
            VALUES(?,?,?,?,?,?,?)''', (project_id, session['user_id'], safe_name, unique_name,
                                    len(df), len(df.columns), now()))
    flash('Dataset uploaded successfully.', 'success')
    return redirect(url_for('dataset', dataset_id=get_latest_dataset_id(session['user_id'], project_id)))


def get_latest_dataset_id(user_id, project_id):
    with db() as conn:
        row = conn.execute('SELECT id FROM datasets WHERE user_id=? AND project_id=? ORDER BY id DESC LIMIT 1',
                          (user_id, project_id)).fetchone()
    return row['id']


def fetch_dataset_record(dataset_id, owner_id=None):
    with db() as conn:
        if owner_id is None:
            return conn.execute('SELECT * FROM datasets WHERE id=?', (dataset_id,)).fetchone()
        return conn.execute('SELECT * FROM datasets WHERE id=? AND user_id=?', (dataset_id, owner_id)).fetchone()


def analysis_context(dataset_record):
    filepath = UPLOAD_DIR / dataset_record['stored_name']
    if not filepath.exists():
        abort(410, 'Dataset file no longer exists. It may have been deleted.')
    df = load_dataset(filepath)
    numeric = df.select_dtypes(include='number')
    desc = numeric.describe().round(3).replace({np.nan: None}).to_dict()
    missing = df.isna().sum().to_dict()
    missing_pct = (df.isna().mean() * 100).round(2).to_dict()
    preview = df.head(12).replace({np.nan: None}).to_dict(orient='records')
    # JSON-safe conversion for Plotly and browser rendering
    corr = numeric.corr().round(3).replace({np.nan: None})
    corr_labels = list(corr.columns)
    corr_values = corr.values.tolist()
    chart_data = {}
    if len(numeric.columns):
        first_num = numeric.columns[0]
        chart_data['hist'] = {'column': str(first_num), 'x': numeric[first_num].dropna().tolist()[:5000]}
    if len(df.columns):
        first_col = df.columns[0]
        counts = df[first_col].astype(str).value_counts().head(12)
        chart_data['bar'] = {'column': str(first_col), 'labels': counts.index.tolist(), 'values': counts.values.tolist()}
    return df, desc, missing, missing_pct, preview, corr_labels, corr_values, chart_data


@app.route('/dataset/<int:dataset_id>')
@login_required
def dataset(dataset_id):
    record = fetch_dataset_record(dataset_id, session['user_id'])
    if not record:
        abort(404)
    df, desc, missing, missing_pct, preview, corr_labels, corr_values, chart_data = analysis_context(record)
    user = get_user()
    with db() as conn:
        prior = conn.execute('SELECT id FROM analyses WHERE dataset_id=? AND user_id=? LIMIT 1',
                            (dataset_id, session['user_id'])).fetchone()
    has_run = bool(prior)
    return render_template('dataset.html', record=record, df_shape=df.shape,
        columns=list(df.columns), preview=preview, numeric_columns=list(df.select_dtypes(include='number').columns),
        stats=desc, missing=missing, missing_pct=missing_pct, corr_labels=corr_labels,
        corr_values=corr_values, chart_data=chart_data, user=user, free_limit=FREE_ANALYSES,
        price=ANALYSIS_PRICE_INR, has_run=has_run)


@app.route('/dataset/<int:dataset_id>/analyze', methods=['POST'])
@login_required
def analyze(dataset_id):
    record = fetch_dataset_record(dataset_id, session['user_id'])
    if not record:
        abort(404)
    with db() as conn:
        user = conn.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
        # This MVP records one usage when the user explicitly runs analysis.
        if user['analyses_used'] < FREE_ANALYSES:
            conn.execute('UPDATE users SET analyses_used=analyses_used+1 WHERE id=?', (session['user_id'],))
        elif user['paid_credits'] > 0:
            conn.execute('UPDATE users SET paid_credits=paid_credits-1 WHERE id=?', (session['user_id'],))
        else:
            flash('Your free analyses are used up. Purchase one analysis credit for ₹15 to continue.', 'error')
            return redirect(url_for('dataset', dataset_id=dataset_id))
        conn.execute('INSERT INTO analyses(dataset_id,user_id,analysis_type,created_at) VALUES(?,?,?,?)',
                    (dataset_id, session['user_id'], 'full_dataset_analysis', now()))
    flash('Analysis run recorded. Charts and statistics are ready below.', 'success')
    return redirect(url_for('dataset', dataset_id=dataset_id))


@app.route('/dataset/<int:dataset_id>/download')
@login_required
def download_dataset(dataset_id):
    record = fetch_dataset_record(dataset_id, session['user_id'])
    if not record:
        abort(404)
    path = UPLOAD_DIR / record['stored_name']
    if not path.exists():
        abort(410)
    return send_file(path, as_attachment=True, download_name=record['original_name'])



@app.route('/payments/create-order', methods=['POST'])
@login_required
def create_payment_order():
    key_id = os.getenv('RAZORPAY_KEY_ID', '')
    key_secret = os.getenv('RAZORPAY_KEY_SECRET', '')
    if not key_id or not key_secret:
        return {'error': 'Payments are not configured on this deployment yet.'}, 503
    try:
        import razorpay
        client = razorpay.Client(auth=(key_id, key_secret))
        order = client.order.create(data={'amount': ANALYSIS_PRICE_INR * 100, 'currency': 'INR',
                                        'receipt': f'meddata_{session["user_id"]}_{secrets.token_hex(5)}'})
        with db() as conn:
            conn.execute('INSERT INTO payments(user_id,amount_paise,provider_order_id,status,created_at) VALUES(?,?,?,?,?)',
                        (session['user_id'], ANALYSIS_PRICE_INR * 100, order['id'], 'pending', now()))
        return {'order_id': order['id'], 'amount': order['amount'], 'currency': order['currency'],
                'key': key_id, 'product_name': 'MedData Analytics — 1 analysis credit', 'email': session['email']}
    except Exception:
        app.logger.exception('Razorpay order creation failed')
        return {'error': 'Could not create payment order. Please try again.'}, 502


@app.route('/payments/verify', methods=['POST'])
@login_required
def verify_payment():
    payload = request.form
    order_id = payload.get('razorpay_order_id', '')
    payment_id = payload.get('razorpay_payment_id', '')
    signature = payload.get('razorpay_signature', '')
    key_secret = os.getenv('RAZORPAY_KEY_SECRET', '')
    if not all([order_id, payment_id, signature, key_secret]):
        return {'error': 'Missing payment verification information.'}, 400
    try:
        import razorpay
        client = razorpay.Client(auth=(os.getenv('RAZORPAY_KEY_ID', ''), key_secret))
        client.utility.verify_payment_signature({'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id, 'razorpay_signature': signature})
        with db() as conn:
            payment = conn.execute('SELECT * FROM payments WHERE provider_order_id=? AND user_id=? AND status=?',
                                (order_id, session['user_id'], 'pending')).fetchone()
            if not payment:
                return {'error': 'Payment order not found or already processed.'}, 409
            conn.execute("UPDATE payments SET provider_payment_id=?,status='paid' WHERE id=?", (payment_id, payment['id']))
            conn.execute('UPDATE users SET paid_credits=paid_credits+1 WHERE id=?', (session['user_id'],))
        return {'ok': True, 'message': 'Payment verified. One analysis credit added.'}
    except Exception:
        app.logger.exception('Payment verification failed')
        return {'error': 'Payment could not be verified. Contact support if money was deducted.'}, 400



@app.route('/admin')
@admin_required
def admin():
    with db() as conn:
        users = conn.execute('SELECT id,email,role,analyses_used,created_at FROM users ORDER BY id DESC').fetchall()
        ds = conn.execute('''SELECT d.*, u.email, p.title project_title FROM datasets d
            JOIN users u ON u.id=d.user_id JOIN projects p ON p.id=d.project_id ORDER BY d.id DESC''').fetchall()
        total_analyses = conn.execute('SELECT COUNT(*) n FROM analyses').fetchone()['n']
        payments = conn.execute('SELECT * FROM payments ORDER BY id DESC').fetchall()
    revenue = sum(p['amount_paise'] for p in payments if p['status'] == 'paid') / 100
    return render_template('admin.html', users=users, datasets=ds, total_analyses=total_analyses, revenue=revenue)


@app.route('/admin/dataset/<int:dataset_id>/download')
@admin_required
def admin_download(dataset_id):
    record = fetch_dataset_record(dataset_id)
    if not record:
        abort(404)
    path = UPLOAD_DIR / record['stored_name']
    if not path.exists():
        abort(410)
    return send_file(path, as_attachment=True, download_name=record['original_name'])


@app.route('/health')
def health():
    return {'status': 'ok'}


# Initialize database
init_db()

if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=int(os.getenv('PORT', 5000)),
        debug=os.getenv('FLASK_DEBUG', '0') == '1'
    )


# Initialize schema for both local runs and WSGI deployments (e.g. Gunicorn).
init_db()
