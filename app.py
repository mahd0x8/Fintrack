import sqlite3, os
from functools import wraps
from flask import Flask, request, jsonify, render_template, g, send_from_directory, session
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'finance-secret-key-change-in-prod')
DB = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), 'finance.db'))

DEFAULT_CATEGORIES = [
    ('Housing',       '🏠', '#7F77DD', 0),
    ('Food',          '🛒', '#1D9E75', 0),
    ('Transport',     '🚗', '#378ADD', 0),
    ('Entertainment', '🎬', '#EF9F27', 0),
    ('Health',        '💊', '#E24B4A', 0),
    ('Other',         '📦', '#888780', 0),
    ('Income',        '💰', '#1D9E75', 1),
]

def get_db():
    if 'db' not in g:
        uri = f'file:{DB}?nolock=1'
        g.db = sqlite3.connect(uri, uri=True, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
        g.db.execute('PRAGMA journal_mode = OFF')
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db: db.close()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            return jsonify({'error': 'unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

def init_db():
    with app.app_context():
        db = get_db()
        db.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                pin_hash TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                amount REAL NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('income','expense')),
                category TEXT NOT NULL,
                date TEXT NOT NULL,
                note TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL UNIQUE,
                amount REAL NOT NULL,
                month TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                target REAL NOT NULL,
                saved REAL NOT NULL DEFAULT 0,
                color TEXT DEFAULT '#7F77DD',
                target_date TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                icon TEXT DEFAULT '📦',
                color TEXT DEFAULT '#888780',
                is_income INTEGER DEFAULT 0
            );
        ''')
        if not db.execute("SELECT 1 FROM settings WHERE key='currency'").fetchone():
            db.execute("INSERT INTO settings (key,value) VALUES ('currency','USD')")
        if not db.execute("SELECT 1 FROM settings WHERE key='theme'").fetchone():
            db.execute("INSERT INTO settings (key,value) VALUES ('theme','auto')")
        if not db.execute('SELECT 1 FROM categories LIMIT 1').fetchone():
            db.executemany(
                'INSERT OR IGNORE INTO categories (name,icon,color,is_income) VALUES (?,?,?,?)',
                DEFAULT_CATEGORIES
            )
            db.commit()
        try:
            db.execute('ALTER TABLE transactions ADD COLUMN goal_id INTEGER REFERENCES goals(id)')
            db.commit()
        except Exception:
            pass
        db.commit()

# ── AUTH ─────────────────────────────────────────────────────────────────────

@app.get('/api/auth/status')
def auth_status():
    db = get_db()
    user = db.execute('SELECT id, username, name FROM users LIMIT 1').fetchone()
    return jsonify({
        'registered': user is not None,
        'authenticated': bool(session.get('authenticated')),
        'name': user['name'] if user else None
    })

@app.post('/api/auth/register')
def auth_register():
    d = request.json
    db = get_db()
    if db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
        return jsonify({'error': 'Account already exists'}), 400
    name = (d.get('name') or '').strip()
    username = (d.get('username') or '').strip().lower()
    password = d.get('password') or ''
    pin = str(d.get('pin') or '')
    if not name or not username or not password or not pin:
        return jsonify({'error': 'All fields are required'}), 400
    if len(pin) != 4 or not pin.isdigit():
        return jsonify({'error': 'PIN must be exactly 4 digits'}), 400
    try:
        db.execute(
            'INSERT INTO users (username, name, password_hash, pin_hash) VALUES (?,?,?,?)',
            (username, name, generate_password_hash(password), generate_password_hash(pin))
        )
        db.commit()
        session['authenticated'] = True
        session['username'] = username
        return jsonify({'ok': True, 'name': name})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Username already taken'}), 409

@app.post('/api/auth/pin')
def auth_pin():
    d = request.json
    db = get_db()
    user = db.execute('SELECT * FROM users LIMIT 1').fetchone()
    if not user:
        return jsonify({'error': 'No account registered'}), 400
    if check_password_hash(user['pin_hash'], str(d.get('pin', ''))):
        session['authenticated'] = True
        session['username'] = user['username']
        return jsonify({'ok': True, 'name': user['name']})
    return jsonify({'error': 'Wrong PIN'}), 401

@app.post('/api/auth/login')
def auth_login():
    d = request.json
    db = get_db()
    username = (d.get('username') or '').strip().lower()
    user = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
    if user and check_password_hash(user['password_hash'], d.get('password', '')):
        session['authenticated'] = True
        session['username'] = user['username']
        return jsonify({'ok': True, 'name': user['name']})
    return jsonify({'error': 'Wrong username or password'}), 401

@app.post('/api/auth/logout')
def auth_logout():
    session.clear()
    return jsonify({'ok': True})

# ── TRANSACTIONS ──────────────────────────────────────────────────────────────

@app.get('/api/transactions')
@login_required
def list_transactions():
    db = get_db()
    q = request.args.get('q','').strip()
    typ = request.args.get('type','')
    cat = request.args.get('category','')
    month = request.args.get('month','')
    sql = '''SELECT t.*, g.name as goal_name
             FROM transactions t LEFT JOIN goals g ON t.goal_id = g.id
             WHERE 1=1'''
    params = []
    if q:
        sql += ' AND t.name LIKE ?'; params.append(f'%{q}%')
    if typ in ('income','expense'):
        sql += ' AND t.type=?'; params.append(typ)
    if cat:
        sql += ' AND t.category=?'; params.append(cat)
    if month:
        sql += ' AND strftime("%Y-%m",t.date)=?'; params.append(month)
    sql += ' ORDER BY t.date DESC, t.id DESC'
    rows = db.execute(sql, params).fetchall()
    return jsonify([dict(r) for r in rows])

@app.post('/api/transactions')
@login_required
def add_transaction():
    d = request.json
    db = get_db()
    goal_id = d.get('goal_id') or None
    cur = db.execute(
        'INSERT INTO transactions (name,amount,type,category,date,note,goal_id) VALUES (?,?,?,?,?,?,?)',
        (d['name'], float(d['amount']), d['type'], d['category'], d['date'], d.get('note',''), goal_id)
    )
    if goal_id:
        db.execute('UPDATE goals SET saved = saved + ? WHERE id = ?', (float(d['amount']), goal_id))
    db.commit()
    return jsonify({'id': cur.lastrowid}), 201

@app.delete('/api/transactions/<int:tid>')
@login_required
def delete_transaction(tid):
    db = get_db()
    tx = db.execute('SELECT * FROM transactions WHERE id=?', (tid,)).fetchone()
    if tx and tx['goal_id']:
        db.execute('UPDATE goals SET saved = MAX(0, saved - ?) WHERE id = ?', (tx['amount'], tx['goal_id']))
    db.execute('DELETE FROM transactions WHERE id=?', (tid,))
    db.commit()
    return jsonify({'ok': True})

@app.put('/api/transactions/<int:tid>')
@login_required
def update_transaction(tid):
    d = request.json
    db = get_db()
    old = db.execute('SELECT * FROM transactions WHERE id=?', (tid,)).fetchone()
    new_goal_id = d.get('goal_id') or None
    if old and old['goal_id']:
        db.execute('UPDATE goals SET saved = MAX(0, saved - ?) WHERE id = ?', (old['amount'], old['goal_id']))
    if new_goal_id:
        db.execute('UPDATE goals SET saved = saved + ? WHERE id = ?', (float(d['amount']), new_goal_id))
    db.execute(
        'UPDATE transactions SET name=?,amount=?,type=?,category=?,date=?,note=?,goal_id=? WHERE id=?',
        (d['name'], float(d['amount']), d['type'], d['category'], d['date'], d.get('note',''), new_goal_id, tid)
    )
    db.commit()
    return jsonify({'ok': True})

# ── BUDGETS ───────────────────────────────────────────────────────────────────

@app.get('/api/budgets')
@login_required
def list_budgets():
    db = get_db()
    from datetime import date
    month = request.args.get('month') or date.today().strftime('%Y-%m')
    cat_colors = {r['name']: r['color'] for r in db.execute('SELECT name, color FROM categories').fetchall()}
    budgets = db.execute('SELECT * FROM budgets WHERE month=?', (month,)).fetchall()
    result = []
    for b in budgets:
        spent = db.execute(
            'SELECT COALESCE(SUM(amount),0) FROM transactions WHERE category=? AND type="expense" AND strftime("%Y-%m",date)=?',
            (b['category'], month)
        ).fetchone()[0]
        result.append({**dict(b), 'spent': spent, 'color': cat_colors.get(b['category'], '#888780')})
    return jsonify(result)

@app.post('/api/budgets')
@login_required
def save_budget():
    d = request.json
    db = get_db()
    db.execute(
        'INSERT INTO budgets (category,amount,month) VALUES (?,?,?) ON CONFLICT(category) DO UPDATE SET amount=?, month=?',
        (d['category'], float(d['amount']), d['month'], float(d['amount']), d['month'])
    )
    db.commit()
    return jsonify({'ok': True})

@app.delete('/api/budgets/<int:bid>')
@login_required
def delete_budget(bid):
    db = get_db()
    db.execute('DELETE FROM budgets WHERE id=?', (bid,))
    db.commit()
    return jsonify({'ok': True})

# ── GOALS ─────────────────────────────────────────────────────────────────────

@app.get('/api/goals')
@login_required
def list_goals():
    rows = get_db().execute('SELECT * FROM goals ORDER BY id').fetchall()
    return jsonify([dict(r) for r in rows])

@app.post('/api/goals')
@login_required
def add_goal():
    d = request.json
    db = get_db()
    cur = db.execute(
        'INSERT INTO goals (name,target,saved,color,target_date) VALUES (?,?,?,?,?)',
        (d['name'], float(d['target']), float(d.get('saved',0)), d.get('color','#7F77DD'), d.get('target_date',''))
    )
    db.commit()
    return jsonify({'id': cur.lastrowid}), 201

@app.put('/api/goals/<int:gid>')
@login_required
def update_goal(gid):
    d = request.json
    db = get_db()
    db.execute(
        'UPDATE goals SET name=?,target=?,saved=?,color=?,target_date=? WHERE id=?',
        (d['name'], float(d['target']), float(d['saved']), d.get('color','#7F77DD'), d.get('target_date',''), gid)
    )
    db.commit()
    return jsonify({'ok': True})

@app.delete('/api/goals/<int:gid>')
@login_required
def delete_goal(gid):
    db = get_db()
    db.execute('DELETE FROM goals WHERE id=?', (gid,))
    db.commit()
    return jsonify({'ok': True})

# ── OVERVIEW ──────────────────────────────────────────────────────────────────

@app.get('/api/overview')
@login_required
def overview():
    db = get_db()
    from datetime import date
    month = request.args.get('month') or date.today().strftime('%Y-%m')
    income = db.execute(
        'SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type="income" AND strftime("%Y-%m",date)=?', (month,)
    ).fetchone()[0]
    expenses = db.execute(
        'SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type="expense" AND strftime("%Y-%m",date)=?', (month,)
    ).fetchone()[0]
    months = []
    import datetime
    y, m = int(month[:4]), int(month[5:])
    for _ in range(6):
        months.insert(0, f'{y}-{m:02d}')
        m -= 1
        if m == 0: m = 12; y -= 1
    flow = []
    for mo in months:
        inc = db.execute('SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type="income" AND strftime("%Y-%m",date)=?',(mo,)).fetchone()[0]
        exp = db.execute('SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type="expense" AND strftime("%Y-%m",date)=?',(mo,)).fetchone()[0]
        flow.append({'month': mo, 'income': inc, 'expenses': exp, 'savings': inc - exp})
    cat_colors = {r['name']: r['color'] for r in db.execute('SELECT name, color FROM categories').fetchall()}
    cats = db.execute(
        'SELECT category, SUM(amount) as total FROM transactions WHERE type="expense" AND strftime("%Y-%m",date)=? GROUP BY category',
        (month,)
    ).fetchall()
    cat_data = [{'category': r['category'], 'total': r['total'], 'color': cat_colors.get(r['category'], '#888780')} for r in cats]
    savings_trend = [{'month': f['month'], 'savings': f['savings']} for f in flow]
    total_goal_savings = db.execute('SELECT COALESCE(SUM(saved),0) FROM goals').fetchone()[0]
    total_budgeted = db.execute('SELECT COALESCE(SUM(amount),0) FROM budgets WHERE month=?', (month,)).fetchone()[0]
    budget_spent = db.execute(
        '''SELECT COALESCE(SUM(amount),0) FROM transactions
           WHERE type="expense" AND strftime("%Y-%m",date)=?
           AND category IN (SELECT category FROM budgets WHERE month=?)''',
        (month, month)
    ).fetchone()[0]
    budget_remaining = total_budgeted - budget_spent
    after_full_budget = (income - expenses) - budget_remaining
    return jsonify({
        'income': income, 'expenses': expenses,
        'left_in_hand': income - expenses,
        'total_goal_savings': total_goal_savings,
        'after_full_budget': after_full_budget,
        'cash_flow': flow,
        'category_breakdown': cat_data,
        'savings_trend': savings_trend
    })

@app.delete('/api/clear/<string:target>')
@login_required
def clear_data(target):
    db = get_db()
    if target == 'transactions':
        db.execute('DELETE FROM transactions')
    elif target == 'budgets':
        db.execute('DELETE FROM budgets')
    elif target == 'goals':
        db.execute('DELETE FROM goals')
    elif target == 'all':
        db.execute('DELETE FROM transactions')
        db.execute('DELETE FROM budgets')
        db.execute('DELETE FROM goals')
        db.execute('DELETE FROM settings')
    else:
        return jsonify({'error': 'unknown target'}), 400
    db.commit()
    return jsonify({'ok': True})

@app.get('/api/settings')
@login_required
def get_settings():
    db = get_db()
    rows = db.execute('SELECT key, value FROM settings').fetchall()
    return jsonify({r['key']: r['value'] for r in rows})

@app.put('/api/settings')
@login_required
def save_settings():
    db = get_db()
    for key, value in request.json.items():
        db.execute('INSERT INTO settings (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=?', (key, value, value))
    db.commit()
    return jsonify({'ok': True})

@app.get('/api/categories')
@login_required
def list_categories():
    rows = get_db().execute('SELECT * FROM categories ORDER BY is_income, name').fetchall()
    return jsonify([dict(r) for r in rows])

@app.post('/api/categories')
@login_required
def add_category():
    d = request.json
    db = get_db()
    try:
        cur = db.execute(
            'INSERT INTO categories (name,icon,color,is_income) VALUES (?,?,?,?)',
            (d['name'].strip(), d.get('icon','📦'), d.get('color','#888780'), int(d.get('is_income',0)))
        )
        db.commit()
        return jsonify({'id': cur.lastrowid}), 201
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Name already exists'}), 409

@app.put('/api/categories/<int:cid>')
@login_required
def update_category(cid):
    d = request.json
    db = get_db()
    old = db.execute('SELECT name FROM categories WHERE id=?', (cid,)).fetchone()
    new_name = d['name'].strip()
    try:
        db.execute('UPDATE categories SET name=?,icon=?,color=? WHERE id=?',
                   (new_name, d.get('icon','📦'), d.get('color','#888780'), cid))
        if old and old['name'] != new_name:
            db.execute('UPDATE transactions SET category=? WHERE category=?', (new_name, old['name']))
        db.commit()
        return jsonify({'ok': True})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Name already exists'}), 409

@app.delete('/api/categories/<int:cid>')
@login_required
def delete_category(cid):
    db = get_db()
    db.execute('DELETE FROM categories WHERE id=?', (cid,))
    db.commit()
    return jsonify({'ok': True})

@app.get('/api/meta')
@login_required
def meta():
    db = get_db()
    cats = db.execute('SELECT * FROM categories ORDER BY is_income, name').fetchall()
    categories  = [r['name']  for r in cats]
    cat_colors  = {r['name']: r['color'] for r in cats}
    cat_icons   = {r['name']: r['icon']  for r in cats}
    goals = [dict(r) for r in db.execute('SELECT id, name, color, saved, target FROM goals ORDER BY name').fetchall()]
    return jsonify({'categories': categories, 'cat_colors': cat_colors, 'cat_icons': cat_icons, 'goals': goals})

@app.get('/assets/<path:filename>')
def assets(filename):
    return send_from_directory(os.path.join(os.path.dirname(__file__), 'assets'), filename)

@app.get('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', debug=True, port=5000)
