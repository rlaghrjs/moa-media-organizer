"""Background physical enumeration and read-only ZIP indexing."""
import os
import time
from pathlib import Path
from moa.contracts import EXTENSIONS,IMAGES
from moa.sources.zip_source import index_zip

def scan_folder(folder,progress=None,extensions=None,previous=()):
    allowed=EXTENSIONS if extensions is None else set(extensions)&EXTENSIONS
    records=[];errors=[];directories=0;last=0;old={}
    for item in previous:
        if item.get('archive') and not item.get('missing'):old.setdefault(os.path.normcase(item['archive']),[]).append(item)
    def add(p):
        if p.suffix.lower()=='.zip' and allowed&IMAGES:
            try:
                entries,problems=index_zip(p,allowed,old.get(os.path.normcase(str(p.absolute())),()),progress);records.extend(entries);errors.extend(problems)
            except Exception as error:errors.append(str(p)+': '+str(error))
        elif p.suffix.lower() in allowed:
            try:
                stat=p.stat();records.append({'path':str(p.absolute()),'size':stat.st_size,'modified':stat.st_mtime_ns})
            except OSError as error:errors.append(str(error))
    if Path(folder).suffix.lower()=='.zip' and not Path(folder).is_dir():
        if Path(folder).exists():add(Path(folder))
        return records,errors
    for directory,_,names in os.walk(folder,onerror=lambda e:errors.append(str(e)),followlinks=False):
        directories+=1
        for name in names:
            add(Path(directory)/name)
            if progress and time.monotonic()-last>.1:
                progress((f'검색 중 · 폴더 {directories:,}개 · 미디어 {len(records):,}개',None,None));last=time.monotonic()
    return records,errors
