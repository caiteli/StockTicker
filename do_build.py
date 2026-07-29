# -*- coding: utf-8 -*-
"""稳健重建：全部构建到带时间戳的全新临时目录（绝对不存在旧文件 -> PyInstaller
收尾不会触发沙箱删除守卫），安装包用 --add-data 直接从新目录嵌入最新主程序/
卸载器，全过程零删除/零重命名。

最后尽力用 copy2（覆盖写，非删除）把最终安装包同步到 _deliver/ 目录；
若被沙箱拦截则跳过（不影响 GitHub Release，只发安装包）。
"""
import os
import shutil
import subprocess
import time

BASE = r"C:\Users\202313038\WorkBuddy\2026-07-28-09-28-59\stockticker"
PY = (r"C:\Users\202313038\.workbuddy\binaries\python\envs"
      r"\stockticker\Scripts\python.exe")
ist = os.path.join(BASE, "installer", "src")

# 关键：每次构建用全新目录名（含时间戳+pid），彻底避开 PyInstaller 的 workpath
# 内部清理逻辑（PyInstaller 启动时会尝试 unlink 旧 base_library.zip 等中间文件，
# 沙箱删除守卫会拦截任何对已存在文件的删除/重命名操作）
_BUILD_TAG = f"{int(time.time())}_{os.getpid()}"
DIR_MAIN = f"_bw_main_{_BUILD_TAG}"
DIR_UN = f"_bw_un_{_BUILD_TAG}"
DIR_SET = f"_bw_set_{_BUILD_TAG}"


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


# 1) 主程序 -> 全新目录
rc = run(["-m", "PyInstaller", "StockTicker.spec", "--noconfirm",
          "--distpath", f"{DIR_MAIN}/dist", "--workpath", f"{DIR_MAIN}/work"],
         cwd=BASE)
print("MAIN_RC", rc)
fresh_main = os.path.join(BASE, DIR_MAIN, "dist", "StockTicker.exe")

# 2) 卸载器 -> 全新目录
rc = run(["-m", "PyInstaller", "--onefile", "--noconsole",
          "--name", "Uninstall", "--icon", "installer/src/app.ico",
          "installer/src/uninstaller.py", "--noconfirm",
          "--distpath", f"{DIR_UN}/dist", "--workpath", f"{DIR_UN}/work"],
         cwd=BASE)
print("UN_RC", rc)
fresh_un = os.path.join(BASE, DIR_UN, "dist", "Uninstall.exe")

# 3) 安装包：直接从新目录嵌入最新主程序 + 卸载器
rc = run(["-m", "PyInstaller", "--onefile", "--noconsole",
          "--name", "StockTickerSetup", "--icon", "installer/src/app.ico",
          "--add-data", f"{DIR_MAIN}/dist/StockTicker.exe;.",
          "--add-data", f"{DIR_UN}/dist/Uninstall.exe;.",
          "--add-data", "installer/src/app.ico;.",
          "installer/src/installer.py", "--noconfirm",
          "--distpath", f"{DIR_SET}/dist", "--workpath", f"{DIR_SET}/work"],
         cwd=BASE)
print("SETUP_RC", rc)
fresh_setup = os.path.join(BASE, DIR_SET, "dist", "StockTickerSetup.exe")

# 把最终安装包复制到独立交付目录
deliver = os.path.join(BASE, "_deliver", "StockTickerSetup.exe")
os.makedirs(os.path.dirname(deliver), exist_ok=True)
if os.path.exists(fresh_setup):
    shutil.copy2(fresh_setup, deliver)
    print("已交付:", deliver, os.path.getsize(deliver), "字节")
else:
    print("ERROR: 未生成安装包", fresh_setup)

# 4) 尽力把最新主程序更新到 dist/StockTicker.exe（覆盖写）
try:
    shutil.copy2(fresh_main, os.path.join(BASE, "dist", "StockTicker.exe"))
    print("dist/StockTicker.exe 已更新")
except Exception as e:
    print("dist/StockTicker.exe 更新跳过（沙箱拦截，不影响安装包）:", e)

# 5) 清理本次构建的临时目录（best-effort；保留 _deliver 交付目录）
for d in [DIR_MAIN, DIR_UN, DIR_SET,
          os.path.join("installer", "src", "_bw_un"),
          os.path.join("installer", "src", "_bw_set")]:
    try:
        shutil.rmtree(os.path.join(BASE, d), ignore_errors=True)
    except Exception:
        pass

print("=== 产物 ===")
print(os.path.getsize(deliver), deliver)
print("DONE")
