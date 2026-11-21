#!/usr/bin/env python3
"""Balcão Fácil – servidor local. Python 3.9+, sem dependências externas. Banco de dados: SQLite."""
import os, sys, json, sqlite3, hashlib, secrets, threading, queue, re, socket, hmac, time, datetime, webbrowser
import base64, subprocess, urllib.parse, urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import escpos

RES = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))      # public/, pages/, sync.js
def _default_data():
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "BalcaoFacil" / "data"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "balcaofacil"
DATA = Path(os.environ.get("BALCAO_DATA") or _default_data())
PORT = int(os.environ.get("PORT", 8080))
BK, VENDOR = DATA / "backups", DATA / "vendor"
BK.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- banco (SQLite)
LOCK = threading.RLock()
db = sqlite3.connect(DATA / "balcaofacil.db", check_same_thread=False, isolation_level=None)
db.execute("PRAGMA journal_mode=WAL"); db.execute("PRAGMA synchronous=FULL")
db.executescript("""
CREATE TABLE IF NOT EXISTS products(id TEXT PRIMARY KEY, data TEXT NOT NULL,
  est_fisico REAL NOT NULL DEFAULT 0, est_reservado REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS history(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entradas(chave TEXT PRIMARY KEY, data TEXT, usuario TEXT, numero TEXT, serie TEXT,
  emissao TEXT, forn_cnpj TEXT, forn_nome TEXT, total REAL, itens TEXT);
CREATE TABLE IF NOT EXISTS docs(kind TEXT, id INTEGER, data TEXT NOT NULL, PRIMARY KEY(kind, id));
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users(name TEXT PRIMARY KEY COLLATE NOCASE, salt TEXT, hash TEXT, role TEXT);
""")
dumps = lambda o: json.dumps(o, ensure_ascii=False)
def kget(k, default=None):
    r = db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return json.loads(r[0]) if r else default
def kset(k, v):
    db.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, dumps(v)))
num = lambda x: int(x) if float(x).is_integer() else float(x)
EMP = ("nome", "cnpj", "endereco", "telefone", "rodape")
ROLES = ("admin", "financeiro", "caixa", "estoquista", "vendedor")
def parse_roles(v):
    r = [x.strip() for x in (v if isinstance(v, list) else str(v or "").split(",")) if x.strip() in ROLES]
    return list(dict.fromkeys(r))
def caps(roles):                      # permissões = união dos perfis marcados
    r = set(roles); a = "admin" in r
    return {"admin": a, "sell": a or bool(r & {"caixa", "estoquista"}), "quote": a or bool(r & {"caixa", "estoquista", "vendedor"}),
            "stock": a or "estoquista" in r, "fin": a or "financeiro" in r}
UNIDADES = ("UN", "KG", "CX", "M", "L", "PCT")
class Err(Exception):
    def __init__(self, msg, code=403): super().__init__(msg); self.code = code

def state(user):
    with LOCK:
        rows = db.execute("SELECT data, est_fisico, est_reservado FROM products ORDER BY rowid").fetchall()
        prods = [dict(json.loads(r[0]), stockPhysical=num(r[1]), stockReserved=num(r[2])) for r in rows] \
                if (rows or kget("init_products")) else None          # None = primeira execução (o app carrega os produtos padrão)
        hist = [json.loads(r[0]) for r in db.execute("SELECT data FROM history ORDER BY seq DESC")]
        return {"v": kget("v", 0), "products": prods, "clients": kget("clients"), "sellers": kget("sellers"),
                "empresa": kget("empresa"), "history": hist, "user": user}

