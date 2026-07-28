# -*- coding: utf-8 -*-
"""
StockTicker 轻量卸载程序（无第三方依赖，体积很小）
- 从注册表读取安装目录
- 确认后删除：主程序、快捷方式、卸载注册表项
- 进程退出后自删除安装目录（避免删除自身文件锁）
可由"控制面板-卸载"或双击 Uninstall.exe 触发。
"""
import sys
import os
import shutil
import winreg
import subprocess
import tempfile
import ctypes

APP_NAME = "StockTicker"
UNINST_REG = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"

MB_OK = 0x0
MB_YESNO = 0x4
MB_ICONINFO = 0x40
MB_ICONQ = 0x20
IDYES = 6


def msgbox(text, title=APP_NAME, flags=MB_ICONINFO):
    try:
        return ctypes.windll.user32.MessageBoxW(0, text, title, flags)
    except Exception:
        return 0


def get_install_dir():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             UNINST_REG + "\\" + APP_NAME, 0, winreg.KEY_READ)
        val, _ = winreg.QueryValueEx(key, "InstallLocation")
        winreg.CloseKey(key)
        return val
    except Exception:
        return None


def remove_reg():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             UNINST_REG, 0, winreg.KEY_WRITE)
        winreg.DeleteKey(key, APP_NAME)
        winreg.CloseKey(key)
    except Exception:
        pass


def remove_shortcuts():
    try:
        dl = os.path.join(os.environ.get("USERPROFILE", "."),
                          "Desktop", APP_NAME + ".lnk")
        if os.path.exists(dl):
            os.remove(dl)
    except Exception:
        pass
    try:
        sm = os.path.join(os.environ.get("APPDATA", "."),
                          "Microsoft\\Windows\\Start Menu\\Programs",
                          APP_NAME + ".lnk")
        if os.path.exists(sm):
            os.remove(sm)
    except Exception:
        pass


def schedule_self_cleanup(install_dir):
    """进程退出后自删除安装目录与卸载器自身，且全程不弹出 cmd 窗口。

    关键修复：
    1) 先把正在运行的本程序(Uninstall.exe)移到 temp（同卷 rename，运行中的
       exe 也允许），使原安装目录立即变空 → rmdir 无需等待本进程退出即可成功，
       从根本上解决“卸载后目录/卸载器残留”。
    2) 用 CREATE_NO_WINDOW(0x08000000) 启动清理 bat，彻底消除黑窗口。
    3) 用重试循环确保：本进程彻底退出后，temp 里的卸载器副本也被删掉、bat 自删。
    """
    try:
        exe = os.path.abspath(sys.executable)
        # 把自身移到 temp（同卷内 rename，Windows 允许移动运行中的 exe）
        moved = exe
        try:
            moved = os.path.join(
                tempfile.gettempdir(),
                "stockticker_uninst_%d.tmp" % os.getpid())
            os.replace(exe, moved)
        except Exception:
            moved = exe   # 移动失败则回退：仍留在原位，靠循环延迟删除

        bat = os.path.join(
            tempfile.gettempdir(),
            "stockticker_cleanup_%d.bat" % os.getpid())
        with open(bat, "w", encoding="utf-8") as f:
            f.write("@echo off\n")
            f.write(":loop\n")
            f.write("ping -n 2 127.0.0.1 >nul\n")   # 等待本进程退出
            f.write('rmdir /s /q "%s" 2>nul\n' % install_dir)
            f.write('del /q "%s" 2>nul\n' % moved)
            f.write('if exist "%s" goto loop\n' % moved)
            f.write('del /q "%~f0" >nul 2>nul\n')   # 自删 bat 自身
        subprocess.Popen(
            [bat],
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            close_fds=True,
        )
    except Exception:
        pass


def main():
    if "/uninstall" not in sys.argv and "/UNINSTALL" not in sys.argv:
        # 直接双击也按卸载处理
        pass

    d = get_install_dir()
    if not d or not os.path.isdir(d):
        msgbox("未找到 StockTicker 的安装记录，可能已被卸载。",
               "卸载 StockTicker")
        return

    r = msgbox(
        "确定要卸载 StockTicker 吗？\n\n安装目录：\n" + d,
        "卸载 StockTicker",
        MB_YESNO | MB_ICONQ,
    )
    if r != IDYES:
        return

    remove_shortcuts()
    remove_reg()

    # 删除安装目录内的所有文件/子目录，但跳过正在运行的本程序自身
    self_path = os.path.abspath(sys.executable)
    try:
        for name in os.listdir(d):
            fp = os.path.join(d, name)
            if os.path.abspath(fp) == self_path:
                continue
            try:
                if os.path.isfile(fp) or os.path.islink(fp):
                    os.remove(fp)
                else:
                    shutil.rmtree(fp, ignore_errors=True)
            except Exception:
                pass
    except Exception:
        pass

    # 先提示，再调度自删（调度后 main 返回、进程退出，便于 temp 副本被清理）
    msgbox("StockTicker 已卸载。", "卸载 StockTicker")
    schedule_self_cleanup(d)


if __name__ == "__main__":
    main()
