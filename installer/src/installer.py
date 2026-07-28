# -*- coding: utf-8 -*-
r"""
StockTicker 安装向导（GUI）
- 选择安装目录（默认 %LOCALAPPDATA%\Programs\StockTicker，无需管理员）
- 可选创建桌面 / 开始菜单快捷方式
- 安装进度；完成后可立即运行
- 自动写入"控制面板-卸载"注册表项，指向内嵌的 Uninstall.exe
单文件打包后即为 StockTickerSetup.exe，内置 StockTicker.exe 与 Uninstall.exe。
"""
import sys
import os
import shutil
import subprocess
import winreg
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QLineEdit, QFileDialog,
    QVBoxLayout, QHBoxLayout, QProgressBar, QCheckBox, QMessageBox, QFrame,
    QSpacerItem, QSizePolicy,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QIcon


def resource_path(rel):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


APP_NAME = "StockTicker"
APP_VERSION = "1.0"
PUBLISHER = "StockTicker"
UNINST_REG = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"


def default_install_dir():
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser(
        "~\\AppData\\Local")
    return os.path.join(local, "Programs", APP_NAME)


def create_shortcut(target, link_path, desc=""):
    try:
        ps = (
            '$ws = New-Object -ComObject WScript.Shell;'
            f'$s = $ws.CreateShortcut("{link_path}");'
            f'$s.TargetPath = "{target}";'
            f'$s.Description = "{desc}";'
            '$s.Save()'
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, timeout=30)
        return os.path.exists(link_path)
    except Exception:
        return False


