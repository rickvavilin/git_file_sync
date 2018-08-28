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


class MyEventHandler(PatternMatchingEventHandler):
    def __init__(self, parent=None, **kwargs):
        super().__init__(**kwargs)
        self.parent = parent

    def on_any_event(self, event):
        self.parent.on_any_event(event)


class GitWatcher(object):
    def __init__(self, path=None, events_timeout=1):
        self.event_handler = MyEventHandler(ignore_patterns=['*.git*'], parent=self)
        self.path = path
        self.events_timeout = events_timeout
        self.observer = Observer()
        self.observer.schedule(self.event_handler, self.path, recursive=True)
        self.observer.start()
        self.events_list = []
        self.stopped = False
        self.git_handler = GitDirectoryHandler(path=self.path)
        self._thread = Thread(target=self._run)

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
            if v.is_directory and os.path.isdir(k):
                self.handle_empty_directory(k)
            if os.path.basename(k) == '.empty' or (v.is_directory and v.event_type == 'modified'):
                continue
            modified_files.append('[{} {}]'.format(EVENTS_ABBR.get(v.event_type), os.path.relpath(k, self.path)))
        self.git_handler.process_changes(comment=' '.join(modified_files))

        self.events_list = []

    def start(self):
        self._thread.start()

    def stop(self):
        self.stopped = True
        self._thread.join()

    def __del__(self):
        self.observer.stop()
        self.observer.join()


class GitDirectoryHandler(object):
    def __init__(self, path=None):
        self.path = path
        if not os.path.isdir(os.path.join(self.path, '.git')):
            print('create repo')
            git.Repo.init(path)
        self.repo = git.Repo(path)

    @staticmethod
    def parse_status(status_data):
        result = []
        for status_line in status_data.split('\n'):
            if ' ' in status_line:
                result.append(status_line.split(' '))
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
        status_data = self.parse_status(self.repo.git.status('--porcelain'))
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

    def process_changes(self,  comment=''):
        if self.repo.is_dirty(index=True, working_tree=True, untracked_files=True):
            self.repo.git.add('.')
            committer = git.Actor.committer()
            committer.name = 'Александр Вавилин'
            committer.email = 'admin@test.com'
            author = git.Actor.author()
            author.name = 'Александр Вавилин'
            author.email = 'admin@test.com'
            self.repo.index.commit(comment, committer=committer, author=author)
            if len(self.repo.remotes) > 0:
                self.repo.git.fetch('origin', 'master')
                try:
                    self.repo.git.merge('FETCH_HEAD')
                except git.GitCommandError:
                    traceback.print_exc()

                self.resolve_conflicts()
                self.repo.git.push('origin', 'master')
