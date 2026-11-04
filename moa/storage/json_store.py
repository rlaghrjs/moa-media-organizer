"""Single-writer JSON library. Existing SQLite is read only for one-time migration."""
import copy
import json
import os
import shutil
import sqlite3
import time
import uuid
from moa.sources.media_source import writable
from pathlib import Path

DEFAULT_SETTINGS={'show_folders':False,'sort':'name','descending':False,'details':False,'width':1380,'height':860,'import_extensions':[]}

def atomic_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    with temporary.open('w',encoding='utf-8') as f:
        json.dump(data,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(temporary,path)

def read_json(path,default):
    if not path.exists():return copy.deepcopy(default)
    with path.open(encoding='utf-8-sig') as f:return json.load(f)

def empty_library():
    return {'version':1,'files':{},'albums':{},'moves':[],'roots':[],'root_filters':{}}

def validate(data):
    if not isinstance(data,dict) or data.get('version')!=1:raise ValueError('지원하지 않는 라이브러리 형식입니다.')
    for key,kind in [('files',dict),('albums',dict),('moves',list),('roots',list)]:
        if not isinstance(data.get(key),kind):raise ValueError('잘못된 라이브러리 항목: '+key)
    for key,item in data['files'].items():
        if not isinstance(item,dict) or not isinstance(item.get('path'),str) or not isinstance(item.get('tags'),list):raise ValueError('파일 정보가 올바르지 않습니다: '+key)
    for name,members in data['albums'].items():
        if not isinstance(members,list) or any(i not in data['files'] for i in members):raise ValueError('앨범 연결이 올바르지 않습니다: '+name)
    filters=data.setdefault('root_filters',{})
    if not isinstance(filters,dict) or any(not isinstance(root,str) or not isinstance(values,list) or any(not isinstance(v,str) for v in values) for root,values in filters.items()):
        raise ValueError('폴더별 확장자 설정이 올바르지 않습니다.')
    return data

class Store:
    def __init__(self,directory,legacy=None):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.file=self.directory/'library.json';self.notice=[];self.save_handler=None
        self.settings=dict(DEFAULT_SETTINGS)
        try:
            settings=read_json(self.directory/'settings.json',{})
            if isinstance(settings,dict):self.settings.update({k:v for k,v in settings.items() if k in DEFAULT_SETTINGS and type(v) is type(DEFAULT_SETTINGS[k])})
        except (ValueError,OSError):self.notice.append('설정을 읽지 못해 기본값으로 시작했습니다.')
        try:self.data=validate(read_json(self.file,empty_library()))
        except (ValueError,OSError) as error:
            backup=self.file.with_suffix('.json.bak')
            self.data=validate(read_json(backup,{}))
            damaged=self.file.with_name('library-damaged-'+str(time.time_ns())+'.json')
            shutil.copy2(self.file,damaged)
            # Preserve the valid backup; do not back up the damaged primary over it.
            atomic_json(self.file,self.data)
            self.notice.append('라이브러리 손상을 감지해 백업을 복구했습니다. 손상본도 보존했습니다.')
        if not self.file.exists():
            if legacy and Path(legacy).exists():self.migrate(legacy)
            self.save()
        journal=self.directory/'pending-move.json'
        if journal.exists():
            # Never delete either physical file automatically during recovery.
            record=read_json(journal,{})
            item=self.data['files'].get(record.get('id'))
            if item and not Path(item['path']).exists():
                for key in ('src','dst'):
                    if record.get(key) and Path(record[key]).is_file():item['path']=record[key];self.save();break
            os.replace(journal,self.directory/('recovered-move-'+str(time.time_ns())+'.json'))
            self.notice.append('중단된 파일 이동 기록이 있습니다. 원본과 대상 파일을 모두 보존했습니다. data 폴더의 recovered-move 기록에서 경로를 확인하세요.')

        journal=self.directory/'pending-rename.json'
        if journal.exists():
            record=read_json(journal,{});item=self.data['files'].get(record.get('id'))
            if item and not Path(item['path']).exists():
                for key in ('dst','src'):
                    if record.get(key) and Path(record[key]).is_file():
                        self.data['files'][record['id']]={**item,'path':record[key]};self.save();break
            os.replace(journal,self.directory/('recovered-rename-'+str(time.time_ns())+'.json'))
            self.notice.append('중단된 이름 변경 기록을 확인했습니다. 실제 파일 경로를 복구하고 기록을 보존했습니다.')

    def migrate(self,path):
        connection=sqlite3.connect(Path(path).absolute().as_uri()+'?mode=ro',uri=True)
        try:
            mapping={}
            for path,tags in connection.execute('SELECT path,tags FROM files'):
                ident=uuid.uuid4().hex;mapping[path]=ident
                try:s=Path(path).stat();size=s.st_size;modified=s.st_mtime_ns
                except OSError:size=modified=0
                self.data['files'][ident]={'path':path,'tags':[t.strip() for t in (tags or '').split(',') if t.strip()],'size':size,'modified':modified}
            for name, in connection.execute('SELECT name FROM albums'):self.data['albums'][name]=[]
            for path,name in connection.execute('SELECT path,album FROM members'):
                if path in mapping:self.data['albums'].setdefault(name,[]).append(mapping[path])
            self.data['roots']=sorted({str(Path(p).parent) for p in mapping})
            self.notice.append(f'기존 분류에서 {len(mapping)}개 파일과 앨범을 가져왔습니다. 기존 DB는 변경하지 않았습니다.')
        finally:connection.close()

    def snapshot(self):
        # Records and membership lists use copy-on-write, so background serialization
        # can keep these references while UI edits replace individual records.
        return {'version':1,'files':dict(self.data['files']),'albums':dict(self.data['albums']),
                'moves':list(self.data['moves']),'roots':list(self.data['roots']),'root_filters':dict(self.data.get('root_filters',{}))}

    def save(self):
        if self.save_handler:self.save_handler()
        else:self.write_now()

    def write_now(self):
        # Filesystem move journal must be durable before deleting the source.
        write_snapshot(self.directory,self.snapshot())

    def save_settings(self):atomic_json(self.directory/'settings.json',self.settings)

    def import_files(self,records,root=None):
        known={os.path.normcase(v['path']):i for i,v in self.data['files'].items()}
        for record in records:
            key=os.path.normcase(record['path']);ident=known.get(key) or uuid.uuid4().hex
            tags=self.data['files'].get(ident,{}).get('tags',[])
            self.data['files'][ident]={**record,'tags':tags};known[key]=ident
        if root and root not in self.data['roots']:self.data['roots'].append(root)
        self.save()

    def album(self,name,ids=()):
        name=name.strip()
        if not name:raise ValueError('앨범 이름을 입력하세요.')
        existed=name in self.data['albums'];members=list(self.data['albums'].get(name,[]));known=set(members);added=[]
        for ident in ids:
            if ident in self.data['files'] and ident not in known:
                members.append(ident);known.add(ident);added.append(ident)
        self.data['albums'][name]=members
        if not existed or added:self.save()
        return added

    def rename_album(self,name,new_name):
        new_name=new_name.strip()
        if name not in self.data['albums']:raise ValueError('앨범이 없습니다.')
        if not new_name:raise ValueError('앨범 이름을 입력하세요.')
        if new_name==name:return False
        if new_name in self.data['albums']:raise ValueError('같은 이름의 앨범이 이미 있습니다.')
        self.data['albums']={new_name if key==name else key:members for key,members in self.data['albums'].items()}
        self.save();return True

    def delete_album(self,name):
        if name not in self.data['albums']:raise ValueError('앨범이 없습니다.')
        self.data['albums']={key:members for key,members in self.data['albums'].items() if key!=name}
        self.save()

    def remove_members(self,name,ids):
        self.data['albums'][name]=[i for i in self.data['albums'][name] if i not in ids];self.save()

    def tags(self,ids,tags):
        for ident in ids:self.data['files'][ident]={**self.data['files'][ident],'tags':list(dict.fromkeys(tags))}
        self.save()

    def move(self,ident,destination,undo_index=None):
        writable(self.data['files'][ident])
        item=self.data['files'][ident];source=Path(item['path']);destination=Path(destination).absolute()
        if not source.is_file():raise ValueError('원본 파일이 없습니다.')
        if any(os.path.normcase(v['path'])==os.path.normcase(str(destination)) for v in self.data['files'].values()):raise ValueError('이미 등록된 대상 경로입니다.')
        if destination.exists():raise FileExistsError('동일 이름의 파일이 있습니다. 덮어쓰지 않았습니다.')
        journal=self.directory/'pending-move.json'
        record={'id':ident,'src':str(source),'dst':str(destination),'phase':'copying'}
        atomic_json(journal,record)
        created=False;committed=False
        before=copy.deepcopy(self.data)
        try:
            with destination.open('xb') as out:
                created=True
                with source.open('rb') as inp:shutil.copyfileobj(inp,out,length=1024*1024)
                out.flush();os.fsync(out.fileno())
            shutil.copystat(source,destination)
            record['phase']='copied';atomic_json(journal,record)
            self.data['files'][ident]={**item,'path':str(destination)}
            if undo_index is None:self.data['moves']=[*self.data['moves'],{'id':ident,'src':str(source),'dst':str(destination),'undone':False}]
            else:self.data['moves']=[{**record,'undone':True} if index==undo_index else record for index,record in enumerate(self.data['moves'])]
            self.write_now();committed=True
            source.unlink()
        except BaseException:
            if source.exists():
                self.data=before
                if committed:self.write_now()
                if created:destination.unlink(missing_ok=True)
                journal.unlink(missing_ok=True)
            raise
        journal.unlink(missing_ok=True)

    def rename_file(self,ident,name,undo_index=None):
        writable(self.data['files'][ident])
        import re
        item=self.data['files'][ident];source=Path(item['path'])
        if not name or name in ('.','..') or re.search(r'[<>:"/\\|?*\x00-\x1f]',name) or name.endswith((' ','.')):
            raise ValueError('파일 이름에 사용할 수 없는 문자 또는 끝 공백이 있습니다.')
        if name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
            raise ValueError('Windows에서 예약된 파일 이름입니다.')
        if Path(name).suffix.casefold()!=source.suffix.casefold():raise ValueError('확장자는 유지해 주세요.')
        destination=source.with_name(name)
        if str(source)==str(destination):return False
        if not source.is_file():raise ValueError('원본 파일이 없습니다.')
        same=os.path.normcase(str(source))==os.path.normcase(str(destination))
        if destination.exists() and not same:raise FileExistsError('같은 이름의 파일이 있습니다. 덮어쓰지 않았습니다.')
        if any(i!=ident and os.path.normcase(v['path'])==os.path.normcase(str(destination)) for i,v in self.data['files'].items()):raise ValueError('이미 등록된 파일 이름입니다.')
        journal=self.directory/'pending-rename.json';record={'id':ident,'src':str(source),'dst':str(destination)}
        atomic_json(journal,record);before=self.snapshot();renamed=False
        try:
            source.rename(destination);renamed=True
            self.data['files'][ident]={**item,'path':str(destination),'missing':False}
            if undo_index is None:self.data['moves']=[*self.data['moves'],{**record,'kind':'rename','undone':False}]
            else:self.data['moves']=[{**r,'undone':True} if i==undo_index else r for i,r in enumerate(self.data['moves'])]
            self.write_now()
        except BaseException:
            if renamed:
                destination.rename(source)
            self.data=before;journal.unlink(missing_ok=True);raise
        journal.unlink(missing_ok=True);return True

    def undo(self):
        for index in range(len(self.data['moves'])-1,-1,-1):
            record=self.data['moves'][index]
            if not record['undone']:
                if self.data['files'][record['id']]['path']!=record['dst']:raise ValueError('현재 파일 위치가 이동 기록과 다릅니다.')
                if record.get('kind')=='rename':self.rename_file(record['id'],Path(record['src']).name,index)
                else:self.move(record['id'],record['src'],index)
                return
        raise ValueError('취소할 이동 기록이 없습니다.')


def write_snapshot(directory,data):
    """Runs on the single file-IO executor, independently of UI updates."""
    validate(data);path=Path(directory)/'library.json'
    if path.exists():
        backup=path.with_suffix('.json.bak');temporary=backup.with_suffix('.bak.tmp')
        with path.open('rb') as source,temporary.open('wb') as output:
            shutil.copyfileobj(source,output);output.flush();os.fsync(output.fileno())
        os.replace(temporary,backup)
    atomic_json(path,data)
