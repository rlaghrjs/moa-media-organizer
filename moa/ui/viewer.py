from pathlib import Path
from PySide6.QtCore import Qt,Signal,QTimer
from PySide6.QtGui import QPixmap,QCursor
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QStackedWidget,QSlider,QFrame,QApplication
from moa.contracts import is_video
from moa.sources.media_source import available
from moa.ui.photo_canvas import PhotoCanvas
from moa.application.gif_playback import GifPlayback
from moa.video.service import VideoService

def time_text(seconds):
    seconds=max(0,int(seconds));minutes,seconds=divmod(seconds,60);hours,minutes=divmod(minutes,60)
    return f'{hours}:{minutes:02}:{seconds:02}' if hours else f'{minutes}:{seconds:02}'

class Viewer(QWidget):
    back=Signal();step=Signal(int);fill=Signal();fullscreen=Signal();playback=Signal(bool)
    def __init__(self,tasks,dll,parent=None):
        super().__init__(parent);self.setFocusPolicy(Qt.FocusPolicy.StrongFocus);self.tasks=tasks;self.current=None;self.photo_key=None;self.duration=0;self.paused=True;self.muted=False
        self.fullscreen_mode=False
        layout=QVBoxLayout(self);self.main_layout=layout;layout.setContentsMargins(0,0,0,0);layout.setSpacing(12)
        self.top_bar=QWidget(self);self.top_bar.setObjectName('ViewerTopBar')
        head=QHBoxLayout(self.top_bar);head.setContentsMargins(8,6,8,6);layout.addWidget(self.top_bar)
        button=QPushButton('← 목록');button.clicked.connect(self.leave);head.addWidget(button)
        self.name=QLabel();self.name.setWordWrap(True);head.addWidget(self.name,1)
        self.fill_button=QPushButton('화면 채우기');self.fill_button.setCheckable(True);self.fill_button.clicked.connect(self.fill);head.addWidget(self.fill_button)
        self.fullscreen_button=QPushButton('전체 화면 (F11)');self.fullscreen_button.clicked.connect(self.fullscreen);head.addWidget(self.fullscreen_button)
        self.stack=QStackedWidget();layout.addWidget(self.stack,1)
        self.photo=PhotoCanvas();self.stack.addWidget(self.photo)
        self.video_host=QFrame();self.video_host.setAttribute(Qt.WidgetAttribute.WA_NativeWindow);self.video_host.setStyleSheet('background: #11151b;');self.video_host.setMinimumSize(180,180);self.stack.addWidget(self.video_host)
        self.message=QLabel('불러오는 중…');self.message.setAlignment(Qt.AlignmentFlag.AlignCenter);self.message.setWordWrap(True);self.message.setStyleSheet('background:#edf1f6;color:#536174;');self.stack.addWidget(self.message)
        self.bottom_bar=QWidget(self);self.bottom_bar.setObjectName('ViewerBottomBar')
        bottom=QVBoxLayout(self.bottom_bar);bottom.setContentsMargins(8,6,8,6);bottom.setSpacing(6);layout.addWidget(self.bottom_bar)
        self.photo_controls=QWidget();row=QHBoxLayout(self.photo_controls);row.setContentsMargins(0,0,0,0);row.addStretch()
        self.zoom_label=QLabel('화면 맞춤')
        for text,callback in [('−',lambda:self.photo.zoom(1/1.25)),('＋',lambda:self.photo.zoom(1.25)),('화면 맞춤',self.photo.fit),('회전',self.photo.rotate)]:
            button=QPushButton(text);button.clicked.connect(callback);row.addWidget(button)
            if text=='−':row.addWidget(self.zoom_label)
        row.addStretch();bottom.addWidget(self.photo_controls);self.photo.zoomChanged.connect(self.zoom_label.setText)
        self.video_controls=QWidget();control=QVBoxLayout(self.video_controls);control.setContentsMargins(0,0,0,0)
        seekrow=QHBoxLayout();control.addLayout(seekrow);self.elapsed=QLabel('0:00');self.length=QLabel('0:00');self.seek=QSlider(Qt.Orientation.Horizontal);self.seek.setRange(0,0)
        seekrow.addWidget(self.elapsed);seekrow.addWidget(self.seek,1);seekrow.addWidget(self.length)
        row=QHBoxLayout();control.addLayout(row);row.addStretch();self.play=QPushButton('재생');row.addWidget(self.play);self.mute=QPushButton('음소거');row.addWidget(self.mute)
        row.addWidget(QLabel('음량'));self.volume=QSlider(Qt.Orientation.Horizontal);self.volume.setRange(0,100);self.volume.setValue(70);self.volume.setMaximumWidth(160);row.addWidget(self.volume);self.volume_value=QLabel('70');self.volume_value.setMinimumWidth(30);row.addWidget(self.volume_value);row.addStretch();bottom.addWidget(self.video_controls)
        nav=QHBoxLayout();nav.addStretch();self.previous=QPushButton('이전 파일');self.previous.clicked.connect(lambda:self.step.emit(-1));nav.addWidget(self.previous);self.position=QLabel();nav.addWidget(self.position);self.next=QPushButton('다음 파일');self.next.clicked.connect(lambda:self.step.emit(1));nav.addWidget(self.next);nav.addStretch();bottom.addLayout(nav)
        self.player=VideoService(dll,self);self.player.state.connect(self.video_state);self.player.error.connect(self.video_error);self.player.ended.connect(self.video_finished)
        self.play.clicked.connect(self.toggle_play);self.mute.clicked.connect(lambda:self.player.send('mute',value=not self.muted))
        self.volume.valueChanged.connect(self.set_volume)
        self.seek.sliderReleased.connect(lambda:self.player.send('seek',value=self.seek.value()/1000))
        self.seek.valueChanged.connect(lambda value: self.player.send('seek',value=value/1000) if not self.seek.isSliderDown() else None)
        self.gif = GifPlayback(tasks, 4096, self)
        self.gif.frameReady.connect(self.gif_frame)
        self.gif.failed.connect(self.gif_error)
        self.tasks.ready.connect(self.asset_ready)
        self.hide_timer=QTimer(self);self.hide_timer.setSingleShot(True);self.hide_timer.setInterval(2500);self.hide_timer.timeout.connect(self.hide_controls)
        self.cursor_timer=QTimer(self);self.cursor_timer.setInterval(80);self.cursor_timer.timeout.connect(self.check_cursor)
        self.last_cursor=QCursor.pos()
        self.top_bar.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.bottom_bar.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)

    def open(self,item,index,total):
        self.gif.stop()
        self.player.stop();self.playback.emit(False);self.current=dict(item);self.photo_key=None
        self.name.setText(Path(item['path']).name+('  [ZIP]' if item.get('archive') else ''));self.name.setToolTip(item['path']);self.update_navigation(index,total)
        video=is_video(item['path']);self.photo_controls.setVisible(not video);self.video_controls.setVisible(video)
        self.position_controls()
        if not available(item):self.video_error('파일을 찾을 수 없습니다. 외부에서 이동·삭제했는지 확인하세요.');return
        if Path(item['path']).suffix.lower() == '.gif':
            self.photo.item.setPixmap(QPixmap())
            self.stack.setCurrentWidget(self.message)
            self.message.setText('GIF를 준비하고 있습니다…')
            self.gif.open(item)
            return
        if video:
            self.paused=True;self.play.setText('재생');self.elapsed.setText('0:00');self.length.setText('0:00');self.seek.blockSignals(True);self.seek.setRange(0,0);self.seek.blockSignals(False)
            self.stack.setCurrentWidget(self.video_host)
            self.player.load(item['path'],int(self.video_host.winId()))
        else:
            self.stack.setCurrentWidget(self.message);self.message.setText('불러오는 중…');self.asset_ready('')
    def asset_ready(self,key):
        if not self.current or is_video(self.current['path']) or Path(self.current['path']).suffix.lower()=='.gif':return
        wanted=self.tasks.key(self.current,4096)
        if key and key!=wanted:return
        pixmap=self.tasks.request(self.current,4096,priority=0)
        if pixmap is not None and self.photo_key!=wanted:
            self.photo_key=wanted;self.photo.set_photo(pixmap);self.stack.setCurrentWidget(self.photo)
        elif wanted in self.tasks.errors:self.message.setText('사진을 열지 못했습니다.\n'+self.tasks.errors[wanted]);self.stack.setCurrentWidget(self.message)
    def update_navigation(self, index, total):
        self.position.setText(f'{index+1} / {total}')
        self.previous.setEnabled(index > 0)
        self.next.setEnabled(index < total-1)

    def gif_frame(self, pixmap, width, height):
        self.photo.set_frame(pixmap)
        self.stack.setCurrentWidget(self.photo)

    def gif_error(self, message):
        self.message.setText('GIF를 열지 못했습니다.\n' + message)
        self.stack.setCurrentWidget(self.message)

    def video_state(self,state):
        if not self.current or not is_video(self.current['path']):return
        self.duration=state['duration'];self.paused=state['paused'];self.muted=state['muted'];self.play.setText('재생' if self.paused else '일시정지');self.mute.setText('음소거 해제' if self.muted else '음소거');self.playback.emit(not self.paused)
        self.elapsed.setText(time_text(state['position']));self.length.setText(time_text(self.duration))
        if not self.seek.isSliderDown():
            self.seek.blockSignals(True);self.seek.setRange(0,max(0,int(self.duration*1000)));self.seek.setValue(int(state['position']*1000));self.seek.blockSignals(False)
        self.volume.blockSignals(True);self.volume.setValue(int(state['volume']));self.volume.blockSignals(False)
        self.volume_value.setText(str(self.volume.value()))
    def video_error(self,message):
        self.player.stop();self.playback.emit(False);self.message.setText('파일을 열지 못했습니다.\n\n'+message);self.stack.setCurrentWidget(self.message)
    def leave(self):self.stop();self.back.emit()
    def stop(self):self.gif.stop();self.player.stop();self.playback.emit(False);self.current=None;self.photo_key=None
    def close_service(self):self.hide_timer.stop();self.cursor_timer.stop();self.gif.close();self.player.close()

    def toggle_play(self):
        if self.current and is_video(self.current['path']):
            self.paused = not self.paused
            self.play.setText('재생' if self.paused else '일시정지')
            self.player.send('pause', value=self.paused)
            self.playback.emit(not self.paused)

    def set_volume(self, value):
        self.volume_value.setText(str(value))
        self.player.send('volume', value=value)

    def video_finished(self):
        self.paused = True
        self.play.setText('재생')
        self.elapsed.setText('0:00')
        self.seek.blockSignals(True)
        self.seek.setValue(0)
        self.seek.blockSignals(False)
        self.playback.emit(False)

    def set_fullscreen_mode(self, enabled):
        self.fullscreen_mode = enabled
        self.photo.allow_upscale = enabled
        self.photo.fit()
        if enabled:
            self.main_layout.removeWidget(self.top_bar)
            self.main_layout.removeWidget(self.bottom_bar)
            self.main_layout.setSpacing(0)
            self.setStyleSheet("""
                QWidget#ViewerTopBar,QWidget#ViewerBottomBar {background:#20252d;}
                QLabel {background:transparent;color:#f0f3f7;}
                QPushButton {background:#303844;color:#f0f3f7;border:1px solid #4a5565;}
                QPushButton:hover {background:#465365;}
            """)
            self.position_controls()
            self.hide_controls()
            self.last_cursor = QCursor.pos()
            self.cursor_timer.start()
        else:
            self.hide_timer.stop()
            self.cursor_timer.stop()
            self.unsetCursor()
            self.setStyleSheet('')
            self.main_layout.insertWidget(0, self.top_bar)
            self.main_layout.addWidget(self.bottom_bar)
            self.main_layout.setSpacing(12)
            self.top_bar.show()
            self.bottom_bar.show()

    def position_controls(self):
        if self.fullscreen_mode:
            self.top_bar.layout().activate()
            self.bottom_bar.layout().activate()
            self.top_bar.setGeometry(0,0,self.width(),self.top_bar.sizeHint().height())
            height=self.bottom_bar.sizeHint().height()
            self.bottom_bar.setGeometry(0,max(0,self.height()-height),self.width(),height)
            self.top_bar.raise_()
            self.bottom_bar.raise_()

    def activity(self):
        if self.fullscreen_mode:
            self.unsetCursor()
            self.position_controls()
            self.top_bar.show()
            self.bottom_bar.show()
            self.top_bar.raise_()
            self.bottom_bar.raise_()
            self.hide_timer.start()

    def hide_controls(self):
        if not self.fullscreen_mode:
            return
        if self.seek.isSliderDown() or self.volume.isSliderDown() or QApplication.activePopupWidget():
            self.hide_timer.start()
            return
        self.top_bar.hide()
        self.bottom_bar.hide()
        self.setCursor(Qt.CursorShape.BlankCursor)

    def pointer_activity(self, point):
        if point != self.last_cursor:
            self.last_cursor=point
            if self.rect().contains(self.mapFromGlobal(point)):
                self.activity()

    def check_cursor(self):
        point=QCursor.pos()
        if not self.window().isActiveWindow():
            self.last_cursor=point
            return
        self.pointer_activity(point)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.position_controls()
