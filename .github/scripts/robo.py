# Автоактивация оплат Robokassa. Ничего личного в лог не пишет (репозиторий публичный).
import os, json, time, hashlib, base64, urllib.request, urllib.error, re

LOGIN = 'Jamli'
P2 = os.environ.get('ROBO_PASS2', '')
KD = os.environ.get('KD_TOKEN', '')
QURL = 'https://ntfy.sh/ugq-af43161359a999ea'
DATA_API = 'https://api.github.com/repos/chamsutdinov-bot/klyuchi-data/contents/buyers.json'
DAY = 24*60*60*1000
HALF = 183*DAY
TERMS = {'m': 30*DAY, 'h': HALF, 'y': 365*DAY, 'f': 100*365*DAY}
PRICE = {'m': 390, 'h': 1990, 'y': 2990, 'f': 1990}
ALPH = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'
STATE = '.github/robo-state.json'
NOW = int(time.time()*1000)

def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8')

def rj(path, default):
    try:
        with open(path, encoding='utf-8') as f: return json.load(f)
    except Exception: return default

def wj(path, d):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f: json.dump(d, f, ensure_ascii=False, separators=(',', ':'))

def check_char(body):
    return ALPH[sum(ALPH.index(c)*(i+1) for i, c in enumerate(body)) % 32]

def parse_key(k):
    m = re.fullmatch(r'([A-Z]{2})-([0-9A-Z]{4})-([0-9A-Z]{4})-([0-9A-Z]{4})', (k or '').upper())
    if not m: return None
    app, body = m.group(1), m.group(2)+m.group(3)+m.group(4)
    if app not in ('UG', 'UW', 'UP') or any(c not in ALPH for c in body) or check_char(body[:11]) != body[11]: return None
    return {'app': app, 'body': body, 'key': f'{app}-{m.group(2)}-{m.group(3)}-{m.group(4)}'}

def sha(s): return hashlib.sha256(s.encode()).hexdigest()

def shard(k):
    h = sha(f"UGK|{k['app']}|{k['body']}")
    path = f"list/{k['app']}/{h[:2]}.json"
    d = rj(path, {})
    d.setdefault('a', {}); d.setdefault('b', []); d.setdefault('m', [])
    if isinstance(d['a'], list): d['a'] = {x: NOW+HALF for x in d['a']}
    return path, h[2:18], d

def set_phone(app, num, u):
    h = sha(f'UGP|{app}|{num}')
    path = f'list/{app}/p/{h[:2]}.json'
    d = rj(path, {}); d[h[2:18]] = u; wj(path, d)

def bump(app):
    st = rj('list/stats.json', {}); st.setdefault(app, {'a': 0, 'b': 0}); st[app]['a'] += 1; wj('list/stats.json', st)

def gh_buyers():
    t = json.loads(get(DATA_API+'?t=%d' % NOW, {'Authorization': 'Bearer '+KD, 'Accept': 'application/vnd.github+json'}))
    return json.loads(base64.b64decode(t['content']).decode('utf-8')), t['sha']

def gh_put_buyers(d, s):
    body = json.dumps({'message': 'Автоактивация', 'content': base64.b64encode(json.dumps(d, ensure_ascii=False, separators=(',', ':')).encode()).decode(), 'sha': s}).encode()
    req = urllib.request.Request(DATA_API, data=body, method='PUT', headers={'Authorization': 'Bearer '+KD, 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read())['content']['sha']

def op_state(inv):
    sig = hashlib.md5(f'{LOGIN}:{inv}:{P2}'.encode()).hexdigest()
    x = get(f'https://auth.robokassa.ru/Merchant/WebService/Service.asmx/OpStateExt?MerchantLogin={LOGIN}&InvoiceID={inv}&Signature={sig}')
    rc = re.search(r'<Result>\s*<Code>(\d+)</Code>', x)
    st = re.search(r'<State>\s*<Code>(\d+)</Code>', x)
    out = re.search(r'<OutSum>([\d.,]+)</OutSum>', x)
    return (int(rc.group(1)) if rc else -1, int(st.group(1)) if st else -1, float(out.group(1).replace(',', '.')) if out else 0.0)

def activate(B, m, k):
    num = re.sub(r'\D', '', str(m['ph']))
    app = k['app']; pl = 'f' if app == 'UP' else (m.get('pl') if m.get('pl') in ('m', 'h', 'y') else 'h')
    T = TERMS[pl]; key = num if app == 'UG' else f'{app}:{num}'
    path, sid, S = shard(k)
    if sid in S['b']: return 'blocked'
    for n, r in B.items():
        if r.get('k') == k['key'] and n != key: return 'other-owner'
    rec = B.get(key)
    if not rec:
        u = NOW+T; B[key] = {'k': k['key'], 'u': u, 't': NOW}; bump(app)
    elif rec.get('k') == k['key']:
        u = max(NOW, rec.get('u', 0))+T; rec['u'] = u
    else:
        u = max(NOW, rec.get('u', 0))+T
        old = parse_key(rec.get('k'))
        if old:
            op, oid, O = shard(old)
            if op == path: O = S
            O['a'].pop(oid, None)
            if oid not in O['m']: O['m'].append(oid)
            if op != path: wj(op, O)
        rec.setdefault('old', []).append(rec.get('k')); rec['k'] = k['key']; rec['u'] = u
    S['a'][sid] = u; S['m'] = [x for x in S['m'] if x != sid]; wj(path, S)
    set_phone(app, num, u)
    return 'ok'

def main():
    if not P2 or not KD:
        print('нет секретов ROBO_PASS2 / KD_TOKEN'); return
    state = rj(STATE, {'done': {}}); done = state.setdefault('done', {})
    for i in [i for i, t in done.items() if NOW-t > 60*DAY]: del done[i]
    tx = get(QURL+'/json?poll=1&since=24h')
    reqs = {}
    for line in tx.splitlines():
        try:
            m = json.loads(json.loads(line).get('message') or '{}')
        except Exception: continue
        inv = str(m.get('inv') or '')
        if inv.isdigit() and m.get('k') and m.get('ph') and inv not in done: reqs[inv] = m
    if not reqs: print('заявок нет'); return
    B = Bs = None; n = 0
    for inv, m in sorted(reqs.items()):
        try: rc, st, out = op_state(inv)
        except Exception as e: print('robokassa: нет ответа'); continue
        if rc != 0 or st != 100: continue
        k = parse_key(m['k'])
        pl = 'f' if k and k['app'] == 'UP' else m.get('pl', 'h')
        if not k or out + 0.01 < PRICE.get(pl, 1990):
            done[inv] = NOW; print('платёж', inv, 'не подходит'); continue
        if B is None: B, Bs = gh_buyers()
        r = activate(B, m, k); done[inv] = NOW; n += 1
        print('платёж', inv, '→', r)
    if B is not None and n: gh_put_buyers(B, Bs)
    wj(STATE, state)

main()
