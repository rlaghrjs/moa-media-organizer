"""UI-side IPC client for the video process."""
import multiprocessing
import time
from pathlib import Path
from PySide6.QtCore import QObject,QTimer,Signal
from moa.video.worker import video_main

class VideoService(QObject):
    state=Signal(dict)
    error=Signal(str)
    def __init__(self,dll,parent=None):
        super().__init__(parent);self.dll=Path(dll);self.process=None;self.connection=None;self.token=0;self.active=False;self.started=0;self.ready=False
        self.timer=QTimer(self);self.timer.timeout.connect(self.poll);self.timer.start(60)
    def start(self,window):
        if self.process and self.process.is_alive():return
        if not self.dll.is_file():raise RuntimeError('libmpv-2.dll을 찾지 못했습니다. vendor/mpv 폴더를 확인하세요.')
        self.close_process();ctx=multiprocessing.get_context('spawn');self.connection,child=ctx.Pipe()
        self.process=ctx.Process(target=video_main,args=(child,str(self.dll),window),name='MoaVideoPlayer',daemon=True)
        self.ready=False;self.started=time.monotonic();self.process.start();child.close()
    def load(self,path,window):
        try:
            self.start(window);self.token+=1;self.active=True
            self.send('load',path=path,token=self.token)
        except Exception as error:self.active=False;self.error.emit(str(error))
    def send(self,action,**values):
        if self.connection:
            try:self.connection.send({'action':action,**values})
            except (OSError,EOFError) as error:self.error.emit(str(error))
    def stop(self):self.active=False;self.token+=1;self.send('stop')
    def poll(self):
        if not self.connection:return
        try:
            for _ in range(25):
                if not self.connection.poll():break
                event=self.connection.recv()
                if event['type']=='ready':self.ready=True
                elif event.get('token')==self.token and self.active:
                    if event['type']=='error':self.error.emit(event['message']);self.active=False
                    else:self.state.emit(event)
            if self.process and not self.process.is_alive() and self.active:
                self.active=False;self.error.emit('영상 재생 프로세스가 종료되었습니다. 다시 열어 주세요.')
            elif not self.ready and time.monotonic()-self.started>15:
                self.close_process();self.error.emit('영상 엔진의 시작 시간이 초과되었습니다. 다시 시도해 주세요.')
        except (OSError,EOFError):
            active=self.active;self.close_process()
            if active:self.error.emit('영상 엔진과의 연결이 종료되었습니다.')
    def close_process(self):
        if self.process:
            self.send('quit');self.process.join(.6)
            if self.process.is_alive():self.process.terminate();self.process.join(.6)
            if not self.process.is_alive():self.process.close()
        if self.connection:self.connection.close()
        self.process=None;self.connection=None;self.active=False
    def close(self):self.timer.stop();self.close_process()
