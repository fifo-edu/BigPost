from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from email.parser import BytesParser
from email.policy import default
from urllib.parse import urlparse, parse_qs
from urllib import request as urlrequest, error as urlerror
from xml.etree import ElementTree as ET
import sqlite3, json, hashlib, secrets, base64, datetime, os, re, shutil, mimetypes, io, csv, difflib
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.fernet import Fernet, InvalidToken

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get('AGF_DATA_DIR', str(ROOT / 'data')))
DB = DATA_DIR / 'agf_v7.db'
PORT = int(os.environ.get('PORT', '8780'))
SESS = {}
OWN_CNPJ_FIXED = '72819139000172'
DEFAULT_WINDOWS_ROOT = r'C:\Users\fifo_\OneDrive\Financeiro AGF'

CATEGORIES = [
'COFINS','PIS','13o SALARIO','ALIMENTACAO/REFEICAO/CESTA BASICA','ALUGUEIS','ASSISTÊNCIA MEDICA/ ODONTOLOGICA E SOCIAL',
'ASSOCIACOES E CONTRIBUICOES','COMBUSTIVEIS','CONDOMÍNIO','CONFRATERNIZACAO / BRINDES','CONSULTORIA E SERVICOS PROFISSIONAIS',
'CONTRIBUICOES A SINDICATO','COPA COZINHA E REFEITORIOS','CORREIOS E CORRESPONDENCIAS','CURSOS E TREINAMENTOS',
'DESCONTOS FINANCEIROS CONCEDIDOS','DESPESA COM AUTONOMO - SERV PRESTADOS','DESPESAS BANCARIAS','DESPESAS COM PESSOAL',
'DESPESAS FINANCEIRAS','DESPESAS GERAIS','DESPESAS NÃO OPERACIONAIS','DESPESAS OPERACIONAIS','DOACOES','ENERGIA ELETRICA',
'FERIAS','FGTS','IMPOSTOS E TAXAS','INDENIZACOES A TERCEIROS','INDENIZACOES E AVISO PREVIO','INDENIZACOES TRABALHISTA',
'INSS','INSS S/ PRO-LABORE','IOF-IMP S/ OP.FINANCEIRA','JUROS SOBRE EMPRESTIMOS E FINANCIAMENTOS','LOCACAO DE EQUIPAMENTOS',
'MANUTENÇÃO DE VEICULO','MANUTENCAO DO IMOBILIZADO','MANUTENCAO REDE/INFORMATICA','MANUTENCAO E CONSERVACAO PREDIAL',
'MANUTENCAO E REPARO','MATERIAIS DE CONSUMO','MATERIAL DE ESCRITORIO','MATERIAL DE LIMPEZA','MULTA E JUROS PAGOS',
'MULTAS FISCAIS/TRANSITO','OUTRAS DESPESAS','OUTRAS DESPESAS OPERACIONAIS','PEDAGIOS / ESTACIONAMENTOS','PERDAS C/CLIENTES',
'PERDAS OPERACIONAIS','PRESTADORES TERCEIRIZADOS PJ','PROCESSOS JUDICIAIS','PRO-LABORE','SALARIOS E ORDENADOS',
'SEGURANCA E MONITORAMENTO','SEGURO DE VIDA','SEGUROS','SERVICOS DE TRANSPORTES','SERVICOS PROFISSIONAIS CONTABEIS',
'SISTEMAS E SOFTWARES','TARIFA CARTAO DE CREDITO','TAXA DE FRANQUIA','TELEFONIA/ INTERNET/ PROVEDOR/ DOMÍNIO',
'UNIFORMES E EQUIP DE SEGURANCA','VALE TRANSPORTE','VIAGENS E REPRESENTACAOES','ADIANTAMENTO A EMPREGADOS',
'ADIANTAMENTO DE 13o SALARIO','ADIANTAMENTO DE FERIAS','ADIANTAMENTO DE FORNECEDORES','ADIANTAMENTO DE SALARIO',
'ADIANTAMENTOS A FORNECEDORES','CARTOES DE CREDITOS','CLIENTES DIVERSOS A RECEBER','DESCONTOS FINANCEIROS OBTIDOS',
'EMPRESA BRASILEIRA DE CORREIOS E   TELEGRAFOS','EMPRESTIMOS A COLABORADORES','ISS','JUROS RECEBIDOS',
'NIVALDO FRANCISCO DOS SANTOS','OUTRAS RECEITAS','OUTRAS RECEITAS OPERACIONAIS','OUTROS CREDITOS','PAGSEGURO',
'RECEITAS FINANCEIRAS','RENDIMENTO DE APLICACAO','VENDA DE SERVICOS']

ROLE_RANK = {'Usuário':1,'Operador':1,'Administrador':2,'Master':3}
ALL_ACCESS = ['dash','novo','pagar','receber','fluxo','dre','bp','canais','fiscal','notas_fiscais','docs','contratos','clientes','fornecedores','audit','export','relatorios']



LICENSE_PRIVATE=DATA_DIR/"license_private.pem"
LICENSE_PUBLIC=DATA_DIR/"license_public.pem"

def ensure_license_keys():
    if LICENSE_PRIVATE.exists() and LICENSE_PUBLIC.exists():
        return
    priv=Ed25519PrivateKey.generate()
    pub=priv.public_key()
    LICENSE_PRIVATE.write_bytes(priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()))
    LICENSE_PUBLIC.write_bytes(pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo))

def _license_b64(b):
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")

def _license_unb64(s):
    return base64.urlsafe_b64decode(s+"="*((4-len(s)%4)%4))

def sign_license(payload):
    ensure_license_keys()
    raw=json.dumps(payload,ensure_ascii=False,separators=(",",":"),sort_keys=True).encode("utf-8")
    priv=serialization.load_pem_private_key(LICENSE_PRIVATE.read_bytes(),password=None)
    sig=priv.sign(raw)
    return "FAGF1."+_license_b64(raw)+"."+_license_b64(sig)

def verify_license(code):
    try:
        prefix,payload64,sig64=code.strip().split(".",2)
        if prefix!="FAGF1":return {"valid":False,"error":"Formato de licença inválido"}
        raw=_license_unb64(payload64);sig=_license_unb64(sig64)
        ensure_license_keys()
        pub=serialization.load_pem_public_key(LICENSE_PUBLIC.read_bytes())
        pub.verify(sig,raw)
        payload=json.loads(raw.decode("utf-8"))
        exp=payload.get("expires_at")
        if exp and exp!="PERPETUA":
            if datetime.date.fromisoformat(exp)<datetime.date.today():
                return {"valid":False,"error":"Licença expirada","payload":payload}
        return {"valid":True,"payload":payload}
    except Exception as e:
        return {"valid":False,"error":"Licença inválida"}

SECRET_KEY_FILE=DATA_DIR/"secret.key"

def ensure_secret_key():
    """Chave simétrica (Fernet) usada só para criptografar segredos sensíveis
    guardados no banco: o certificado digital A1 (.pfx), a senha dele e o
    token de acesso do provedor de emissão fiscal. Fica fora do repositório
    (data/ não é versionado), igual às chaves de licença."""
    if SECRET_KEY_FILE.exists():
        return
    SECRET_KEY_FILE.write_bytes(Fernet.generate_key())

def encrypt_secret(raw_bytes):
    ensure_secret_key()
    return Fernet(SECRET_KEY_FILE.read_bytes()).encrypt(raw_bytes)

def decrypt_secret(token_bytes):
    if not token_bytes:return None
    ensure_secret_key()
    try:return Fernet(SECRET_KEY_FILE.read_bytes()).decrypt(bytes(token_bytes))
    except InvalidToken:return None

def current_company_profile():
    with db() as c:
        r=c.execute("select * from company_profile where id=1").fetchone()
    return dict(r) if r else {}

def current_license():
    code=get_setting("active_license","")
    return verify_license(code) if code else {"valid":False,"error":"Licença não instalada"}

# Esta implantação é de uma única empresa (não multi-tenant): a licença não
# precisa mais de uma tela para gerar/colar código — ela já nasce ativa,
# assinada com os dados reais da licenciada. Se um futuro Painel Master
# externo passar a emitir licenças para múltiplas instalações, isto pode ser
# substituído por uma licença recebida de lá.
DEFAULT_LICENSE_CUSTOMER_NAME="2V'S SERVIÇOS POSTAIS LTDA"
DEFAULT_LICENSE_TAX_ID="72.819.139/0001-72"
DEFAULT_LICENSE_MAX_USERS=50

def ensure_default_license():
    """Se ainda não houver uma licença ativa e válida nesta instalação, gera e
    ativa automaticamente uma licença perpétua assinada (chave Ed25519 já
    guardada em data/), sem nenhum passo manual. Também preenche Dados da
    Empresa (razão social/CNPJ) se ainda estiverem vazios, para não haver
    preenchimento duplicado do que a licença já contém. Idempotente: uma vez
    ativa, chamadas seguintes não fazem nada."""
    if current_license().get('valid'):
        return
    payload={
        'product':'Financeiro AGF',
        'license_id':secrets.token_hex(8).upper(),
        'customer_name':DEFAULT_LICENSE_CUSTOMER_NAME,
        'tax_id':DEFAULT_LICENSE_TAX_ID,
        'issued_at':datetime.date.today().isoformat(),
        'expires_at':'PERPETUA',
        'max_users':DEFAULT_LICENSE_MAX_USERS,
        'features':['financeiro']
    }
    code=sign_license(payload)
    with db() as c:
        c.execute('insert or ignore into issued_licenses(license_code,customer_name,tax_id,expires_at,max_users,features,created_at,created_by,revoked) values(?,?,?,?,?,?,?,?,0)',
                  (code,payload['customer_name'],payload['tax_id'],payload['expires_at'],payload['max_users'],json.dumps(payload['features'],ensure_ascii=False),now(),'Sistema (automático)'))
        row=c.execute('select legal_name,tax_id from company_profile where id=1').fetchone()
        if row and not (row['legal_name'] or '').strip():
            c.execute('update company_profile set legal_name=?,updated_at=? where id=1',(DEFAULT_LICENSE_CUSTOMER_NAME,now()))
        if row and not (row['tax_id'] or '').strip():
            c.execute('update company_profile set tax_id=?,updated_at=? where id=1',(DEFAULT_LICENSE_TAX_ID,now()))
    set_setting('active_license',code)

def current_fiscal_config():
    with db() as c:
        r=c.execute("select * from fiscal_config where id=1").fetchone()
    return dict(r) if r else {}

def fiscal_config_public(cfg=None):
    """Versão do fiscal_config segura para mandar ao frontend: nunca inclui o
    certificado, a senha ou o token em si — só o suficiente para a tela saber
    o que já está configurado e mostrar status/validade."""
    cfg=cfg if cfg is not None else current_fiscal_config()
    return {
        'cert_uploaded':bool(cfg.get('cert_pfx_enc')),
        'cert_filename':cfg.get('cert_filename') or '',
        'cert_uploaded_at':cfg.get('cert_uploaded_at') or '',
        'cert_expires_at':cfg.get('cert_expires_at') or '',
        'token_configured':bool(cfg.get('api_token_enc')),
        'provider':cfg.get('provider') or 'focusnfe',
        'environment':cfg.get('environment') or 'homologacao',
        'company_synced':bool(cfg.get('company_synced')),
        'regime_tributario':cfg.get('regime_tributario'),
        'inscricao_municipal':cfg.get('inscricao_municipal') or '',
        'codigo_municipio':cfg.get('codigo_municipio') or '',
        'item_lista_servico':cfg.get('item_lista_servico') or '',
        'codigo_tributario_municipio':cfg.get('codigo_tributario_municipio') or '',
        'aliquota_iss':cfg.get('aliquota_iss'),
        'optante_simples_nacional':bool(cfg.get('optante_simples_nacional',1)),
    }

FOCUS_BASE_URLS={'homologacao':'https://homologacao.focusnfe.com.br/v2','producao':'https://api.focusnfe.com.br/v2'}

class FocusError(Exception):
    def __init__(self,message,status=None,payload=None):
        super().__init__(message);self.status=status;self.payload=payload

def focus_request(method,path,token,body=None,query=None,timeout=30):
    """Chamada HTTP genérica à API da Focus NFe. Autenticação HTTP Basic com
    o token de acesso como usuário e senha em branco (padrão documentado da
    Focus NFe). Levanta FocusError em qualquer resposta que não seja 2xx,
    com o payload de erro (quando a Focus devolve JSON) anexado."""
    if not token:raise FocusError('Token de acesso da Focus NFe não configurado. Cadastre-o em Dados da Empresa > Certificado Digital / Integração Fiscal.')
    base=FOCUS_BASE_URLS.get((query or {}).pop('__environment__',None) or 'homologacao',FOCUS_BASE_URLS['homologacao'])
    url=base+path
    if query:
        qs='&'.join(f'{k}={v}' for k,v in query.items() if v is not None)
        if qs:url+=('&' if '?' in url else '?')+qs
    data=json.dumps(body,ensure_ascii=False).encode('utf-8') if body is not None else None
    auth=base64.b64encode((token+':').encode('utf-8')).decode('ascii')
    req=urlrequest.Request(url,data=data,method=method,headers={'Authorization':f'Basic {auth}','Content-Type':'application/json','Accept':'application/json'})
    try:
        with urlrequest.urlopen(req,timeout=timeout) as resp:
            raw=resp.read();ctype=resp.headers.get('Content-Type','')
            return json.loads(raw) if raw and 'json' in ctype else (json.loads(raw) if raw else {})
    except urlerror.HTTPError as e:
        raw=e.read()
        try:payload=json.loads(raw) if raw else {}
        except Exception:payload={'mensagem':raw.decode('utf-8','replace')}
        msg=payload.get('mensagem') or payload.get('erros') or f'Erro HTTP {e.code} na Focus NFe'
        raise FocusError(str(msg),status=e.code,payload=payload)
    except urlerror.URLError as e:
        raise FocusError(f'Não foi possível conectar à Focus NFe: {e.reason}')

def focus_environment(cfg):
    return cfg.get('environment') or 'homologacao'

def focus_token(cfg):
    return (decrypt_secret(cfg.get('api_token_enc')) or b'').decode('utf-8') or None

