"""Source identities and navigation; no codecs or archive I/O."""
import os
from pathlib import Path,PurePosixPath

def identity(item):
    if item.get('archive'):return ('zip',os.path.normcase(item['archive']),item['member'])
    return ('file',os.path.normcase(item['path']))

def physical_path(item):return item.get('archive') or item['path']

def scope_matcher(view):
    kind,value=view
    if kind=='folder':
        root=os.path.normcase(str(value)).rstrip('\\/');prefix=root+os.sep
        def contains(item):
            path=os.path.normcase(physical_path(item))
            return path==root or path.startswith(prefix)
        return contains
    if kind=='zip':
        archive=os.path.normcase(value)
        return lambda item:os.path.normcase(item.get('archive',''))==archive
    if kind=='zipfolder':
        archive,prefix=value;archive=os.path.normcase(archive);prefix=str(PurePosixPath(prefix)).rstrip('/')
        return lambda item:os.path.normcase(item.get('archive',''))==archive and (str(PurePosixPath(item.get('member','')))==prefix or str(PurePosixPath(item.get('member',''))).startswith(prefix+'/'))
    return lambda item:True

def in_scope(item,view):return scope_matcher(view)(item)

def available(item):return not item.get('missing') and Path(physical_path(item)).is_file()

def writable(item):
    if item.get('archive'):raise ValueError('ZIP 내부 사진은 읽기 전용입니다. 이름 변경·이동은 일반 파일에서 사용할 수 있습니다.')
