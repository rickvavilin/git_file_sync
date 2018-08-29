from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler
from threading import Thread
import datetime
import git
import time
import os
import traceback
__author__ = 'Aleksandr Vavilin'

EVENTS_PRIORITIES = {
    'created': 100,
    'modified': 90
}

EVENTS_ABBR = {
    'created': '+',
    'modified': 'M',
    'deleted': '-',
    'moved': '=>'
}

#  ignore patterns from
#  https://github.com/hbons/SparkleShare/blob/master/Sparkles/BaseFetcher.cs#L257

IGNORE_PATTERNS = [
    "*.git*",
    "*.autosave",
    "*~",  # gedit and emacs
    ".~lock.*",  # LibreOffice
    "*.part", "*.crdownload",  # Firefox and Chromium temporary download files
    ".*.sw[a-z]", "*.un~", "*.swp", "*.swo",  # vi(m)
    ".directory",  # KDE
    "*.kate-swp",  # Kate
    ".DS_Store", "Icon\r", "._*", ".Spotlight-V100", ".Trashes",  # Mac OS X
    "*(Autosaved).graffle",  # Omnigraffle
    "Thumbs.db", "Desktop.ini",  # Windows
    "~*.tmp", "~*.TMP", "*~*.tmp", "*~*.TMP",  # MS Office
    "~*.ppt", "~*.PPT", "~*.pptx", "~*.PPTX",
    "~*.xls", "~*.XLS", "~*.xlsx", "~*.XLSX",
    "~*.doc", "~*.DOC", "~*.docx", "~*.DOCX",
    "~$*",
    "*.a$v",  # QuarkXPress
    "*/CVS/*", ".cvsignore", "*/.cvsignore",  # CVS
    "/.svn/*", "*/.svn/*",  # Subversion
    "/.hg/*", "*/.hg/*", "*/.hgignore",  # Mercurial
    "/.bzr/*", "*/.bzr/*", "*/.bzrignore"  # Bazaar

]


class MyEventHandler(PatternMatchingEventHandler):
    def __init__(self, parent=None, **kwargs):
        super().__init__(**kwargs)
        self.parent = parent

    def on_any_event(self, event):
        self.parent.on_any_event(event)


class GitWatcher(object):
    def __init__(self, path=None, events_timeout=1, notifier=None, notify_callback=None):
        self.event_handler = MyEventHandler(ignore_patterns=IGNORE_PATTERNS, parent=self)
        self.path = path
        self.events_timeout = events_timeout
        self.observer = Observer()
        self.observer.schedule(self.event_handler, self.path, recursive=True)
        self.observer.start()
        self.events_list = []
        self.stopped = False
        self.git_handler = GitDirectoryHandler(path=self.path, parent=self)
        self._thread = Thread(target=self._run)
        self.notifier = notifier
        self.notify_callback = notify_callback
        if self.notifier:
            self.notifier.parent = self

    def on_notify(self, message):
        print(message)
        if self.notify_callback:
            self.notify_callback('Синхронизация с сервером')
        self.git_handler.update_from_remote()
        if self.notify_callback:
            self.notify_callback('Синхронизация с сервером выполнена')

    def on_push(self):
        self.notifier.send_notify('hello')
        if self.notify_callback:
            self.notify_callback('Отправка файлов')

    def on_any_event(self, event):
        self.events_list.append({
            'event': event,
            'timestamp': datetime.datetime.now()
        })

    def _run(self):
        while not self.stopped:
            time.sleep(0.1)
            if len(self.events_list) > 0:
                last_event = self.events_list[-1]
                if (datetime.datetime.now()-last_event['timestamp']).total_seconds() > self.events_timeout:
                    self.process_events()

    @staticmethod
    def touch(path):
        with open(path, 'w'):
            pass

    @staticmethod
    def get_empty_file_path(path):
        return os.path.join(path, '.empty')

    def handle_empty_directory(self, path):
        dir_list = os.listdir(path)
        if len(dir_list) == 0:
            self.touch(self.get_empty_file_path(path))
        elif os.path.isfile(self.get_empty_file_path(path)) and len(dir_list) > 1:
            os.unlink(self.get_empty_file_path(path))

    def process_events(self):
        modified_paths = {}
        for event in self.events_list:
            if event['event'].src_path in modified_paths:
                if (EVENTS_PRIORITIES.get(event['event'].event_type, 100) >
                        EVENTS_PRIORITIES.get(modified_paths[event['event'].src_path].event_type, 0)):
                    modified_paths[event['event'].src_path] = event['event']
            else:
                modified_paths[event['event'].src_path] = event['event']
        modified_files = []
        for k, v in modified_paths.items():
            print(k, v)
            if v.is_directory and os.path.isdir(k):
                self.handle_empty_directory(k)
            if os.path.basename(k) == '.empty' or (v.is_directory and v.event_type == 'modified'):
                continue
            modified_files.append('[{} {}]'.format(EVENTS_ABBR.get(v.event_type), os.path.relpath(k, self.path)))
        self.git_handler.process_changes()

        self.events_list = []

    def start(self):
        self._thread.start()

    def stop(self):
        self.stopped = True
        self._thread.join()
        self.observer.stop()
        self.observer.join()
        if self.notifier:
            self.notifier.stop()

    def __del__(self):
        self.observer.stop()
        self.observer.join()


