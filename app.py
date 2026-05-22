import os, sqlite3
from functools import wraps
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'troque-essa-chave')
DB_NAME = os.environ.get('DB_NAME', 'rpg_v3.db')

def now(): return datetime.now().strftime('%d/%m/%Y %H:%M:%S')
def db():
    c = sqlite3.connect(DB_NAME); c.row_factory = sqlite3.Row; return c

def init_db():
    c=db(); q=c.execute
    q('CREATE TABLE IF NOT EXISTS roles(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT UNIQUE,label TEXT,color TEXT,can_admin INTEGER DEFAULT 0,can_deal INTEGER DEFAULT 0,can_money INTEGER DEFAULT 0,can_roles INTEGER DEFAULT 0,can_badges INTEGER DEFAULT 0,can_market INTEGER DEFAULT 0)')
    q('CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE,password_hash TEXT,role_id INTEGER,balance INTEGER DEFAULT 1000,online INTEGER DEFAULT 0,created_at TEXT)')
    q('CREATE TABLE IF NOT EXISTS transactions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,admin_id INTEGER,amount INTEGER,type TEXT,description TEXT,created_at TEXT)')
    q('CREATE TABLE IF NOT EXISTS bets(id INTEGER PRIMARY KEY AUTOINCREMENT,creator_id INTEGER,opponent_id INTEGER,dealer_id INTEGER,amount INTEGER,status TEXT DEFAULT "pending",winner_id INTEGER,created_at TEXT,resolved_at TEXT)')
    q('CREATE TABLE IF NOT EXISTS badges(id INTEGER PRIMARY KEY AUTOINCREMENT,emoji TEXT,name TEXT,rarity TEXT,description TEXT,created_at TEXT)')
    q('CREATE TABLE IF NOT EXISTS inventory(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,badge_id INTEGER,equipped INTEGER DEFAULT 0,acquired_at TEXT)')
    q('CREATE TABLE IF NOT EXISTS marketplace(id INTEGER PRIMARY KEY AUTOINCREMENT,seller_id INTEGER,inventory_id INTEGER,price INTEGER,status TEXT DEFAULT "active",created_at TEXT,buyer_id INTEGER,sold_at TEXT)')
    for r in [('player','Jogador','#ff3b8d',0,0,0,0,0,0),('dealer','Crupiê','#9b5cff',0,1,0,0,0,0),('admin','Admin','#ffd166',1,1,1,1,1,1)]:
        if not q('SELECT id FROM roles WHERE name=?',(r[0],)).fetchone():
            q('INSERT INTO roles(name,label,color,can_admin,can_deal,can_money,can_roles,can_badges,can_market) VALUES(?,?,?,?,?,?,?,?,?)', r)
    admin_role=q("SELECT id FROM roles WHERE name='admin'").fetchone()['id']; dealer_role=q("SELECT id FROM roles WHERE name='dealer'").fetchone()['id']
    if not q("SELECT id FROM users WHERE username='admin'").fetchone():
        q('INSERT INTO users(username,password_hash,role_id,balance,online,created_at) VALUES(?,?,?,?,?,?)',('admin',generate_password_hash('admin123'),admin_role,999999,0,now()))
    if not q("SELECT id FROM users WHERE username='crupie'").fetchone():
        q('INSERT INTO users(username,password_hash,role_id,balance,online,created_at) VALUES(?,?,?,?,?,?)',('crupie',generate_password_hash('crupie123'),dealer_role,1000,0,now()))
    if not q('SELECT id FROM badges LIMIT 1').fetchone():
        for b in [('👑','Rei do Cassino','lendária','Entregue pelos admins aos dominadores do ranking.'),('🔥','Apostador Insano','épica','Para quem encara apostas altas.'),('🃏','Carta Selvagem','rara','Símbolo de imprevisibilidade.'),('💎','Elite Hyakkaou','épica','Status de elite social.'),('🐈','House Pet','comum','Marca social da academia.')]:
            q('INSERT INTO badges(emoji,name,rarity,description,created_at) VALUES(?,?,?,?,?)',(*b,now()))
    c.commit(); c.close()

