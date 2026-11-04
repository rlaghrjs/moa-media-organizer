from PySide6.QtCore import Qt,Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QGraphicsView,QGraphicsScene,QGraphicsPixmapItem

class PhotoCanvas(QGraphicsView):
    zoomChanged=Signal(str)
    def __init__(self,parent=None):
        super().__init__(parent);self.scene_object=QGraphicsScene(self);self.setScene(self.scene_object)
        self.item=QGraphicsPixmapItem();self.scene_object.addItem(self.item);self.fitting=True
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform);self.setDragMode(self.DragMode.ScrollHandDrag)
        self.setBackgroundBrush(Qt.GlobalColor.black);self.setTransformationAnchor(self.ViewportAnchor.AnchorUnderMouse)
    def set_photo(self,pixmap):
        self.item.setPixmap(pixmap);self.item.setRotation(0);self.fit()
    def fit(self):
        self.fitting=True;self.resetTransform();self.setSceneRect(self.item.sceneBoundingRect())
        if not self.item.pixmap().isNull():self.fitInView(self.item,Qt.AspectRatioMode.KeepAspectRatio)
        self.zoomChanged.emit('화면 맞춤')
    def zoom(self,factor):
        current=self.transform().m11()
        if .03<current*factor<12:
            self.fitting=False;self.scale(factor,factor);self.zoomChanged.emit(f'{self.transform().m11()*100:.0f}%')
    def rotate(self):self.item.setRotation((self.item.rotation()+90)%360);self.fit()
    def wheelEvent(self,event):self.zoom(1.2 if event.angleDelta().y()>0 else 1/1.2);event.accept()
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.fitting:self.fit()