def write_uninstall_reg(install_dir, uninstall_exe):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINST_REG,
                             0, winreg.KEY_WRITE)
        sub = winreg.CreateKey(key, APP_NAME)
        winreg.SetValueEx(sub, "DisplayName", 0, winreg.REG_SZ,
                          APP_NAME + " 行情小工具")
        winreg.SetValueEx(sub, "UninstallString", 0, winreg.REG_SZ,
                          f'"{uninstall_exe}" /uninstall')
        winreg.SetValueEx(sub, "InstallLocation", 0, winreg.REG_SZ,
                          install_dir)
        winreg.SetValueEx(sub, "DisplayIcon", 0, winreg.REG_SZ,
                          os.path.join(install_dir, "StockTicker.exe"))
        winreg.SetValueEx(sub, "Publisher", 0, winreg.REG_SZ, PUBLISHER)
        winreg.SetValueEx(sub, "DisplayVersion", 0, winreg.REG_SZ,
                          APP_VERSION)
        winreg.SetValueEx(sub, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(sub, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.CloseKey(sub)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


class InstallWorker(QThread):
    progress = Signal(int, str)
    finished = Signal(bool, str)

    def __init__(self, src_exe, src_uninst, dest_dir, desktop, startmenu):
        super().__init__()
        self.src_exe = src_exe
        self.src_uninst = src_uninst
        self.dest_dir = dest_dir
        self.desktop = desktop
        self.startmenu = startmenu

    def run(self):
        try:
            os.makedirs(self.dest_dir, exist_ok=True)
            self.progress.emit(10, "正在创建安装目录…")

            exe_dst = os.path.join(self.dest_dir, "StockTicker.exe")
            self.progress.emit(20, "正在复制主程序 StockTicker.exe…")
            shutil.copyfile(self.src_exe, exe_dst)

            self.progress.emit(55, "正在复制卸载程序 Uninstall.exe…")
            uninst_dst = os.path.join(self.dest_dir, "Uninstall.exe")
            if os.path.exists(self.src_uninst):
                shutil.copyfile(self.src_uninst, uninst_dst)
            else:
                uninst_dst = exe_dst  # 兜底：没有独立卸载器时指向安装向导

            self.progress.emit(70, "正在创建快捷方式…")
            if self.desktop:
                dl = os.path.join(os.environ.get("USERPROFILE", "."),
                                  "Desktop", APP_NAME + ".lnk")
                create_shortcut(exe_dst, dl, APP_NAME + " 行情小工具")
            if self.startmenu:
                sm = os.path.join(os.environ.get("APPDATA", "."),
                                  "Microsoft\\Windows\\Start Menu\\Programs",
                                  APP_NAME + ".lnk")
                create_shortcut(exe_dst, sm, APP_NAME + " 行情小工具")

            self.progress.emit(85, "正在写入卸载信息…")
            write_uninstall_reg(self.dest_dir, uninst_dst)

            self.progress.emit(100, "安装完成")
            self.finished.emit(True, self.dest_dir)
        except Exception as e:
            self.finished.emit(False, str(e))


class Installer(QWidget):
    def __init__(self):
        super().__init__()
        self.dest_dir = default_install_dir()
        self.exe_dst = None
        self._build_ui()
        self.worker = None

    def _build_ui(self):
        self.setWindowTitle(APP_NAME + " 安装向导")
        self.setFixedSize(460, 340)
        try:
            self.setWindowIcon(QIcon(resource_path("app.ico")))
        except Exception:
            pass

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(10)

        title = QLabel(APP_NAME + " 行情小工具")
        title.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))
        sub = QLabel("桌面浮动行情 · 实时刷新 · 迷你 K 线")
        sub.setFont(QFont("Microsoft YaHei", 10))
        sub.setStyleSheet("color:#6a6f77;")
        root.addWidget(title)
        root.addWidget(sub)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("color:#cfd2d8;")
        root.addWidget(line)

        root.addWidget(QLabel("安装位置："))

        path_row = QHBoxLayout()
        self.path_edit = QLineEdit(self.dest_dir)
        self.path_edit.setFont(QFont("Consolas", 10))
        browse = QPushButton("浏览…")
        browse.setFixedWidth(72)
        browse.clicked.connect(self._browse)
        path_row.addWidget(self.path_edit)
        path_row.addWidget(browse)
        root.addLayout(path_row)

        self.cb_desktop = QCheckBox("创建桌面快捷方式")
        self.cb_desktop.setChecked(True)
        self.cb_startmenu = QCheckBox("创建开始菜单快捷方式")
        self.cb_startmenu.setChecked(True)
        root.addWidget(self.cb_desktop)
        root.addWidget(self.cb_startmenu)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setVisible(False)
        root.addWidget(self.bar)

        self.status = QLabel("")
        self.status.setStyleSheet("color:#6a6f77;font-size:11px;")
        self.status.setMinimumHeight(16)
        root.addWidget(self.status)

        # 安装完成后“运行”勾选框（默认勾选，完成时按此启动程序）
        self.cb_run = QCheckBox("安装完成后运行 StockTicker")
        self.cb_run.setChecked(True)
        self.cb_run.setVisible(False)
        root.addWidget(self.cb_run)

        root.addItem(QSpacerItem(0, 0, QSizePolicy.Minimum,
                                 QSizePolicy.Expanding))

        btn_row = QHBoxLayout()
        btn_row.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding,
                                    QSizePolicy.Minimum))
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setFixedWidth(90)
        self.btn_cancel.clicked.connect(self.close)
        self.btn_main = QPushButton("安装")
        self.btn_main.setFixedWidth(90)
        self.btn_main.setDefault(True)
        self.btn_main.clicked.connect(self._install)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_main)
        root.addLayout(btn_row)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(
            self, "选择安装目录", self.path_edit.text())
        if d:
            self.path_edit.setText(d)

    def _install(self):
        dest = self.path_edit.text().strip()
        if not dest:
            QMessageBox.warning(self, "提示", "请填写安装目录。")
            return
        # 尝试在此创建目录以验证可写
        try:
            os.makedirs(dest, exist_ok=True)
        except Exception as e:
            QMessageBox.warning(self, "无法写入",
                                f"该目录不可写：\n{dest}\n\n错误：{e}")
            return

        src_exe = resource_path("StockTicker.exe")
        src_uninst = resource_path("Uninstall.exe")
        if not os.path.exists(src_exe):
            QMessageBox.critical(self, "错误",
                                 "安装包内未找到 StockTicker.exe，"
                                 "安装程序可能损坏。")
            return

        self.dest_dir = dest
        self.exe_dst = os.path.join(dest, "StockTicker.exe")

        # 锁定 UI
        for w in (self.path_edit, self.cb_desktop, self.cb_startmenu,
                  self.btn_main, self.btn_cancel):
            w.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setValue(0)
        self.status.setText("准备安装…")

        self.worker = InstallWorker(
            src_exe, src_uninst, dest,
            self.cb_desktop.isChecked(), self.cb_startmenu.isChecked())
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_progress(self, val, text):
        self.bar.setValue(val)
        self.status.setText(text)

    def _on_finished(self, ok, info):
        self.bar.setValue(100 if ok else self.bar.value())
        if ok:
            self.status.setText("安装完成！可立即运行或稍后从快捷方式启动。")
            self.cb_run.setVisible(True)
            self.btn_cancel.setVisible(False)
            self.btn_main.setText("完成")
            self.btn_main.setEnabled(True)
            try:
                self.btn_main.clicked.disconnect()
            except Exception:
                pass
            self.btn_main.clicked.connect(self._finish)
        else:
            self.status.setText("安装失败：" + info)
            self.btn_cancel.setEnabled(True)
            self.btn_main.setText("重试")
            self.btn_main.setEnabled(True)
            try:
                self.btn_main.clicked.disconnect()
            except Exception:
                pass
            self.btn_main.clicked.connect(self._install)

    def _finish(self):
        # 勾选时在关闭安装向导前，用系统原生方式启动程序（完全脱离父进程，
        # 比 subprocess.Popen 更可靠，避免“点了打不开”的问题）
        if self.cb_run.isChecked() and self.exe_dst and os.path.exists(self.exe_dst):
            try:
                os.startfile(self.exe_dst)
            except Exception:
                try:
                    subprocess.Popen([self.exe_dst])
                except Exception:
                    pass
        self.close()


def main():
    app = QApplication(sys.argv)
    try:
        app.setWindowIcon(QIcon(resource_path("app.ico")))
    except Exception:
        pass
    w = Installer()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
