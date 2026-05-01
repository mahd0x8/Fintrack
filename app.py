import sqlite3, os
from flask import Flask, request, jsonify, render_template, g, send_from_directory

app = Flask(__name__)
DB = os.path.join(os.path.dirname(__file__), 'finance.db')

CATEGORIES = ['Housing', 'Food', 'Transport', 'Entertainment', 'Health', 'Income', 'Other']
CAT_COLORS = {
    'Housing': '#7F77DD', 'Food': '#1D9E75', 'Transport': '#378ADD',
    'Entertainment': '#EF9F27', 'Health': '#E24B4A', 'Income': '#1D9E75', 'Other': '#888780'
}
CAT_ICONS = {
    'Housing': '🏠', 'Food': '🛒', 'Transport': '🚗',
    'Entertainment': '🎬', 'Health': '💊', 'Income': '💰', 'Other': '📦'
}

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db: db.close()

def init_db():
    with app.app_context():
        db = get_db()
        db.executescript('''
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
        ''')
        if not db.execute("SELECT 1 FROM settings WHERE key='currency'").fetchone():
            db.execute("INSERT INTO settings (key,value) VALUES ('currency','USD')")
        if not db.execute("SELECT 1 FROM settings WHERE key='theme'").fetchone():
            db.execute("INSERT INTO settings (key,value) VALUES ('theme','auto')")
        # Add goal_id column to transactions if missing (migration)
        try:
            db.execute('ALTER TABLE transactions ADD COLUMN goal_id INTEGER REFERENCES goals(id)')
            db.commit()
        except Exception:
            pass
        # Seed sample data if empty
        if not db.execute('SELECT 1 FROM transactions LIMIT 1').fetchone():
            db.executescript('''
                INSERT INTO transactions (name,amount,type,category,date) VALUES
                  ('Salary deposit',2425,'income','Income','2026-05-01'),
                  ('Grocery store',67,'expense','Food','2026-05-01'),
                  ('Uber ride',14,'expense','Transport','2026-04-30'),
                  ('Netflix subscription',18,'expense','Entertainment','2026-04-30'),
                  ('Rent',1100,'expense','Housing','2026-04-30'),
                  ('Freelance payment',500,'income','Income','2026-04-29'),
                  ('Gym membership',45,'expense','Health','2026-04-28'),
                  ('Restaurant dinner',52,'expense','Food','2026-04-27'),
                  ('Salary deposit',2425,'income','Income','2026-04-15'),
                  ('Electric bill',85,'expense','Housing','2026-04-10'),
                  ('Amazon purchase',120,'expense','Other','2026-04-08'),
                  ('Coffee shop',22,'expense','Food','2026-04-05'),
                  ('Bus pass',40,'expense','Transport','2026-04-02'),
                  ('Salary deposit',2425,'income','Income','2026-03-15'),
                  ('Rent',1100,'expense','Housing','2026-03-01');
                INSERT INTO budgets (category,amount,month) VALUES
                  ('Housing',1200,'2026-05'),
                  ('Food',600,'2026-05'),
                  ('Transport',400,'2026-05'),
                  ('Entertainment',300,'2026-05'),
                  ('Health',200,'2026-05'),
                  ('Other',500,'2026-05');
                INSERT INTO goals (name,target,saved,color,target_date) VALUES
                  ('Emergency fund',10000,7000,'#7F77DD','2026-11-01'),
                  ('Vacation to Japan',1700,1500,'#1D9E75','2026-06-01'),
                  ('New laptop',1000,250,'#EF9F27','2027-02-01');
            ''')
        db.commit()

# ── TRANSACTIONS ────────────────────────────────────────────────────────────

@app.get('/api/transactions')
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
def delete_transaction(tid):
    db = get_db()
    tx = db.execute('SELECT * FROM transactions WHERE id=?', (tid,)).fetchone()
    if tx and tx['goal_id']:
        db.execute('UPDATE goals SET saved = MAX(0, saved - ?) WHERE id = ?', (tx['amount'], tx['goal_id']))
    db.execute('DELETE FROM transactions WHERE id=?', (tid,))
    db.commit()
    return jsonify({'ok': True})