def focus_sync_company(cfg,profile,pfx_bytes=None,cert_password=None):
    """Cria (primeira vez) ou atualiza (já sincronizado) o cadastro da
    empresa na Focus NFe, incluindo o certificado A1 quando informado.
    Retorna o dict de resposta da Focus (contém o 'id' interno deles, que
    guardamos em fiscal_config.focus_empresa_id para as próximas atualizações)."""
    token=focus_token(cfg)
    body={
        'nome':profile.get('legal_name') or profile.get('trade_name') or '',
        'nome_fantasia':profile.get('trade_name') or '',
        'cnpj':digits(profile.get('tax_id')),
        'regime_tributario':int(cfg['regime_tributario']) if cfg.get('regime_tributario') else 3,
        'logradouro':profile.get('address') or '',
        'numero':'S/N',
        'bairro':profile.get('city') or '',
        'municipio':profile.get('city') or '',
        'cep':digits(profile.get('zip_code')) or '00000000',
        'uf':profile.get('state') or '',
        'email':profile.get('email') or '',
        'telefone':digits(profile.get('phone')) or '',
        'inscricao_municipal':cfg.get('inscricao_municipal') or '',
        'habilita_nfse':True,
    }
    if pfx_bytes:
        body['arquivo_certificado_base64']=base64.b64encode(pfx_bytes).decode('ascii')
        body['senha_certificado']=cert_password or ''
    q={'__environment__':focus_environment(cfg)}
    if cfg.get('focus_empresa_id'):
        return focus_request('PUT',f"/empresas/{cfg['focus_empresa_id']}",token,body=body,query=q)
    return focus_request('POST','/empresas',token,body=body,query=q)

def focus_emit_nfse(cfg,profile,ref,tomador,servico):
    token=focus_token(cfg)
    body={
        'data_emissao':datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S-03:00'),
        'natureza_operacao':'1',
        'optante_simples_nacional':bool(cfg.get('optante_simples_nacional',1)),
        'prestador':{'cnpj':digits(profile.get('tax_id')),'inscricao_municipal':cfg.get('inscricao_municipal') or ''},
        'tomador':tomador,
        'servico':servico,
    }
    q={'ref':ref,'__environment__':focus_environment(cfg)}
    return focus_request('POST','/nfse',token,body=body,query=q)

def focus_consult_nfse(cfg,ref):
    token=focus_token(cfg)
    return focus_request('GET',f'/nfse/{ref}',token,query={'__environment__':focus_environment(cfg)})

def focus_cancel_nfse(cfg,ref,justificativa):
    token=focus_token(cfg)
    body={'justificativa':justificativa} if justificativa else None
    return focus_request('DELETE',f'/nfse/{ref}',token,body=body,query={'__environment__':focus_environment(cfg)})

def extract_cert_expiry(pfx_bytes,password):
    """Lê a data de validade (not_valid_after) direto do certificado A1,
    sem depender do usuário informar manualmente. Retorna '' se não
    conseguir abrir o arquivo com a senha informada (o chamador decide se
    isso é motivo de erro ou só de aviso)."""
    try:
        _,cert,_=pkcs12.load_key_and_certificates(pfx_bytes,password.encode('utf-8') if password else None)
        if not cert:return ''
        dt=getattr(cert,'not_valid_after_utc',None) or cert.not_valid_after
        return dt.date().isoformat()
    except Exception:
        return ''

def now(): return datetime.datetime.now().isoformat(timespec='seconds')
def digits(s): return re.sub(r'\D','',str(s or ''))
def fmt_cnpj(s):
    d=digits(s)
    return f'{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}' if len(d)==14 else str(s or '')
def normalize_date(v):
    if not v:return ''
    s=str(v)
    m=re.search(r'(\d{2})[/-](\d{2})[/-](\d{4})',s)
    if m:return f'{m.group(3)}-{m.group(2)}-{m.group(1)}'
    m=re.search(r'(\d{4})-(\d{2})-(\d{2})',s)
    return m.group(0) if m else ''
def date_br(v):
    s=str(v or '')
    m=re.search(r'(\d{4})-(\d{2})-(\d{2})',s)
    return f'{m.group(3)}/{m.group(2)}/{m.group(1)}' if m else ''
EMAIL_RX = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
def valid_email(v):
    return bool(EMAIL_RX.match(str(v or '').strip()))
def valid_password(p):
    p = str(p or '')
    if not (4 <= len(p) <= 15): return False
    if not re.search(r'[A-Z]', p): return False
    if not re.search(r'[a-z]', p): return False
    if not re.search(r'[0-9]', p): return False
    if not re.search(r'[^A-Za-z0-9]', p): return False
    return True
PASSWORD_RULE_MSG = 'A senha deve ter de 4 a 15 caracteres e conter letra maiúscula, letra minúscula, número e caractere especial.'
def month_add(value, months):
    d=datetime.date.fromisoformat(normalize_date(value));n=d.month-1+months
    y=d.year+n//12;m=n%12+1
    last=(datetime.date(y+(m==12),1 if m==12 else m+1,1)-datetime.timedelta(days=1)).day
    return datetime.date(y,m,min(d.day,last)).isoformat()
def ph(p,s=None):
    s=s or secrets.token_bytes(16); d=hashlib.pbkdf2_hmac('sha256',p.encode('utf-8'),s,180000)
    return base64.b64encode(s).decode()+':'+base64.b64encode(d).decode()
def pv(p,h):
    try:
        a,b=h.split(':'); calc=ph(p,base64.b64decode(a)).split(':')[1]; return secrets.compare_digest(calc,b)
    except:return False
def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def log_event(user,action,details):
    payload=json.dumps(details,ensure_ascii=False,default=str)
    with db() as c:c.execute('insert into audit(created_at,user,action,details) values(?,?,?,?)',(now(),user,action,payload))
    try:
        (ROOT/'logs').mkdir(exist_ok=True)
        with (ROOT/'logs'/'audit.log').open('a',encoding='utf-8') as f:f.write(f'{now()}\t{user}\t{action}\t{payload}\n')
    except:pass

def get_setting(k,default=''):
    with db() as c:r=c.execute('select value from settings where key=?',(k,)).fetchone()
    return r['value'] if r else default
def set_setting(k,v):
    with db() as c:c.execute('insert into settings(key,value) values(?,?) on conflict(key) do update set value=excluded.value',(k,str(v)))
def own_cnpjs():
    try: vals=json.loads(get_setting('company_tax_ids',json.dumps([OWN_CNPJ_FIXED])))
    except: vals=[OWN_CNPJ_FIXED]
    vals={digits(x) for x in vals if digits(x)}; vals.add(OWN_CNPJ_FIXED); return vals

def archive_root():
    configured=get_setting('document_root',DEFAULT_WINDOWS_ROOT)
    env_root=os.environ.get('AGF_ARCHIVE_DIR')
    if env_root:return Path(env_root)
    if os.name=='nt':return Path(configured)
    return DATA_DIR/'archive'
def ensure_archive_structure():
    r=archive_root()
    for p in ['01 - Documentos/Clientes','01 - Documentos/Fornecedores','02 - Importacoes/XML','02 - Importacoes/PDF','03 - Comprovantes','04 - Relatorios','05 - Exportacoes','06 - Logs','07 - Documentos Gerais','08 - Contratos','99 - Temporarios']:(r/p).mkdir(parents=True,exist_ok=True)
    return r

def init():
    DB.parent.mkdir(parents=True,exist_ok=True)
    seed=ROOT/'data_seed'/'agf_v7.db'
    if not DB.exists() and seed.exists():
        shutil.copy2(seed,DB)
    with db() as c:
        c.executescript('''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,display_name TEXT,role TEXT,password_hash TEXT,active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY,name TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS parties(id INTEGER PRIMARY KEY,tax_id TEXT UNIQUE,name TEXT,address TEXT,classification TEXT NOT NULL,category_id INTEGER NOT NULL,party_type TEXT NOT NULL CHECK(party_type IN('Cliente','Fornecedor','Ambos')),folder_scope TEXT DEFAULT '',updated_at TEXT);
CREATE TABLE IF NOT EXISTS transactions(id INTEGER PRIMARY KEY,type TEXT,status TEXT,tax_id TEXT,party_name TEXT,issue_date TEXT,due_date TEXT,classification TEXT,category TEXT,amount REAL,document_no TEXT,notes TEXT,source TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,created_at TEXT,user TEXT,action TEXT,details TEXT);
CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY,created_at TEXT,tax_id TEXT,party_name TEXT,doc_type TEXT,original_name TEXT,stored_path TEXT,transaction_id INTEGER);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS channels(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT UNIQUE NOT NULL,opening_balance REAL,opening_balance_set INTEGER NOT NULL DEFAULT 0,active INTEGER NOT NULL DEFAULT 1,created_at TEXT);
CREATE TABLE IF NOT EXISTS company_profile(id INTEGER PRIMARY KEY CHECK(id=1),legal_name TEXT,trade_name TEXT,tax_id TEXT,email TEXT,phone TEXT,address TEXT,city TEXT,state TEXT,zip_code TEXT,updated_at TEXT);
CREATE TABLE IF NOT EXISTS issued_licenses(id INTEGER PRIMARY KEY AUTOINCREMENT,license_code TEXT UNIQUE,customer_name TEXT,tax_id TEXT,expires_at TEXT,max_users INTEGER,features TEXT,created_at TEXT,created_by TEXT,revoked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS contract_categories(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT UNIQUE NOT NULL,created_at TEXT,created_by TEXT);
CREATE TABLE IF NOT EXISTS contracts(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,category_id INTEGER,counterparty TEXT,tax_id TEXT,description TEXT,start_date TEXT,first_due_date TEXT,amount REAL,installments INTEGER,movement_type TEXT,classification TEXT,transaction_category TEXT,original_name TEXT,stored_path TEXT,created_at TEXT,created_by TEXT);
CREATE TABLE IF NOT EXISTS deleted_transactions(id INTEGER PRIMARY KEY AUTOINCREMENT,transaction_id INTEGER,transaction_json TEXT,reason TEXT,deleted_at TEXT,deleted_by TEXT);
CREATE TABLE IF NOT EXISTS fiscal_config(id INTEGER PRIMARY KEY CHECK(id=1),cert_pfx_enc BLOB,cert_password_enc BLOB,cert_filename TEXT,cert_uploaded_at TEXT,cert_expires_at TEXT,provider TEXT DEFAULT 'focusnfe',api_token_enc BLOB,environment TEXT DEFAULT 'homologacao',company_synced INTEGER NOT NULL DEFAULT 0,focus_empresa_id TEXT,regime_tributario INTEGER,inscricao_municipal TEXT,codigo_municipio TEXT,item_lista_servico TEXT,codigo_tributario_municipio TEXT,aliquota_iss REAL,optante_simples_nacional INTEGER NOT NULL DEFAULT 1,updated_at TEXT,updated_by TEXT);
CREATE TABLE IF NOT EXISTS nfse_notes(id INTEGER PRIMARY KEY AUTOINCREMENT,ref TEXT UNIQUE,transaction_id INTEGER,tomador_tax_id TEXT,tomador_name TEXT,valor REAL,discriminacao TEXT,status TEXT,numero TEXT,codigo_verificacao TEXT,url_pdf TEXT,caminho_xml TEXT,erro_mensagem TEXT,created_at TEXT,created_by TEXT,updated_at TEXT);
CREATE TABLE IF NOT EXISTS fiscal_layout_templates(id INTEGER PRIMARY KEY AUTOINCREMENT,doc_type TEXT NOT NULL,signature TEXT NOT NULL,skeleton_sample TEXT,fields_json TEXT NOT NULL,use_count INTEGER NOT NULL DEFAULT 0,created_at TEXT,created_by TEXT,updated_at TEXT,UNIQUE(doc_type,signature));

''')
        if not c.execute("select 1 from users where lower(username)='fifo'").fetchone():c.execute("insert into users(username,display_name,role,password_hash,active) values('Fifo','Fifo','Master',?,1)",(ph('2010'),))
        for x in CATEGORIES:c.execute('insert or ignore into categories(name) values(?)',(x,))
        c.execute('insert or ignore into settings(key,value) values(?,?)',('company_tax_ids',json.dumps([OWN_CNPJ_FIXED])))
        c.execute('insert or ignore into settings(key,value) values(?,?)',('document_root',DEFAULT_WINDOWS_ROOT))
        txcols={r['name'] for r in c.execute('pragma table_info(transactions)').fetchall()}
        if 'channel_id' not in txcols:c.execute('alter table transactions add column channel_id INTEGER')
        if 'contract_id' not in txcols:c.execute('alter table transactions add column contract_id INTEGER')
        ucols={r['name'] for r in c.execute('pragma table_info(users)').fetchall()}
        if 'permissions' not in ucols:c.execute("alter table users add column permissions TEXT DEFAULT '[]'")
        if 'failed_attempts' not in ucols:c.execute('alter table users add column failed_attempts INTEGER DEFAULT 0')
        if 'locked' not in ucols:c.execute('alter table users add column locked INTEGER DEFAULT 0')
        chcols={r['name'] for r in c.execute('pragma table_info(channels)').fetchall()}
        if 'accounting_code' not in chcols:c.execute("alter table channels add column accounting_code TEXT DEFAULT ''")
        fccols={r['name'] for r in c.execute('pragma table_info(fiscal_config)').fetchall()}
        if 'focus_empresa_id' not in fccols:c.execute('alter table fiscal_config add column focus_empresa_id TEXT')
        # Categorias de contrato não são mais pré-cadastradas: o usuário cria a sua própria lista
        # (via "Nova categoria abaixo de Contratos"), assim como clientes e fornecedores.
        for ch in ('Itaú','Banco do Brasil','Cash'):
            c.execute('insert or ignore into channels(name,opening_balance,opening_balance_set,active,created_at) values(?,NULL,0,1,?)',(ch,now()))
        c.execute("insert or ignore into company_profile(id,legal_name,trade_name,tax_id,email,phone,address,city,state,zip_code,updated_at) values(1,'','','','','','','','','',?)",(now(),))
        c.execute("insert or ignore into fiscal_config(id,provider,environment,company_synced,optante_simples_nacional,updated_at) values(1,'focusnfe','homologacao',0,1,?)",(now(),))
    ensure_license_keys();ensure_secret_key();ensure_default_license()

def remove_known_fictitious_transactions():
    """Remove somente a carga fictícia original, sem tocar em uma base divergente."""
    columns=('id','type','status','tax_id','party_name','issue_date','due_date','classification','category','amount','document_no','notes','source','created_at','channel_id')
    with db() as c:
        rows=c.execute('select '+','.join(columns)+' from transactions order by id').fetchall()
        if len(rows)!=56:return False
        payload=[{key:row[key] for key in columns} for row in rows]
        digest=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
        if digest!='55108f6d43f77ece0d94ac003763fc93d3750741a5847b3f5a4757c3037767f4':return False
        c.execute('delete from transactions')
        c.execute("delete from sqlite_sequence where name='transactions'")
    return True



CNPJ_RX=re.compile(r'(?<!\d)(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})(?!\d)')

def clean_text(s):
    s=(s or '').replace('\xa0',' '); s=re.sub(r'[ \t]+',' ',s); s=re.sub(r'\n{3,}','\n\n',s); return s.strip()
def money_br(s):
    try:return float(str(s).replace('.','').replace(',','.'))
    except:return 0.0