def apply(b, cp):
    """Estoque = soma de variações (UPDATE atômico). Permissões aplicadas aqui, no servidor."""
    admin, staff = cp["admin"], cp["stock"]
    hist, ds = b.get("history") or [], b.get("dstock") or {}
    if not staff and (b.get("upsert") or b.get("del") or b.get("sellers") is not None):
        raise Err("Seu perfil não pode alterar produtos nem vendedores.")
    if (hist or ds or isinstance(b.get("clients"), list)) and not cp["quote"]:
        raise Err("Seu perfil não registra vendas nem orçamentos.")
    if not cp["sell"] and (any(h.get("type") != "ORCAMENTO" for h in hist) or any(float(d[0] or 0) != 0 for d in ds.values())):
        raise Err("O perfil Vendedor só gera orçamentos; a venda é finalizada pelo Caixa.")
    if ds and not staff and not hist:
        raise Err("Ajuste manual de estoque exige perfil Estoquista ou Administrador.")
    with LOCK:
        db.execute("BEGIN IMMEDIATE")
        try:
            fresh = set()
            for p in b.get("upsert") or []:
                pid = str(p["id"])
                rest = {k: v for k, v in p.items() if k not in ("stockPhysical", "stockReserved")}
                if db.execute("SELECT 1 FROM products WHERE id=?", (pid,)).fetchone():
                    db.execute("UPDATE products SET data=? WHERE id=?", (dumps(rest), pid))
                else:
                    db.execute("INSERT INTO products(id,data,est_fisico,est_reservado) VALUES(?,?,?,?)",
                               (pid, dumps(rest), float(p.get("stockPhysical") or 0), float(p.get("stockReserved") or 0)))
                    fresh.add(pid)
                kset("init_products", True)
            for pid, d in (b.get("dstock") or {}).items():
                if pid not in fresh:
                    db.execute("UPDATE products SET est_fisico=est_fisico+?, est_reservado=MAX(0,est_reservado+?) WHERE id=?",
                               (float(d[0] or 0), float(d[1] or 0), pid))
            for pid in b.get("del") or []:
                db.execute("DELETE FROM products WHERE id=?", (str(pid),))
            for k in ("clients", "sellers"):
                if isinstance(b.get(k), list): kset(k, b[k])
            if admin and isinstance(b.get("empresa"), dict):
                kset("empresa", {k: str(b["empresa"].get(k) or "").strip()[:160] for k in EMP})
            for h in reversed(b.get("history") or []):
                if db.execute("UPDATE history SET data=? WHERE id=?", (dumps(h), str(h["id"]))).rowcount == 0:
                    db.execute("INSERT INTO history(id,data) VALUES(?,?)", (str(h["id"]), dumps(h)))
            v = kget("v", 0) + 1; kset("v", v)
            db.execute("COMMIT"); return v
        except Exception:
            db.execute("ROLLBACK"); raise

