"""Application-owned album icon, created once on the UI thread."""
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QPolygonF


def album_icon():
    pixmap=QPixmap(24,24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter=QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor('#97b7dd'))
    painter.drawRoundedRect(QRectF(2,2,18,18),3,3)
    painter.setBrush(QColor('#3977b8'))
    painter.drawRoundedRect(QRectF(5,5,18,18),3,3)
    painter.setBrush(QColor('#f4f8ff'))
    painter.drawEllipse(QRectF(15,8,4,4))
    painter.drawPolygon(QPolygonF([QPointF(8,19),QPointF(13,12),QPointF(20,19)]))
    painter.end()
    return QIcon(pixmap)
