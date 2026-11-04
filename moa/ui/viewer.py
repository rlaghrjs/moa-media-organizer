from pathlib import Path
from PySide6.QtCore import Qt,Signal
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QStackedWidget,QSlider,QFrame
from moa.contracts import is_video
from moa.sources.media_source import available
from moa.ui.photo_canvas import PhotoCanvas
from moa.video.service import VideoService

def time_text(seconds):
    seconds=max(0,int(seconds));minutes,seconds=divmod(seconds,60);hours,minutes=divmod(minutes,60)
    return f'{hours}:{minutes:02}:{seconds:02}' if hours else f'{minutes}:{seconds:02}'

class Viewer(QWidget):
    back=Signal();step=Signal(int);fill=Signal();fullscreen=Signal();playback=Signal(bool)
    def __init__(self,tasks,dll,parent=None):
        super().__init__(parent);self.setFocusPolicy(Qt.FocusPolicy.StrongFocus);self.tasks=tasks;self.current=None;self.photo_key=None;self.duration=0;self.paused=True;self.muted=False
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(12)
        head=QHBoxLayout();layout.addLayout(head)
        button=QPushButton('← 목록');button.clicked.connect(self.leave);head.addWidget(button)
        self.name=QLabel();self.name.setWordWrap(True);head.addWidget(self.name,1)
        self.fill_button=QPushButton('화면 채우기');self.fill_button.setCheckable(True);self.fill_button.clicked.connect(self.fill);head.addWidget(self.fill_button)
        self.fullscreen_button=QPushButton('전체 화면 (F11)');self.fullscreen_button.clicked.connect(self.fullscreen);head.addWidget(self.fullscreen_button)
        self.stack=QStackedWidget();layout.addWidget(self.stack,1)
        self.photo=PhotoCanvas();self.stack.addWidget(self.photo)
        self.video_host=QFrame();self.video_host.setAttribute(Qt.WidgetAttribute.WA_NativeWindow);self.video_host.setStyleSheet('background: #11151b;');self.video_host.setMinimumSize(180,180);self.stack.addWidget(self.video_host)
        self.message=QLabel('파일을 준비하고 있습니다…');self.message.setAlignment(Qt.AlignmentFlag.AlignCenter);self.message.setWordWrap(True);self.message.setStyleSheet('background:#edf1f6;color:#536174;');self.stack.addWidget(self.message)
        self.photo_controls=QWidget();row=QHBoxLayout(self.photo_controls);row.setContentsMargins(0,0,0,0);row.addStretch()
        self.zoom_label=QLabel('화면 맞춤')
        for text,callback in [('−',lambda:self.photo.zoom(1/1.25)),('＋',lambda:self.photo.zoom(1.25)),('화면 맞춤',self.photo.fit),('회전',self.photo.rotate)]:
            button=QPushButton(text);button.clicked.connect(callback);row.addWidget(button)
            if text=='−':row.addWidget(self.zoom_label)
        row.addStretch();layout.addWidget(self.photo_controls);self.photo.zoomChanged.connect(self.zoom_label.setText)
        self.video_controls=QWidget();control=QVBoxLayout(self.video_controls);control.setContentsMargins(0,0,0,0)
        seekrow=QHBoxLayout();control.addLayout(seekrow);self.elapsed=QLabel('0:00');self.length=QLabel('0:00');self.seek=QSlider(Qt.Orientation.Horizontal);self.seek.setRange(0,0)
        seekrow.addWidget(self.elapsed);seekrow.addWidget(self.seek,1);seekrow.addWidget(self.length)
        row=QHBoxLayout();control.addLayout(row);row.addStretch();self.play=QPushButton('재생');row.addWidget(self.play);self.mute=QPushButton('음소거');row.addWidget(self.mute)
        row.addWidget(QLabel('음량'));self.volume=QSlider(Qt.Orientation.Horizontal);self.volume.setRange(0,100);self.volume.setValue(70);self.volume.setMaximumWidth(160);row.addWidget(self.volume);row.addStretch();layout.addWidget(self.video_controls)
        nav=QHBoxLayout();nav.addStretch();self.previous=QPushButton('이전 파일');self.previous.clicked.connect(lambda:self.step.emit(-1));nav.addWidget(self.previous);self.position=QLabel();nav.addWidget(self.position);self.next=QPushButton('다음 파일');self.next.clicked.connect(lambda:self.step.emit(1));nav.addWidget(self.next);nav.addStretch();layout.addLayout(nav)
        self.note=QLabel();self.note.setAlignment(Qt.AlignmentFlag.AlignCenter);self.note.setStyleSheet('color:#728095;font-size:11px;');layout.addWidget(self.note)
        self.player=VideoService(dll,self);self.player.state.connect(self.video_state);self.player.error.connect(self.video_error)
        self.play.clicked.connect(lambda:self.player.send('pause',value=not self.paused));self.mute.clicked.connect(lambda:self.player.send('mute',value=not self.muted))
        self.volume.valueChanged.connect(lambda value:self.player.send('volume',value=value))
        self.seek.sliderReleased.connect(lambda:self.player.send('seek',value=self.seek.value()/1000))
        self.seek.valueChanged.connect(lambda value: self.player.send('seek',value=value/1000) if not self.seek.isSliderDown() else None)
        self.tasks.ready.connect(self.asset_ready)
    def open(self,item,index,total):
        self.player.stop();self.playback.emit(False);self.current=dict(item);self.photo_key=None
        self.name.setText(Path(item['path']).name+('  [ZIP]' if item.get('archive') else ''));self.name.setToolTip(item['path']);self.position.setText(f'{index+1} / {total}');self.previous.setEnabled(index>0);self.next.setEnabled(index<total-1)
        video=is_video(item['path']);self.photo_controls.setVisible(not video);self.video_controls.setVisible(video)
        self.note.setText('영상은 내부 libmpv 엔진으로 재생됩니다.' if video else '사진을 드래그해 이동 · 마우스 휠로 확대/축소')
        if not available(item):self.video_error('파일을 찾을 수 없습니다. 외부에서 이동·삭제했는지 확인하세요.');return
        if video:
            self.paused=True;self.play.setText('재생');self.elapsed.setText('0:00');self.length.setText('0:00');self.seek.blockSignals(True);self.seek.setRange(0,0);self.seek.blockSignals(False)
            self.stack.setCurrentWidget(self.video_host)
            self.player.load(item['path'],int(self.video_host.winId()))
        else:
            self.stack.setCurrentWidget(self.message);self.message.setText('사진을 준비하고 있습니다…');self.asset_ready('')
    def asset_ready(self,key):
        if not self.current or is_video(self.current['path']):return
        wanted=self.tasks.key(self.current,4096)
        if key and key!=wanted:return
        pixmap=self.tasks.request(self.current,4096,priority=0)
        if pixmap is not None and self.photo_key!=wanted:
            self.photo_key=wanted;self.photo.set_photo(pixmap);self.stack.setCurrentWidget(self.photo)
        elif wanted in self.tasks.errors:self.message.setText('사진을 열지 못했습니다.\n'+self.tasks.errors[wanted]);self.stack.setCurrentWidget(self.message)
    def video_state(self,state):
        if not self.current or not is_video(self.current['path']):return
        self.duration=state['duration'];self.paused=state['paused'];self.muted=state['muted'];self.play.setText('재생' if self.paused else '일시정지');self.mute.setText('음소거 해제' if self.muted else '음소거');self.playback.emit(not self.paused)
        self.elapsed.setText(time_text(state['position']));self.length.setText(time_text(self.duration))
        if not self.seek.isSliderDown():
            self.seek.blockSignals(True);self.seek.setRange(0,max(0,int(self.duration*1000)));self.seek.setValue(int(state['position']*1000));self.seek.blockSignals(False)
        self.volume.blockSignals(True);self.volume.setValue(int(state['volume']));self.volume.blockSignals(False)
    def video_error(self,message):
        self.player.stop();self.playback.emit(False);self.message.setText('파일을 열지 못했습니다.\n\n'+message+'\n\n목록으로 돌아가 파일을 다시 열어 주세요.');self.stack.setCurrentWidget(self.message)
    def leave(self):self.stop();self.back.emit()
    def stop(self):self.player.stop();self.playback.emit(False);self.current=None;self.photo_key=None
    def close_service(self):self.player.close()
