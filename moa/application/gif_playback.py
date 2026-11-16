"""Bounded GIF playback. Frame decoding runs outside the UI process."""
import time
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QPixmap
from moa.image.gif_worker import render_gif_frame


class GifPlayback(QObject):
    frameReady = Signal(QPixmap, int, int)
    failed = Signal(str)

    def __init__(self, tasks, size, parent=None):
        super().__init__(parent)
        self.tasks = tasks
        self.size = size
        self.item = None
        self.source_key = None
        self.generation = 0
        self.future = None
        self.frame_number = 0
        self.cycles = 0
        self.finished = False
        self.deadline = 0
        self.worker_pid = None
        self.timer = QTimer(self)
        self.timer.setInterval(10)
        self.timer.timeout.connect(self.poll)

    def open(self, item):
        key = self.tasks.key(item, 0)
        if self.source_key == key:
            return
        self.stop()
        self.item = dict(item)
        self.source_key = key
        self.timer.start()
        self.poll()

    def stop(self):
        self.generation += 1
        self.item = None
        self.source_key = None
        self.frame_number = 0
        self.cycles = 0
        self.finished = False
        self.deadline = 0
        if self.future is not None:
            self.future[0].cancel()
        # Poll a running request until it completes, then release its frame bytes.
        if self.future is None:
            self.timer.stop()

    def poll(self):
        now = time.monotonic()
        if self.future is not None:
            future, generation, started = self.future
            if not future.done():
                if now - started > 15:
                    self.tasks.reset_gif_pool()
                    self.future = None
                    self.stop()
                    self.failed.emit('GIF 읽기 시간이 초과되었습니다.')
                return
            if now < self.deadline and generation == self.generation:
                return
            self.future = None
            if generation == self.generation and self.item is not None:
                try:
                    result = future.result()
                    if result['error']:
                        raise ValueError(result['error'])
                    pixmap = QPixmap()
                    if not pixmap.loadFromData(result['data'], 'PNG'):
                        raise ValueError('GIF 프레임을 표시하지 못했습니다.')
                    self.worker_pid = result['pid']
                    self.frameReady.emit(pixmap, result['width'], result['height'])
                    self.frame_number += 1
                    if self.frame_number >= result['frames']:
                        self.frame_number = 0
                        self.cycles += 1
                        loops = result['loop']
                        self.finished = loops != 0 and self.cycles >= (1 if loops is None else loops + 1)
                    self.deadline = now + result['duration'] / 1000
                except Exception as error:
                    self.stop()
                    self.failed.emit(str(error))
        if self.item is None or self.finished:
            if self.future is None:
                self.timer.stop()
            return
        if self.future is None:
            try:
                future = self.tasks.gif_executor().submit(
                    render_gif_frame, self.item, self.source_key, self.frame_number, self.size
                )
                self.future = (future, self.generation, now)
            except Exception as error:
                self.stop()
                self.failed.emit(str(error))

    def close(self):
        self.stop()
        self.timer.stop()
        self.future = None
