from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler, DirModifiedEvent
from threading import Thread
import datetime
import git
import time
import os
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

    def touch(self, path):
        with open(path, 'w'):
            pass

    def get_empty_file_path(self, path):
        return os.path.join(path, '.empty')

    def handle_empty_directory(self, path):
        dir_list = os.listdir(path)
        if len(dir_list)==0:
            self.touch(self.get_empty_file_path(path))
        elif os.path.isfile(self.get_empty_file_path(path)) and len(dir_list)>1:
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
        self.repo = git.Repo(path)
        if not os.path.isdir(os.path.join('.git')):
            self.repo.init(path)

    def process_changes(self,  comment=''):
        if self.repo.is_dirty(index=True, working_tree=True, untracked_files=True):
            self.repo.git.add('.')
            committer = git.Actor.committer()
            committer.name = 'admin'
            committer.email = 'admin@test.com'
            self.repo.index.commit(comment, committer=committer)
            if len(self.repo.remotes) > 0:
                origin = self.repo.remotes['origin']
                print(origin.fetch())
                
                self.repo.git.push('origin', 'master')