def me():
    if 'uid' not in session: return None
    c=db(); u=c.execute('''SELECT u.*,r.name role_name,r.label role_label,r.color role_color,r.can_admin,r.can_deal,r.can_money,r.can_roles,r.can_badges,r.can_market FROM users u JOIN roles r ON r.id=u.role_id WHERE u.id=?''',(session['uid'],)).fetchone(); c.close(); return u
@app.context_processor
def inject(): return {'me': me()}
def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if 'uid' not in session:
            flash('Faça login primeiro.','error'); return redirect(url_for('login'))
        return f(*a, **k)
    return w
def perm(p):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            u=me()
            if not u or not (u['can_admin'] or u[p]):
                flash('Sem permissão.','error'); return redirect(url_for('dashboard'))
            return f(*a, **k)
        return w
    return deco
def stats(c, uid):
    total=c.execute('SELECT COUNT(*) c FROM bets WHERE status="approved" AND (creator_id=? OR opponent_id=?)',(uid,uid)).fetchone()['c']
    wins=c.execute('SELECT COUNT(*) c FROM bets WHERE status="approved" AND winner_id=?',(uid,)).fetchone()['c']; losses=total-wins
    won=c.execute('SELECT COALESCE(SUM(amount),0) s FROM bets WHERE status="approved" AND winner_id=?',(uid,)).fetchone()['s']
    lost=c.execute('SELECT COALESCE(SUM(amount),0) s FROM bets WHERE status="approved" AND (creator_id=? OR opponent_id=?) AND winner_id!=?',(uid,uid,uid)).fetchone()['s']
    return {'total':total,'wins':wins,'losses':losses,'winrate':round(wins*100/total,1) if total else 0,'won':won,'lost':lost}
def tx(c, uid, amount, typ, desc, admin_id=None): c.execute('INSERT INTO transactions(user_id,admin_id,amount,type,description,created_at) VALUES(?,?,?,?,?,?)',(uid,admin_id,amount,typ,desc,now()))

@app.route('/')
def index(): return redirect(url_for('dashboard') if 'uid' in session else url_for('login'))
@app.route('/register',methods=['GET','POST'])
def register():
    c=db()
    if request.method=='POST':
        username=request.form['username'].strip(); password=request.form['password'].strip(); role=c.execute("SELECT id FROM roles WHERE name='player'").fetchone()['id']
        if len(username)<3 or len(password)<4: flash('Usuário mínimo 3 letras e senha mínimo 4.','error')
        else:
            try:
                c.execute('INSERT INTO users(username,password_hash,role_id,balance,online,created_at) VALUES(?,?,?,?,?,?)',(username,generate_password_hash(password),role,1000,0,now())); c.commit(); flash('Conta criada.','success'); return redirect(url_for('login'))
            except sqlite3.IntegrityError: flash('Usuário já existe.','error')
    c.close(); return render_template('register.html')
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        c=db(); u=c.execute('SELECT * FROM users WHERE username=?',(request.form['username'].strip(),)).fetchone()
        if u and check_password_hash(u['password_hash'], request.form['password']):
            session['uid']=u['id']; c.execute('UPDATE users SET online=1 WHERE id=?',(u['id'],)); c.commit(); c.close(); return redirect(url_for('dashboard'))
        c.close(); flash('Login inválido.','error')
    return render_template('login.html')
@app.route('/logout')
@login_required
def logout():
    c=db(); c.execute('UPDATE users SET online=0 WHERE id=?',(session['uid'],)); c.commit(); c.close(); session.clear(); return redirect(url_for('login'))
