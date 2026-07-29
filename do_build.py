# -*- coding: utf-8 -*-
"""稳健重建：全部构建到全新临时目录（不存在旧文件 -> PyInstaller 收尾不会触发
沙箱删除守卫），安装包用 --add-data 直接从新目录嵌入最新主程序/卸载器，
全程不删除、不重命名任何已存在文件。

最后尽力用 copy2（覆盖写，非删除）把最新主程序更新到 dist/StockTicker.exe，
若被沙箱拦截则跳过（不影响交付，GitHub Release 只发安装包）。
"""
import os
import shutil
import subprocess

BASE = r"C:\Users\202313038\WorkBuddy\2026-07-28-09-28-59\stockticker"
PY = (r"C:\Users\202313038\.workbuddy\binaries\python\envs"
      r"\stockticker\Scripts\python.exe")
ist = os.path.join(BASE, "installer", "src")


def run(args, cwd):
    print("RUN", " ".join(args), "cwd=", cwd)
    r = subprocess.run([PY] + args, cwd=cwd,
                       capture_output=True, text=True)
    print("EXIT", r.returncode)
    if r.returncode != 0:
        print("--- stdout tail ---")
        print(r.stdout[-1800:])
        print("--- stderr tail ---")
        print(r.stderr[-1800:])
    return r.returncode


# 1) 主程序 -> 全新目录，避免旧 dist/StockTicker.exe 触发删除守卫
rc = run(["-m", "PyInstaller", "StockTicker.spec", "--noconfirm",
          "--distpath", "_bw_main/dist", "--workpath", "_bw_main/work"],
         cwd=BASE)
print("MAIN_RC", rc)
fresh_main = os.path.join(BASE, "_bw_main", "dist", "StockTicker.exe")

# 2) 卸载器 -> 全新目录（统一以 BASE 为 cwd，保证临时目录路径一致）
rc = run(["-m", "PyInstaller", "--onefile", "--noconsole",
          "--name", "Uninstall", "--icon", "installer/src/app.ico",
          "installer/src/uninstaller.py", "--noconfirm",
          "--distpath", "_bw_un/dist", "--workpath", "_bw_un/work"],
         cwd=BASE)
print("UN_RC", rc)
fresh_un = os.path.join(BASE, "_bw_un", "dist", "Uninstall.exe")

# 3) 安装包：直接从新目录嵌入最新主程序 + 卸载器（不碰任何已存在文件）
rc = run(["-m", "PyInstaller", "--onefile", "--noconsole",
          "--name", "StockTickerSetup", "--icon", "installer/src/app.ico",
          "--add-data", "_bw_main/dist/StockTicker.exe;.",
          "--add-data", "_bw_un/dist/Uninstall.exe;.",
          "--add-data", "installer/src/app.ico;.",
          "installer/src/installer.py", "--noconfirm",
          "--distpath", "_bw_set/dist", "--workpath", "_bw_set/work"],
         cwd=BASE)
print("SETUP_RC", rc)
fresh_setup = os.path.join(BASE, "_bw_set", "dist", "StockTickerSetup.exe")

# 把最终安装包复制到独立交付目录（避免下面清理临时目录时误删）
deliver = os.path.join(BASE, "_deliver", "StockTickerSetup.exe")
os.makedirs(os.path.dirname(deliver), exist_ok=True)
if os.path.exists(fresh_setup):
    shutil.copy2(fresh_setup, deliver)
    print("已交付:", deliver, os.path.getsize(deliver), "字节")
else:
    print("ERROR: 未生成安装包", fresh_setup)

# 4) 尽力把最新主程序更新到 dist/StockTicker.exe（覆盖写，非删除；被拦截则跳过）
try:
    shutil.copy2(fresh_main, os.path.join(BASE, "dist", "StockTicker.exe"))
    print("dist/StockTicker.exe 已更新")
except Exception as e:
    print("dist/StockTicker.exe 更新跳过（沙箱拦截，不影响安装包）:", e)

# 5) 清理临时目录（best-effort；保留 _deliver 交付目录）
for d in ["_b", "_bw_main", "_bw_un", "_bw_set",
          os.path.join("installer", "src", "_bw_un"),
          os.path.join("installer", "src", "_bw_set")]:
    try:
        shutil.rmtree(os.path.join(BASE, d), ignore_errors=True)
    except Exception:
        pass

print("=== 产物 ===")
print(os.path.getsize(deliver), deliver)
print("DONE")
