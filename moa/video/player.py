"""Small libmpv C API adapter; no Qt or photo processing dependencies."""
import ctypes as C
from pathlib import Path

class Event(C.Structure):
    _fields_=[('event_id',C.c_int),('error',C.c_int),('reply_userdata',C.c_uint64),('data',C.c_void_p)]
class EndFile(C.Structure):
    _fields_=[('reason',C.c_int),('error',C.c_int)]

class Player:
    def __init__(self,dll,window=None,headless=False):
        self.lib=C.CDLL(str(Path(dll).absolute()))
        signatures={'mpv_create':([],C.c_void_p),'mpv_initialize':([C.c_void_p],C.c_int),'mpv_set_option_string':([C.c_void_p,C.c_char_p,C.c_char_p],C.c_int),'mpv_set_property_string':([C.c_void_p,C.c_char_p,C.c_char_p],C.c_int),'mpv_get_property':([C.c_void_p,C.c_char_p,C.c_int,C.c_void_p],C.c_int),'mpv_command':([C.c_void_p,C.POINTER(C.c_char_p)],C.c_int),'mpv_wait_event':([C.c_void_p,C.c_double],C.POINTER(Event)),'mpv_terminate_destroy':([C.c_void_p],None),'mpv_error_string':([C.c_int],C.c_char_p)}
        for name,(args,result) in signatures.items():
            function=getattr(self.lib,name);function.argtypes=args;function.restype=result
        self.handle=self.lib.mpv_create()
        if not self.handle:raise RuntimeError('libmpv 초기화 실패')
        try:
            options={'config':'no','terminal':'no','input-default-bindings':'no','input-vo-keyboard':'no','osc':'no','idle':'yes','keep-open':'yes','pause':'yes','volume':'70','hwdec':'auto-safe','demuxer-max-bytes':'64MiB','demuxer-max-back-bytes':'16MiB','vd-lavc-threads':'2','osd-level':'0'}
            if headless:options.update({'vo':'null','ao':'null'})
            elif window:options.update({'wid':str(int(window)&0xffffffff),'vo':'gpu','gpu-context':'d3d11','force-window':'yes'})
            for key,value in options.items():self.check(self.lib.mpv_set_option_string(self.handle,key.encode(),value.encode()))
            self.check(self.lib.mpv_initialize(self.handle))
        except BaseException:self.close();raise
    def check(self,result):
        if result<0:raise RuntimeError(self.lib.mpv_error_string(result).decode('utf-8','replace'))
        return result
    def command(self,*args):
        encoded=[str(a).encode('utf-8') for a in args]
        values=(C.c_char_p*(len(encoded)+1))(*encoded,None)
        self.check(self.lib.mpv_command(self.handle,values))
    def set(self,name,value):self.check(self.lib.mpv_set_property_string(self.handle,name.encode(),str(value).encode()))
    def number(self,name,default=0):
        value=C.c_double()
        return value.value if self.lib.mpv_get_property(self.handle,name.encode(),5,C.byref(value))>=0 else default
    def flag(self,name,default=False):
        value=C.c_int()
        return bool(value.value) if self.lib.mpv_get_property(self.handle,name.encode(),3,C.byref(value))>=0 else default
    def events(self):
        result=[]
        for _ in range(50):
            event=self.lib.mpv_wait_event(self.handle,0).contents
            if not event.event_id:break
            if event.event_id==7 and event.data:
                end=C.cast(event.data,C.POINTER(EndFile)).contents
                if end.reason==4:result.append(('error',self.lib.mpv_error_string(end.error).decode('utf-8','replace')))
            elif event.event_id==7:result.append(('ended',''))
            elif event.event_id==8:result.append(('loaded',''))
        return result
    def close(self):
        if self.handle:self.lib.mpv_terminate_destroy(self.handle);self.handle=None
