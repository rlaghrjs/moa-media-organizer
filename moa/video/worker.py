"""Dedicated libmpv process. Messages contain commands/status, never video frames."""
import os
import time
from moa.video.player import Player

def video_main(connection,dll,window,headless=False):
    player=None;token=0;active=False
    try:
        import ctypes
        if os.name=='nt':
            try:
                set_dpi=ctypes.WinDLL('user32').SetProcessDpiAwarenessContext
                set_dpi.argtypes=[ctypes.c_void_p];set_dpi.restype=ctypes.c_int
                set_dpi(ctypes.c_void_p(-4))
            except (AttributeError,OSError):pass
        player=Player(dll,window,headless);connection.send({'type':'ready','pid':os.getpid()})
        last=0
        while True:
            if connection.poll(.04):
                request=connection.recv();action=request['action']
                if action=='quit':break
                try:
                    if action=='load':
                        token=request['token'];active=True
                        player.set('pause','yes');player.command('loadfile',request['path'],'replace')
                    elif action=='stop':active=False;player.command('stop')
                    elif action=='pause':player.set('pause','yes' if request['value'] else 'no')
                    elif action=='seek':player.command('seek',request['value'],'absolute+exact')
                    elif action=='volume':player.set('volume',request['value'])
                    elif action=='mute':player.set('mute','yes' if request['value'] else 'no')
                except Exception as error:connection.send({'type':'error','token':token,'message':str(error)})
            for kind,message in player.events():
                if kind=='error' and active:connection.send({'type':'error','token':token,'message':message})
            if active and time.monotonic()-last>.18:
                last=time.monotonic()
                connection.send({'type':'state','token':token,'position':player.number('time-pos'),'duration':player.number('duration'),'paused':player.flag('pause',True),'volume':player.number('volume',70),'muted':player.flag('mute'),'output_width':player.number('osd-width'),'output_height':player.number('osd-height'),'pid':os.getpid()})
    except (EOFError,BrokenPipeError):pass
    except Exception as error:
        try:connection.send({'type':'error','token':token,'message':str(error)})
        except (BrokenPipeError,EOFError):pass
    finally:
        if player:player.close()
        connection.close()
