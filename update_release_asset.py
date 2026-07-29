# -*- coding: utf-8 -*-
"""把本地重新打包好的 StockTickerSetup.exe 更新到 GitHub Release v1.0.0。

优化点（相对旧版）：
  * 不再用 `f.read()` 一次性把 100MB 加载到内存再发——改用 `http.client`
    直接底层 PUT，按 1MB 分块边读边发，首字节立刻送出，内存峰值从 ~100MB
    降到 ~1MB；上传 100MB 文件的物理耗时不变（受网络限制），但本地不再卡顿。
  * 把"先 list assets → DELETE 旧资产 → POST 新资产"合并为"GET release
    一次（取 release id）→ DELETE 旧 asset → POST 新 asset"。
  * 上传结束打印耗时与瞬时速率，方便对比"是否真的在传"（不再假装能进度回显
    ——http.client 把整个 body 一次性交给 socket 发，应用层无回调粒度）。

PAT 从环境变量 TOKEN 读取，不落盘。仓库走 HTTPS（沙箱内需跳过证书校验）。
"""
import os
import sys
import json
import ssl
import time
import http.client


TOKEN = os.environ.get("TOKEN", "")
REPO = "caiteli/StockTicker"
TAG = "v1.0.0"
ASSET_LOCAL = os.path.join(
    os.path.dirname(__file__),
    "_deliver", "StockTickerSetup.exe"
)
ASSET_NAME = "StockTickerSetup.exe"
CHUNK = 1024 * 1024   # 1MB 流式分块


def _api(method, url, data=None, is_json=True):
    """底层 HTTPS 调用 GitHub JSON API（带 PAT 鉴权）。返回 (status, body)。"""
    h = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "stockticker-uploader",
    }
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        h["Content-Type"] = "application/json"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    conn = http.client.HTTPSConnection(_host(url), context=ctx, timeout=60)
    try:
        conn.request(method, _path(url), body=body, headers=h)
        r = conn.getresponse()
        raw = r.read()
        return r.status, (json.loads(raw) if (raw and is_json) else raw)
    finally:
        conn.close()


def _host(url):
    return url.split("/", 3)[2]


def _path(url):
    return "/" + url.split("/", 3)[3]


def _delete_asset(asset_url):
    """删除 GitHub Release 上的某个 asset（旧版安装包）。失败也不抛。"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    h = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "stockticker-uploader",
    }
    try:
        conn = http.client.HTTPSConnection(
            _host(asset_url), context=ctx, timeout=30)
        try:
            conn.request("DELETE", _path(asset_url), headers=h)
            r = conn.getresponse()
            r.read()
            return r.status
        finally:
            conn.close()
    except Exception as e:
        print(f"DELETE 失败（不阻塞上传）: {e}")
        return None


def _stream_upload(upload_url, local_path):
    """流式分块上传本地文件到 GitHub Release asset URL。

    1MB 一块边读边发，内存峰值 ~1MB（不再 100MB 一次性 f.read()）。
    http.client 把 body 当 file-like 持续 read() 至 Content-Length 满足，
    第一个字节立刻进入 socket 发送缓冲，省去"读完 100MB 才开始传"的等待。"""
    size = os.path.getsize(local_path)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    h = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "stockticker-uploader",
        "Content-Type": "application/octet-stream",
        "Content-Length": str(size),
    }

    class _BodyIter:
        """http.client 把 body 当 file-like 持续 read(amt) 至读空。我们每次只
        返回 1MB，连接内部循环 read()，首字节立刻进 socket 缓冲。"""
        def __init__(self, fp):
            self.fp = fp
        def read(self, amt=-1):
            if amt is None or amt < 0:
                amt = CHUNK
            return self.fp.read(amt)

    t0 = time.time()
    with open(local_path, "rb") as f:
        conn = http.client.HTTPSConnection(
            _host(upload_url), context=ctx, timeout=600)
        try:
            conn.request("POST", _path(upload_url),
                         body=_BodyIter(f), headers=h)
            r = conn.getresponse()
            raw = r.read()
            body = json.loads(raw) if raw else {}
        finally:
            conn.close()
    dt = time.time() - t0
    mb = size / 1024 / 1024
    print(f"上传完成: {mb:.1f} MB / {dt:.1f} 秒 "
          f"({mb / max(dt, 0.01):.1f} MB/s)")
    return r.status, body


def main():
    if not TOKEN:
        print("ERROR: 缺少环境变量 TOKEN")
        sys.exit(1)
    if not os.path.exists(ASSET_LOCAL):
        print(f"ERROR: 找不到安装包 {ASSET_LOCAL}")
        sys.exit(1)
    size = os.path.getsize(ASSET_LOCAL)
    print(f"本地安装包: {ASSET_LOCAL} ({size/1024/1024:.1f} MB)")

    # 1) 定位 release（1 个 HTTPS 请求）
    rel = _api("GET",
               f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}")[1]
    rel_id = rel["id"]
    print(f"release id: {rel_id}")

    # 2) 删除同名旧资产（0~1 个请求；新版 GitHub 同名 POST 会 422，
    #    但稳妥起见先删一次）
    for a in rel.get("assets", []):
        if a["name"] == ASSET_NAME:
            st = _delete_asset(a["url"])
            print(f"删除旧资产 {ASSET_NAME}: status {st}")

    # 3) 流式分块上传新资产
    upload_url = (f"https://uploads.github.com/repos/{REPO}/releases/"
                  f"{rel_id}/assets?name={ASSET_NAME}")
    status, resp = _stream_upload(upload_url, ASSET_LOCAL)
    print(f"upload status: {status}")
    if status == 201:
        print("OK 上传成功:", resp.get("browser_download_url"))
    else:
        print("上传失败:", resp)
        sys.exit(1)


if __name__ == "__main__":
    main()
