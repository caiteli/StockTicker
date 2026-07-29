import urllib.request, json, ssl, os, sys

TOKEN = os.environ['TOKEN']
REPO = 'caiteli/StockTicker'

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

payload = json.dumps({
    'description': 'Windows 桌面半透明浮动行情小工具 · 上班摸鱼看盘神器：置顶叠在任意窗口、无任务栏入口、Ctrl+Alt+H 一键隐身，悄悄盯大盘不挡事。',
    'topics': [
        'stock-ticker', '摸鱼', '看盘', '行情', '股票',
        'pyside6', 'desktop-widget', 'windows', '量化', 'pyqt'
    ],
}).encode('utf-8')

req = urllib.request.Request(
    f'https://api.github.com/repos/{REPO}',
    data=payload, method='PATCH')
req.add_header('Authorization', f'Bearer {TOKEN}')
req.add_header('Accept', 'application/vnd.github+json')
req.add_header('Content-Type', 'application/json')

with urllib.request.urlopen(req, context=ctx) as r:
    data = json.loads(r.read())
    print('status:', r.status)
    print('description:', data.get('description'))

# 话题单独用 topics 接口设置（仅允许小写 ASCII：字母/数字/连字符）
topics = ['stock-ticker', 'mofish', 'stock', 'quote', 'pyside6',
          'pyqt', 'windows', 'desktop-widget', 'quant', 'watchlist']
tpayload = json.dumps({'names': topics}).encode('utf-8')
req2 = urllib.request.Request(
    f'https://api.github.com/repos/{REPO}/topics',
    data=tpayload, method='PUT')
req2.add_header('Authorization', f'Bearer {TOKEN}')
req2.add_header('Accept', 'application/vnd.github+json')
req2.add_header('Content-Type', 'application/json')
with urllib.request.urlopen(req2, context=ctx) as r2:
    d2 = json.loads(r2.read())
    print('topics status:', r2.status)
    print('topics:', d2.get('names'))