def parse_danfe(text):
    t=clean_text(text); out={'document_kind':'NF-e','warnings':[]}
    m=re.search(r'\bNF[\-\s]?e\b\s*(?:\n|\s)*(?:N[ºo°\.]?\s*)?([0-9][0-9\.\-]{2,20})',t,re.I)
    if not m:m=re.search(r'\bN[ºo°\.]?\s*([0-9]{1,3}(?:\.[0-9]{3}){1,4})',t,re.I)
    if m:out['document_no']=re.sub(r'\D','',m.group(1))
    md=re.search(r'DESTINAT[ÁA]RIO\s*/\s*REMETENTE',t,re.I); before=t[:md.start()] if md else t; dest=t[md.end():] if md else ''
    m=re.search(r'Recebemos\s+de\s+(.{2,160}?)(?:\s+os\s+produtos|\s+os\s+servi[cç]os)',t,re.I|re.S)
    if m:out['provider_name']=re.sub(r'\s+',' ',m.group(1)).strip(' :-')
    taxes=[fmt_cnpj(x.group(1)) for x in CNPJ_RX.finditer(before)]
    if taxes:out['provider_tax_id']=taxes[-1]
    streets=list(re.finditer(r'((?:AVENIDA|AV\.|RUA|R\.|RODOVIA|ROD\.|ESTRADA|ALAMEDA|PRA[CÇ]A|TRAVESSA)\s+[^\n]{3,140})',before,re.I))
    if streets:
        st=streets[-1]; parts=[st.group(1).strip()]; tail=before[st.end():st.end()+180]
        for ln in [x.strip() for x in tail.splitlines() if x.strip()][:3]:
            if any(k in ln.lower() for k in ('chave de acesso','nº ','serie','série','danfe')):break
            parts.append(ln)
        out['provider_address']=' | '.join(parts[:3])
    mt=re.search(r'(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})',dest)
    if mt:
        out['taker_tax_id']=fmt_cnpj(mt.group(1)); tail=dest[mt.end():mt.end()+220]
        mm=re.search(r'\s*([^\n]{3,160}?)(?=\s+\d{2}/\d{2}/\d{4}|\n)',tail,re.I)
        if mm:out['taker_name']=re.sub(r'\s+',' ',mm.group(1)).strip(' :-')
    ma=re.search(r'Endere[cç]o[^\n]*\n([^\n]{5,220})',dest,re.I)
    if ma:out['taker_address']=re.sub(r'\s+',' ',ma.group(1)).strip()
    mi=re.search(r'(?:Data da emiss[aã]o|Emiss[aã]o)\s*[:]?[^\d]{0,10}(\d{2}/\d{2}/\d{4})',t,re.I)
    if not mi:mi=re.search(r'Emiss[aã]o:\s*(\d{2}/\d{2}/\d{4})',t,re.I)
    if mi:out['issue_date']=normalize_date(mi.group(1))
    mv=re.search(r'Valor\s+total\s+da\s+nota',t,re.I)
    if mv:
        vals=re.findall(r'(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})',t[mv.end():mv.end()+260])
        if vals:out['amount']=money_br(vals[-1])
    if not out.get('amount'):
        mm=re.search(r'Valor\s+total\s*:\s*R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})',t,re.I)
        if mm:out['amount']=money_br(mm.group(1))
    out=classify_fiscal(out)
    return enrich_with_layout_learning('nfe',t,out,['tax_id','party_name','amount','document_no'])

def parse_nfse(text):
    t=clean_text(text);out={'document_kind':'NFS-e','warnings':[]}
    # semantic sections, position independent. A busca do marcador de parada começa
    # só depois do fim da linha do próprio rótulo, para não se autocolidir quando o
    # rótulo de abertura contém uma das palavras de parada (ex.: "TOMADOR DE SERVIÇOS"
    # contém "Serviços", que também é usado para encerrar a seção do tomador).
    def section(labelset,stopset):
        low=t.lower();starts=[]
        for lab in labelset:
            p=low.find(lab.lower())
            if p>=0:starts.append((p,len(lab)))
        if not starts:return ''
        p,l=min(starts)
        line_end=t.find('\n',p+l); scan_from=line_end+1 if line_end>=0 else p+l
        ends=[low.find(x.lower(),scan_from) for x in stopset]; ends=[x for x in ends if x>p]
        return t[p:min(ends) if ends else min(len(t),p+1600)]
    prov=section(['Prestador do Serviço','Prestador de Serviço','Emitente'],['Tomador do Serviço','Tomador','Adquirente','Discriminação','Valores'])
    tak=section(['Tomador do Serviço','Tomador','Adquirente'],['Discriminação','Valores','Serviços'])
    # Cabeçalho do documento (do início até o bloco do tomador): em alguns leiautes municipais
    # (ex.: Jundiaí/SHARMAQ) o CNPJ e o endereço do prestador saem, na extração do PDF, ANTES
    # do rótulo "PRESTADOR DE SERVIÇOS" — por isso são buscados também nesta faixa mais ampla.
    low_full=t.lower(); tp=low_full.find('tomador')
    header=t[:tp] if tp>0 else t
    def tax(sec):
        m=CNPJ_RX.search(sec);return fmt_cnpj(m.group(1)) if m else ''
    def name(sec):
        # Em alguns leiautes o rótulo "Nome/Razão Social:" vem colado sem espaço/quebra
        # de linha ao campo anterior (ex.: "...Inscrição Municipal: 49051Nome/Razão Social: X").
        # Por isso localizamos a posição exata do rótulo dentro da linha, em vez de dividir
        # a linha inteira no primeiro ":"/"-" (que pegaria o rótulo errado).
        lines=[x.strip() for x in sec.splitlines() if x.strip()]
        lab_rx=re.compile(r'raz[aã]o\s+social\s*[:\-]?\s*',re.I)
        for i,x in enumerate(lines):
            lm=lab_rx.search(x)
            if lm:
                val=x[lm.end():].strip()
                if not val:
                    val=lines[i+1] if i+1<len(lines) else ''
                # Corta se outro rótulo vier colado logo em seguida, sem separador.
                stop=re.search(r'\s*(?:Endere[çc]o|Complemento|Bairro|Munic[íi]pio|UF|CEP|Telefone|Fone|E-?mail|Inscri[çc][ãa]o)\s*[:]',val,re.I)
                if stop:val=val[:stop.start()].strip()
                if val:return val
        for x in lines[1:8]:
            if len(x)>3 and not CNPJ_RX.search(x) and not any(k in x.lower() for k in ('prestador','tomador','cnpj','cpf','endereço','endereco')):return x
        return ''
    def address(sec):
        # Endereço completo: rua/número/bairro/CEP + complemento + Município/UF, cada dado
        # buscado no seu próprio campo/rótulo quando existir; com fallback por palavra-chave
        # de logradouro para leiautes que não rotulam "Endereço:" explicitamente.
        parts=[]
        m=re.search(r'Endere[cç]o\s*[:]?\s*([^\n]{4,200})',sec,re.I)
        if m:
            street=re.split(r'\s+(?:Telefone|Fone|Munic[íi]pio|UF)\s*:',m.group(1).strip(),1)[0]
            street=re.sub(r'\s+',' ',street).strip()
            if street:parts.append(street)
        else:
            sm=re.search(r'((?:AVENIDA|AV\.?|RUA|R\.|RODOVIA|ROD\.|ESTRADA|ALAMEDA|PRA[CÇ]A|TRAVESSA)\s+[^\n]{3,140})',sec,re.I)
            if sm:
                lines=[re.sub(r'\s+',' ',sm.group(1)).strip()]
                for ln in [x.strip() for x in sec[sm.end():sm.end()+220].splitlines() if x.strip()][:2]:
                    low2=ln.lower()
                    if any(k in low2 for k in ('prestador','tomador','razão social','razao social','fone:','telefone:','e-mail','inscrição','inscricao','cnpj')):break
                    lines.append(ln)
                parts.append(' - '.join(lines))
        mc=re.search(r'Complemento\s*[:]?\s*([^\n]{1,80})',sec,re.I)
        if mc:
            comp=re.split(r'\s+(?:Telefone|Munic[íi]pio|UF)\s*:',mc.group(1).strip(),1)[0].strip()
            if comp:parts.append(comp)
        mm=re.search(r'Munic[íi]pio\s*[:]?\s*([^\n]{2,60}?)(?=\s+UF\s*:|\s+e-?mail|\n|$)',sec,re.I)
        mu=re.search(r'\bUF\s*[:]?\s*([A-Z]{2})\b',sec)
        if mm or mu:
            cu=mm.group(1).strip() if mm else ''
            if mu:cu=(cu+' - '+mu.group(1)) if cu else mu.group(1)
            if cu:parts.append(cu)
        return ' - '.join(p for p in parts if p)
    out['provider_tax_id']=tax(header) or tax(prov);out['provider_name']=name(prov);out['provider_address']=address(header) or address(prov)
    out['taker_tax_id']=tax(tak);out['taker_name']=name(tak);out['taker_address']=address(tak)
    # Número da nota: em alguns leiautes o número sai ANTES do rótulo "Número da Nota" na
    # extração do PDF (célula de tabela em ordem diferente da visual); testa os dois sentidos
    # antes de cair no padrão genérico "NFS-e Nº ..." (que evita capturar paginação "NFS-e 1/1").
    m=re.search(r'([0-9]{3,20})\s*(?:Número|Numero)\s+da\s+Nota',t,re.I)
    if not m:m=re.search(r'(?:Número|Numero)\s+da\s+Nota\s*[:]?\s*\n?\s*([0-9]{3,20})',t,re.I)
    if not m:m=re.search(r'(?:NFS-e|NFSe)\s*(?:N[ºo°\.]*)?\s*([0-9]{3,20})(?!\s*/)',t,re.I)
    if m:out['document_no']=m.group(1)
    mi=re.search(r'(?:Data\s+e\s+Hora\s+de\s+Emiss[aã]o|Data de Emiss[aã]o|Emiss[aã]o)\s*[:]?[^\d]{0,15}(\d{2}/\d{2}/\d{4})',t,re.I)
    if mi:out['issue_date']=normalize_date(mi.group(1))
    for lab in ['Valor Líquido','Valor Liquido','Valor dos Serviços','Valor dos Servicos','Valor Total da Nota','Valor a Pagar']:
        m=re.search(re.escape(lab)+r'[^\d]{0,90}(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})',t,re.I)
        if m:out['amount']=money_br(m.group(1));break
    # Discriminação dos serviços -> vai para o campo Observação do lançamento.
    md=re.search(r'DISCRIMINA[ÇC][ÃA]O\s+DOS\s+SERVI[ÇC]OS',t,re.I)
    if md:
        stop=re.search(r'C[óo]digo\s+Servi[çc]o|TRIBUTOS\s+FEDERAIS|Base\s+de\s+C[áa]lculo|VALOR\s+TOTAL\s+DA\s+NOTA',t[md.end():],re.I)
        chunk=t[md.end():md.end()+(stop.start() if stop else 1200)]
        desc=re.sub(r'\n{2,}','\n',chunk).strip()
        if desc:out['service_description']=desc
    out=classify_fiscal(out)
    return enrich_with_layout_learning('nfse',t,out,['tax_id','party_name','amount','document_no'])

def classify_fiscal(out):
    pt=digits(out.get('provider_tax_id')); own=own_cnpjs()
    if pt and pt in own:
        out.update({'direction':'Emitida pela empresa','type':'Receita','party_type':'Cliente','tax_id':out.get('taker_tax_id',''),'party_name':out.get('taker_name',''),'party_address':out.get('taker_address','')})
    else:
        out.update({'direction':'Recebida de fornecedor','type':'Despesa','party_type':'Fornecedor','tax_id':out.get('provider_tax_id',''),'party_name':out.get('provider_name',''),'party_address':out.get('provider_address','')})
    if out.get('service_description'):out['notes']=out['service_description']
    required=['tax_id','party_name','amount','document_no']
    missing=[x for x in required if not out.get(x)]
    if missing:out['warnings'].append('Conferir campos: '+', '.join(missing))
    out['confidence']=max(20,100-len(missing)*20)
    return out

def is_boleto_text(txt):
    # Heurística de detecção de boleto: presença de linha digitável (44-48 dígitos)
    # combinada com termos típicos de cobrança bancária, e ausência de marcadores de NF-e/NFS-e.
    if re.search(r'DANFE|Documento Auxiliar da Nota Fiscal|\bNF-e\b|NFS-e|NFSe|Nota Fiscal de Servi',txt,re.I):
        return False
    has_barcode=bool(re.search(r'(?<!\d)(?:\d[ .-]?){44,48}(?!\d)',txt))
    has_boleto_terms=bool(re.search(r'ficha de compensa|linha digit[aá]vel|c[oó]digo de barras|benefici[aá]rio|cedente|sacado|nosso n[úu]mero|boleto',txt,re.I))
    return has_barcode and has_boleto_terms

# --- Aprendizado de leiaute fiscal (NF-e/NFS-e/Boleto/XML) ---------------------------------
# Cada prefeitura/banco/emissor tem seu próprio modelo de documento. Quando os interpretadores
# acima (parse_danfe/parse_nfse/parse_boleto_text/parse_xml) não conseguem extrair os campos
# obrigatórios, tentamos nesta ordem: (1) um modelo já aprendido antes para um leiaute igual ou
# muito parecido; (2) pedir à IA (Anthropic) para extrair os campos, se houver uma chave
# cadastrada; (3) se nada funcionar, devolver o texto bruto para o usuário marcar os campos na
# tela — o que vira automaticamente um novo modelo aprendido para a próxima vez.
ANTHROPIC_MODEL='claude-3-5-haiku-20241022'
DOC_KIND_LABELS={'nfe':'NF-e (DANFE)','nfse':'NFS-e','boleto':'Boleto','xml_nfe':'XML Fiscal (NF-e)','xml_nfse':'XML Fiscal (NFS-e)'}
FISCAL_FIELD_LABELS={
    'tax_id':'CNPJ ou CPF da contraparte (cliente/fornecedor/prestador/tomador — não da própria empresa emitente, quando dá para identificar)',
    'party_name':'Nome ou razão social da contraparte',
    'amount':'Valor total do documento (número; use ponto decimal, ex.: 1234.56)',
    'document_no':'Número do documento/nota',
    'issue_date':'Data de emissão (formato DD/MM/AAAA)',
    'due_date':'Data de vencimento (formato DD/MM/AAAA)',
    'barcode_line':'Linha digitável do boleto (somente dígitos, com ou sem pontos/espaços)',
}