# ---------------------------------------------------------------- NF-e (entrada de estoque)
def nfe_commit(b, user):
    chave = re.sub(r"\D", "", str(b.get("chave") or "")); itens = b.get("itens") or []
    if len(chave) != 44 or not itens: raise Err("Nota inválida: informe a chave de 44 dígitos e ao menos um item.", 400)
    forn = b.get("fornecedor") or {}; cnpj = str(forn.get("cnpj") or ""); upd = bool(b.get("atualizarPreco"))
    with LOCK:
        db.execute("BEGIN IMMEDIATE")
        try:
            ja = db.execute("SELECT data, usuario FROM entradas WHERE chave=?", (chave,)).fetchone()
            if ja: raise Err(f"Esta nota já foi lançada em {ja[0]} por {ja[1]}.", 409)
            mp = kget("nfemap", {}); log = []
            nxt = max([int(r[0]) for r in db.execute("SELECT id FROM products") if r[0].isdigit()] + [1000]) + 1
            for it in itens:
                qtd, custo = float(it["qtd"]), float(it["custo"])
                if qtd <= 0 or custo < 0: raise Err("Quantidade ou custo inválido em um dos itens.", 400)
                pid = str(it.get("pid") or "")
                row = db.execute("SELECT data FROM products WHERE id=?", (pid,)).fetchone() if pid else None
                if row:
                    d = json.loads(row[0]); d["cost"] = round(custo, 4)
                    if upd: d["price"] = round(custo * (1 + float(d.get("margin") or 0) / 100), 2)
                    db.execute("UPDATE products SET data=?, est_fisico=est_fisico+? WHERE id=?", (dumps(d), qtd, pid))
                else:
                    m = float(it["margem"]) if it.get("margem") not in (None, "") else 40.0
                    un = str(it.get("un") or "UN").upper(); pid = str(nxt); nxt += 1
                    d = {"id": pid, "ref": str(it.get("cprod") or "S/REF")[:30], "ean": it.get("ean") or "SEM EAN",
                         "description": str(it.get("desc") or "Produto")[:120], "unit": un if un in UNIDADES else "UN",
                         "cost": round(custo, 4), "margin": m, "price": round(custo * (1 + m / 100), 2)}
                    db.execute("INSERT INTO products(id,data,est_fisico,est_reservado) VALUES(?,?,?,0)", (pid, dumps(d), qtd))
                mp[f"{cnpj}|{it.get('cprod')}"] = pid
                log.append({"pid": pid, "desc": d["description"], "qtd": qtd, "custo": custo, "novo": not row})
            kset("nfemap", mp); kset("init_products", True)
            when = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
            db.execute("INSERT INTO entradas VALUES(?,?,?,?,?,?,?,?,?,?)", (chave, when, user, str(b.get("numero") or ""),
                       str(b.get("serie") or ""), str(b.get("emissao") or ""), cnpj, str(forn.get("nome") or ""),
                       float(b.get("total") or 0), dumps(log)))
            if b.get("financeiro", True):
                dups = [d for d in (b.get("duplicatas") or []) if d.get("dVenc") and float(d.get("vDup") or 0) > 0]
                doc_add("compras", {"data": str(b.get("emissao") or "")[:10] or datetime.date.today().isoformat(),
                        "fornecedor": str(forn.get("nome") or "Fornecedor"), "nfe": str(b.get("numero") or ""),
                        "valor": str(round(float(b.get("total") or 0), 2)), "pagamento": "Boleto" if dups else "A definir",
                        "observacoes": "Gerada pela NF-e " + chave}, user)
                for dp in dups:
                    doc_add("boletos", {"fornecedor": str(forn.get("nome") or "Fornecedor"), "descricao": f"NF-e {b.get('numero') or ''} dup. {dp.get('nDup') or ''}".strip(),
                            "valor": str(round(float(dp["vDup"]), 2)), "vencimento": str(dp["dVenc"])[:10], "status": "Em aberto",
                            "origem": "NF-e", "observacoes": ""}, user)
            v = kget("v", 0) + 1; kset("v", v); db.execute("COMMIT"); return v, log
        except Exception:
            db.execute("ROLLBACK"); raise

# ---------------------------------------------------------------- requisições, trocas e entregas
DOCS = {"requisicoes": ("dataSolicitacao", "codigo", "produto", "quantidade", "solicitante"),
        "trocas": ("data", "codigo", "quantidade", "solicitante", "status"),
        "entregas": ("orcamento", "vendedor", "dataEntrega", "endereco", "status"),
        "boletos": ("fornecedor", "valor", "vencimento", "status"),
        "compras": ("data", "fornecedor", "valor"),
        "despesas": ("descricao", "valor", "categoria", "data")}
FIN = ("boletos", "compras", "despesas")                     # só Administrador e Financeiro
def fin_ok(kind, cp):
    if kind in FIN and not cp["fin"]: raise Err("Apenas Administrador ou Financeiro acessam boletos, compras e despesas.")
def doc_add(kind, it, user):
    it = dict(it, criadoPor=user, criadoEm=datetime.datetime.now().strftime("%d/%m/%Y %H:%M"))
    nid = (db.execute("SELECT MAX(id) FROM docs WHERE kind=?", (kind,)).fetchone()[0] or 0) + 1
    db.execute("INSERT INTO docs(kind,id,data) VALUES(?,?,?)", (kind, nid, dumps(it))); return dict(it, id=nid)
def docs_list(kind, cp):
    if kind not in DOCS: raise Err("Tipo inválido.", 400)
    fin_ok(kind, cp)
    with LOCK:
        return [dict(json.loads(r[1]), id=r[0]) for r in db.execute("SELECT id,data FROM docs WHERE kind=? ORDER BY id DESC", (kind,))]
