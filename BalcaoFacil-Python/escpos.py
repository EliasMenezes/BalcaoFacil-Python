"""Impressão térmica ESC/POS (80 mm / 58 mm) por rede (TCP 9100) ou USB (spooler do Windows, CUPS ou dispositivo)."""
import os, re, socket, subprocess, textwrap, glob

PERFIS = {  # parâmetros-base; todos aceitam ESC/POS padrão. Ajuste "colunas" e "tabela" se necessário.
    "epson":      {"nome": "Epson TM-T20 / TM-T20X / TM-T88", "cols": 48},
    "elgin":      {"nome": "Elgin i7 / i8 / i9", "cols": 48},
    "bematech":   {"nome": "Bematech MP-4200 TH / MP-100S TH", "cols": 48},
    "daruma":     {"nome": "Daruma DR800 / DR700", "cols": 48},
    "tanca":      {"nome": "Tanca TP-650 / TP-620", "cols": 48},
    "sweda":      {"nome": "Sweda SI-300", "cols": 48},
    "controlid":  {"nome": "Control iD Print iD", "cols": 48},
    "generica80": {"nome": "Genérica ESC/POS 80 mm (Xprinter e similares)", "cols": 48},
    "generica58": {"nome": "Genérica ESC/POS 58 mm", "cols": 32},
}
CP = {"cp850": 2, "cp858": 19, "cp860": 3, "cp437": 0}      # ESC t n (tabelas de caracteres mais comuns no Brasil)
PADRAO = {"modo": "navegador", "perfil": "epson", "cols": 48, "tabela": "cp850", "corte": "gsv",
          "gaveta": False, "auto": False, "host": "", "porta": 9100, "usb": ""}

def limpar(b):
    c = dict(PADRAO)
    c["modo"] = b.get("modo") if b.get("modo") in ("navegador", "rede", "usb") else "navegador"
    c["perfil"] = b.get("perfil") if b.get("perfil") in PERFIS else "epson"
    c["cols"] = max(24, min(64, int(b.get("cols") or PERFIS[c["perfil"]]["cols"])))
    c["tabela"] = b.get("tabela") if b.get("tabela") in CP else "cp850"
    c["corte"] = b.get("corte") if b.get("corte") in ("gsv", "escm", "nenhum") else "gsv"
    c["gaveta"], c["auto"] = bool(b.get("gaveta")), bool(b.get("auto"))
    c["host"] = str(b.get("host") or "").strip()[:100]
    c["porta"] = max(1, min(65535, int(b.get("porta") or 9100)))
    c["usb"] = str(b.get("usb") or "").strip()[:200]
    return c

def _money(v): return "R$ " + f"{float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
def _q(v): return f"{float(v):g}".replace(".", ",")

class _Doc:
    def __init__(self, cfg):
        self.cols, self.enc = int(cfg["cols"]), cfg["tabela"]
        self.b = bytearray(b"\x1b@\x1bt" + bytes([CP[self.enc]]))
    def ln(self, s="", al=0, bold=False, big=False):
        self.b += b"\x1ba" + bytes([al]) + b"\x1bE" + bytes([bold]) + b"\x1d!" + bytes([0x11 if big else 0])
        self.b += str(s).encode(self.enc, "replace") + b"\n" + b"\x1d!\x00\x1bE\x00\x1ba\x00"
    def lr(self, l, r, big=False):
        w = self.cols // (2 if big else 1); l = l[:max(0, w - len(r) - 1)]
        self.ln(l + " " * (w - len(l) - len(r)) + r, bold=big, big=big)
    def wrap(self, s, **k):
        for p in textwrap.wrap(str(s), self.cols) or [""]: self.ln(p, **k)
    def sep(self): self.ln("-" * self.cols)
    def fim(self, cfg, abrir_gaveta=False):
        self.b += b"\n\n\n\n"
        if cfg["corte"] == "gsv": self.b += b"\x1dVB\x00"          # corte parcial com avanço
        elif cfg["corte"] == "escm": self.b += b"\x1bm"            # guilhotinas mais antigas
        if abrir_gaveta: self.b += b"\x1bp\x00\x19\xfa"
        return bytes(self.b)

def _cab(d, emp):
    e = emp or {}
    if e.get("nome"): d.wrap(e["nome"], al=1, bold=True)
    if e.get("cnpj"): d.ln("CNPJ: " + e["cnpj"], al=1)
    end = " - ".join(x for x in (e.get("endereco"), ("Tel: " + e["telefone"]) if e.get("telefone") else "") if x)
    if end: d.wrap(end, al=1)
    if any(e.get(k) for k in ("nome", "cnpj", "endereco", "telefone")): d.sep()

