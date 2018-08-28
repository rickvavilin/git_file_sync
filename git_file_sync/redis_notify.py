import redis
import threading


class RedisNotifier(object):
    def __init__(self, host='127.0.0.1', port=6379, pubsub_channel_name='git_sync', parent=None):
        self.redis = redis.Redis(host=host, port=port)
        self.parent = parent
        self.pubsub_channel_name = pubsub_channel_name
        self.pubsub = self.redis.pubsub()
        self.pubsub.subscribe(self.pubsub_channel_name)
        self.thread = threading.Thread(target=self._run)

    def _run(self):
        try:
            for message in self.pubsub.listen():
                if message['type'] == 'message':
                    if self.parent:
                        self.parent.on_notify(message['data'])
        finally:
            self.pubsub.unsubscribe(self.pubsub_channel_name)

    def start(self):
        self.thread.start()

    def stop(self):
        self.pubsub.unsubscribe(self.pubsub_channel_name)
        self.thread.join()

    def send_notify(self, data):
        self.redis.publish(self.pubsub_channel_name, data)

    def __del__(self):
        self.stop()