def docs_save(b, s):
    kind = b.get("kind")
    if kind not in DOCS: raise Err("Tipo inválido.", 400)
    fin_ok(kind, s["caps"])
    with LOCK:
        if b.get("del") is not None:
            if not (s["caps"]["stock"] or s["caps"]["fin"]): raise Err("Seu perfil não exclui registros.")
            db.execute("DELETE FROM docs WHERE kind=? AND id=?", (kind, int(b["del"]))); return {"ok": 1}
        raw = b.get("item") or {}; iid = raw.get("id")
        it = {k: ("" if v is None else str(v).strip()[:500]) for k, v in raw.items() if k != "id"}
        falta = [k for k in DOCS[kind] if not it.get(k)]
        if falta: raise Err("Preencha os campos obrigatórios: " + ", ".join(falta), 400)
        for campo in ("quantidade", "valor"):
            if campo in it:
                try: assert float(it[campo]) > 0
                except Exception: raise Err(("Quantidade" if campo == "quantidade" else "Valor") + " inválido(a).", 400)
        agora = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
        if iid:
            row = db.execute("SELECT data FROM docs WHERE kind=? AND id=?", (kind, int(iid))).fetchone()
            if not row: raise Err("Registro não encontrado.", 404)
            old = json.loads(row[0]); it.update(criadoPor=old.get("criadoPor"), criadoEm=old.get("criadoEm"), editadoPor=s["name"], editadoEm=agora)
            db.execute("UPDATE docs SET data=? WHERE kind=? AND id=?", (dumps(it), kind, int(iid))); return dict(it, id=int(iid))
        return doc_add(kind, it, s["name"])
def printer_cfg():
    with LOCK: return {**escpos.PADRAO, **(kget("impressora") or {})}

def backup():
    f = BK / f"balcaofacil-{datetime.date.today()}.db"
    with LOCK:
        dst = sqlite3.connect(f); db.backup(dst); dst.close()
    for old in sorted(BK.glob("balcaofacil-*.db"))[:-30]: old.unlink()
def backup_loop():
    while True:
        try: backup()
        except Exception as e: print("backup falhou:", e)
        time.sleep(3600)

# ---------------------------------------------------------------- usuários
def hpw(pw, salt): return hashlib.scrypt(pw.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=32).hex()
def set_user(name, pw, roles):
    salt = secrets.token_hex(12); rs = ",".join(parse_roles(roles)) or "vendedor"
    with LOCK:
        db.execute("INSERT INTO users(name,salt,hash,role) VALUES(?,?,?,?) ON CONFLICT(name) DO UPDATE SET "
                   "salt=excluded.salt, hash=excluded.hash, role=excluded.role", (name, salt, hpw(pw, salt), rs))
def no_users():
    with LOCK: return not db.execute("SELECT 1 FROM users LIMIT 1").fetchone()
MINPW = 6

def migrate_legacy():
    """Importa o db.json da versão Node.js (usuários, produtos, vendas, empresa)."""
    f = DATA / "db.json"
    with LOCK:
        if not f.exists() or db.execute("SELECT 1 FROM users LIMIT 1").fetchone(): return
        old = json.loads(f.read_text("utf-8")); db.execute("BEGIN IMMEDIATE")
        for u in old.get("users") or []:
            db.execute("INSERT OR REPLACE INTO users VALUES(?,?,?,?)", (u["name"], u["salt"], u["hash"], u["role"]))
        if old.get("products") is not None:
            for p in old["products"]:
                rest = {k: v for k, v in p.items() if k not in ("stockPhysical", "stockReserved")}
                db.execute("INSERT OR REPLACE INTO products(id,data,est_fisico,est_reservado) VALUES(?,?,?,?)",
                           (str(p["id"]), dumps(rest), float(p.get("stockPhysical") or 0), float(p.get("stockReserved") or 0)))
            kset("init_products", True)
        for k in ("clients", "sellers", "empresa"):
            if old.get(k) is not None: kset(k, old[k])
        for h in reversed(old.get("history") or []):
            db.execute("INSERT OR IGNORE INTO history(id,data) VALUES(?,?)", (str(h["id"]), dumps(h)))
        db.execute("COMMIT")
    f.rename(f.with_suffix(".json.migrado")); print("Dados do db.json importados para o SQLite.")

