"""A normal child widget for suggestions. It never creates a floating popup window."""
from PySide6.QtCore import Qt,QSize,Signal,QPoint,QEvent
from PySide6.QtWidgets import QWidget,QFrame,QHBoxLayout,QVBoxLayout,QLabel,QPushButton,QListView,QStyledItemDelegate,QAbstractItemView

class SuggestionDelegate(QStyledItemDelegate):
    def sizeHint(self,option,index):return QSize(360,42)

class SearchPanel(QWidget):
    dismissed=Signal()
    def __init__(self,parent,anchor):
        super().__init__(parent)
        # libmpv also draws into a native child window.
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setObjectName('SearchSuggestionHost')
        outside=QHBoxLayout(self);outside.setContentsMargins(0,0,0,0)
        self.frame=QFrame(self);self.frame.setObjectName('SearchSuggestionFrame');self.anchor=anchor
        outside.addWidget(self.frame,1)
        layout=QVBoxLayout(self.frame);layout.setContentsMargins(8,6,8,8);layout.setSpacing(4)
        header=QHBoxLayout();self.caption=QLabel('검색 제안 · 현재 폴더/앨범');self.caption.setObjectName('SuggestionCaption');header.addWidget(self.caption,1)
        close=QPushButton('×');close.setAccessibleName('검색 제안 닫기');close.setFixedSize(28,28);close.clicked.connect(self.dismissed);header.addWidget(close);layout.addLayout(header)
        self.list=QListView();self.list.setObjectName('SearchSuggestionList');self.list.setItemDelegate(SuggestionDelegate(self.list));self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus);self.list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.list.setUniformItemSizes(True);self.list.setTextElideMode(Qt.TextElideMode.ElideMiddle);self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);layout.addWidget(self.list)
        self.empty=QLabel('이름·태그 제안이 없습니다.');self.empty.setObjectName('SuggestionCaption');layout.addWidget(self.empty)
        self.all_button=QPushButton('전체 결과 보기');self.all_button.setObjectName('AllSearchResults');layout.addWidget(self.all_button)
        self.setStyleSheet('''
        QWidget#SearchSuggestionHost{background:#f7f9fc;}
        QFrame#SearchSuggestionFrame{background:white;border:1px solid #cad7e6;border-radius:7px;}
        QLabel#SuggestionCaption{background:white;color:#66768a;font-size:11px;padding:4px;border:0;}
        QListView#SearchSuggestionList{background:white;color:#23364b;border:0;font-size:13px;outline:none;}
        QListView#SearchSuggestionList::item{padding:8px 10px;border:0;border-radius:4px;}
        QListView#SearchSuggestionList::item:hover{background:#f0f5fb;}
        QListView#SearchSuggestionList::item:selected{background:#dceafd;color:#174c88;}
        QPushButton#AllSearchResults{background:#eaf2fc;color:#195b9d;border:1px solid #d3e2f4;min-height:26px;text-align:left;font-size:13px;font-weight:600;padding:7px 12px;}
        QPushButton#AllSearchResults:hover,QPushButton#AllSearchResults:focus{background:#dceafd;}
        ''');parent.installEventFilter(self);anchor.installEventFilter(self);self.hide()
    def set_rows(self,count,footer):
        self.caption.setText('검색 제안 · 현재 폴더/앨범');self.list.setEnabled(True);self.all_button.setEnabled(True)
        self.list.setVisible(count>0);self.empty.setVisible(count==0)
        self.list.setFixedHeight(min(4,max(1,count))*42+2);self.all_button.setText(footer);self.reposition();self.show();self.raise_()
    def show_loading(self):
        self.caption.setText('검색 제안 준비 중…');self.list.setEnabled(False);self.all_button.setEnabled(False)

    def reposition(self):
        parent=self.parentWidget()
        point=self.anchor.mapTo(parent,QPoint(self.anchor.width(),self.anchor.height()+4))
        width=min(parent.width(),max(300,self.anchor.width()))
        self.layout().activate()
        height=self.sizeHint().height()
        self.setGeometry(max(0,min(point.x()-width,parent.width()-width)),max(0,min(point.y(),parent.height()-height)),width,height)

    def eventFilter(self,watched,event):
        if self.isVisible() and event.type() in (QEvent.Type.Resize,QEvent.Type.Move):
            self.reposition()
        return super().eventFilter(watched,event)
