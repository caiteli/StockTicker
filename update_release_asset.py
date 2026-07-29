# -*- coding: utf-8 -*-
"""把本地重新打包好的 StockTickerSetup.exe 更新到 GitHub Release v1.0.0。

步骤：
1. 找到 v1.0.0 这个 release；
2. 删除其中已存在的 StockTickerSetup.exe 资产（同名不能重复上传）；
3. 上传新的安装包。

PAT 从环境变量 TOKEN 读取，不落盘。仓库走 HTTPS（沙箱内需跳过证书校验）。
"""
import os
import sys
import json
import ssl
import urllib.request

TOKEN = os.environ.get("TOKEN", "")
REPO = "caiteli/StockTicker"
TAG = "v1.0.0"
ASSET_LOCAL = os.path.join(
    os.path.dirname(__file__),
    "_deliver", "StockTickerSetup.exe"
)
ASSET_NAME = "StockTickerSetup.exe"

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def api(method, url, data=None, headers=None, is_json=True):
    h = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "stockticker-uploader",
    }
    if headers:
        h.update(headers)
    body = None
    if data is not None:
        if isinstance(data, (dict, list)):
            body = json.dumps(data).encode("utf-8")
            h["Content-Type"] = "application/json"
        else:
            body = data
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    with urllib.request.urlopen(req, context=ctx) as r:
        raw = r.read()
        return r.status, (json.loads(raw) if (raw and is_json) else raw)


def main():
    if not TOKEN:
        print("ERROR: 缺少环境变量 TOKEN")
        sys.exit(1)
    if not os.path.exists(ASSET_LOCAL):
        print(f"ERROR: 找不到安装包 {ASSET_LOCAL}")
        sys.exit(1)
    size = os.path.getsize(ASSET_LOCAL)
    print(f"本地安装包: {ASSET_LOCAL} ({size} 字节)")

    # 1) 定位 release
    status, rel = api("GET",
                      f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}")
    print("get release status:", status, "id:", rel.get("id"))
    rel_id = rel["id"]

    # 2) 删除同名旧资产
    for a in rel.get("assets", []):
        if a["name"] == ASSET_NAME:
            dstatus, _ = api("DELETE", a["url"])
            print(f"删除旧资产 {ASSET_NAME}: status {dstatus}")

    # 3) 上传新资产
    upload_url = (f"https://uploads.github.com/repos/{REPO}/releases/"
                  f"{rel_id}/assets?name={ASSET_NAME}")
    with open(ASSET_LOCAL, "rb") as f:
        data = f.read()
    status, resp = api(
        "POST", upload_url, data=data,
        headers={"Content-Type": "application/octet-stream"},
        is_json=True)
    print("upload status:", status)
    if status == 201:
        print("OK 上传成功:", resp.get("browser_download_url"))
    else:
        print("上传失败:", resp)
        sys.exit(1)


if __name__ == "__main__":
    main()
