import urllib.request, json, ssl, os, sys

TOKEN = os.environ['TOKEN']
REPO = 'caiteli/StockTicker'
EXE = r'C:/Users/202313038/WorkBuddy/2026-07-28-09-28-59/stockticker/installer/src/dist/StockTickerSetup.exe'
NOTES = r'C:/Users/202313038/WorkBuddy/2026-07-28-09-28-59/stockticker/RELEASE_NOTES.md'

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def api(url, data=None, method='GET', headers=None, binary=False):
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('Authorization', f'Bearer {TOKEN}')
    req.add_header('Accept', 'application/vnd.github+json')
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, context=ctx) as r:
        body = r.read()
        return r.status, body

with open(NOTES, 'r', encoding='utf-8') as f:
    body_text = f.read()

payload = json.dumps({
    'tag_name': 'v1.0.0',
    'name': 'StockTicker v1.0.0',
    'body': body_text,
    'draft': False,
    'prerelease': False,
}).encode('utf-8')

print('[1/3] Creating release...', flush=True)
status, resp = api(f'https://api.github.com/repos/{REPO}/releases',
                   data=payload, method='POST',
                   headers={'Content-Type': 'application/json'})
print('create status:', status, flush=True)
rel = json.loads(resp)
if status >= 400:
    print('ERROR creating release:', resp.decode('utf-8', 'replace')[:500], flush=True)
    sys.exit(1)
rel_id = rel['id']
upload_url = rel['upload_url'].split('{')[0]
print('release id:', rel_id, upload_url, flush=True)

print('[2/3] Uploading StockTickerSetup.exe (this may take a while)...', flush=True)
with open(EXE, 'rb') as f:
    filedata = f.read()
print('file bytes:', len(filedata), flush=True)
up_url = upload_url + '?name=StockTickerSetup.exe'
status2, resp2 = api(up_url, data=filedata, method='POST',
                     headers={'Content-Type': 'application/octet-stream'})
print('upload status:', status2, flush=True)
try:
    j = json.loads(resp2)
    print('asset id:', j.get('id'), 'name:', j.get('name'), 'size:', j.get('size'), flush=True)
    print('browser_download_url:', j.get('browser_download_url'), flush=True)
except Exception as e:
    print('upload response (raw):', resp2.decode('utf-8', 'replace')[:500], flush=True)

print('[3/3] Done.', flush=True)
