from pathlib import Path
from datetime import datetime
import json
import heapq
from PySide6.QtCore import Qt,QAbstractTableModel,QModelIndex,QMimeData,QSize,QRect,Signal
from PySide6.QtGui import QColor,QPainter,QPen,QFont,QPixmap
from PySide6.QtWidgets import QStyledItemDelegate,QStyle,QTreeWidget
from moa.contracts import MIME,is_video

class MediaModel(QAbstractTableModel):
    def __init__(self,store,tasks,parent=None):
        super().__init__(parent);self.store=store;self.tasks=tasks;self.ids=[];self.lookup={};tasks.ready.connect(self.thumbnail_ready)
    def reset(self,ids):
        self.beginResetModel();self.ids=list(ids);self.lookup={}
        self.endResetModel()
    def insert_sorted(self,ids,key,reverse=False):
        known=set(self.ids);fresh=sorted(set(ids)-known,key=key,reverse=reverse)
        if not fresh:return
        added=set(fresh);merged=list(heapq.merge(self.ids,fresh,key=key,reverse=reverse));self.lookup.clear()
        index=0
        while index<len(merged):
            if merged[index] not in added:index+=1;continue
            end=index+1
            while end<len(merged) and merged[end] in added:end+=1
            self.beginInsertRows(QModelIndex(),index,end-1);self.ids[index:index]=merged[index:end];self.endInsertRows();index=end

    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.ids)
    def columnCount(self,parent=QModelIndex()):return 5
    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():return None
        item=self.store.data['files'][self.ids[index.row()]];p=Path(item['path']);column=index.column()
        if role==Qt.ItemDataRole.DisplayRole:
            return [p.name+(' [ZIP]' if item.get('archive') else '')+(' (파일 없음)' if item.get('missing') else ''),datetime.fromtimestamp(item.get('modified',0)/1e9).strftime('%Y-%m-%d %H:%M') if item.get('modified') else '파일 없음',p.suffix.upper().lstrip('.'),f"{item.get('size',0)/1048576:.1f} MB",', '.join(item['tags'])][column]
        if role==Qt.ItemDataRole.ToolTipRole:return item['path']
        if role==Qt.ItemDataRole.UserRole:return self.ids[index.row()]
        return None
    def headerData(self,section,orientation,role=Qt.ItemDataRole.DisplayRole):
        return ['이름','수정한 날짜','확장자','크기','태그'][section] if orientation==Qt.Orientation.Horizontal and role==Qt.ItemDataRole.DisplayRole else None
    def flags(self,index):
        return Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsSelectable|Qt.ItemFlag.ItemIsDragEnabled if index.isValid() else Qt.ItemFlag.NoItemFlags
    def mimeTypes(self):return [MIME]
    def mimeData(self,indexes):
        mime=QMimeData();ids=list(dict.fromkeys(self.ids[i.row()] for i in indexes if i.isValid()))
        mime.setData(MIME,json.dumps(ids).encode());return mime
    def supportedDragActions(self):return Qt.DropAction.CopyAction
    def thumbnail_ready(self,key):
        row=self.lookup.get(key)
        if row is not None:self.dataChanged.emit(self.index(row,0),self.index(row,0),[])

class ThumbnailDelegate(QStyledItemDelegate):
    def sizeHint(self,option,index):return QSize(178,195)
    def paint(self,painter,option,index):
        painter.save();rect=option.rect.adjusted(4,4,-4,-4);selected=bool(option.state&QStyle.StateFlag.State_Selected)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor('#3978bd') if selected else QColor('#e8edf2'),1))
        painter.setBrush(QColor('#eaf2fc') if selected else QColor('#ffffff'));painter.drawRoundedRect(rect,5,5)
        model=index.model();item=model.store.data['files'][model.ids[index.row()]]
        image_rect=QRect(rect.x()+7,rect.y()+7,rect.width()-14,125)
        model.lookup[model.tasks.key(item,256)]=index.row()
        pixmap=model.tasks.request(item,256)
        if pixmap is not None:
            scaled=pixmap.scaled(image_rect.size(),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(image_rect.center().x()-scaled.width()//2,image_rect.center().y()-scaled.height()//2,scaled)
        else:
            painter.fillRect(image_rect,QColor('#f1f4f8'));painter.setPen(QColor('#687f99'))
            painter.setFont(QFont('Segoe UI',22));painter.drawText(image_rect,Qt.AlignmentFlag.AlignCenter,'▶' if is_video(item['path']) else '▧')
        if is_video(item['path']):
            badge=QRect(image_rect.right()-48,image_rect.bottom()-22,47,21);painter.fillRect(badge,QColor('#35465c'));painter.setPen(QColor('white'));painter.setFont(QFont('Segoe UI',8));painter.drawText(badge,Qt.AlignmentFlag.AlignCenter,Path(item['path']).suffix[1:].upper())
        painter.setPen(QColor('#273444'));painter.setFont(QFont('맑은 고딕',9))
        name=painter.fontMetrics().elidedText(Path(item['path']).name+(' [ZIP]' if item.get('archive') else '')+(' (파일 없음)' if item.get('missing') else ''),Qt.TextElideMode.ElideMiddle,rect.width()-18)
        painter.drawText(QRect(rect.x()+9,rect.y()+139,rect.width()-18,21),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,name)
        painter.setFont(QFont('Segoe UI',8));painter.setPen(QColor('#738093'))
        modified=datetime.fromtimestamp(item.get('modified',0)/1e9).strftime('%Y.%m.%d') if item.get('modified') else '파일 없음'
        painter.drawText(QRect(rect.x()+9,rect.y()+164,rect.width()-18,15),modified)
        painter.restore()

class AlbumTree(QTreeWidget):
    filesDropped=Signal(str,list)
    def __init__(self,parent=None):
        super().__init__(parent);self.setUniformRowHeights(True);self.setAnimated(False);self.setWordWrap(False);self.setHeaderHidden(True);self.setAcceptDrops(True);self.setDropIndicatorShown(True);self.setDragDropMode(QTreeWidget.DragDropMode.DropOnly)
    def dragEnterEvent(self,event):
        if event.mimeData().hasFormat(MIME):event.acceptProposedAction()
        else:event.ignore()
    def dragMoveEvent(self,event):
        item=self.itemAt(event.position().toPoint())
        if item and item.data(0,Qt.ItemDataRole.UserRole) and item.data(0,Qt.ItemDataRole.UserRole)[0]=='album':event.setDropAction(Qt.DropAction.CopyAction);event.accept()
        else:event.ignore()
    def dropEvent(self,event):
        item=self.itemAt(event.position().toPoint());data=item.data(0,Qt.ItemDataRole.UserRole) if item else None
        if not data or data[0]!='album':event.ignore();return
        try:
            ids=json.loads(bytes(event.mimeData().data(MIME)))
            if not isinstance(ids,list) or any(not isinstance(i,str) for i in ids):raise ValueError('잘못된 파일 선택')
        except (ValueError,UnicodeError):event.ignore();return
        self.filesDropped.emit(data[1],ids);event.setDropAction(Qt.DropAction.CopyAction);event.accept()
