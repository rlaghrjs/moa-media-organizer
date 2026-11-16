from pathlib import Path
from datetime import datetime
import json
import heapq
from PySide6.QtCore import Qt,QAbstractTableModel,QModelIndex,QMimeData,QSize,QRect,Signal
from PySide6.QtGui import QColor,QPainter,QPen,QFont,QPixmap,QDrag
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

HIERARCHY_MIME = 'application/x-moa-album-node'


class AlbumTree(QTreeWidget):
    filesDropped = Signal(str, list)
    hierarchyDropped = Signal(str, str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.validate_hierarchy = None
        self.setUniformRowHeights(True)
        self.setAnimated(False)
        self.setWordWrap(False)
        self.setHeaderHidden(True)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QTreeWidget.DragDropMode.DragDrop)

    def startDrag(self, supported_actions):
        item = self.currentItem()
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not data or data[0] not in ('album', 'albumfolder'):
            return
        mime = QMimeData()
        mime.setData(HIERARCHY_MIME, json.dumps({'kind':data[0], 'id':data[1]}).encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(item.icon(0).pixmap(24,24))
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME) or event.mimeData().hasFormat(HIERARCHY_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def drop_payload(self, mime, item):
        if item is None:
            return None
        data = item.data(0, Qt.ItemDataRole.UserRole)
        try:
            if mime.hasFormat(HIERARCHY_MIME):
                payload = json.loads(bytes(mime.data(HIERARCHY_MIME)))
                if not isinstance(payload, dict) or payload.get('kind') not in ('album','albumfolder') or not isinstance(payload.get('id'), str):
                    return None
                if data and data[0]=='albumfolder':
                    target = data[1]
                elif item.data(0,Qt.ItemDataRole.UserRole+1)=='albums':
                    target = None
                else:
                    return None
                if not self.validate_hierarchy or not self.validate_hierarchy(payload['kind'],payload['id'],target):
                    return None
                return ('hierarchy',payload,target)
            if mime.hasFormat(MIME) and data and data[0]=='album':
                ids = json.loads(bytes(mime.data(MIME)))
                if isinstance(ids,list) and all(isinstance(ident,str) for ident in ids):
                    return ('files',ids,data[1])
        except (ValueError, UnicodeError):
            pass
        return None

    def dragMoveEvent(self, event):
        payload = self.drop_payload(event.mimeData(),self.itemAt(event.position().toPoint()))
        if payload:
            event.setDropAction(Qt.DropAction.MoveAction if payload[0]=='hierarchy' else Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        payload = self.drop_payload(event.mimeData(),self.itemAt(event.position().toPoint()))
        if payload is None:
            event.ignore()
            return
        kind, content, target = payload
        if kind=='hierarchy':
            self.hierarchyDropped.emit(content['kind'],content['id'],target)
            event.setDropAction(Qt.DropAction.MoveAction)
        else:
            self.filesDropped.emit(target,content)
            event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
