"""Debounced JSON writer on the shared single-writer file IO executor."""
from collections import deque
from PySide6.QtCore import QObject,QTimer,Signal
from moa.storage.json_store import write_snapshot

class LibrarySaver(QObject):
    changed=Signal(str)
    failed=Signal(str)
    idle=Signal()
    def __init__(self,store,executor,parent=None):
        super().__init__(parent);self.store=store;self.executor=executor;self.dirty=False;self.futures=deque();self.last_error=''
        self.debounce=QTimer(self);self.debounce.setSingleShot(True);self.debounce.setInterval(300);self.debounce.timeout.connect(self.flush)
        self.timer=QTimer(self);self.timer.setInterval(60);self.timer.timeout.connect(self.poll);self.timer.start()
        store.save_handler=self.request
    @property
    def pending(self):return self.dirty or bool(self.futures)
    def request(self):
        self.dirty=True;self.last_error='';self.debounce.start();self.changed.emit('분류 정보 저장 대기…')
    def flush(self,force=False):
        self.debounce.stop()
        if (self.futures and not force) or not self.dirty:return
        snapshot=self.store.snapshot();self.dirty=False;self.last_error=''
        self.futures.append(self.executor.submit(write_snapshot,self.store.directory,snapshot))
        self.changed.emit('분류 정보 저장 중…')
    def poll(self):
        completed=False
        while self.futures and self.futures[0].done():
            future=self.futures.popleft();completed=True
            try:future.result()
            except Exception as error:
                self.dirty=True;self.last_error=str(error);self.changed.emit('분류 정보 저장 실패');self.failed.emit(str(error));return
        if not completed:return
        if not self.futures and self.dirty and not self.last_error:self.flush()
        elif not self.pending:self.changed.emit('');self.idle.emit()
    def close(self):
        if self.pending:raise RuntimeError('분류 저장이 끝나지 않았습니다.')
        self.debounce.stop();self.timer.stop();self.store.save_handler=None