# ---------------------------------------------------------------- recursos offline
def vendor():
    B = "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/"
    for url, dest in (("https://cdn.tailwindcss.com", "tailwind.js"), (B + "css/all.min.css", "css/all.min.css"),
                      (B + "webfonts/fa-solid-900.woff2", "webfonts/fa-solid-900.woff2"),
                      (B + "webfonts/fa-brands-400.woff2", "webfonts/fa-brands-400.woff2"),
                      (B + "webfonts/fa-regular-400.woff2", "webfonts/fa-regular-400.woff2")):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=30).read()
            (VENDOR / dest).parent.mkdir(parents=True, exist_ok=True); (VENDOR / dest).write_bytes(data); print("baixado:", dest)
        except Exception as e:
            print(f"Falha ao baixar {dest} ({e}). O sistema usará a internet quando houver."); return

# ---------------------------------------------------------------- HTTP
LOGIN = (RES / "pages" / "login.html").read_text("utf-8")
SETUP = (RES / "pages" / "primeiro.html").read_text("utf-8")
SESS, SLOCK = {}, threading.Lock()
CLIENTS, CL = set(), threading.Lock()
MIME = {".js": "application/javascript", ".css": "text/css", ".woff2": "font/woff2"}
ICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><rect width="512" height="512" rx="96" fill="#0f172a"/>'
        '<text x="256" y="350" font-family="Arial" font-weight="700" font-size="300" text-anchor="middle" fill="#38bdf8">B</text></svg>')
