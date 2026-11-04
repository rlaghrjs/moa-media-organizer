"""Bounded, prioritized task broker. Native image objects are made only in UI thread."""
import hashlib
import heapq
import itertools
import multiprocessing
import os
import time
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from PySide6.QtCore import QObject,QTimer,Signal
from PySide6.QtGui import QPixmap,QImage
from moa.contracts import is_video
from moa.image.worker import render_photo
from moa.video.thumbnail_worker import render_video_thumbnail

class MediaTasks(QObject):
    ready=Signal(str)
    def __init__(self,cache,parent=None):
        super().__init__(parent);self.cache=Path(cache);self.cache.mkdir(parents=True,exist_ok=True)
        ctx=multiprocessing.get_context('spawn')
        self.photo_pool=ProcessPoolExecutor(max_workers=max(1,min(2,(os.cpu_count() or 2)-1)),mp_context=ctx)
        self.video_pool=ProcessPoolExecutor(max_workers=1,mp_context=ctx)
        self.queue=[];self.serial=itertools.count();self.pending={};self.inflight={};self.memory=OrderedDict();self.errors={};self.bytes=0;self.generation=0;self.playing=False;self.closed=False
        self.timer=QTimer(self);self.timer.timeout.connect(self.poll);self.timer.start(70)
        self.dimensions=OrderedDict();self.active_archives={};self.worker_pids=set();self.last_prune=0
    def key(self,item,size):
        source=f"v2|{item['path']}|{item.get('modified',0)}|{item.get('size',0)}|{size}"
        if size==400:source+="|resolution-v1"
        if item.get('archive'):source+=f"|zip|{item.get('archive_signature','')}|{item.get('crc','')}"
        return hashlib.sha256(source.encode()).hexdigest()
    def cached(self,item,size):
        key=self.key(item,size)
        if key in self.memory:self.memory.move_to_end(key);return self.memory[key]
        path=self.cache/(key+'.png')
        if path.exists():
            if size==400:
                image=QImage(str(path));self.record_dimensions(key,image.text('MoaResolution'));pixmap=QPixmap.fromImage(image)
            else:pixmap=QPixmap(str(path))
            if not pixmap.isNull():self.remember(key,pixmap);return pixmap
        return None
    def record_dimensions(self,key,value):
        if value:
            self.dimensions[key]=value
            self.dimensions.move_to_end(key)
            if len(self.dimensions)>4096:self.dimensions.popitem(last=False)

    def remember(self,key,pixmap):
        if key in self.memory:return
        cost=pixmap.width()*pixmap.height()*4
        self.memory[key]=pixmap;self.bytes+=cost
        while self.bytes>96*1024*1024 and len(self.memory)>1:
            _,old=self.memory.popitem(last=False);self.bytes-=old.width()*old.height()*4
    def request(self,item,size,priority=10):
        if self.closed:return None
        key=self.key(item,size);pixmap=self.cached(item,size)
        if pixmap is not None or key in self.errors or key in self.inflight:return pixmap
        existing=self.pending.get(key)
        if existing is not None and existing[0]<=priority:return None
        if existing is None and len(self.pending)>=256:
            worst=max(self.pending,key=lambda k:(self.pending[k][0],self.pending[k][1]))
            if self.pending[worst][0]<=priority:return None
            del self.pending[worst]
        job=(priority,next(self.serial),key,dict(item),size,self.generation);self.pending[key]=job
        # Remove superseded/evicted jobs so urgent selections cannot be starved.
        self.queue=list(self.pending.values());heapq.heapify(self.queue)
        return None
    def new_generation(self):
        self.generation+=1;self.pending.clear();self.queue.clear()
    def poll(self):
        if self.closed:return
        for video_type in (False,True):
            stalled=[key for key,(_,v,start) in self.inflight.items() if v==video_type and time.monotonic()-start>30]
            if not stalled:continue
            pool=self.video_pool if video_type else self.photo_pool
            if hasattr(pool,'terminate_workers'):pool.terminate_workers()
            else:
                # Older Python: terminate known spawned children before shutting down the pool.
                for process in list(getattr(pool,'_processes',{}).values()):
                    if process.is_alive():process.terminate()
                pool.shutdown(wait=False,cancel_futures=True)
            for key,(_,v,_) in list(self.inflight.items()):
                if v==video_type:
                    del self.inflight[key];self.active_archives.pop(key,None);self.errors[key]='미디어 읽기 시간이 초과되었습니다. 파일을 다시 불러와 확인하세요.';self.ready.emit(key)
            replacement=ProcessPoolExecutor(max_workers=1 if video_type else max(1,min(2,(os.cpu_count() or 2)-1)),mp_context=multiprocessing.get_context('spawn'))
            if video_type:self.video_pool=replacement
            else:self.photo_pool=replacement
        for key,(future,video,started) in list(self.inflight.items()):
            if not future.done():continue
            del self.inflight[key];self.active_archives.pop(key,None)
            try:
                result=future.result();self.worker_pids.add(result['pid'])
                self.record_dimensions(key,result.get('resolution'))
                if result['error']:self.errors[key]=result['error']
                else:
                    pixmap=QPixmap(result['path'])
                    if pixmap.isNull():self.errors[key]='캐시 이미지를 읽지 못했습니다.'
                    else:self.remember(key,pixmap)
            except Exception as error:self.errors[key]=str(error)
            self.ready.emit(key)
        deferred=[]
        # At most two photo and one video-thumbnail tasks; playback lowers background concurrency.
        for _ in range(min(len(self.queue),64)):
            job=heapq.heappop(self.queue);priority,serial,key,item,size,generation=job
            if self.pending.get(key)!=job:continue
            video=is_video(item['path']);active=sum(1 for _,v,_ in self.inflight.values() if v==video)
            limit=0 if video and self.playing else (1 if video or self.playing else 2)
            if active>=limit:deferred.append(job);continue
            # A single container is read by at most one task at a time.
            archive=item.get('archive')
            if archive and archive in self.active_archives.values():deferred.append(job);continue
            del self.pending[key]
            try:
                function=render_video_thumbnail if video else render_photo
                pool=self.video_pool if video else self.photo_pool
                future=pool.submit(function,item if item.get('archive') else item['path'],size,str(self.cache/(key+'.png')))
                self.inflight[key]=(future,video,time.monotonic())
                if archive:self.active_archives[key]=archive
            except Exception as error:self.errors[key]=str(error);self.ready.emit(key)
        for job in deferred:heapq.heappush(self.queue,job)
    def prune(self):
        # Called on exit, after all workers are stopped. Keep disk cache below 512 MiB.
        paths=[];total=0
        for path in self.cache.glob('*.png'):
            try:stat=path.stat();paths.append((stat.st_mtime,path,stat.st_size));total+=stat.st_size
            except OSError:pass
        for _,path,size in sorted(paths):
            if total<=512*1024*1024:break
            try:path.unlink();total-=size
            except OSError:pass
    def close(self):
        self.closed=True;self.timer.stop();self.pending.clear();self.queue.clear()
        for future,_,_ in self.inflight.values():future.cancel()
        for pool in (self.photo_pool,self.video_pool):
            # Worker termination prevents a broken codec from keeping the app alive indefinitely.
            if hasattr(pool,'terminate_workers'):pool.terminate_workers()
            else:pool.shutdown(wait=False,cancel_futures=True)
        self.prune()
