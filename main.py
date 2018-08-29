__author__ = 'Aleksandr Vavilin'
from git_file_sync import sync, redis_notify
import os
import time
import sys

if __name__ == '__main__':
    redis_notifier = redis_notify.RedisNotifier(host='192.168.24.4')
    redis_notifier.start()
    watcher = sync.GitWatcher(os.path.abspath(sys.argv[1]), notifier=redis_notifier)
    watcher.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        watcher.stop()