def montar(tx, emp, cfg):
    d, orc = _Doc(cfg), tx.get("type") == "ORCAMENTO"
    _cab(d, emp)
    d.ln("ORCAMENTO DE COMPRA (RESERVA)" if orc else "DOCUMENTO AUXILIAR DE VENDA (DAV)", al=1, bold=True)
    d.ln("*** SEM VALOR FISCAL ***", al=1); d.sep()
    d.wrap("Registro: " + str(tx.get("id", ""))); d.wrap("Data: " + str(tx.get("date", "")))
    d.wrap("Cliente: " + str(tx.get("cliente", ""))); d.wrap("Vendedor: " + str(tx.get("vendedor", ""))); d.sep()
    for it in tx.get("items") or []:
        p = it.get("product") or {}
        d.wrap(f"{p.get('id', '')} {p.get('description', '')}")
        extra = f"  desc {_money(it.get('discount'))}" if it.get("discount") else ""
        d.lr(f"  {_q(it.get('qty', 0))} x {_money(it.get('unitPrice'))}{extra}", _money(it.get("subtotal")))
    d.sep()
    d.lr("Subtotal", _money(tx.get("subtotal")))
    if tx.get("discount"): d.lr("Desconto", "-" + _money(tx.get("discount")))
    d.lr("TOTAL", _money(tx.get("total")), big=True)
    d.wrap("Pagamento: " + str(tx.get("paymentMethod", "")))
    if orc: d.ln("* ITENS RESERVADOS NO ESTOQUE *", al=1, bold=True)
    d.sep(); d.wrap((emp or {}).get("rodape") or "Obrigado pela preferencia!", al=1)
    return d.fim(cfg, abrir_gaveta=bool(cfg.get("gaveta")) and not orc)

def teste(cfg, emp):
    d = _Doc(cfg); _cab(d, emp)
    d.ln("TESTE DE IMPRESSAO", al=1, bold=True); d.sep()
    d.ln("Acentos: áéíóú âêô ãõ ç ÀÉÍÓÚ Ç"); d.ln("Moeda: " + _money(1234.5))
    d.ln(f"Colunas: {cfg['cols']}  Tabela: {cfg['tabela']}  Corte: {cfg['corte']}")
    d.ln("0123456789" * 6, ) if cfg["cols"] >= 60 else d.ln(("0123456789" * 7)[:cfg["cols"]])
    d.lr("Esquerda", "Direita"); d.lr("TOTAL", _money(99.9), big=True)
    d.ln("Se os acentos sairem errados, troque a", al=1); d.ln("tabela de caracteres nas configuracoes.", al=1)
    return d.fim(cfg)

def _win_raw(nome, dados):
    import ctypes
    from ctypes import wintypes
    sp = ctypes.WinDLL("winspool.drv", use_last_error=True)
    class DOC(ctypes.Structure):
        _fields_ = [("pDocName", wintypes.LPWSTR), ("pOutputFile", wintypes.LPWSTR), ("pDatatype", wintypes.LPWSTR)]
    h = wintypes.HANDLE()
    if not sp.OpenPrinterW(nome, ctypes.byref(h), None):
        raise OSError(f"Impressora '{nome}' não encontrada no Windows (erro {ctypes.get_last_error()}).")
    try:
        if not sp.StartDocPrinterW(h, 1, ctypes.byref(DOC("Balcao Facil", None, "RAW"))):
            raise OSError(f"O Windows recusou o trabalho de impressão (erro {ctypes.get_last_error()}).")
        sp.StartPagePrinter(h); n = wintypes.DWORD()
        ok = sp.WritePrinter(h, dados, len(dados), ctypes.byref(n))
        sp.EndPagePrinter(h); sp.EndDocPrinter(h)
        if not ok or n.value != len(dados): raise OSError("Falha ao enviar os dados à impressora.")
    finally: sp.ClosePrinter(h)

def _usb(nome, dados):
    if not nome: raise OSError("Escolha a impressora USB nas configurações.")
    if re.fullmatch(r"(?i)(COM|LPT)\d+", nome) and os.name == "nt":
        with open("\\\\.\\" + nome, "wb") as f: f.write(dados); return
    if os.name == "nt": return _win_raw(nome, dados)
    if nome.startswith("/dev/"):
        with open(nome, "wb") as f: f.write(dados); return
    try: subprocess.run(["lp", "-d", nome, "-o", "raw"], input=dados, check=True, capture_output=True, timeout=20)
    except FileNotFoundError: raise OSError("Comando 'lp' (CUPS) não encontrado.")
    except subprocess.CalledProcessError as e: raise OSError("CUPS recusou o trabalho: " + e.stderr.decode(errors="replace").strip())

def enviar(cfg, dados):
    if cfg.get("modo") == "rede":
        if not cfg.get("host"): raise OSError("Informe o IP da impressora nas configurações.")
        try:
            with socket.create_connection((cfg["host"], int(cfg.get("porta") or 9100)), timeout=5) as s: s.sendall(dados)
        except OSError as ex:
            raise OSError(f"Não foi possível falar com a impressora em {cfg['host']}:{cfg.get('porta') or 9100} ({ex.strerror or ex}). Confira o IP, a porta e se ela está ligada.")
    elif cfg.get("modo") == "usb": _usb(cfg.get("usb", ""), dados)
    else: raise OSError("Impressão direta desativada nas configurações.")

def listar():
    try:
        if os.name == "nt":
            out = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Printer | Select-Object -ExpandProperty Name"],
                                 capture_output=True, text=True, timeout=20, creationflags=0x08000000).stdout
        else:
            out = subprocess.run(["lpstat", "-e"], capture_output=True, text=True, timeout=10).stdout
    except Exception: out = ""
    nomes = [l.strip() for l in out.splitlines() if l.strip()]
    return nomes + ([] if os.name == "nt" else sorted(glob.glob("/dev/usb/lp*")))
