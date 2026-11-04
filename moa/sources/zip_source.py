"""Read-only ZIP access. Never extract members to the filesystem."""
from datetime import datetime
from pathlib import Path,PurePosixPath
from zipfile import ZipFile
from moa.contracts import IMAGES
MAX_MEMBER_BYTES=128*1024*1024

def open_zip(path):
    # UTF-8 flags take precedence. Prefer legacy Korean names, then ZIP's standard encoding.
    try:return ZipFile(path,'r',metadata_encoding='cp949')
    except UnicodeDecodeError:return ZipFile(path,'r')

def safe_member(name):
    p=PurePosixPath(name)
    return bool(name) and not p.is_absolute() and '..' not in p.parts and '\\' not in name and ':' not in name

def index_zip(path,allowed=None,previous=(),progress=None):
    path=str(Path(path).absolute());stat=Path(path).stat();allowed=IMAGES if allowed is None else set(allowed)&IMAGES
    old=list(previous)
    # Only reuse a complete index with exactly the same filter and container signature.
    signature=[stat.st_mtime_ns,stat.st_size,stat.st_ctime_ns]
    if old and all(i.get('archive_signature')==signature and i.get('archive_filter')==sorted(allowed) for i in old):
        return [{k:v for k,v in item.items() if k not in ('tags','missing')} for item in old],[]
    records=[];errors=[];seen=set()
    with open_zip(path) as archive:
        for n,info in enumerate(archive.infolist()):
            if progress and n%500==0:progress(('ZIP 목록 확인 · '+Path(path).name,n,len(archive.filelist)))
            if info.is_dir() or PurePosixPath(info.filename).suffix.lower() not in allowed:continue
            if not safe_member(info.filename):errors.append(Path(path).name+': 지원하지 않는 내부 경로');continue
            if info.filename in seen:errors.append(Path(path).name+': 중복 내부 경로 '+info.filename);continue
            seen.add(info.filename)
            if info.flag_bits&1:errors.append(Path(path).name+': 암호 사진 제외 · '+info.filename);continue
            if info.file_size>MAX_MEMBER_BYTES:errors.append(Path(path).name+': 128 MiB 초과 사진 제외 · '+info.filename);continue
            try:modified=int(datetime(*info.date_time).timestamp()*1e9)
            except (ValueError,OverflowError,OSError):modified=stat.st_mtime_ns
            records.append({'path':path+'!/'+info.filename,'archive':path,'member':info.filename,'size':info.file_size,'modified':modified,'crc':info.CRC,'offset':info.header_offset,'archive_signature':signature,'archive_filter':sorted(allowed)})
    return records,errors

def read_member(item):
    path=item['archive'];stat=Path(path).stat()
    if item.get('archive_signature')!=[stat.st_mtime_ns,stat.st_size,stat.st_ctime_ns]:raise ValueError('ZIP이 변경되었습니다. 새로고침 후 다시 열어 주세요.')
    with open_zip(path) as archive:
        info=archive.getinfo(item['member'])
        if 'offset' in item and info.header_offset!=item['offset']:
            info=next((i for i in archive.infolist() if i.filename==item['member'] and i.header_offset==item['offset']),None)
            if info is None:raise ValueError('ZIP 사진 위치가 변경되었습니다. 새로고침해 주세요.')
        if info.flag_bits&1:raise ValueError('암호 ZIP 사진은 지원하지 않습니다.')
        if info.CRC!=item['crc'] or info.file_size!=item['size']:raise ValueError('ZIP 사진이 변경되었습니다. 새로고침해 주세요.')
        if info.file_size>MAX_MEMBER_BYTES:raise ValueError('사진의 압축 해제 크기가 제한을 초과합니다.')
        with archive.open(info) as source:data=source.read(MAX_MEMBER_BYTES+1)
        if len(data)>MAX_MEMBER_BYTES:raise ValueError('사진 크기가 제한을 초과합니다.')
        return data
