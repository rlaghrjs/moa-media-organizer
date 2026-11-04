"""Windows Shell thumbnail provider with Pillow fallback."""
import ctypes as C
from ctypes import wintypes as W
from pathlib import Path
from PIL import Image, ImageOps

class GUID(C.Structure):
    _fields_ = [('Data1', W.DWORD), ('Data2', W.WORD), ('Data3', W.WORD), ('Data4', C.c_ubyte * 8)]
class SIZE(C.Structure):
    _fields_ = [('cx', C.c_long), ('cy', C.c_long)]
class HEADER(C.Structure):
    _fields_ = [('size', W.DWORD), ('width', C.c_long), ('height', C.c_long), ('planes', W.WORD), ('bits', W.WORD), ('compression', W.DWORD), ('image_size', W.DWORD), ('x', C.c_long), ('y', C.c_long), ('used', W.DWORD), ('important', W.DWORD)]
class INFO(C.Structure):
    _fields_ = [('header', HEADER), ('colors', W.DWORD * 3)]

def shell_image(path, size):
    ole = C.OleDLL('ole32')
    hr = ole.CoInitializeEx(None, 2)
    initialized = hr in (0, 1)
    obj, bitmap = C.c_void_p(), W.HBITMAP()
    try:
        iid = GUID()
        ole.CLSIDFromString(C.c_wchar_p('{bcc18b79-ba16-442f-80c4-8a59c30c463b}'), C.byref(iid))
        create = C.OleDLL('shell32').SHCreateItemFromParsingName
        create.argtypes = [W.LPCWSTR, C.c_void_p, C.POINTER(GUID), C.POINTER(C.c_void_p)]
        create.restype = C.c_long
        if create(str(Path(path).absolute()), None, C.byref(iid), C.byref(obj)) < 0:
            return None
        table = C.cast(obj, C.POINTER(C.POINTER(C.c_void_p))).contents
        get_image = C.WINFUNCTYPE(C.c_long, C.c_void_p, SIZE, C.c_int, C.POINTER(W.HBITMAP))(table[3])
        # THUMBNAILONLY: do not mistake a generic file icon for a preview.
        if get_image(obj, SIZE(size, size), 8, C.byref(bitmap)) < 0:
            return None
        gdi = C.WinDLL('gdi32')
        gdi.CreateCompatibleDC.restype = W.HDC
        gdi.GetDIBits.argtypes = [W.HDC, W.HBITMAP, W.UINT, W.UINT, C.c_void_p, C.POINTER(INFO), W.UINT]
        gdi.DeleteObject.argtypes = [W.HGDIOBJ]
        gdi.DeleteDC.argtypes = [W.HDC]
        dc = gdi.CreateCompatibleDC(None)
        try:
            info = INFO()
            info.header.size = C.sizeof(HEADER)
            if not gdi.GetDIBits(dc, bitmap, 0, 0, None, C.byref(info), 0):
                return None
            width, height = info.header.width, abs(info.header.height)
            info.header.height = -height
            info.header.bits = 32
            info.header.compression = 0
            data = C.create_string_buffer(width * height * 4)
            if not gdi.GetDIBits(dc, bitmap, 0, height, data, C.byref(info), 0):
                return None
            return Image.frombytes('RGB', (width, height), data.raw, 'raw', 'BGRX')
        finally:
            gdi.DeleteDC(dc)
            gdi.DeleteObject(bitmap)
    finally:
        if obj:
            table = C.cast(obj, C.POINTER(C.POINTER(C.c_void_p))).contents
            C.WINFUNCTYPE(W.ULONG, C.c_void_p)(table[2])(obj)
        if initialized:
            ole.CoUninitialize()