def text_skeleton(text):
    """Normaliza o texto extraído para um 'esqueleto' que representa o leiaute (rótulos e
    estrutura) sem os valores variáveis (números, nomes, endereços, datas) — usado para
    reconhecer se um documento novo veio do mesmo modelo/cidade/banco de um já aprendido antes.
    Uma linha 'Rótulo: valor' vira 'Rótulo: <V>' (o valor em si não entra no esqueleto); uma
    linha só de rótulo/estrutura (maiúsculas, ou só números/símbolos) é mantida com os dígitos
    trocados por '#'; qualquer outro texto livre (nomes, endereços em linha própria) vira um
    marcador genérico — assim dois documentos do mesmo modelo com dados diferentes (nomes,
    valores, datas diferentes) produzem o mesmo esqueleto."""
    out=[];prev_filler=False
    for line in (text or '').split('\n'):
        s=line.strip()
        if not s:continue
        m=re.match(r'^([^:]{1,50}:)\s*(.+)$',s)
        if m:
            out.append(re.sub(r'\d','#',m.group(1))+' <V>');prev_filler=False;continue
        norm=re.sub(r'\d','#',s)
        if len(s)<=60 and (s.upper()==s or re.fullmatch(r'[#/.\-, ]+',norm) is not None):
            out.append(norm);prev_filler=False
        elif not prev_filler:
            out.append('<TEXTO>');prev_filler=True
    return '\n'.join(out)

def layout_signature(skeleton):
    return hashlib.sha256(skeleton[:4000].encode('utf-8')).hexdigest()

def find_layout_template(c,doc_type,signature,skeleton):
    row=c.execute('select * from fiscal_layout_templates where doc_type=? and signature=?',(doc_type,signature)).fetchone()
    if row:return dict(row)
    best=None;best_ratio=0.0
    for cand in c.execute('select * from fiscal_layout_templates where doc_type=?',(doc_type,)).fetchall():
        ratio=difflib.SequenceMatcher(None,skeleton[:4000],(cand['skeleton_sample'] or '')[:4000]).ratio()
        if ratio>best_ratio:best_ratio=ratio;best=cand
    return dict(best) if best and best_ratio>=0.88 else None

def derive_field_rule(raw_text,start,end):
    # A âncora "before" usa só a LINHA atual até o valor marcado (normalmente "Rótulo: "), nunca
    # um número fixo de caracteres — um recuo fixo podia invadir a linha anterior e capturar
    # parte de OUTRO valor variável (ex.: o CNPJ ou a data do campo anterior), o que nunca bate
    # em um documento diferente. Se a linha do valor não tiver rótulo próprio (rótulo e valor em
    # linhas separadas), usa a linha anterior inteira como contexto.
    line_start=raw_text.rfind('\n',0,start)+1
    before=raw_text[line_start:start]
    if len(before.strip())<3:
        prev_end=line_start-1
        prev_start=raw_text.rfind('\n',0,prev_end)+1 if prev_end>0 else 0
        before=raw_text[prev_start:start]
    before=before[-80:]
    after_raw=raw_text[end:end+20]
    # só usamos o texto seguinte como âncora quando ele é estável (sem dígitos) — se tiver
    # dígitos é provavelmente parte de OUTRO valor variável (data, valor, CNPJ), que muda de
    # documento para documento e não serve como referência fixa.
    after=after_raw if not re.search(r'\d',after_raw) else ''
    return {'before':before,'after':after,'length':end-start}

def apply_layout_template(raw_text,fields_json):
    try:rules=json.loads(fields_json) if isinstance(fields_json,str) else (fields_json or {})
    except Exception:return {}
    out={}
    for field,rule in rules.items():
        before=rule.get('before','');after=rule.get('after','');length=int(rule.get('length') or 0)
        pos=raw_text.find(before) if before else -1
        if pos<0:continue
        start=pos+len(before)
        end=raw_text.find(after,start) if after else -1
        if end<0:
            nl=raw_text.find('\n',start)
            end=nl if nl>=0 else min(len(raw_text),start+max(length,1)+40)
        value=raw_text[start:end].strip()
        if value:out[field]=value
    return out

def get_ai_api_key():
    enc=get_setting('ai_api_key_enc','')
    if not enc:return None
    try:raw=decrypt_secret(enc.encode('ascii'))
    except Exception:return None
    return raw.decode('utf-8') if raw else None

def ai_extract_fields(api_key,raw_text,doc_type,fields):
    """Pede à IA (Anthropic) para extrair os campos pedidos de um documento fiscal cujo
    leiaute os interpretadores internos não reconheceram. Para cada campo, pede também o
    trecho verbatim do texto original de onde tirou o valor, para permitir aprender esse
    leiaute e não precisar chamar a IA de novo da próxima vez."""
    wanted={k:FISCAL_FIELD_LABELS.get(k,k) for k in fields}
    prompt=('Você está extraindo dados de um documento fiscal/financeiro brasileiro '
        f'(tipo: {doc_type}) cujo texto foi extraído automaticamente de um PDF ou XML e é dado abaixo.\n\n'
        'Extraia os seguintes campos:\n'+'\n'.join(f'- {k}: {label}' for k,label in wanted.items())+
        '\n\nResponda SOMENTE com um JSON (sem markdown, sem texto adicional) no formato:\n'
        '{"campo": {"value": "valor normalizado", "excerpt": "trecho EXATO copiado do texto original de onde veio o valor"}, ...}\n'
        'Se não encontrar um campo com segurança, omita-o do JSON. O "excerpt" precisa ser uma cópia literal '
        '(caractere a caractere) de um trecho do texto abaixo — isso é usado para localizar o campo automaticamente da próxima vez.\n\n'
        '--- TEXTO DO DOCUMENTO ---\n'+raw_text[:12000])
    body=json.dumps({'model':ANTHROPIC_MODEL,'max_tokens':1024,'messages':[{'role':'user','content':prompt}]},ensure_ascii=False).encode('utf-8')
    req=urlrequest.Request('https://api.anthropic.com/v1/messages',data=body,method='POST',
        headers={'x-api-key':api_key,'anthropic-version':'2023-06-01','Content-Type':'application/json'})
    try:
        with urlrequest.urlopen(req,timeout=30) as resp:payload=json.loads(resp.read())
    except Exception:return None
    try:
        text_out=''.join(b.get('text','') for b in payload.get('content',[]) if b.get('type')=='text')
        m=re.search(r'\{.*\}',text_out,re.S)
        data=json.loads(m.group(0) if m else text_out)
    except Exception:return None
    result={}
    for k in fields:
        item=data.get(k)
        if isinstance(item,dict) and item.get('value'):
            result[k]={'value':str(item['value']).strip(),'excerpt':str(item.get('excerpt') or '').strip()}
    return result or None

def enrich_with_layout_learning(doc_type,raw_text,out,required):
    """Tenta completar campos obrigatórios que os interpretadores não conseguiram extrair,
    nesta ordem: modelo já aprendido -> IA (se configurada) -> devolve o texto bruto para o
    usuário marcar os campos na tela (o que aprende um modelo novo para a próxima vez)."""
    missing=[k for k in required if not out.get(k)]
    if not missing:return out
    skeleton=text_skeleton(raw_text);signature=layout_signature(skeleton)
    with db() as c:tmpl=find_layout_template(c,doc_type,signature,skeleton)
    if tmpl:
        for k,v in apply_layout_template(raw_text,tmpl['fields_json']).items():
            if v and not out.get(k):out[k]=v
        missing=[k for k in required if not out.get(k)]
        if not missing:
            with db() as c:c.execute('update fiscal_layout_templates set use_count=use_count+1 where id=?',(tmpl['id'],))
            out['warnings']=[w for w in out.get('warnings',[]) if not w.startswith('Conferir campos')]
            out['confidence']=max(out.get('confidence',60),80);out['learned_layout_used']=True
            return out
    api_key=get_ai_api_key()
    if api_key:
        ai_result=ai_extract_fields(api_key,raw_text,doc_type,missing)
        if ai_result:
            learn_fields={}
            for field,item in ai_result.items():
                value,excerpt=item.get('value'),item.get('excerpt')
                if value and not out.get(field):out[field]=value
                if excerpt:
                    pos=raw_text.find(excerpt)
                    if pos>=0:learn_fields[field]={'text':excerpt,'start':pos,'end':pos+len(excerpt)}
            missing=[k for k in required if not out.get(k)]
            out['ai_assisted']=True
            if learn_fields:out['_learn_candidate']={'doc_type':doc_type,'signature':signature,'skeleton':skeleton,'raw_text':raw_text,'fields':learn_fields}
            if not missing:
                out['warnings']=[w for w in out.get('warnings',[]) if not w.startswith('Conferir campos')]
                out['confidence']=max(out.get('confidence',60),75)
                return out
    out['needs_training']=True;out['raw_text']=raw_text;out['doc_type']=doc_type
    out['signature']=signature;out['skeleton']=skeleton;out['required_fields']=required
    return out

def build_parsed_from_template(doc_type,applied):
    """Monta um resultado no mesmo formato de classify_fiscal() a partir dos campos que um
    modelo aprendido conseguiu extrair, para alimentar a mesma tela de conferência."""
    out=dict(applied)
    out.setdefault('document_kind',DOC_KIND_LABELS.get(doc_type,'Documento'))
    out.setdefault('warnings',[]);out.setdefault('issue_date','');out.setdefault('document_no','')
    out.setdefault('type','Despesa');out.setdefault('party_type','Fornecedor')
    out.setdefault('direction','Boleto a pagar' if doc_type=='boleto' else 'Recebida de fornecedor')
    missing=[k for k in ('tax_id','party_name','amount') if not out.get(k)]
    out['confidence']=max(20,90-len(missing)*20)
    if missing:out['warnings'].append('Confira os campos preenchidos automaticamente pelo modelo aprendido.')
    out['learned_layout_used']=True
    return out

def parse_pdf(blob):
    try:
        from pypdf import PdfReader
        txt='\n'.join((p.extract_text() or '') for p in PdfReader(io.BytesIO(blob)).pages)
    except Exception as e:return {'warnings':[f'Falha ao ler PDF: {e}'],'confidence':0}
    if re.search(r'DANFE|Documento Auxiliar da Nota Fiscal|\bNF-e\b',txt,re.I):return parse_danfe(txt)
    if re.search(r'NFS-e|NFSe|Nota Fiscal de Servi',txt,re.I):return parse_nfse(txt)
    if is_boleto_text(txt):return parse_boleto_text(txt)
    # Sem marcador claro: mantém compatibilidade tentando como NFS-e, mas sinaliza a incerteza.
    out=parse_nfse(txt)
    out['warnings'].append('Tipo de documento não identificado com certeza (NF-e/NFS-e/Boleto); revise os campos.')
    return out

def parse_boleto_text(txt):
    flat=' '.join(txt.split())
    out={'document_kind':'Boleto','warnings':[],'type':'Despesa','party_type':'Fornecedor','direction':'Boleto a pagar','party_name':'','party_address':'','tax_id':'','document_no':'','issue_date':'','due_date':'','amount':0,'barcode_line':''}
    # Linha digitável: aceita formatos bancários e de arrecadação com pontuação ou espaços.
    candidates=re.findall(r'(?<!\d)(?:\d[ .-]?){44,48}(?!\d)',txt)
    if candidates:
        best=max(candidates,key=len)
        digs=digits(best)
        if len(digs) in (44,46,47,48): out['barcode_line']=best.strip()
    # CNPJ/CPF do beneficiário. Prefere ocorrências próximas de Beneficiário/Cedente.
    for pat in [r'(?:Benefici[aá]rio|Cedente|Favorecido)[\s\S]{0,220}?(?:CNPJ|CPF)\s*[:\-]?\s*([\d.\-/]{11,18})',r'(?:CNPJ|CPF)\s*[:\-]?\s*([\d.\-/]{11,18})']:
        m=re.search(pat,txt,re.I)
        if m:
            raw=digits(m.group(1)); out['tax_id']=fmt_cnpj(raw) if len(raw)==14 else raw; break
    # Nome do beneficiário/cedente.
    lines=[x.strip() for x in txt.splitlines() if x.strip()]
    for i,line in enumerate(lines):
        low=line.lower()
        if any(k in low for k in ('beneficiário','beneficiario','cedente','favorecido')):
            val=re.split(r'[:\-]',line,1)
            cand=val[1].strip() if len(val)>1 else ''
            if not cand and i+1<len(lines): cand=lines[i+1].strip()
            if cand and len(cand)>2 and not re.search(r'cnpj|cpf|agência|agencia|código|codigo',cand,re.I):
                out['party_name']=cand[:180]; break
    # Vencimento
    for pat in [r'(?:Vencimento|Data de Vencimento)\s*[:\-]?\s*(\d{2}/\d{2}/\d{4})',r'(?:Vencimento|Data de Vencimento)[^\d]{0,40}(\d{2}/\d{2}/\d{4})']:
        m=re.search(pat,txt,re.I)
        if m: out['due_date']=normalize_date(m.group(1)); break
    # Valor do documento / valor cobrado.
    for lab in ['Valor do Documento','Valor Cobrado','Valor a Pagar','Valor Documento','Valor Total']:
        m=re.search(re.escape(lab)+r'[^\d]{0,45}(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})',txt,re.I)
        if m: out['amount']=money_br(m.group(1)); break
    # Número do documento / nosso número
    for pat in [r'(?:N[ºo°.]?\s*do Documento|Número do Documento|Numero do Documento)\s*[:\-]?\s*([A-Za-z0-9.\-/]+)',r'(?:Nosso N[úu]mero|Nosso Numero)\s*[:\-]?\s*([A-Za-z0-9.\-/]+)']:
        m=re.search(pat,txt,re.I)
        if m: out['document_no']=m.group(1).strip(); break
    t=clean_text(txt)
    required=['party_name','tax_id','due_date','amount','barcode_line']
    out=enrich_with_layout_learning('boleto',t,out,required)
    labels={'party_name':'beneficiário','tax_id':'CNPJ/CPF','due_date':'vencimento','amount':'valor','barcode_line':'linha digitável'}
    missing=[labels[k] for k in required if not out.get(k)]
    if missing: out['warnings'].append('Conferir campos: '+', '.join(missing))
    out['confidence']=max(20,100-len(missing)*15)
    return out

def parse_boleto(blob):
    try:
        from pypdf import PdfReader
        txt='\n'.join((p.extract_text() or '') for p in PdfReader(io.BytesIO(blob)).pages)
    except Exception as e:
        return {'document_kind':'Boleto','warnings':[f'Falha ao ler boleto PDF: {e}'],'confidence':0,'type':'Despesa','party_type':'Fornecedor','direction':'Boleto a pagar'}
    return parse_boleto_text(txt)

