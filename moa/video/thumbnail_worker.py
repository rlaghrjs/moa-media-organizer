"""Video thumbnail tasks have their own process pool, independent of photos."""
import os
import time
from pathlib import Path

def video_resolution(path):
    from moa.video.player import Player
    dll=Path(__file__).resolve().parents[2]/'vendor'/'mpv'/'libmpv-2.dll'
    player=Player(dll,headless=True)
    try:
        player.command('loadfile',path,'replace')
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            width=int(player.number('width'))
            height=int(player.number('height'))
            if width>0 and height>0:
                return f"{width} × {height}"
            if any(kind=='error' for kind,_ in player.events()):
                break
            time.sleep(.025)
        return ''
    finally:
        player.close()

def render_video_thumbnail(path,size,destination):
    from moa.platform.shell_thumbnail import shell_image
    temporary=Path(destination).with_name(Path(destination).stem+'.'+str(os.getpid())+'.tmp.png')
    resolution=''
    if size==400:
        try:resolution=video_resolution(path)
        except (OSError,RuntimeError):pass
    try:
        from PIL.PngImagePlugin import PngInfo
        metadata=PngInfo()
        if resolution:metadata.add_text('MoaResolution',resolution)
        image=shell_image(path,size)
        if image is None:raise ValueError('영상 썸네일을 만들 수 없습니다. 내부 뷰어에서 재생할 수 있습니다.')
        Path(destination).parent.mkdir(parents=True,exist_ok=True)
        image.thumbnail((size,size));image.save(temporary,'PNG',pnginfo=metadata);os.replace(temporary,destination)
        return {'path':str(destination),'error':'','pid':os.getpid(),'resolution':resolution}
    except Exception as error:
        temporary.unlink(missing_ok=True)
        return {'path':'','error':str(error),'pid':os.getpid(),'resolution':resolution}