@app.route('/dashboard')
@login_required
def dashboard():
    u=me(); c=db(); ranking=c.execute('''SELECT u.username,u.balance,r.label role_label,r.color role_color FROM users u JOIN roles r ON r.id=u.role_id ORDER BY balance DESC LIMIT 10''').fetchall()
    recent=c.execute('''SELECT b.*,c.username creator,o.username opponent,w.username winner FROM bets b JOIN users c ON c.id=b.creator_id JOIN users o ON o.id=b.opponent_id LEFT JOIN users w ON w.id=b.winner_id WHERE b.creator_id=? OR b.opponent_id=? OR b.dealer_id=? ORDER BY b.id DESC LIMIT 8''',(u['id'],u['id'],u['id'])).fetchall()
    s=stats(c,u['id']); c.close(); return render_template('dashboard.html',ranking=ranking,recent=recent,stats=s)
@app.route('/ranking')
@login_required
def ranking():
    c=db(); users=c.execute('''SELECT u.username,u.balance,r.label role_label,r.color role_color FROM users u JOIN roles r ON r.id=u.role_id ORDER BY balance DESC''').fetchall(); c.close(); return render_template('ranking.html',users=users)
@app.route('/profile/<username>')
@login_required
def profile(username):
    c=db(); u=c.execute('''SELECT u.*,r.label role_label,r.color role_color FROM users u JOIN roles r ON r.id=u.role_id WHERE username=?''',(username,)).fetchone()
    if not u: c.close(); abort(404)
    badges=c.execute('''SELECT i.equipped,b.emoji,b.name,b.rarity,b.description FROM inventory i JOIN badges b ON b.id=i.badge_id WHERE i.user_id=? ORDER BY i.equipped DESC,i.id DESC''',(u['id'],)).fetchall()
    bets=c.execute('''SELECT b.*,c.username creator,o.username opponent,w.username winner FROM bets b JOIN users c ON c.id=b.creator_id JOIN users o ON o.id=b.opponent_id LEFT JOIN users w ON w.id=b.winner_id WHERE b.status='approved' AND (b.creator_id=? OR b.opponent_id=?) ORDER BY b.id DESC LIMIT 10''',(u['id'],u['id'])).fetchall()
    s=stats(c,u['id']); c.close(); return render_template('profile.html',user=u,badges=badges,bets=bets,stats=s)
@app.route('/bet/new',methods=['GET','POST'])
@login_required
def bet_new():
    u=me(); c=db()
    if request.method=='POST':
        opp=int(request.form['opponent_id']); dealer=int(request.form['dealer_id']); amount=int(request.form['amount'])
        o=c.execute('SELECT * FROM users WHERE id=?',(opp,)).fetchone(); d=c.execute('SELECT u.*,r.can_deal,r.can_admin FROM users u JOIN roles r ON r.id=u.role_id WHERE u.id=?',(dealer,)).fetchone()
        if opp==u['id'] or amount<=0: flash('Aposta inválida.','error')
        elif not o or not d or not d['online'] or not (d['can_deal'] or d['can_admin']): flash('Jogador/crupiê inválido.','error')
        elif u['balance']<amount or o['balance']<amount: flash('Saldo insuficiente.','error')
        else:
            c.execute('INSERT INTO bets(creator_id,opponent_id,dealer_id,amount,status,created_at) VALUES(?,?,?,?,?,?)',(u['id'],opp,dealer,amount,'pending',now())); c.commit(); c.close(); flash('Aposta enviada ao crupiê.','success'); return redirect(url_for('dashboard'))
    players=c.execute('SELECT id,username,balance FROM users WHERE id!=? ORDER BY username',(u['id'],)).fetchall(); dealers=c.execute('''SELECT u.id,u.username FROM users u JOIN roles r ON r.id=u.role_id WHERE u.online=1 AND (r.can_deal=1 OR r.can_admin=1)''').fetchall(); c.close(); return render_template('bet_new.html',players=players,dealers=dealers)
@app.route('/dealer')
@login_required
@perm('can_deal')
def dealer():
    u=me(); c=db(); bets=c.execute('''SELECT b.*,c.username creator,o.username opponent FROM bets b JOIN users c ON c.id=b.creator_id JOIN users o ON o.id=b.opponent_id WHERE b.status='pending' AND (b.dealer_id=? OR ?=1) ORDER BY b.id DESC''',(u['id'],u['can_admin'])).fetchall(); c.close(); return render_template('dealer.html',bets=bets)