@app.put('/api/transactions/<int:tid>')
def update_transaction(tid):
    d = request.json
    db = get_db()
    old = db.execute('SELECT * FROM transactions WHERE id=?', (tid,)).fetchone()
    new_goal_id = d.get('goal_id') or None
    # Reverse old goal contribution
    if old and old['goal_id']:
        db.execute('UPDATE goals SET saved = MAX(0, saved - ?) WHERE id = ?', (old['amount'], old['goal_id']))
    # Apply new goal contribution
    if new_goal_id:
        db.execute('UPDATE goals SET saved = saved + ? WHERE id = ?', (float(d['amount']), new_goal_id))
    db.execute(
        'UPDATE transactions SET name=?,amount=?,type=?,category=?,date=?,note=?,goal_id=? WHERE id=?',
        (d['name'], float(d['amount']), d['type'], d['category'], d['date'], d.get('note',''), new_goal_id, tid)
    )
    db.commit()
    return jsonify({'ok': True})

# ── BUDGETS ─────────────────────────────────────────────────────────────────

@app.get('/api/budgets')
def list_budgets():
    db = get_db()
    month = request.args.get('month', '2026-05')
    budgets = db.execute('SELECT * FROM budgets WHERE month=?', (month,)).fetchall()
    result = []
    for b in budgets:
        spent = db.execute(
            'SELECT COALESCE(SUM(amount),0) FROM transactions WHERE category=? AND type="expense" AND strftime("%Y-%m",date)=?',
            (b['category'], month)
        ).fetchone()[0]
        result.append({**dict(b), 'spent': spent, 'color': CAT_COLORS.get(b['category'],'#888780')})
    return jsonify(result)

@app.post('/api/budgets')
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
def delete_budget(bid):
    db = get_db()
    db.execute('DELETE FROM budgets WHERE id=?', (bid,))
    db.commit()
    return jsonify({'ok': True})

# ── GOALS ───────────────────────────────────────────────────────────────────

@app.get('/api/goals')
def list_goals():
    rows = get_db().execute('SELECT * FROM goals ORDER BY id').fetchall()
    return jsonify([dict(r) for r in rows])

@app.post('/api/goals')
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
def delete_goal(gid):
    db = get_db()
    db.execute('DELETE FROM goals WHERE id=?', (gid,))
    db.commit()
    return jsonify({'ok': True})

# ── OVERVIEW ────────────────────────────────────────────────────────────────

@app.get('/api/overview')
def overview():
    db = get_db()
    month = request.args.get('month', '2026-05')

    income = db.execute(
        'SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type="income" AND strftime("%Y-%m",date)=?', (month,)
    ).fetchone()[0]
    expenses = db.execute(
        'SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type="expense" AND strftime("%Y-%m",date)=?', (month,)
    ).fetchone()[0]

    # Monthly cash flow: last 6 months
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

    # Category breakdown for current month
    cats = db.execute(
        'SELECT category, SUM(amount) as total FROM transactions WHERE type="expense" AND strftime("%Y-%m",date)=? GROUP BY category',
        (month,)
    ).fetchall()
    cat_data = [{'category': r['category'], 'total': r['total'], 'color': CAT_COLORS.get(r['category'],'#888780')} for r in cats]

    # Savings trend
    savings_trend = [{'month': f['month'], 'savings': f['savings']} for f in flow]

    total_goal_savings = db.execute('SELECT COALESCE(SUM(saved),0) FROM goals').fetchone()[0]
    total_budgeted = db.execute('SELECT COALESCE(SUM(amount),0) FROM budgets WHERE month=?', (month,)).fetchone()[0]
    after_full_budget = (income - expenses) - total_budgeted

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
def get_settings():
    db = get_db()
    rows = db.execute('SELECT key, value FROM settings').fetchall()
    return jsonify({r['key']: r['value'] for r in rows})

@app.put('/api/settings')
def save_settings():
    db = get_db()
    for key, value in request.json.items():
        db.execute('INSERT INTO settings (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=?', (key, value, value))
    db.commit()
    return jsonify({'ok': True})

@app.get('/api/meta')
def meta():
    goals = [dict(r) for r in get_db().execute('SELECT id, name, color, saved, target FROM goals ORDER BY name').fetchall()]
    return jsonify({'categories': CATEGORIES, 'cat_colors': CAT_COLORS, 'cat_icons': CAT_ICONS, 'goals': goals})

@app.get('/assets/<path:filename>')
def assets(filename):
    return send_from_directory(os.path.join(os.path.dirname(__file__), 'assets'), filename)

@app.get('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', debug=True, port=5000)
