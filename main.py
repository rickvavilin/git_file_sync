__author__ = 'Aleksandr Vavilin'
from git_file_sync import api
import os
import time

if __name__ == '__main__':
    watcher = api.GitWatcher(os.path.abspath('data'))
    watcher.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        watcher.stop()
