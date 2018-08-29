from git_file_sync_ui import gui
from git_file_sync import sync, redis_notify
import os
import time
import sys
__author__ = 'Aleksandr Vavilin'


def notify_callback(message):
    print(message)
    mw.tray_icon.showMessage(
        "Tray Program",
        message,
        gui.QSystemTrayIcon.Information,
        2000
    )

if __name__ == '__main__':

    redis_notifier = redis_notify.RedisNotifier(host='192.168.24.4')
    redis_notifier.start()
    watcher = sync.GitWatcher(os.path.abspath('data'), notifier=redis_notifier, notify_callback=notify_callback)
    watcher.start()
    app, mw = gui.init()
    gui.exec_app(app)
    watcher.stop()