@app.route('/dealer/resolve/<int:bid>',methods=['POST'])
@login_required
@perm('can_deal')
def resolve(bid):
    u=me(); c=db(); b=c.execute('SELECT * FROM bets WHERE id=?',(bid,)).fetchone(); winner=int(request.form['winner_id'])
    if not b or b['status']!='pending' or (b['dealer_id']!=u['id'] and not u['can_admin']) or winner not in (b['creator_id'],b['opponent_id']): flash('Aposta inválida.','error'); c.close(); return redirect(url_for('dealer'))
    loser=b['opponent_id'] if winner==b['creator_id'] else b['creator_id']; lo=c.execute('SELECT * FROM users WHERE id=?',(loser,)).fetchone()
    if lo['balance']<b['amount']: c.execute('UPDATE bets SET status="cancelled",resolved_at=? WHERE id=?',(now(),bid)); flash('Cancelada: perdedor sem saldo.','error')
    else:
        c.execute('UPDATE users SET balance=balance+? WHERE id=?',(b['amount'],winner)); c.execute('UPDATE users SET balance=balance-? WHERE id=?',(b['amount'],loser)); c.execute('UPDATE bets SET status="approved",winner_id=?,resolved_at=? WHERE id=?',(winner,now(),bid)); tx(c,winner,b['amount'],'bet_win',f'Vitória na aposta #{bid}'); tx(c,loser,-b['amount'],'bet_loss',f'Derrota na aposta #{bid}'); flash('Aposta aprovada.','success')
    c.commit(); c.close(); return redirect(url_for('dealer'))
@app.route('/dealer/cancel/<int:bid>',methods=['POST'])
@login_required
@perm('can_deal')
def cancel_bet(bid):
    u=me(); c=db(); b=c.execute('SELECT * FROM bets WHERE id=?',(bid,)).fetchone()
    if b and b['status']=='pending' and (b['dealer_id']==u['id'] or u['can_admin']): c.execute('UPDATE bets SET status="cancelled",resolved_at=? WHERE id=?',(now(),bid)); c.commit(); flash('Aposta cancelada.','success')
    c.close(); return redirect(url_for('dealer'))
@app.route('/market')
@login_required
def market():
    c=db(); listings=c.execute('''SELECT m.*,b.emoji,b.name,b.rarity,b.description,u.username seller FROM marketplace m JOIN inventory i ON i.id=m.inventory_id JOIN badges b ON b.id=i.badge_id JOIN users u ON u.id=m.seller_id WHERE m.status='active' ORDER BY m.id DESC''').fetchall(); c.close(); return render_template('market.html',listings=listings)
@app.route('/market/buy/<int:mid>',methods=['POST'])
@login_required
def market_buy(mid):
    u=me(); c=db(); m=c.execute('''SELECT m.*,i.badge_id,b.name badge FROM marketplace m JOIN inventory i ON i.id=m.inventory_id JOIN badges b ON b.id=i.badge_id WHERE m.id=? AND m.status='active' ''',(mid,)).fetchone()
    if not m: flash('Anúncio não encontrado.','error')
    elif m['seller_id']==u['id']: flash('Você não pode comprar de si mesmo.','error')
    elif u['balance']<m['price']: flash('Saldo insuficiente.','error')
    else:
        c.execute('UPDATE users SET balance=balance-? WHERE id=?',(m['price'],u['id'])); c.execute('UPDATE users SET balance=balance+? WHERE id=?',(m['price'],m['seller_id'])); c.execute('UPDATE inventory SET user_id=?,equipped=0 WHERE id=?',(u['id'],m['inventory_id'])); c.execute('UPDATE marketplace SET status="sold",buyer_id=?,sold_at=? WHERE id=?',(u['id'],now(),mid)); tx(c,u['id'],-m['price'],'market_buy',f'Compra: {m["badge"]}'); tx(c,m['seller_id'],m['price'],'market_sale',f'Venda: {m["badge"]}'); c.commit(); flash('Insígnia comprada.','success')
    c.close(); return redirect(url_for('inventory'))