class GitDirectoryHandler(object):
    def __init__(self, path=None, parent=None):
        self.path = path
        self.parent = parent
        if not os.path.isdir(os.path.join(self.path, '.git')):
            print('create repo')
            git.Repo.init(path)
        self.repo = git.Repo(path)
        with open(os.path.join(self.path, '.git', 'info', 'exclude'), 'w') as f:
            for pattern in IGNORE_PATTERNS:
                f.write(pattern+'\n')

    @staticmethod
    def parse_status(status_data):
        result = []
        for status_line in status_data.split('\x00'):
            if ' ' in status_line:
                file_name = status_line[3:]
                result.append((status_line[:2], file_name))
        return result

    @staticmethod
    def get_resolved_file_name(name, ext, commit):
        return '{name} [{author_name}, {date}] {ext}'.format(
            name=name,
            ext=ext,
            author_name=commit.author.name,
            date=datetime.datetime.fromtimestamp(commit.committed_date).strftime('%d-%m-%Y %H-%M-%S')

        )

    def resolve_conflicts(self):
        status_data = self.parse_status(self.repo.git.status('--porcelain', '-z'))
        if len(status_data) > 0:
            print(status_data)
            for status, file_path in status_data:
                if status in ['UU', 'AA', 'AU', 'UA']:
                    remote_commit = self.repo.commit('FETCH_HEAD')
                    local_commit = self.repo.commit('HEAD')
                    file_name, file_ext = os.path.splitext(file_path)
                    self.repo.git.checkout('--theirs', file_path)
                    if os.path.isfile(os.path.join(self.path, file_path)):

                        os.rename(os.path.join(self.path, file_path),
                                  os.path.join(self.path, self.get_resolved_file_name(
                                      name=file_name,
                                      ext=file_ext,
                                      commit=remote_commit
                                  )))
                    self.repo.git.checkout('--ours', file_path)
                    if os.path.isfile(os.path.join(self.path, file_path)):
                        os.rename(os.path.join(self.path, file_path),
                                  os.path.join(self.path, self.get_resolved_file_name(
                                      name=file_name,
                                      ext=file_ext,
                                      commit=local_commit
                                  )))
                    self.repo.git.checkout('ORIG_HEAD', file_path)
                elif status in ['DU']:
                    pass
                elif status in ['UD']:
                    self.repo.git.checkout('--ours', file_path)
            self.repo.git.add('.')
            self.repo.git.update_environment(GIT_AUTHOR_NAME='git-synchronizer',
                                             GIT_AUTHOR_EMAIL='synchronizer@test.com')
            self.repo.git.commit('-m', 'fix conflicts')

    def update_from_remote(self):
        if len(self.repo.remotes) > 0:
            self.repo.git.fetch('origin', 'master')
            try:
                self.repo.git.merge('FETCH_HEAD')
            except git.GitCommandError:
                traceback.print_exc()
            self.resolve_conflicts()

    def process_changes(self):
        if self.repo.is_dirty(index=True, working_tree=True, untracked_files=True):
            status_lines = self.parse_status(self.repo.git.status('--porcelain', '-z'))
            comment = ' '.join(['[ {} {} ]'.format(sl[0], sl[1]) for sl in status_lines])
            self.repo.git.add('.')
            committer = git.Actor.committer()
            committer.name = 'Александр Вавилин'
            committer.email = 'admin@test.com'
            author = git.Actor.author()
            author.name = 'Александр Вавилин'
            author.email = 'admin@test.com'
            print(comment)
            self.repo.index.commit(comment, committer=committer, author=author)
            if len(self.repo.remotes) > 0:
                self.update_from_remote()
                self.repo.git.push('origin', 'master')
                if self.parent:
                    self.parent.on_push()