def parse_xml(blob):
    root=ET.fromstring(blob); tags={el.tag.split('}')[-1]:el.text for el in root.iter() if el.text and el.text.strip()}
    # NF-e standard
    emit=next((el for el in root.iter() if el.tag.split('}')[-1]=='emit'),None);dest=next((el for el in root.iter() if el.tag.split('}')[-1]=='dest'),None)
    def child(parent,name):
        if parent is None:return ''
        for el in parent.iter():
            if el.tag.split('}')[-1]==name:return el.text or ''
        return ''
    out={'document_kind':'XML Fiscal','provider_tax_id':fmt_cnpj(child(emit,'CNPJ')),'provider_name':child(emit,'xNome'),'taker_tax_id':fmt_cnpj(child(dest,'CNPJ')),'taker_name':child(dest,'xNome'),'document_no':tags.get('nNF',''),'issue_date':normalize_date(tags.get('dhEmi') or tags.get('dEmi') or ''),'amount':float(tags.get('vNF') or tags.get('vLiq') or 0),'warnings':[]}
    out=classify_fiscal(out)
    root_tag=root.tag.split('}')[-1]
    doc_type='xml_nfe' if root_tag in ('NFe','nfeProc') else 'xml_nfse'
    flat_dump='\n'.join(f'{k}: {v.strip()}' for k,v in tags.items())
    return enrich_with_layout_learning(doc_type,flat_dump,out,['tax_id','party_name','amount','document_no'])