@app.route('/inventory')
@login_required
def inventory():
    u=me(); c=db(); items=c.execute('''SELECT i.*,b.emoji,b.name,b.rarity,b.description,m.id listing_id,m.price listing_price FROM inventory i JOIN badges b ON b.id=i.badge_id LEFT JOIN marketplace m ON m.inventory_id=i.id AND m.status='active' WHERE i.user_id=? ORDER BY i.equipped DESC,i.id DESC''',(u['id'],)).fetchall(); c.close(); return render_template('inventory.html',items=items)
@app.route('/inventory/equip/<int:iid>',methods=['POST'])
@login_required
def equip(iid):
    u=me(); c=db()
    if c.execute('SELECT id FROM inventory WHERE id=? AND user_id=?',(iid,u['id'])).fetchone(): c.execute('UPDATE inventory SET equipped=0 WHERE user_id=?',(u['id'],)); c.execute('UPDATE inventory SET equipped=1 WHERE id=?',(iid,)); c.commit(); flash('Insígnia equipada.','success')
    c.close(); return redirect(url_for('inventory'))
@app.route('/inventory/sell/<int:iid>',methods=['POST'])
@login_required
def sell(iid):
    u=me(); price=int(request.form['price']); c=db(); item=c.execute('SELECT id FROM inventory WHERE id=? AND user_id=?',(iid,u['id'])).fetchone(); active=c.execute('SELECT id FROM marketplace WHERE inventory_id=? AND status="active"',(iid,)).fetchone()
    if item and not active and price>0: c.execute('INSERT INTO marketplace(seller_id,inventory_id,price,status,created_at) VALUES(?,?,?,?,?)',(u['id'],iid,price,'active',now())); c.commit(); flash('Anunciado no marketplace.','success')
    else: flash('Não foi possível anunciar.','error')
    c.close(); return redirect(url_for('inventory'))
@app.route('/market/cancel/<int:mid>',methods=['POST'])
@login_required
def market_cancel(mid):
    u=me(); c=db(); m=c.execute('SELECT * FROM marketplace WHERE id=? AND status="active"',(mid,)).fetchone()
    if m and (m['seller_id']==u['id'] or u['can_market'] or u['can_admin']): c.execute('UPDATE marketplace SET status="cancelled" WHERE id=?',(mid,)); c.commit(); flash('Anúncio cancelado.','success')
    c.close(); return redirect(url_for('inventory'))
@app.route('/admin')
@login_required
@perm('can_money')
def admin():
    c=db(); users=c.execute('''SELECT u.id,u.username,u.balance,u.online,r.label role_label FROM users u JOIN roles r ON r.id=u.role_id ORDER BY u.username''').fetchall(); hist=c.execute('''SELECT t.*,u.username user,a.username admin FROM transactions t JOIN users u ON u.id=t.user_id LEFT JOIN users a ON a.id=t.admin_id ORDER BY t.id DESC LIMIT 50''').fetchall(); c.close(); return render_template('admin.html',users=users,hist=hist)
@app.route('/admin/money',methods=['POST'])
@login_required
@perm('can_money')
def admin_money():
    u=me(); c=db(); uid=int(request.form['user_id']); amount=int(request.form['amount']); action=request.form['action']; desc=request.form['description'].strip() or 'Alteração manual'; signed=amount if action=='add' else -amount; target=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    if target and amount>0 and target['balance']+signed>=0: c.execute('UPDATE users SET balance=balance+? WHERE id=?',(signed,uid)); tx(c,uid,signed,'admin_money',desc,u['id']); c.commit(); flash('Saldo atualizado.','success')
    else: flash('Operação inválida.','error')
    c.close(); return redirect(url_for('admin'))
