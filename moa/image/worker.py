"""Photo decoding only. Runs in spawned image processes, never in the UI."""
import os
from pathlib import Path

def render_photo(path,size,destination):
    from PySide6.QtCore import QSize,Qt
    from PySide6.QtGui import QImageReader
    QImageReader.setAllocationLimit(256)
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_name(destination.stem+'.'+str(os.getpid())+'.tmp.png')
    buffer=None;raw=None
    if isinstance(path,dict):
        try:
            from moa.sources.zip_source import read_member
            from PySide6.QtCore import QBuffer,QByteArray,QIODevice
            raw=read_member(path);buffer=QBuffer();buffer.setData(QByteArray(raw));buffer.open(QIODevice.OpenModeFlag.ReadOnly)
            reader=QImageReader(buffer)
        except Exception as error:return {'path':'','error':str(error),'pid':os.getpid()}
    else:reader=QImageReader(path)
    reader.setAutoTransform(True)
    original=reader.size()
    resolution=f"{original.width()} × {original.height()}" if original.isValid() else ""
    if original.isValid() and max(original.width(),original.height())>size:reader.setScaledSize(original.scaled(QSize(size,size),Qt.AspectRatioMode.KeepAspectRatio))
    image=reader.read()
    try:
        if not image.isNull():
            image.setText("MoaResolution",resolution)
            if not image.save(str(temporary),'PNG'):raise OSError('사진 캐시를 저장하지 못했습니다.')
        else:
            from PIL import Image,ImageOps
            try:
                from io import BytesIO
                with Image.open(BytesIO(raw) if raw is not None else path) as source:
                    if raw is not None and source.width*source.height>64*1024*1024:raise ValueError('사진 해상도가 읽기 제한을 초과합니다.')
                    from PIL.PngImagePlugin import PngInfo
                    resolution=f"{source.width} × {source.height}"
                    metadata=PngInfo();metadata.add_text("MoaResolution",resolution)
                    source.draft('RGB',(size,size));photo=ImageOps.exif_transpose(source);photo.thumbnail((size,size));photo.convert('RGB').save(temporary,'PNG',pnginfo=metadata)
            except Exception:
                # HEIC support follows the Windows installed thumbnail provider.
                if raw is not None:raise ValueError('ZIP 사진을 읽지 못했습니다. 이 형식에 필요한 이미지 코덱이 없거나 사진이 손상되었습니다.')
                from moa.platform.shell_thumbnail import shell_image
                photo=shell_image(path,min(size,2048))
                if photo is None:raise ValueError('이 사진 형식을 읽을 수 없거나 파일이 손상되었습니다.')
                photo.thumbnail((size,size));photo.save(temporary,'PNG')
        os.replace(temporary,destination)
        return {'path':str(destination),'error':'','resolution':resolution,'pid':os.getpid()}
    except Exception as error:
        temporary.unlink(missing_ok=True)
        return {'path':'','error':str(error),'pid':os.getpid()}