MANIFEST = {"name": "Balcão Fácil", "short_name": "Balcão Fácil", "start_url": "/", "display": "standalone",
            "background_color": "#0f172a", "theme_color": "#0f172a",
            "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}]}

def page():
    f = RES / "public" / "index.html"
    if not f.exists(): return "<h2>Arquivo public/index.html não encontrado.</h2>"
    h = f.read_text("utf-8")
    if (VENDOR / "tailwind.js").exists():
        h = re.sub(r'<script src="https://cdn\.tailwindcss\.com[^"]*"></script>', lambda m: '<script src="/vendor/tailwind.js"></script>', h, 1)
    if (VENDOR / "css" / "all.min.css").exists():
        h = re.sub(r'<link[^>]*font-awesome[^>]*>', lambda m: '<link rel="stylesheet" href="/vendor/css/all.min.css">', h, 1)
    h = re.sub(r'<link[^>]*(?:googleapis|gstatic)[^>]*>', "", h).replace("setupBeforeUnload();", "")
    inj = ('<link rel="manifest" href="/manifest.webmanifest"><meta name="theme-color" content="#0f172a">'
           '<meta name="apple-mobile-web-app-capable" content="yes"><link rel="apple-touch-icon" href="/icon.svg">'
           '<script src="/sync.js"></script>')
    return re.sub(r'<head[^>]*>', lambda m: m.group(0) + inj, h, 1)

def broadcast(msg):
    data = ("data: " + json.dumps(msg) + "\n\n").encode()
    with CL:
        for q in list(CLIENTS): q.put(data)

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def out(self, code, body, ctype, extra=()):
        if isinstance(body, str): body = body.encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in extra: self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)
    def js(self, o, code=200, extra=()): self.out(code, dumps(o), "application/json; charset=utf-8", extra)
    def html(self, s): self.out(200, s, "text/html; charset=utf-8")
    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 8_000_000: raise ValueError("grande demais")
        return json.loads(self.rfile.read(n) or b"{}")
    def sid(self):
        m = re.search(r"(?:^|;\s*)sid=([a-f0-9]+)", self.headers.get("Cookie", "")); return m.group(1) if m else None

    def do_GET(self): self.route("GET")
    def do_POST(self): self.route("POST")

    def route(self, method):
        u = urllib.parse.urlsplit(self.path); p = u.path; q = urllib.parse.parse_qs(u.query)
        try:
            if p == "/login" and method == "GET": return self.html(SETUP if no_users() else LOGIN)
            if p == "/api/setup" and method == "POST": return self.primeiro_acesso()
            if p == "/manifest.webmanifest": return self.out(200, dumps(MANIFEST), "application/manifest+json; charset=utf-8")
            if p == "/icon.svg": return self.out(200, ICON, "image/svg+xml")
            if p == "/api/login" and method == "POST": return self.login()
            with SLOCK:
                s = SESS.get(self.sid())
                if s and s["exp"] > time.time(): s["exp"] = time.time() + 43200
                else: s = None
            if not s:
                if p.startswith("/api/"): return self.js({"error": "auth"}, 401)
                return self.out(302, b"", "text/plain", [("Location", "/login")])
            if p == "/api/logout":
                with SLOCK: SESS.pop(self.sid(), None)
                return self.js({"ok": 1}, extra=[("Set-Cookie", "sid=; Max-Age=0; Path=/")])
            if p == "/sync.js": return self.out(200, (RES / "sync.js").read_bytes(), "application/javascript; charset=utf-8")
            if p == "/api/state": return self.js(state({"name": s["name"], "roles": s["roles"], "caps": s["caps"], "role": ",".join(s["roles"])}))
            if p == "/api/events": return self.sse()
            if p == "/api/sync" and method == "POST":
                v = apply(self.body(), s["caps"])
                broadcast({"v": v, "by": s["name"], "cid": self.headers.get("X-CID", "")}); return self.js({"v": v})
            if p == "/api/nfe/map": return self.js({"map": kget("nfemap", {})})
            if p == "/api/nfe/entradas":
                with LOCK:
                    rows = db.execute("SELECT data,usuario,numero,serie,forn_nome,total,itens FROM entradas ORDER BY rowid DESC LIMIT 100").fetchall()
                return self.js([{"data": r[0], "usuario": r[1], "numero": r[2], "serie": r[3], "fornecedor": r[4], "total": r[5], "itens": len(json.loads(r[6]))} for r in rows])
            if p == "/api/nfe" and method == "POST":
                if not s["caps"]["stock"]: raise Err("Apenas Estoquista ou Administrador lança NF-e.")
                v, log = nfe_commit(self.body(), s["name"])
                broadcast({"v": v, "by": s["name"], "cid": self.headers.get("X-CID", "")}); return self.js({"v": v, "itens": log})
            if p == "/api/docs":
                if method == "GET": return self.js(docs_list(str((q.get("kind") or [""])[0]), s["caps"]))
                b = self.body(); r = docs_save(b, s)
                broadcast({"docs": b.get("kind"), "by": s["name"], "cid": self.headers.get("X-CID", "")}); return self.js(r)
            if p == "/api/impressora":
                if method == "GET": return self.js({"cfg": printer_cfg(), "perfis": escpos.PERFIS})
                if not s["caps"]["admin"]: raise Err("Apenas o administrador altera a impressora.")
                with LOCK: kset("impressora", escpos.limpar(self.body()))
                return self.js({"cfg": printer_cfg()})
            if p == "/api/impressoras":
                if not s["caps"]["admin"]: raise Err("Apenas o administrador lista as impressoras.")
                return self.js({"lista": escpos.listar()})
            if p == "/api/imprimir" and method == "POST":
                b = self.body(); cfg = printer_cfg(); emp = kget("empresa")
                if b.get("teste"):
                    if not s["caps"]["admin"]: raise Err("Apenas o administrador imprime a página de teste.")
                    data = escpos.teste(cfg, emp)
                elif isinstance(b.get("tx"), dict): data = escpos.montar(b["tx"], emp, cfg)
                else: raise Err("Registro de venda ausente.", 400)
                try: escpos.enviar(cfg, data)
                except OSError as e: raise Err(str(e), 502)
                return self.js({"ok": 1})
            if p == "/api/senha" and method == "POST": return self.senha(s)
            if p == "/api/users": return self.users(s, method)
            if p.startswith("/vendor/"):
                f = (VENDOR / p[len("/vendor/"):]).resolve()
                if VENDOR.resolve() in f.parents and f.is_file():
                    return self.out(200, f.read_bytes(), MIME.get(f.suffix, "application/octet-stream"))
            if p in ("/", "/index.html"): return self.html(page())
            self.out(404, "404", "text/plain")
        except Err as e: self.js({"error": str(e)}, e.code)
        except (BrokenPipeError, ConnectionResetError): pass
        except Exception as e:
            print("erro:", e)
            try: self.js({"error": "erro interno"}, 500)
            except Exception: pass

    def entrar(self, nome, roles):
        t = secrets.token_hex(24)
        with SLOCK: SESS[t] = {"name": nome, "roles": roles, "caps": caps(roles), "exp": time.time() + 43200}
        self.js({"ok": 1}, extra=[("Set-Cookie", f"sid={t}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200")])

    def login(self):
        b = self.body()
        with LOCK: r = db.execute("SELECT name,salt,hash,role FROM users WHERE name=?", (str(b.get("user") or ""),)).fetchone()
        if not r or not hmac.compare_digest(hpw(str(b.get("pass") or ""), r[1]), r[2]):
            time.sleep(0.7); return self.js({"error": "Usuário ou senha inválidos"}, 401)
        self.entrar(r[0], parse_roles(r[3]))

    def primeiro_acesso(self):
        """Primeiro acesso: cria o administrador (só no computador do servidor e só se ainda não existir usuário)."""
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            raise Err(f"Faça o primeiro acesso no computador onde o sistema está instalado (http://localhost:{PORT}).")
        b = self.body(); nome = str(b.get("user") or "").strip(); pw = str(b.get("pass") or "")
        if not re.fullmatch(r"[\w.\- ]{2,30}", nome) or len(pw) < MINPW:
            raise Err(f"Informe o nome do administrador (2 a 30 caracteres) e uma senha com {MINPW} ou mais caracteres.", 400)
        with LOCK:
            if not no_users(): raise Err("O administrador já foi criado. Entre com o seu usuário.", 409)
            set_user(nome, pw, ["admin"])
        self.entrar(nome, ["admin"])

    def senha(self, s):
        b = self.body()
        with LOCK: r = db.execute("SELECT salt,hash FROM users WHERE name=?", (s["name"],)).fetchone()
        if not r or not hmac.compare_digest(hpw(str(b.get("atual") or ""), r[0]), r[1]):
            time.sleep(0.7); raise Err("Senha atual incorreta.", 403)
        nova = str(b.get("nova") or "")
        if len(nova) < MINPW: raise Err(f"A nova senha precisa ter {MINPW} ou mais caracteres.", 400)
        salt = secrets.token_hex(12)
        with LOCK: db.execute("UPDATE users SET salt=?, hash=? WHERE name=?", (salt, hpw(nova, salt), s["name"]))
        self.js({"ok": 1})

    def users(self, s, method):
        if not s["caps"]["admin"]: raise Err("Apenas o administrador gerencia usuários.")
        if method == "GET":
            with LOCK: return self.js([{"name": r[0], "roles": parse_roles(r[1])} for r in db.execute("SELECT name,role FROM users ORDER BY rowid")])
        b = self.body(); nome = str(b.get("name") or b.get("del") or "").strip()
        if b.get("del"):
            if nome.lower() == s["name"].lower(): raise Err("Você não pode excluir o próprio usuário.", 400)
            with LOCK: db.execute("DELETE FROM users WHERE name=?", (nome,))
            with SLOCK:
                for t in [t for t, v in SESS.items() if v["name"].lower() == nome.lower()]: del SESS[t]
            return self.js({"ok": 1})
        roles, pw = parse_roles(b.get("roles")), str(b.get("pass") or "")
        if not re.fullmatch(r"[\w.\- ]{2,30}", nome): raise Err("Nome inválido (2 a 30 caracteres).", 400)
        if not roles: raise Err("Marque ao menos um perfil.", 400)
        with LOCK:
            ex = db.execute("SELECT 1 FROM users WHERE name=?", (nome,)).fetchone()
            if (not ex or pw) and len(pw) < MINPW: raise Err(f"A senha precisa ter {MINPW} ou mais caracteres.", 400)
            if ex and "admin" not in roles and not any("admin" in parse_roles(r[0]) for r in db.execute("SELECT role FROM users WHERE name<>?", (nome,))):
                raise Err("Deve existir ao menos um administrador.", 400)
            if ex and not pw: db.execute("UPDATE users SET role=? WHERE name=?", (",".join(roles), nome))
            else: set_user(nome, pw, roles)
        with SLOCK:
            for v in SESS.values():
                if v["name"].lower() == nome.lower(): v["roles"], v["caps"] = roles, caps(roles)
        self.js({"ok": 1})

    def sse(self):
        q = queue.Queue()
        with CL: CLIENTS.add(q)
        self.send_response(200); self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache"); self.end_headers(); self.close_connection = True
        try:
            self.wfile.write(b"retry: 2000\n\n"); self.wfile.flush()
            while True:
                try: d = q.get(timeout=25)
                except queue.Empty: d = b": ping\n\n"
                self.wfile.write(d); self.wfile.flush()
        except OSError: pass
        finally:
            with CL: CLIENTS.discard(q)