class H(SimpleHTTPRequestHandler):
    def end_headers(self):
        # Evita que o navegador reutilize frontend de versões anteriores.
        self.send_header('Cache-Control','no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma','no-cache')
        self.send_header('Expires','0')
        super().end_headers()
    def J(self,o,n=200,cookie=None):
        b=json.dumps(o,ensure_ascii=False,default=str).encode('utf-8');self.send_response(n);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(b)))
        if cookie:self.send_header('Set-Cookie',cookie)
        self.end_headers();self.wfile.write(b)
    def user(self):
        m=re.search(r'sid=([^;]+)',self.headers.get('Cookie',''));return SESS.get(m.group(1)) if m else None
    def require(self,role='Usuário'):
        u=self.user()
        if not u:self.J({'error':'Não autenticado'},401);return None
        if ROLE_RANK.get(u['role'],0)<ROLE_RANK.get(role,1):self.J({'error':'Sem permissão'},403);return None
        if u['role']!='Master':
            lic=current_license()
            if not lic.get('valid'):
                self.J({'error':'Licença do Financeiro AGF não está ativa ou é inválida. Contate o responsável Master.'},402);return None
        return u
    def can(self,u,permission):
        return u['role'] in ('Master','Administrador') or permission in (u.get('permissions') or [])
    def require_access(self,u,permission):
        if not self.can(u,permission):self.J({'error':'Seu operador não possui acesso a este módulo'},403);return False
        return True
    def do_GET(self):
        path=urlparse(self.path).path
        if path=='/api/session':return self.J({'authenticated':bool(self.user()),'user':self.user()})
        if path=='/api/state':
            u=self.require()
            if not u:return
            with db() as c:
                data={'user':u,'permissions':ALL_ACCESS if u['role'] in ('Master','Administrador') else u.get('permissions',[]),'categories':[dict(x) for x in c.execute('select * from categories order by name')],'parties':[dict(x) for x in c.execute('select * from parties order by name')],'transactions':[dict(x) for x in c.execute('select * from transactions order by due_date,id')],'audit':[dict(x) for x in c.execute('select * from audit order by id desc limit 300')],'documents':[dict(x) for x in c.execute('select * from documents order by id desc limit 200')],'users':[{**dict(x),'permissions':json.loads(x['permissions'] or '[]')} for x in c.execute('select id,username,display_name,role,active,permissions,failed_attempts,locked from users order by username')] if u['role'] in ('Master','Administrador') else [],'settings':{'document_root':get_setting('document_root',DEFAULT_WINDOWS_ROOT),'company_tax_ids':sorted(own_cnpjs()),'ai_key_configured':bool(get_setting('ai_api_key_enc',''))},
                'company_profile':current_company_profile(),
                'license':current_license(),
                'issued_licenses':[dict(x) for x in c.execute('select id,license_code,customer_name,tax_id,expires_at,max_users,features,created_at,created_by,revoked from issued_licenses order by id desc limit 100')] if u['role']=='Master' else [],
                'contract_categories':[dict(x) for x in c.execute('select * from contract_categories order by name')],
                'contracts':[dict(x) for x in c.execute('''select ct.*,cc.name category_name from contracts ct left join contract_categories cc on cc.id=ct.category_id order by ct.id desc''')],
                'channels':[dict(x) for x in c.execute('''select ch.id,ch.name,ch.opening_balance,ch.opening_balance_set,ch.active,ch.accounting_code,
                    coalesce(sum(case when t.status='Efetivado' and t.type='Receita' then t.amount else 0 end),0) effective_income,
                    coalesce(sum(case when t.status='Efetivado' and t.type='Despesa' then t.amount else 0 end),0) effective_expense,
                    case when ch.opening_balance_set=1 then coalesce(ch.opening_balance,0)
                      +coalesce(sum(case when t.status='Efetivado' and t.type='Receita' then t.amount else 0 end),0)
                      -coalesce(sum(case when t.status='Efetivado' and t.type='Despesa' then t.amount else 0 end),0)
                    else null end current_balance
                    from channels ch left join transactions t on t.channel_id=ch.id
                    where ch.active=1 group by ch.id order by ch.id''')],
                'fiscal_config':fiscal_config_public() if u['role'] in ('Master','Administrador') else {},
                'nfse_notes':[dict(x) for x in c.execute('select * from nfse_notes order by id desc limit 200')] }
            if u['role']=='Operador':
                perms=set(u.get('permissions') or [])
                if not perms.intersection({'dash','novo','pagar','receber','fluxo','dre','canais','fiscal','contratos'}):data['transactions']=[]
                elif not perms.intersection({'dash','fluxo','dre','novo','fiscal','contratos'}):
                    data['transactions']=[x for x in data['transactions'] if (x['type']=='Despesa' and 'pagar' in perms) or (x['type']=='Receita' and 'receber' in perms)]
                if not perms.intersection({'clientes','fornecedores'}):data['parties']=[]
                if 'docs' not in perms:data['documents']=[]
                if 'contratos' not in perms:data['contracts']=[];data['contract_categories']=[]
                if 'audit' not in perms:data['audit']=[]
                if 'canais' not in perms:data['channels']=[]
                if 'notas_fiscais' not in perms:data['nfse_notes']=[]
            return self.J(data)
        if path=='/api/export/transactions':
            u=self.require()
            if not u:return
            if not self.require_access(u,'export'):return
            return self.export_transactions_csv(u)
        if path in ('/api/export/conciliacao','/api/export/contabil'):
            u=self.require()
            if not u:return
            if not self.require_access(u,'export'):return
            q=parse_qs(urlparse(self.path).query)
            raw_channel=q.get('channel_id',[''])[0]
            date_from=normalize_date(q.get('from',[''])[0])
            date_to=normalize_date(q.get('to',[''])[0])
            if raw_channel=='all':
                if path=='/api/export/conciliacao':return self.J({'error':'Selecione um canal financeiro específico para a Conciliação Bancária.'},400)
                return self.export_contabil_all_csv(u,date_from,date_to)
            try:channel_id=int(raw_channel)
            except:return self.J({'error':'Selecione um canal financeiro.'},400)
            if path=='/api/export/conciliacao':return self.export_conciliacao_csv(u,channel_id,date_from,date_to)
            return self.export_contabil_csv(u,channel_id,date_from,date_to)
        if path=='/api/company-logo':
            u=self.require()
            if not u:return
            ext=get_setting('company_logo_ext','')
            f=DATA_DIR/('company_logo'+ext) if ext else None
            if not f or not f.exists():return self.J({'error':'Sem logo cadastrada'},404)
            b=f.read_bytes();ctype=mimetypes.guess_type(str(f))[0] or 'application/octet-stream'
            self.send_response(200);self.send_header('Content-Type',ctype);self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
            return
        if path=='/':self.path='/static/index.html'
        return super().do_GET()
    def export_transactions_csv(self,u):
        with db() as c:
            rows=[dict(x) for x in c.execute('select * from transactions order by due_date,id')]
        if u['role']=='Operador':
            perms=set(u.get('permissions') or [])
            if not perms.intersection({'pagar','receber','dash','fluxo','dre'}):rows=[]
            elif not perms.intersection({'dash','fluxo','dre'}):
                rows=[x for x in rows if (x['type']=='Despesa' and 'pagar' in perms) or (x['type']=='Receita' and 'receber' in perms)]
        buf=io.StringIO();buf.write('﻿')
        w=csv.writer(buf,delimiter=';')
        w.writerow(['Tipo','Status','CNPJ/CPF','Nome','Emissao','Vencimento','Classificacao','Categoria','Valor','Documento','Origem','Observacoes'])
        for r in rows:
            w.writerow([r.get('type',''),r.get('status',''),r.get('tax_id',''),r.get('party_name',''),date_br(r.get('issue_date','')),date_br(r.get('due_date','')),r.get('classification',''),r.get('category',''),str(r.get('amount') or 0).replace('.',','),r.get('document_no',''),r.get('source',''),r.get('notes','') or ''])
        b=buf.getvalue().encode('utf-8')
        log_event(u['username'],'EXPORTAR_LANCAMENTOS',{'linhas':len(rows)})
        self.send_response(200)
        self.send_header('Content-Type','text/csv; charset=utf-8')
        self.send_header('Content-Disposition',f'attachment; filename="lancamentos_{datetime.date.today().isoformat()}.csv"')
        self.send_header('Content-Length',str(len(b)))
        self.end_headers()
        self.wfile.write(b)
    def _send_csv(self,b,filename):
        self.send_response(200)
        self.send_header('Content-Type','text/csv; charset=utf-8')
        self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
        self.send_header('Content-Length',str(len(b)))
        self.end_headers()
        self.wfile.write(b)
    def export_conciliacao_csv(self,u,channel_id,date_from,date_to):
        with db() as c:
            ch=c.execute('select * from channels where id=? and active=1',(channel_id,)).fetchone()
            if not ch:return self.J({'error':'Canal financeiro não encontrado.'},404)
            rows=[dict(x) for x in c.execute("select * from transactions where channel_id=? and status='Efetivado' order by due_date,id",(channel_id,))]
        if u['role']=='Operador':
            perms=set(u.get('permissions') or [])
            if not perms.intersection({'pagar','receber','dash','fluxo','dre','canais'}):rows=[]
            elif not perms.intersection({'dash','fluxo','dre','canais'}):
                rows=[x for x in rows if (x['type']=='Despesa' and 'pagar' in perms) or (x['type']=='Receita' and 'receber' in perms)]
        saldo=float(ch['opening_balance'] or 0) if ch['opening_balance_set'] else 0.0
        before=[r for r in rows if date_from and (r.get('due_date') or '')<date_from]
        for r in before:
            amt=float(r.get('amount') or 0)
            saldo += amt if r['type']=='Receita' else -amt
        period=[r for r in rows if (not date_from or (r.get('due_date') or '')>=date_from) and (not date_to or (r.get('due_date') or '')<=date_to)]
        buf=io.StringIO();buf.write('﻿')
        w=csv.writer(buf,delimiter=';')
        w.writerow(['Data','NF','Histórico','Crédito','Débito','Saldo'])
        brnum=lambda n:f'{n:.2f}'.replace('.',',')
        w.writerow(['','','SALDO ANTERIOR','','',brnum(saldo)])
        for r in period:
            amt=float(r.get('amount') or 0)
            if r['type']=='Receita':saldo+=amt;cred,deb=brnum(amt),''
            else:saldo-=amt;cred,deb='',brnum(amt)
            w.writerow([date_br(r.get('due_date','')),r.get('document_no',''),r.get('party_name',''),cred,deb,brnum(saldo)])
        b=buf.getvalue().encode('utf-8')
        log_event(u['username'],'EXPORTAR_CONCILIACAO',{'canal':ch['name'],'de':date_from,'ate':date_to,'linhas':len(period)})
        self._send_csv(b,f"conciliacao_{re.sub(r'[^A-Za-z0-9]+','_',ch['name'])}_{datetime.date.today().isoformat()}.csv")
    def export_contabil_csv(self,u,channel_id,date_from,date_to):
        with db() as c:
            ch=c.execute('select * from channels where id=? and active=1',(channel_id,)).fetchone()
            if not ch:return self.J({'error':'Canal financeiro não encontrado.'},404)
            if not (ch['accounting_code'] or '').strip():return self.J({'error':'Este canal ainda não tem um código contábil definido. Informe o código em Canais Financeiros antes de exportar.'},400)
            rows=[dict(x) for x in c.execute("select * from transactions where channel_id=? and status='Efetivado' order by due_date,id",(channel_id,))]
        if u['role']=='Operador':
            perms=set(u.get('permissions') or [])
            if not perms.intersection({'pagar','receber','dash','fluxo','dre','canais'}):rows=[]
            elif not perms.intersection({'dash','fluxo','dre','canais'}):
                rows=[x for x in rows if (x['type']=='Despesa' and 'pagar' in perms) or (x['type']=='Receita' and 'receber' in perms)]
        period=[r for r in rows if (not date_from or (r.get('due_date') or '')>=date_from) and (not date_to or (r.get('due_date') or '')<=date_to)]
        code=ch['accounting_code'].strip()
        lines=[';Data;   Valor   ;Débito;Crédito;Histórico']
        for r in period:
            amt=float(r.get('amount') or 0);valor=f'{amt:.2f}'.replace('.',',')
            if r['type']=='Receita':deb,cred,hist=code,'','RECEBIMENTO CLIENTE '+str(r.get('party_name') or '')
            else:deb,cred,hist='',code,'PAGAMENTO FORNECEDOR '+str(r.get('party_name') or '')
            lines.append(';'.join(['Lançamento',date_br(r.get('due_date','')),valor,deb,cred,hist]))
        text='\r\n'.join(lines)+'\r\n'
        try:b=text.encode('cp1252')
        except UnicodeEncodeError:b=text.encode('utf-8')
        log_event(u['username'],'EXPORTAR_CONTABIL',{'canal':ch['name'],'de':date_from,'ate':date_to,'linhas':len(period)})
        self._send_csv(b,f"importacao_contabil_{re.sub(r'[^A-Za-z0-9]+','_',ch['name'])}_{datetime.date.today().isoformat()}.csv")
    def export_contabil_all_csv(self,u,date_from,date_to):
        with db() as c:
            channels=[dict(x) for x in c.execute('select * from channels where active=1 order by name')]
        with_code=[ch for ch in channels if (ch.get('accounting_code') or '').strip()]
        without_code=[ch['name'] for ch in channels if not (ch.get('accounting_code') or '').strip()]
        if not with_code:return self.J({'error':'Nenhum canal ativo tem código contábil definido. Informe o código em Canais Financeiros antes de exportar.'},400)
        perms=set(u.get('permissions') or []) if u['role']=='Operador' else None
        lines=[';Data;   Valor   ;Débito;Crédito;Histórico'];total_rows=0
        for ch in with_code:
            with db() as c:
                rows=[dict(x) for x in c.execute("select * from transactions where channel_id=? and status='Efetivado' order by due_date,id",(ch['id'],))]
            if perms is not None:
                if not perms.intersection({'pagar','receber','dash','fluxo','dre','canais'}):rows=[]
                elif not perms.intersection({'dash','fluxo','dre','canais'}):
                    rows=[x for x in rows if (x['type']=='Despesa' and 'pagar' in perms) or (x['type']=='Receita' and 'receber' in perms)]
            period=[r for r in rows if (not date_from or (r.get('due_date') or '')>=date_from) and (not date_to or (r.get('due_date') or '')<=date_to)]
            code=ch['accounting_code'].strip()
            for r in period:
                amt=float(r.get('amount') or 0);valor=f'{amt:.2f}'.replace('.',',')
                if r['type']=='Receita':deb,cred,hist=code,'','RECEBIMENTO CLIENTE '+str(r.get('party_name') or '')
                else:deb,cred,hist='',code,'PAGAMENTO FORNECEDOR '+str(r.get('party_name') or '')
                lines.append(';'.join(['Lançamento',date_br(r.get('due_date','')),valor,deb,cred,hist]))
                total_rows+=1
        text='\r\n'.join(lines)+'\r\n'
        try:b=text.encode('cp1252')
        except UnicodeEncodeError:b=text.encode('utf-8')
        log_event(u['username'],'EXPORTAR_CONTABIL',{'canal':'Todos','canais_sem_codigo':without_code,'de':date_from,'ate':date_to,'linhas':total_rows})
        self._send_csv(b,f"importacao_contabil_TODOS_OS_CANAIS_{datetime.date.today().isoformat()}.csv")
    def parse(self):
        n=int(self.headers.get('Content-Length',0));ctype=self.headers.get('Content-Type','')
        if 'multipart/form-data' in ctype:
            raw=self.rfile.read(n);msg=BytesParser(policy=default).parsebytes(b'Content-Type: '+ctype.encode()+b'\r\nMIME-Version: 1.0\r\n\r\n'+raw);fields={};files=[]
            for part in msg.iter_parts():
                name=part.get_param('name',header='content-disposition');fn=part.get_filename()
                if fn:files.append((name,fn,part.get_payload(decode=True)))
                else:
                    payload=part.get_payload(decode=True)
                    fields[name]=payload.decode('utf-8',errors='replace') if payload is not None else ''
            return fields,files
        try:return json.loads(self.rfile.read(n) or b'{}'),None
        except:return {},None
    def do_POST(self):
        path=urlparse(self.path).path;d,files=self.parse()
        if path=='/api/login':
            with db() as c:r=c.execute('select * from users where lower(username)=lower(?) and active=1',(d.get('username',''),)).fetchone()
            if not r:return self.J({'error':'Usuário ou senha inválidos'},401)
            if r['locked']:return self.J({'error':'Usuário bloqueado após 3 tentativas. Solicite o desbloqueio ao Master ou Administrador.'},423)
            if not pv(d.get('password',''),r['password_hash']):
                attempts=int(r['failed_attempts'] or 0)+1
                with db() as c:c.execute('update users set failed_attempts=?,locked=? where id=?',(attempts,1 if attempts>=3 else 0,r['id']))
                log_event(r['username'],'LOGIN_FALHOU',{'tentativa':attempts,'bloqueado':attempts>=3})
                return self.J({'error':'Usuário bloqueado após 3 tentativas.' if attempts>=3 else f'Usuário ou senha inválidos. Tentativa {attempts} de 3.'},423 if attempts>=3 else 401)
            with db() as c:c.execute('update users set failed_attempts=0 where id=?',(r['id'],))
            try:permissions=json.loads(r['permissions'] or '[]')
            except:permissions=[]
            sid=secrets.token_urlsafe(24);SESS[sid]={'id':r['id'],'username':r['username'],'display_name':r['display_name'] or r['username'],'role':r['role'],'permissions':permissions};log_event(r['username'],'LOGIN',{});return self.J({'ok':True},cookie=f'sid={sid}; Path=/; HttpOnly; SameSite=Strict')
        if path=='/api/logout':
            m=re.search(r'sid=([^;]+)',self.headers.get('Cookie',''));SESS.pop(m.group(1),None) if m else None;return self.J({'ok':True},cookie='sid=; Path=/; Max-Age=0')
        u=self.require()
        if not u:return
        if files is not None:
            if not files:return self.J({'error':'Arquivo não enviado'},400)
            _,fn,blob=files[0]
            if path in ('/api/import-pdf','/api/import-xml','/api/import-boleto','/api/archive-only') and not self.require_access(u,'fiscal'):return
            if path=='/api/import-pdf':p=parse_pdf(blob)
            elif path=='/api/import-xml':p=parse_xml(blob)
            elif path=='/api/import-boleto':p=parse_boleto(blob)
            elif path=='/api/fiscal/import-batch':
                if not self.require_access(u,'fiscal'):return
                kind=str(d.get('kind') or '').strip()
                if kind not in ('nfe','nfse','boleto','xml'):return self.J({'error':'Tipo de lote inválido'},400)
                if len(files)>20:return self.J({'error':'Envie no máximo 20 arquivos por lote'},400)
                results=[]
                for _,bfn,bblob in files:
                    try:
                        if kind=='xml':parsed=parse_xml(bblob)
                        elif kind=='boleto':parsed=parse_boleto(bblob)
                        else:parsed=parse_pdf(bblob)
                        parsed['original_name']=bfn
                        results.append({'filename':bfn,'ok':True,'parsed':parsed})
                    except Exception as e:
                        results.append({'filename':bfn,'ok':False,'error':str(e)})
                log_event(u['username'],'IMPORTAR_LOTE_FISCAL',{'tipo':kind,'arquivos':len(files)})
                return self.J({'ok':True,'results':results})
            elif path=='/api/archive-only':
                return self.archive_document(u,d,fn,blob,None)
            elif path=='/api/document/general':
                if not self.require_access(u,'docs'):return
                category=str(d.get('category') or 'Geral').strip();safe=re.sub(r'[^\w\-. ]','_',category)
                dest=ensure_archive_structure()/'07 - Documentos Gerais'/safe;dest.mkdir(parents=True,exist_ok=True);final=dest/fn;final.write_bytes(blob)
                with db() as c:cur=c.execute('insert into documents(created_at,tax_id,party_name,doc_type,original_name,stored_path,transaction_id) values(?,?,?,?,?,?,NULL)',(now(),'','',f'Documento Geral — {category}',fn,str(final)))
                log_event(u['username'],'ARQUIVAR_DOCUMENTO_GERAL',{'arquivo':str(final),'categoria':category,'document_id':cur.lastrowid});return self.J({'ok':True})
            elif path=='/api/contract':
                if not self.require_access(u,'contratos'):return
                return self.create_contract(u,d,fn,blob)
            elif path=='/api/company-logo':
                if u['role'] not in ('Master','Administrador'):return self.J({'error':'Sem permissão'},403)
                ext=Path(fn).suffix.lower() or '.png'
                if ext not in ('.png','.jpg','.jpeg','.gif','.webp','.svg'):return self.J({'error':'Formato de imagem não suportado'},400)
                old_ext=get_setting('company_logo_ext','')
                if old_ext:
                    old=DATA_DIR/('company_logo'+old_ext)
                    if old.exists():old.unlink()
                (DATA_DIR/('company_logo'+ext)).write_bytes(blob)
                set_setting('company_logo_ext',ext)
                log_event(u['username'],'ALTERAR_LOGO_EMPRESA',{'arquivo':fn});return self.J({'ok':True})
            elif path=='/api/company-certificate':
                if u['role'] not in ('Master','Administrador'):return self.J({'error':'Sem permissão'},403)
                ext=Path(fn).suffix.lower()
                if ext not in ('.pfx','.p12'):return self.J({'error':'Envie um arquivo de certificado A1 (.pfx ou .p12)'},400)
                password=str(d.get('cert_password') or '')
                if not password:return self.J({'error':'Informe a senha do certificado'},400)
                expiry=extract_cert_expiry(blob,password)
                if not expiry:return self.J({'error':'Não foi possível abrir o certificado com a senha informada. Confira o arquivo e a senha.'},400)
                aliquota=None
                if str(d.get('aliquota_iss') or '').strip():
                    try:aliquota=float(str(d['aliquota_iss']).replace(',','.'))
                    except:return self.J({'error':'Alíquota do ISS inválida'},400)
                with db() as c:
                    c.execute('''update fiscal_config set cert_pfx_enc=?,cert_password_enc=?,cert_filename=?,cert_uploaded_at=?,cert_expires_at=?,
                        regime_tributario=?,inscricao_municipal=?,codigo_municipio=?,item_lista_servico=?,codigo_tributario_municipio=?,
                        aliquota_iss=?,optante_simples_nacional=?,updated_at=?,updated_by=? where id=1''',
                        (encrypt_secret(blob),encrypt_secret(password.encode('utf-8')),fn,now(),expiry,
                         int(d['regime_tributario']) if str(d.get('regime_tributario') or '').strip() else None,
                         str(d.get('inscricao_municipal') or '').strip(),str(d.get('codigo_municipio') or '').strip(),
                         str(d.get('item_lista_servico') or '').strip(),str(d.get('codigo_tributario_municipio') or '').strip(),
                         aliquota,1 if str(d.get('optante_simples_nacional','1')) in ('1','true','True','on') else 0,
                         now(),u['username']))
                log_event(u['username'],'CADASTRAR_CERTIFICADO_DIGITAL',{'arquivo':fn,'validade':expiry})
                return self.J({'ok':True,'cert_expires_at':expiry})
            else:return self.J({'error':'Rota inválida'},404)
            p['original_name']=fn;log_event(u['username'],'INTERPRETAR_BOLETO' if path=='/api/import-boleto' else 'INTERPRETAR_FISCAL',{'arquivo':fn,'resultado':p});return self.J({'ok':True,'parsed':p})
        if path=='/api/company-profile':
            if not self.require('Master'):return
            fields=('legal_name','trade_name','tax_id','email','phone','address','city','state','zip_code')
            vals=[str(d.get(k,'')).strip() for k in fields]
            with db() as c:
                c.execute("""update company_profile set legal_name=?,trade_name=?,tax_id=?,email=?,phone=?,address=?,city=?,state=?,zip_code=?,updated_at=? where id=1""",(*vals,now()))
            log_event(u['username'],'ALTERAR_DADOS_EMPRESA',{k:d.get(k,'') for k in fields})
            return self.J({'ok':True})
        if path=='/api/fiscal-provider-token':
            if u['role'] not in ('Master','Administrador'):return self.J({'error':'Sem permissão'},403)
            token=str(d.get('token') or '').strip()
            if not token:return self.J({'error':'Informe o token de acesso'},400)
            environment=str(d.get('environment') or 'homologacao').strip()
            if environment not in ('homologacao','producao'):return self.J({'error':'Ambiente inválido'},400)
            with db() as c:
                c.execute('update fiscal_config set api_token_enc=?,environment=?,updated_at=?,updated_by=? where id=1',
                          (encrypt_secret(token.encode('utf-8')),environment,now(),u['username']))
            log_event(u['username'],'CADASTRAR_TOKEN_FOCUS_NFE',{'environment':environment})
            return self.J({'ok':True})
        if path=='/api/ai-provider-key':
            if u['role'] not in ('Master','Administrador'):return self.J({'error':'Sem permissão'},403)
            key=str(d.get('api_key') or '').strip()
            if not key:return self.J({'error':'Informe a chave de API'},400)
            set_setting('ai_api_key_enc',encrypt_secret(key.encode('utf-8')).decode('ascii'))
            log_event(u['username'],'CADASTRAR_CHAVE_IA',{});return self.J({'ok':True})
        if path=='/api/fiscal/learn-layout':
            if not self.require_access(u,'fiscal'):return
            doc_type=str(d.get('doc_type') or '').strip()
            signature=str(d.get('signature') or '').strip()
            raw_text=str(d.get('raw_text') or '')
            skeleton=str(d.get('skeleton') or '') or text_skeleton(raw_text)
            fields=d.get('fields') or {}
            if not doc_type or not signature or not raw_text or not fields:
                return self.J({'error':'Dados insuficientes para aprender este modelo de documento'},400)
            rules={}
            for field,info in fields.items():
                try:start=int(info.get('start'));end=int(info.get('end'))
                except Exception:continue
                if end<=start or start<0 or end>len(raw_text):continue
                rules[field]=derive_field_rule(raw_text,start,end)
            if not rules:return self.J({'error':'Nenhum campo válido foi marcado'},400)
            fields_json=json.dumps(rules,ensure_ascii=False)
            with db() as c:
                c.execute('''insert into fiscal_layout_templates(doc_type,signature,skeleton_sample,fields_json,use_count,created_at,created_by,updated_at)
                    values(?,?,?,?,1,?,?,?)
                    on conflict(doc_type,signature) do update set fields_json=excluded.fields_json,skeleton_sample=excluded.skeleton_sample,updated_at=excluded.updated_at,use_count=fiscal_layout_templates.use_count+1''',
                    (doc_type,signature,skeleton[:4000],fields_json,now(),u['username'],now()))
            applied=apply_layout_template(raw_text,fields_json)
            parsed=build_parsed_from_template(doc_type,applied)
            log_event(u['username'],'APRENDER_LEIAUTE_FISCAL',{'doc_type':doc_type,'signature':signature,'campos':list(rules.keys())})
            return self.J({'ok':True,'parsed':parsed})
        if path=='/api/fiscal/sync-company':
            if u['role'] not in ('Master','Administrador'):return self.J({'error':'Sem permissão'},403)
            cfg=current_fiscal_config()
            if not cfg.get('api_token_enc'):return self.J({'error':'Cadastre o token de acesso da Focus NFe antes de sincronizar'},400)
            pfx=decrypt_secret(cfg.get('cert_pfx_enc'))
            cert_password=None
            if cfg.get('cert_password_enc'):
                raw=decrypt_secret(cfg['cert_password_enc']);cert_password=raw.decode('utf-8') if raw else None
            try:
                resp=focus_sync_company(cfg,current_company_profile(),pfx_bytes=pfx,cert_password=cert_password)
            except FocusError as e:
                log_event(u['username'],'SINCRONIZAR_EMPRESA_FOCUS_ERRO',{'erro':str(e)})
                return self.J({'error':f'Erro ao sincronizar com a Focus NFe: {e}'},400)
            focus_id=str(resp.get('id') or cfg.get('focus_empresa_id') or '')
            with db() as c:
                c.execute('update fiscal_config set focus_empresa_id=?,company_synced=1,updated_at=?,updated_by=? where id=1',(focus_id,now(),u['username']))
            log_event(u['username'],'SINCRONIZAR_EMPRESA_FOCUS',{'focus_empresa_id':focus_id})
            return self.J({'ok':True,'focus_empresa_id':focus_id})
        if path=='/api/nfse/emit':
            if not self.require_access(u,'notas_fiscais'):return
            cfg=current_fiscal_config()
            if not cfg.get('company_synced'):return self.J({'error':'Sincronize a empresa com a Focus NFe antes de emitir notas (Dados da Empresa > Certificado Digital / Integração Fiscal).'},400)
            try:valor=float(str(d.get('valor')).replace(',','.'))
            except:return self.J({'error':'Valor do serviço inválido'},400)
            if valor<=0:return self.J({'error':'Valor do serviço deve ser maior que zero'},400)
            discriminacao=str(d.get('discriminacao') or '').strip()
            if not discriminacao:return self.J({'error':'Descrição do serviço é obrigatória'},400)
            tomador_tax_id=digits(d.get('tomador_tax_id'));tomador_name=str(d.get('tomador_name') or '').strip()
            if not tomador_tax_id or not tomador_name:return self.J({'error':'CPF/CNPJ e nome do tomador são obrigatórios'},400)
            tomador={
                'razao_social':tomador_name,
                'email':str(d.get('tomador_email') or '').strip(),
                'endereco':{
                    'logradouro':str(d.get('tomador_logradouro') or '').strip(),
                    'numero':str(d.get('tomador_numero') or 'S/N').strip(),
                    'bairro':str(d.get('tomador_bairro') or '').strip(),
                    'codigo_municipio':str(d.get('tomador_codigo_municipio') or cfg.get('codigo_municipio') or '').strip(),
                    'uf':str(d.get('tomador_uf') or '').strip(),
                    'cep':digits(d.get('tomador_cep')),
                }
            }
            if len(tomador_tax_id)>11:tomador['cnpj']=tomador_tax_id
            else:tomador['cpf']=tomador_tax_id
            if str(d.get('tomador_telefone') or '').strip():tomador['telefone']=digits(d.get('tomador_telefone'))
            aliquota=cfg.get('aliquota_iss')
            if str(d.get('aliquota_iss') or '').strip():
                try:aliquota=float(str(d['aliquota_iss']).replace(',','.'))
                except:return self.J({'error':'Alíquota do ISS inválida'},400)
            servico={
                'valor_servicos':valor,
                'iss_retido':bool(d.get('iss_retido')),
                'item_lista_servico':str(d.get('item_lista_servico') or cfg.get('item_lista_servico') or '').strip(),
                'codigo_tributario_municipio':str(d.get('codigo_tributario_municipio') or cfg.get('codigo_tributario_municipio') or '').strip(),
                'discriminacao':discriminacao,
                'codigo_municipio':str(cfg.get('codigo_municipio') or '').strip(),
                'aliquota':aliquota,
            }
            transaction_id=int(d['transaction_id']) if str(d.get('transaction_id') or '').strip() else None
            ref='agf-'+secrets.token_hex(6)
            try:
                resp=focus_emit_nfse(cfg,current_company_profile(),ref,tomador,servico)
            except FocusError as e:
                log_event(u['username'],'EMITIR_NFSE_ERRO',{'erro':str(e),'ref':ref})
                return self.J({'error':f'Erro ao emitir a nota: {e}'},400)
            status=resp.get('status') or 'processando_autorizacao'
            with db() as c:
                cur=c.execute('''insert into nfse_notes(ref,transaction_id,tomador_tax_id,tomador_name,valor,discriminacao,status,numero,codigo_verificacao,url_pdf,caminho_xml,erro_mensagem,created_at,created_by,updated_at)
                    values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (ref,transaction_id,tomador_tax_id,tomador_name,valor,discriminacao,status,resp.get('numero'),resp.get('codigo_verificacao'),resp.get('url_danfse'),resp.get('caminho_xml_nota_fiscal'),None,now(),u['username'],now()))
            log_event(u['username'],'EMITIR_NFSE',{'ref':ref,'status':status,'valor':valor,'tomador':tomador_name})
            return self.J({'ok':True,'id':cur.lastrowid,'ref':ref,'status':status})
        if path=='/api/nfse/consult':
            if not self.require_access(u,'notas_fiscais'):return
            note=self.find_nfse_note(d)
            if not note:return self.J({'error':'Nota não encontrada'},404)
            cfg=current_fiscal_config()
            try:
                resp=focus_consult_nfse(cfg,note['ref'])
            except FocusError as e:
                return self.J({'error':f'Erro ao consultar a nota: {e}'},400)
            status=resp.get('status') or note['status']
            erros=resp.get('erros')
            erro_msg='; '.join(str(x.get('mensagem') or x) for x in erros) if erros else None
            with db() as c:
                c.execute('''update nfse_notes set status=?,numero=?,codigo_verificacao=?,url_pdf=?,caminho_xml=?,erro_mensagem=?,updated_at=? where id=?''',
                    (status,resp.get('numero'),resp.get('codigo_verificacao'),resp.get('url_danfse'),resp.get('caminho_xml_nota_fiscal'),erro_msg,now(),note['id']))
            log_event(u['username'],'CONSULTAR_NFSE',{'ref':note['ref'],'status':status})
            return self.J({'ok':True,'status':status})
        if path=='/api/nfse/cancel':
            if not self.require_access(u,'notas_fiscais'):return
            note=self.find_nfse_note(d)
            if not note:return self.J({'error':'Nota não encontrada'},404)
            justificativa=str(d.get('justificativa') or '').strip()
            if not (15<=len(justificativa)<=255):return self.J({'error':'Justificativa deve ter entre 15 e 255 caracteres'},400)
            cfg=current_fiscal_config()
            try:
                resp=focus_cancel_nfse(cfg,note['ref'],justificativa)
            except FocusError as e:
                return self.J({'error':f'Erro ao cancelar a nota: {e}'},400)
            status=resp.get('status') or 'cancelado'
            with db() as c:
                c.execute('update nfse_notes set status=?,updated_at=? where id=?',(status,now(),note['id']))
            log_event(u['username'],'CANCELAR_NFSE',{'ref':note['ref'],'justificativa':justificativa})
            return self.J({'ok':True,'status':status})
        if path=='/api/license/generate':
            if not self.require('Master'):return
            customer=str(d.get('customer_name','')).strip()
            if not customer:return self.J({'error':'Nome do licenciado é obrigatório'},400)
            expires=str(d.get('expires_at') or 'PERPETUA').strip()
            max_users=int(d.get('max_users') or 1)
            features=d.get('features') or ['financeiro']
            payload={
                'product':'Financeiro AGF',
                'license_id':secrets.token_hex(8).upper(),
                'customer_name':customer,
                'tax_id':str(d.get('tax_id','')).strip(),
                'issued_at':datetime.date.today().isoformat(),
                'expires_at':expires,
                'max_users':max_users,
                'features':features
            }
            code=sign_license(payload)
            with db() as c:
                c.execute('insert into issued_licenses(license_code,customer_name,tax_id,expires_at,max_users,features,created_at,created_by,revoked) values(?,?,?,?,?,?,?,?,0)',
                          (code,customer,payload['tax_id'],expires,max_users,json.dumps(features,ensure_ascii=False),now(),u['username']))
            log_event(u['username'],'GERAR_LICENCA',payload)
            return self.J({'ok':True,'license_code':code,'payload':payload})
        if path=='/api/license/activate':
            if not self.require('Master'):return
            code=str(d.get('license_code','')).strip()
            result=verify_license(code)
            if not result.get('valid'):return self.J({'error':result.get('error','Licença inválida')},400)
            set_setting('active_license',code)
            log_event(u['username'],'ATIVAR_LICENCA',result.get('payload',{}))
            return self.J({'ok':True,'license':result})
        if path=='/api/channel':
            if not self.require_access(u,'canais'):return
            name=str(d.get('name','')).strip()
            if not name:return self.J({'error':'Nome do canal é obrigatório'},400)
            with db() as c:
                try:c.execute('insert into channels(name,opening_balance,opening_balance_set,active,created_at) values(?,NULL,0,1,?)',(name,now()))
                except sqlite3.IntegrityError:return self.J({'error':'Canal já cadastrado'},400)
            log_event(u['username'],'CADASTRAR_CANAL',{'name':name});return self.J({'ok':True})
        if path=='/api/channel/opening-balance':
            if not self.require_access(u,'canais'):return
            try:cid=int(d.get('id'));bal=float(d.get('opening_balance'))
            except:return self.J({'error':'Canal ou saldo inicial inválido'},400)
            with db() as c:
                ch=c.execute('select * from channels where id=? and active=1',(cid,)).fetchone()
                if not ch:return self.J({'error':'Canal não encontrado'},404)
                if ch['opening_balance_set']:return self.J({'error':'Saldo inicial já foi informado para este canal'},400)
                c.execute('update channels set opening_balance=?,opening_balance_set=1 where id=?',(bal,cid))
            log_event(u['username'],'DEFINIR_SALDO_INICIAL_CANAL',{'id':cid,'name':ch['name'],'opening_balance':bal});return self.J({'ok':True})
        if path=='/api/channel/accounting-code':
            if not self.require_access(u,'canais'):return
            try:cid=int(d.get('id'))
            except:return self.J({'error':'Canal inválido'},400)
            code=str(d.get('accounting_code','')).strip()
            with db() as c:
                ch=c.execute('select * from channels where id=? and active=1',(cid,)).fetchone()
                if not ch:return self.J({'error':'Canal não encontrado'},404)
                c.execute('update channels set accounting_code=? where id=?',(code,cid))
            log_event(u['username'],'DEFINIR_CODIGO_CONTABIL_CANAL',{'id':cid,'name':ch['name'],'accounting_code':code});return self.J({'ok':True})
        if path=='/api/party':
            if not (self.can(u,'clientes') or self.can(u,'fornecedores')):return self.J({'error':'Seu operador não possui acesso a este módulo'},403)
            if not d.get('tax_id') or not d.get('classification') or not d.get('category_id') or d.get('party_type') not in ('Cliente','Fornecedor','Ambos'):return self.J({'error':'CNPJ/CPF, Classificação, Categoria e Tipo são obrigatórios'},400)
            with db() as c:
                old=c.execute('select * from parties where tax_id=?',(d['tax_id'],)).fetchone();c.execute('''insert into parties(tax_id,name,address,classification,category_id,party_type,folder_scope,updated_at) values(?,?,?,?,?,?,?,?) on conflict(tax_id) do update set name=excluded.name,address=excluded.address,classification=excluded.classification,category_id=excluded.category_id,party_type=excluded.party_type,folder_scope=excluded.folder_scope,updated_at=excluded.updated_at''',(d['tax_id'],d.get('name',''),d.get('address',''),d['classification'],int(d['category_id']),d['party_type'],d.get('folder_scope',''),now()))
            log_event(u['username'],'ALTERAR_CADASTRO' if old else 'CADASTRAR',d);return self.J({'ok':True})
        if path=='/api/transaction':
            if not self.require_access(u,'novo'):return
            return self.create_tx(u,d,require_party=True)
        if path=='/api/fiscal/full':
            if not self.require_access(u,'fiscal'):return
            # Importação fiscal/boleto nunca exige nem associa canal financeiro.
            # O canal será definido somente no momento da efetivação do pagamento/recebimento.
            d.pop('channel_id', None)
            d['status']='Aguardando Pagamento'
            if not d.get('classification') or not d.get('category_id') or not d.get('tax_id') or not d.get('party_name'):return self.J({'error':'Complete Classificação, Categoria, CNPJ/CPF e Nome'},400)
            with db() as c:c.execute('''insert into parties(tax_id,name,address,classification,category_id,party_type,updated_at) values(?,?,?,?,?,?,?) on conflict(tax_id) do update set name=excluded.name,address=excluded.address,classification=excluded.classification,category_id=excluded.category_id,party_type=excluded.party_type,updated_at=excluded.updated_at''',(d['tax_id'],d['party_name'],d.get('party_address',''),d['classification'],int(d['category_id']),d['party_type'],now()))
            return self.create_tx(u,d,require_party=True)
        if path=='/api/transaction/update':
            if d.get('status')=='Efetivado' and not d.get('channel_id'):
                return self.J({'error':'Para efetivar o lançamento, selecione o canal financeiro'},400)
            with db() as c:
                old=c.execute('select * from transactions where id=?',(int(d['id']),)).fetchone()
                if not old:return self.J({'error':'Lançamento não encontrado'},404)
                if not self.require_access(u,'pagar' if old['type']=='Despesa' else 'receber'):return
                c.execute('update transactions set type=?,status=?,tax_id=?,party_name=?,issue_date=?,due_date=?,classification=?,category=?,amount=?,document_no=?,notes=?,channel_id=? where id=?',(d['type'],d['status'],d.get('tax_id',''),d.get('party_name',''),normalize_date(d.get('issue_date','')),normalize_date(d.get('due_date','')),d.get('classification',''),d.get('category',''),float(d.get('amount') or 0),d.get('document_no',''),d.get('notes',''),int(d.get('channel_id')) if d.get('channel_id') else None,int(d['id'])))
            log_event(u['username'],'ALTERAR_LANCAMENTO',{'antes':dict(old),'depois':d});return self.J({'ok':True})
        if path=='/api/transaction/delete':
            txid=int(d.get('id') or 0);reason=str(d.get('reason') or '').strip()
            if not reason:return self.J({'error':'O motivo da exclusão é obrigatório'},400)
            with db() as c:
                old=c.execute('select * from transactions where id=?',(txid,)).fetchone()
                if not old:return self.J({'error':'Lançamento não encontrado'},404)
                if old['type'] not in ('Despesa','Receita'):return self.J({'error':'Exclusão permitida somente em Contas a Pagar e Contas a Receber'},400)
                permission='pagar' if old['type']=='Despesa' else 'receber'
                if not self.require_access(u,permission):return
                c.execute('insert into deleted_transactions(transaction_id,transaction_json,reason,deleted_at,deleted_by) values(?,?,?,?,?)',(txid,json.dumps(dict(old),ensure_ascii=False),reason,now(),u['username']))
                c.execute('delete from transactions where id=?',(txid,))
            log_event(u['username'],'EXCLUIR_LANCAMENTO',{'id':txid,'motivo':reason,'lancamento':dict(old)});return self.J({'ok':True})
        if path=='/api/contract-category':
            if not self.require_access(u,'contratos'):return
            name=str(d.get('name') or '').strip()
            if not name:return self.J({'error':'Informe o nome da categoria'},400)
            with db() as c:
                try:c.execute('insert into contract_categories(name,created_at,created_by) values(?,?,?)',(name,now(),u['username']))
                except sqlite3.IntegrityError:return self.J({'error':'Categoria já cadastrada'},400)
            log_event(u['username'],'CRIAR_CATEGORIA_CONTRATO',{'name':name});return self.J({'ok':True})
        if path=='/api/contract/extra-launch':
            if not self.require_access(u,'contratos'):return
            try:
                contract_id=int(d.get('contract_id') or 0);amount=float(str(d.get('amount') or '').replace(',','.'))
            except:return self.J({'error':'Contrato ou valor inválido'},400)
            kind=d.get('kind')
            if kind not in ('juros','indexador'):return self.J({'error':'Tipo de lançamento extra inválido'},400)
            indexer=str(d.get('indexer') or '').strip()
            if kind=='indexador' and indexer not in ('CDI','IPCA','Inflação'):return self.J({'error':'Selecione um indexador válido (CDI, IPCA ou Inflação)'},400)
            if amount<=0:return self.J({'error':'Informe um valor válido'},400)
            with db() as c:
                ct=c.execute('select * from contracts where id=?',(contract_id,)).fetchone()
                if not ct:return self.J({'error':'Contrato não encontrado'},404)
                label='Taxa de Juros' if kind=='juros' else f'Indexador ({indexer})'
                category='JUROS SOBRE EMPRESTIMOS E FINANCIAMENTOS' if kind=='juros' else f'ATUALIZAÇÃO MONETÁRIA - {indexer.upper()}'
                tag='JUR' if kind=='juros' else f'IDX-{indexer[:3].upper()}'
                for i in range(ct['installments']):
                    due=month_add(ct['first_due_date'],i);doc=f"CTR-{contract_id}-{tag}-{i+1:03d}/{ct['installments']:03d}"
                    c.execute('''insert into transactions(type,status,tax_id,party_name,issue_date,due_date,classification,category,amount,document_no,notes,source,created_at,channel_id,contract_id) values(?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?)''',(ct['movement_type'],'Aguardando Pagamento',ct['tax_id'],ct['counterparty'],ct['start_date'],due,ct['classification'],category,amount,doc,f"{label} do contrato: {ct['title']}",'Contrato',now(),contract_id))
            log_event(u['username'],'CRIAR_LANCAMENTO_EXTRA_CONTRATO',{'contrato_id':contract_id,'tipo':kind,'indexador':indexer,'valor':amount,'recorrencias':ct['installments']});return self.J({'ok':True,'transactions_created':ct['installments']})
        if path=='/api/user':
            if u['role'] not in ('Master','Administrador'):return self.J({'error':'Sem permissão'},403)
            if d.get('role') not in ROLE_RANK:return self.J({'error':'Perfil inválido'},400)
            if u['role']=='Administrador' and d.get('role') in ('Master','Administrador'):return self.J({'error':'Administrador pode criar somente Operador ou Usuário'},403)
            if not valid_email(d.get('username')):return self.J({'error':'Informe um e-mail válido como usuário'},400)
            if not valid_password(d.get('password')):return self.J({'error':PASSWORD_RULE_MSG},400)
            permissions=[x for x in (d.get('permissions') or []) if x in ALL_ACCESS] if d.get('role')=='Operador' else []
            with db() as c:
                try:c.execute('insert into users(username,display_name,role,password_hash,active,permissions,failed_attempts,locked) values(?,?,?,?,1,?,0,0)',(d['username'],d.get('display_name') or d['username'],d['role'],ph(d['password']),json.dumps(permissions,ensure_ascii=False)))
                except sqlite3.IntegrityError:return self.J({'error':'Usuário já existe'},400)
            safe=dict(d);safe.pop('password',None);log_event(u['username'],'CADASTRAR_USUARIO',safe);return self.J({'ok':True})
        if path=='/api/user/update':
            if u['role'] not in ('Master','Administrador'):return self.J({'error':'Sem permissão'},403)
            uid=int(d.get('id') or 0)
            if uid==u['id']:return self.J({'error':'Você não pode executar esta ação na sua própria conta'},400)
            if d.get('role') not in ROLE_RANK:return self.J({'error':'Perfil inválido'},400)
            if u['role']=='Administrador' and d.get('role') in ('Master','Administrador'):return self.J({'error':'Administrador pode definir somente Operador ou Usuário'},403)
            with db() as c:
                target=c.execute('select id,username,role from users where id=?',(uid,)).fetchone()
                if not target:return self.J({'error':'Usuário não encontrado'},404)
                if u['role']=='Administrador' and target['role']!='Operador':return self.J({'error':'Administrador só pode editar usuários Operador'},403)
                display_name=str(d.get('display_name') or '').strip() or target['username']
                permissions=[x for x in (d.get('permissions') or []) if x in ALL_ACCESS] if d.get('role')=='Operador' else []
                c.execute('update users set display_name=?,role=?,permissions=? where id=?',(display_name,d['role'],json.dumps(permissions,ensure_ascii=False),uid))
            log_event(u['username'],'EDITAR_USUARIO',{'usuario':target['username'],'display_name':display_name,'role':d['role'],'permissions':permissions});return self.J({'ok':True})
        if path=='/api/user/reset-password':
            if u['role'] not in ('Master','Administrador'):return self.J({'error':'Sem permissão'},403)
            uid=int(d.get('id') or 0);new_password=str(d.get('password') or '').strip()
            if not valid_password(new_password):return self.J({'error':PASSWORD_RULE_MSG},400)
            with db() as c:
                target=c.execute('select id,username,role from users where id=?',(uid,)).fetchone()
                if not target:return self.J({'error':'Usuário não encontrado'},404)
                if u['role']=='Administrador' and target['role']!='Operador':return self.J({'error':'Administrador só pode redefinir senha de Operador'},403)
                c.execute('update users set password_hash=?,failed_attempts=0,locked=0 where id=?',(ph(new_password),uid))
            log_event(u['username'],'REDEFINIR_SENHA_DESBLOQUEAR',{'usuario':target['username']});return self.J({'ok':True})
        if path in ('/api/user/block','/api/user/unblock','/api/user/delete'):
            if u['role'] not in ('Master','Administrador'):return self.J({'error':'Sem permissão'},403)
            uid=int(d.get('id') or 0)
            if uid==u['id']:return self.J({'error':'Você não pode executar esta ação na sua própria conta'},400)
            with db() as c:
                target=c.execute('select id,username,role from users where id=?',(uid,)).fetchone()
                if not target:return self.J({'error':'Usuário não encontrado'},404)
                if u['role']=='Administrador' and target['role']!='Operador':return self.J({'error':'Administrador só pode gerenciar usuários Operador'},403)
                if path=='/api/user/block':
                    c.execute('update users set active=0 where id=?',(uid,))
                elif path=='/api/user/unblock':
                    c.execute('update users set active=1,locked=0,failed_attempts=0 where id=?',(uid,))
                else:
                    if target['role']=='Master':
                        remaining=c.execute("select count(*) n from users where role='Master' and id!=?",(uid,)).fetchone()['n']
                        if remaining==0:return self.J({'error':'Não é possível excluir o último usuário Master'},400)
                    c.execute('delete from users where id=?',(uid,))
            action={'/api/user/block':'BLOQUEAR_USUARIO','/api/user/unblock':'DESBLOQUEAR_USUARIO','/api/user/delete':'EXCLUIR_USUARIO'}[path]
            log_event(u['username'],action,{'usuario':target['username']});return self.J({'ok':True})
        if path=='/api/settings':
            if not self.require('Master'):return
            if 'document_root' in d:set_setting('document_root',d['document_root'])
            if 'company_tax_ids' in d:
                vals=[digits(x) for x in d['company_tax_ids'] if digits(x)];vals.append(OWN_CNPJ_FIXED);set_setting('company_tax_ids',json.dumps(sorted(set(vals))))
            return self.J({'ok':True})
        return self.J({'error':'Rota inválida'},404)
    def create_tx(self,u,d,require_party=True):
        with db() as c:
            p=c.execute('select p.*,c.name category from parties p join categories c on c.id=p.category_id where p.tax_id=?',(d.get('tax_id',''),)).fetchone()
        if require_party and not p:return self.J({'error':'Cadastre/valide primeiro os parâmetros do cliente/fornecedor'},400)
        typ=d.get('type')
        if p:
            if p['party_type']=='Cliente':typ='Receita'
            elif p['party_type']=='Fornecedor':typ='Despesa'
            elif typ not in ('Receita','Despesa'):return self.J({'error':'Cadastro Ambos: escolha Receita ou Despesa'},400)
            classification=p['classification'];category=p['category'];party_name=p['name'];tax_id=p['tax_id']
        else:
            classification=d.get('classification','');category=d.get('category','');party_name=d.get('party_name','');tax_id=d.get('tax_id','')
        status=d.get('status','Aguardando Pagamento')
        channel_id=None
        if d.get('channel_id') not in (None,'',0,'0'):
            try:channel_id=int(d.get('channel_id'))
            except:return self.J({'error':'Canal financeiro inválido'},400)
            with db() as c:
                ch=c.execute('select id from channels where id=? and active=1',(channel_id,)).fetchone()
                if not ch:return self.J({'error':'Canal financeiro inválido'},400)
        if status=='Efetivado' and channel_id is None:
            return self.J({'error':'Para efetivar o lançamento, selecione o canal financeiro'},400)
        with db() as c:
            cur=c.execute('insert into transactions(type,status,tax_id,party_name,issue_date,due_date,classification,category,amount,document_no,notes,source,created_at,channel_id) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(typ,status,tax_id,party_name,normalize_date(d.get('issue_date','')),normalize_date(d.get('due_date','')),classification,category,float(d.get('amount') or 0),d.get('document_no',''),d.get('notes',''),d.get('source','Manual'),now(),channel_id))
        log_event(u['username'],'LANCAR',{'id':cur.lastrowid,'type':typ,'tax_id':tax_id});return self.J({'ok':True,'id':cur.lastrowid,'type':typ})
    def find_nfse_note(self,d):
        with db() as c:
            if str(d.get('id') or '').strip():
                r=c.execute('select * from nfse_notes where id=?',(int(d['id']),)).fetchone()
            elif str(d.get('ref') or '').strip():
                r=c.execute('select * from nfse_notes where ref=?',(str(d['ref']),)).fetchone()
            else:return None
        return dict(r) if r else None
    def create_contract(self,u,fields,fn,blob):
        required=('title','category_id','counterparty','first_due_date','amount','installments','movement_type','classification')
        if any(not str(fields.get(k,'')).strip() for k in required):return self.J({'error':'Preencha todos os campos obrigatórios do contrato'},400)
        try:
            category_id=int(fields['category_id']);amount=float(str(fields['amount']).replace(',','.'));installments=int(fields['installments'])
        except:return self.J({'error':'Categoria, valor ou número de parcelas inválido'},400)
        if installments<1 or installments>600:return self.J({'error':'Informe de 1 a 600 recorrências'},400)
        movement=fields['movement_type']
        if movement not in ('Despesa','Receita'):return self.J({'error':'Tipo de movimento inválido'},400)
        first_due=normalize_date(fields['first_due_date']);start=normalize_date(fields.get('start_date') or first_due)
        if not first_due:return self.J({'error':'Primeiro vencimento inválido. Use DD/MM/AAAA.'},400)
        safe=re.sub(r'[^\w\-. ]','_',fields['title']);dest=ensure_archive_structure()/'08 - Contratos'/safe;dest.mkdir(parents=True,exist_ok=True);final=dest/fn;final.write_bytes(blob)
        with db() as c:
            cat_row=c.execute('select name from contract_categories where id=?',(category_id,)).fetchone()
            if not cat_row:return self.J({'error':'Categoria de contrato não encontrada'},404)
            tx_category=cat_row['name']
            cur=c.execute('''insert into contracts(title,category_id,counterparty,tax_id,description,start_date,first_due_date,amount,installments,movement_type,classification,transaction_category,original_name,stored_path,created_at,created_by) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(fields['title'],category_id,fields['counterparty'],fields.get('tax_id',''),fields.get('description',''),start,first_due,amount,installments,movement,fields['classification'],tx_category,fn,str(final),now(),u['username']))
            contract_id=cur.lastrowid
            for i in range(installments):
                due=month_add(first_due,i);doc=f'CTR-{contract_id}-{i+1:03d}/{installments:03d}'
                c.execute('''insert into transactions(type,status,tax_id,party_name,issue_date,due_date,classification,category,amount,document_no,notes,source,created_at,channel_id,contract_id) values(?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?)''',(movement,'Aguardando Pagamento',fields.get('tax_id',''),fields['counterparty'],start,due,fields['classification'],tx_category,amount,doc,f"Recorrência do contrato: {fields['title']}",'Contrato',now(),contract_id))
            c.execute('insert into documents(created_at,tax_id,party_name,doc_type,original_name,stored_path,transaction_id) values(?,?,?,?,?,?,NULL)',(now(),fields.get('tax_id',''),fields['counterparty'],'Contrato',fn,str(final)))
        log_event(u['username'],'CRIAR_CONTRATO_RECORRENTE',{'contrato_id':contract_id,'titulo':fields['title'],'recorrencias':installments,'valor':amount});return self.J({'ok':True,'contract_id':contract_id,'transactions_created':installments})
    def archive_document(self,u,fields,fn,blob,txid):
        tax=fields.get('tax_id','');name=fields.get('party_name','');ptype=fields.get('party_type','Fornecedor')
        with db() as c:p=c.execute('select * from parties where tax_id=?',(tax,)).fetchone()
        scope=(p['folder_scope'] if p and p['folder_scope'] else '')
        if not scope:
            base='Clientes' if ptype=='Cliente' else 'Fornecedores';safe=re.sub(r'[^\w\-. ]','_',name or tax or 'Sem Cadastro');scope=f'01 - Documentos/{base}/{safe}'
            if p:
                with db() as c:c.execute('update parties set folder_scope=? where tax_id=?',(scope,tax))
        dest=ensure_archive_structure()/scope;dest.mkdir(parents=True,exist_ok=True);final=dest/fn;final.write_bytes(blob)
        with db() as c:cur=c.execute('insert into documents(created_at,tax_id,party_name,doc_type,original_name,stored_path,transaction_id) values(?,?,?,?,?,?,?)',(now(),tax,name,fields.get('doc_type','Fiscal'),fn,str(final),txid))
        log_event(u['username'],'ARQUIVAR_DOCUMENTO',{'arquivo':str(final),'document_id':cur.lastrowid});return self.J({'ok':True,'path':str(final)})
    def log_message(self,fmt,*args):pass

if __name__=='__main__':
    init();remove_known_fictitious_transactions();ensure_archive_structure();os.chdir(ROOT);print(f'Financeiro AGF ouvindo em 0.0.0.0:{PORT}');ThreadingHTTPServer(('0.0.0.0',PORT),H).serve_forever()
