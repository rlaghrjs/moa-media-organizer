"""Pure-data preparation for imports, folder trees and filtered listings."""
import os
import uuid
from pathlib import Path
from moa.contracts import natural,EXTENSIONS
from moa.storage.json_store import write_snapshot
from moa.application.scan import scan_folder
from moa.sources.media_source import identity,physical_path,in_scope,scope_matcher

def report(callback,label,current=None,total=None):
    if callback:callback((label,current,total))

def import_library(data,folder,directory,progress=None,extensions=None):
    allowed=sorted(EXTENSIONS if extensions is None else set(extensions)&EXTENSIONS)
    records,errors=scan_folder(folder,progress,allowed,data['files'].values())
    known={identity(v):i for i,v in data['files'].items()}
    total=len(records)
    for index,record in enumerate(records):
        key=identity(record);ident=known.get(key) or uuid.uuid4().hex
        data['files'][ident]={**record,'tags':data['files'].get(ident,{}).get('tags',[]),'missing':False};known[key]=ident
        if index%250==0:report(progress,'파일 목록 준비',index,total)
    if folder not in data['roots']:data['roots'].append(folder)
    data.setdefault('root_filters',{})[folder]=allowed
    report(progress,'라이브러리 저장 중…');write_snapshot(directory,data)
    return data,len(records),errors

def listing_ids(data,view,needle,sort,descending,progress=None,search_mode='all'):
    kind,value=view
    candidates=data['albums'].get(value,[]) if kind=='album' else data['files'].keys()
    ids=[];total=len(candidates);accept=scope_matcher(view)
    for n,ident in enumerate(candidates):
        item=data['files'].get(ident)
        if item is None:continue
        if not accept(item):continue
        if not matches(item,needle,search_mode):continue
        ids.append(ident)
        if n%1000==0:report(progress,'파일 목록 준비',n,total)
    def key(ident):
        item=data['files'][ident];name=natural(os.path.basename(item['path']))
        return (item.get('modified',0),name) if sort=='date' else (os.path.splitext(item['path'])[1].lower(),name) if sort=='type' else name
    report(progress,'파일 정렬 중…');ids.sort(key=key,reverse=descending)
    return ids

def tree_plan(data,show_folders,progress=None):
    # entries: stable key, parent key, label, navigation payload, icon type
    entries=[('library',None,'라이브러리',None,None),('all','library',f"모든 파일   {len(data['files'])}",('all',None),'all')]
    if show_folders:
        entries.append(('folders',None,'실제 폴더',None,None))
        roots=[str(Path(r).parent) if Path(r).suffix.lower()=='.zip' else r for r in data['roots']] or list({str(Path(v['path']).parent) for v in data['files'].values()})
        accepted=set();roots_out=[]
        for root in sorted(set(roots),key=lambda p:len(Path(p).parts)):
            normalized=os.path.normcase(root)
            if normalized in accepted or any(os.path.normcase(str(parent)) in accepted for parent in Path(root).parents):continue
            accepted.add(normalized);roots_out.append(root)
        known={};folders=set()
        for n,item in enumerate(data['files'].values()):
            folders.add(os.path.dirname(physical_path(item)))
            if n%1000==0:report(progress,'폴더 경로 수집',n,len(data['files']))
        root_map={os.path.normcase(p):p for p in roots_out}
        for root in roots_out:
            key='folder:'+os.path.normcase(root);known[os.path.normcase(root)]=key
            entries.append((key,'folders',Path(root).name or root,('folder',root),'folder'))
        for n,folder in enumerate(sorted(folders,key=natural)):
            folder_path=Path(folder);root=None
            for parent in [folder_path,*folder_path.parents]:
                root=root_map.get(os.path.normcase(str(parent)))
                if root:break
            if not root:continue
            current=Path(root)
            for part in folder_path.relative_to(root).parts:
                parent_key=known[os.path.normcase(str(current))];current=current/part;normalized=os.path.normcase(str(current))
                if normalized not in known:
                    key='folder:'+normalized;known[normalized]=key;entries.append((key,parent_key,part,('folder',str(current)),'folder'))
            if n%250==0:report(progress,'폴더 경로 구성',n,len(folders))
    archives={}
    for item in data['files'].values():
        if item.get('archive'):archives.setdefault(item['archive'],set()).add(str(Path(item['member']).parent).replace('\\','/'))
    if archives:
        entries.append(('archives',None,'ZIP 사진 · 읽기 전용',None,None))
        for archive,folders in sorted(archives.items(),key=lambda p:natural(p[0])):
            rootkey='zip:'+archive;entries.append((rootkey,'archives',Path(archive).name,('zip',archive),'folder'));known={'.':rootkey}
            for folder in sorted(folders,key=natural):
                current=''
                for part in folder.split('/'):
                    if part=='.':continue
                    parent=known[current or '.'];current=(current+'/' if current else '')+part
                    if current not in known:
                        key=rootkey+'!/'+current;known[current]=key;entries.append((key,parent,part,('zipfolder',(archive,current)),'folder'))
    entries.append(('albums',None,'앨범 · 원본 위치 유지',None,None))
    for name,members in sorted(data['albums'].items(),key=lambda pair:natural(pair[0])):
        entries.append(('album:'+name,'albums',f'{name}   {len(members)}',('album',name),'album'))
    return entries