@app.route('/admin/roles',methods=['GET','POST'])
@login_required
@perm('can_roles')
def roles():
    c=db()
    if request.method=='POST':
        vals=(request.form['name'].strip().lower().replace(' ','_'),request.form['label'].strip(),request.form.get('color','#ff3b8d'),1 if request.form.get('can_admin') else 0,1 if request.form.get('can_deal') else 0,1 if request.form.get('can_money') else 0,1 if request.form.get('can_roles') else 0,1 if request.form.get('can_badges') else 0,1 if request.form.get('can_market') else 0)
        try: c.execute('INSERT INTO roles(name,label,color,can_admin,can_deal,can_money,can_roles,can_badges,can_market) VALUES(?,?,?,?,?,?,?,?,?)',vals); c.commit(); flash('Cargo criado.','success')
        except sqlite3.IntegrityError: flash('Cargo já existe.','error')
    roles=c.execute('SELECT * FROM roles ORDER BY id').fetchall(); users=c.execute('''SELECT u.id,u.username,u.role_id,r.label role_label FROM users u JOIN roles r ON r.id=u.role_id ORDER BY username''').fetchall(); c.close(); return render_template('roles.html',roles=roles,users=users)
@app.route('/admin/set-role',methods=['POST'])
@login_required
@perm('can_roles')
def set_role():
    c=db(); c.execute('UPDATE users SET role_id=? WHERE id=?',(int(request.form['role_id']),int(request.form['user_id']))); c.commit(); c.close(); flash('Cargo atualizado.','success'); return redirect(url_for('roles'))
@app.route('/admin/badges',methods=['GET','POST'])
@login_required
@perm('can_badges')
def badges():
    c=db()
    if request.method=='POST': c.execute('INSERT INTO badges(emoji,name,rarity,description,created_at) VALUES(?,?,?,?,?)',(request.form['emoji'],request.form['name'],request.form['rarity'],request.form['description'],now())); c.commit(); flash('Insígnia criada.','success')
    badges=c.execute('SELECT * FROM badges ORDER BY id DESC').fetchall(); users=c.execute('SELECT id,username FROM users ORDER BY username').fetchall(); inv=c.execute('''SELECT i.id,u.username,b.emoji,b.name,b.rarity FROM inventory i JOIN users u ON u.id=i.user_id JOIN badges b ON b.id=i.badge_id ORDER BY i.id DESC LIMIT 50''').fetchall(); c.close(); return render_template('badges.html',badges=badges,users=users,inv=inv)
@app.route('/admin/give-badge',methods=['POST'])
@login_required
@perm('can_badges')
def give_badge():
    c=db(); c.execute('INSERT INTO inventory(user_id,badge_id,equipped,acquired_at) VALUES(?,?,0,?)',(int(request.form['user_id']),int(request.form['badge_id']),now())); c.commit(); c.close(); flash('Insígnia enviada.','success'); return redirect(url_for('badges'))
from flask import jsonify

@app.route("/api/ranking")
def api_ranking():
    c = db()
    users = c.execute("""
        SELECT u.username, u.balance, r.label AS role
        FROM users u
        JOIN roles r ON r.id = u.role_id
        ORDER BY u.balance DESC
        LIMIT 10
    """).fetchall()
    c.close()

    return jsonify([
        {
            "username": u["username"],
            "balance": u["balance"],
            "role": u["role"]
        }
        for u in users
    ])


@app.route("/api/profile/<username>")
def api_profile(username):
    c = db()

    user = c.execute("""
        SELECT u.id, u.username, u.balance, r.label AS role
        FROM users u
        JOIN roles r ON r.id = u.role_id
        WHERE u.username = ?
    """, (username,)).fetchone()

    if not user:
        c.close()
        return jsonify({"error": "Usuário não encontrado"}), 404

    s = stats(c, user["id"])
    c.close()

    return jsonify({
        "username": user["username"],
        "balance": user["balance"],
        "role": user["role"],
        "bets": s["total"],
        "wins": s["wins"],
        "losses": s["losses"],
        "winrate": s["winrate"],
        "total_won": s["won"],
        "total_lost": s["lost"]
    })
if __name__ == '__main__': init_db(); app.run(debug=True)
else: init_db()
