"""Background suggestions displayed inside the application's normal layout."""
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QObject,QTimer,Signal,Qt,QEvent,QModelIndex
from PySide6.QtGui import QStandardItemModel,QStandardItem
from PySide6.QtWidgets import QApplication,QWidget
from moa.application.library_jobs import search_suggestions

class SearchControl(QObject):
    chosen=Signal(str,str)
    edited=Signal()
    def __init__(self,line,snapshot,context,panel,parent=None):
        super().__init__(parent);self.line=line;self.snapshot=snapshot;self.context=context;self.panel=panel;self.revision=0;self.future=None;self.waiting=False;self.closed=False;self.footer=None
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='MoaSearch')
        self.model=QStandardItemModel(self);self.panel.list.setModel(self.model)
        self.panel.list.clicked.connect(self.choose);self.panel.all_button.clicked.connect(self.choose_all);self.panel.dismissed.connect(self.invalidate)
        self.line.setClearButtonEnabled(True);self.line.installEventFilter(self);QApplication.instance().installEventFilter(self)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(180);self.timer.timeout.connect(self.start)
        self.poller=QTimer(self);self.poller.setInterval(55);self.poller.timeout.connect(self.poll);self.poller.start();self.line.textChanged.connect(self.text_changed)
    def text_changed(self,text):
        self.revision+=1;self.waiting=bool(text.strip()) and self.future is not None;self.edited.emit()
        if text.strip():
            if self.panel.isVisible():self.panel.show_loading()
            self.timer.start()
        else:self.timer.stop();self.panel.hide();self.chosen.emit('all','')
    def start(self):
        if self.closed or not self.line.text().strip():return
        if self.future is not None:self.waiting=True;return
        revision=self.revision;scope=self.context();query=self.line.text();data=self.snapshot()
        self.future=(self.executor.submit(search_suggestions,data,scope,query),revision,scope);self.waiting=False
    def poll(self):
        if self.future is None or not self.future[0].done():return
        future,revision,scope=self.future;self.future=None
        try:rows=future.result()
        except Exception:rows=[]
        if revision==self.revision and scope==self.context() and self.line.text().strip():
            self.model.clear();self.footer=None
            for row in rows:
                if row['kind']=='all':self.footer=row;continue
                item=QStandardItem(row['label']);item.setData(row,Qt.ItemDataRole.UserRole);item.setToolTip(row['label']);self.model.appendRow(item)
            self.panel.list.setCurrentIndex(QModelIndex())
            if self.line.hasFocus() and self.footer:self.panel.set_rows(self.model.rowCount(),self.footer['label'])
        if self.waiting and not self.timer.isActive():self.start()
    def choose(self,index):
        if not self.panel.list.isEnabled():return
        payload=index.data(Qt.ItemDataRole.UserRole)
        if payload:self.apply(payload)
    def choose_all(self):
        if self.footer:self.apply(self.footer)
        else:self.apply({'kind':'all','query':self.line.text().strip()})
    def apply(self,payload):
        self.invalidate();self.line.blockSignals(True);self.line.setText(payload['query']);self.line.blockSignals(False);self.chosen.emit(payload['kind'],payload['query'])
    def invalidate(self):
        self.revision+=1;self.waiting=False;self.timer.stop();self.panel.hide()
    def eventFilter(self,watched,event):
        if self.closed:return False
        if event.type()==QEvent.Type.MouseButtonPress and self.panel.isVisible() and isinstance(watched,QWidget):
            if watched is not self.line and not self.line.isAncestorOf(watched) and watched is not self.panel and not self.panel.isAncestorOf(watched):self.invalidate()
        if watched is self.line and event.type()==QEvent.Type.ShortcutOverride and self.panel.isVisible() and event.key()==Qt.Key.Key_Escape:
            event.accept();return True
        if watched is self.line and event.type()==QEvent.Type.KeyPress:
            key=event.key()
            if key==Qt.Key.Key_Escape and self.panel.isVisible():self.invalidate();return True
            if key in (Qt.Key.Key_Down,Qt.Key.Key_Up) and self.panel.isVisible() and self.panel.list.isEnabled():
                count=self.model.rowCount()
                if count:
                    row=self.panel.list.currentIndex().row();row=(row+1)%count if key==Qt.Key.Key_Down else (row-1)%count
                    self.panel.list.setCurrentIndex(self.model.index(row,0));self.panel.list.scrollTo(self.model.index(row,0))
                return True
            if key in (Qt.Key.Key_Return,Qt.Key.Key_Enter):
                index=self.panel.list.currentIndex()
                if self.panel.isVisible() and self.panel.list.isEnabled() and index.isValid():self.choose(index)
                else:self.apply({'kind':'all','query':self.line.text().strip()})
                return True
        return super().eventFilter(watched,event)
    def close(self):
        self.closed=True;self.timer.stop();self.poller.stop();self.panel.hide();self.line.removeEventFilter(self);QApplication.instance().removeEventFilter(self);self.executor.shutdown(wait=False,cancel_futures=True)