def matches(item,query,mode='all'):
    needle=query.strip().casefold()
    if not needle:return True
    if mode=='tag':return any(needle==str(tag).casefold() for tag in item['tags'])
    if mode=='name':return needle in os.path.basename(item['path']).casefold()
    return needle in (item['path']+' '+','.join(item['tags'])).casefold()


def search_suggestions(data,view,query):
    needle=query.strip().casefold()
    if not needle:return []
    kind,value=view;candidates=data['albums'].get(value,[]) if kind=='album' else data['files'].keys()
    tags={};names={};total=0;accept=scope_matcher(view)
    for ident in candidates:
        item=data['files'].get(ident)
        if item is None:continue
        if not accept(item):continue
        if matches(item,needle):total+=1
        name=os.path.basename(item['path'])
        if needle in name.casefold():names[name]=names.get(name,0)+1
        for tag in set(item['tags']):
            if needle in tag.casefold():tags[tag]=tags.get(tag,0)+1
    rank=lambda pair:(not pair[0].casefold().startswith(needle),natural(pair[0]))
    rows=[{'kind':'tag','query':tag,'label':f'[태그]  {tag}   · {count}개'} for tag,count in sorted(tags.items(),key=rank)[:4]]
    rows += [{'kind':'name','query':name,'label':f'[이름]  {name}   · {count}개'} for name,count in sorted(names.items(),key=rank)[:4]]
    rows.append({'kind':'all','query':query.strip(),'label':f'전체 결과 보기   · {total}개'})
    return rows


def refresh_library(data,targets,directory,progress=None):
    """Manual reconciliation. Preserve file IDs, albums and missing-file records."""
    known={identity(item):ident for ident,item in data['files'].items()}
    filters=data.get('root_filters',{});seen=set();healthy=[];errors=[];added=modified=missing=restored=0
    for number,folder in enumerate(dict.fromkeys(targets)):
        inherited=set()
        for root in data['roots']:
            if Path(folder).is_relative_to(root):inherited.update(filters.get(root,EXTENSIONS))
        allowed=filters.get(folder,sorted(inherited) if inherited else EXTENSIONS)
        report(progress,f'새로고침 · {number+1}/{len(targets)} 폴더 검색 중…')
        records,problems=scan_folder(folder,progress,allowed,data['files'].values());errors.extend(problems)
        if not problems:healthy.append((folder,set(allowed)))
        for record in records:
            key=identity(record);seen.add(key);ident=known.get(key)
            if ident is None:ident=uuid.uuid4().hex;known[key]=ident;added+=1
            else:
                old=data['files'][ident]
                if old.get('modified')!=record['modified'] or old.get('size')!=record['size'] or old.get('archive_signature')!=record.get('archive_signature') or old.get('crc')!=record.get('crc'):modified+=1
                if old.get('missing'):restored+=1
            data['files'][ident]={**record,'tags':data['files'].get(ident,{}).get('tags',[]),'missing':False}
        report(progress,'파일 변경 비교',number+1,len(targets))
    for ident,item in list(data['files'].items()):
        if identity(item) in seen:continue
        # Do not infer deletion when a directory scan reported access/IO errors.
        if any(Path(physical_path(item)).is_relative_to(folder) and Path(item['path']).suffix.lower() in allowed for folder,allowed in healthy):
            if not item.get('missing'):
                data['files'][ident]={**item,'missing':True};missing+=1
    if added or modified or missing or restored:
        report(progress,'변경 정보 저장 중…');write_snapshot(directory,data)
    return data,{'added':added,'modified':modified,'missing':missing,'restored':restored,'errors':errors}