# ---------------------------------------------------------------- execução
def run():
    migrate_legacy()
    url = f"http://localhost:{PORT}"
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    except OSError:
        print("O Balcão Fácil já está em execução."); 
        if "--servidor" not in sys.argv: webbrowser.open(url)
        return
    srv.daemon_threads = True
    threading.Thread(target=backup_loop, daemon=True).start()
    if not (VENDOR / "tailwind.js").exists(): threading.Thread(target=vendor, daemon=True).start()   # recursos offline, 1ª vez
    print(f"\nBalcão Fácil rodando. Dados em: {DATA}\n  Neste PC:  {url}")
    if no_users(): print("  PRIMEIRO ACESSO: abra o endereço acima neste computador e crie a senha do administrador.")
    try:
        for ip in sorted({i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)} - {"127.0.0.1"}):
            print(f"  Na rede:   http://{ip}:{PORT}")
    except OSError: pass
    if "--servidor" not in sys.argv and not os.environ.get("BALCAO_NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try: srv.serve_forever()
    except KeyboardInterrupt: pass

def atalho():
    """Cria o atalho "Balcão Fácil" na Área de Trabalho (Windows ou Linux) apontando para este executável."""
    exe = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve()
    if os.name == "nt":
        ps = ('$d=[Environment]::GetFolderPath("Desktop");$s=(New-Object -ComObject WScript.Shell).CreateShortcut("$d\\Balcão Fácil.lnk");'
              f'$s.TargetPath="{exe}";$s.WorkingDirectory="{exe.parent}";$s.WindowStyle=7;$s.Description="Balcão Fácil";$s.Save()')
        subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", base64.b64encode(ps.encode("utf-16-le")).decode()], creationflags=0x08000000)
    else:
        try: desk = Path(subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True).stdout.strip() or Path.home() / "Desktop")
        except OSError: desk = Path.home() / "Desktop"
        desk.mkdir(parents=True, exist_ok=True); f = desk / "Balcão Fácil.desktop"
        f.write_text(f"[Desktop Entry]\nType=Application\nName=Balcão Fácil\nComment=Frente de caixa e estoque\nExec={exe}\nTerminal=true\nIcon=applications-office\n", "utf-8")
        f.chmod(0o755)
    print("Atalho criado na Área de Trabalho.")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "adduser":
        if len(sys.argv) < 4: sys.exit("uso: balcaofacil adduser NOME SENHA [perfis separados por vírgula: admin,financeiro,caixa,estoquista,vendedor]")
        set_user(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "caixa"); print("Usuário salvo.")
    elif cmd == "vendor": vendor()
    elif cmd == "atalho": atalho()
    else: run()
