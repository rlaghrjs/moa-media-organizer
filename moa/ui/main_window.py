from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import os
import textwrap
import queue
import time
from PySide6.QtCore import Qt,QTimer,QItemSelectionModel,QPoint,QSize,QEvent
from PySide6.QtGui import QAction,QActionGroup,QFont,QCursor,QKeySequence,QShortcut,QPixmap
from PySide6.QtWidgets import (QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QPushButton,QSplitter,QTreeWidgetItem,QListView,QTableView,QAbstractItemView,QStackedWidget,QFileDialog,QInputDialog,QMessageBox,QMenuBar,QStyle,QHeaderView,QSizePolicy,QApplication,QProgressBar,QAbstractSpinBox,QTextEdit,QPlainTextEdit,QSlider,QDialog,QMenu)
from moa.contracts import natural,is_video,EXTENSIONS
from moa.application.library_jobs import tree_plan,listing_ids,import_library,refresh_library,matches
from moa.storage.async_saver import LibrarySaver
from moa.application.media_tasks import MediaTasks
from moa.ui.media_model import MediaModel,ThumbnailDelegate,AlbumTree
from moa.ui.viewer import Viewer
from moa.ui.import_dialog import ExtensionDialog
from moa.ui.search_control import SearchControl
from moa.ui.search_panel import SearchPanel
from moa.sources.media_source import physical_path,writable
from moa.contracts import IMAGES

STYLE='''
QMainWindow,QWidget{font-family:"맑은 고딕";font-size:12px;color:#293649;background:#ffffff;}
QMenuBar{background:#f3f5f8;border-bottom:1px solid #e1e6ed;padding:5px 12px;spacing:3px;}
QMenuBar::item{padding:8px 15px;background:transparent;border-radius:4px;}
QMenuBar::item:selected,QMenu::item:selected{background:#e7f0fc;color:#205fa8;}
QMenu{background:white;border:1px solid #dce3ec;padding:6px;}
QMenu::item{padding:9px 28px 9px 17px;border-radius:3px;}
QMenu::separator{height:1px;background:#e3e8ef;margin:5px;}
QPushButton{background:#ffffff;border:1px solid #d9e1eb;border-radius:5px;padding:7px 12px;min-height:17px;}
QPushButton:hover{background:#f1f6fd;border-color:#8cb0dc;} QPushButton:checked{background:#e7f0fc;color:#205fa8;}
QPushButton:disabled{color:#a4acb7;background:#f7f8fa;}
QLineEdit{border:1px solid #dbe2eb;border-radius:6px;padding:8px;background:white;selection-background-color:#d9e8fc;}
QTreeWidget{background:#f5f7fa;border:0;padding:10px 5px;outline:none;}
QTreeWidget::item{padding:8px 6px;border-radius:4px;}QTreeWidget::item:selected{background:#e4eefc;color:#245f9f;}
QListView,QTableView{background:white;border:0;outline:none;selection-background-color:#e6f0fd;selection-color:#273649;}
QTableView::item{padding:9px;border-bottom:1px solid #edf0f4;}
QHeaderView::section{background:#f7f9fc;padding:10px;border:0;border-bottom:1px solid #e1e6ee;}
QSplitter::handle{background:#e7ebf1;width:1px;}
QStatusBar{background:#f7f9fc;border-top:1px solid #e4e9f0;color:#6a788b;}
QScrollBar:vertical{background:#f8fafc;width:11px;border:0;}QScrollBar::handle:vertical{background:#c5ceda;border-radius:5px;min-height:28px;}QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}
QSlider::groove:horizontal{height:4px;background:#dce3ed;border-radius:2px;}QSlider::handle:horizontal{background:#377bbd;width:13px;margin:-5px 0;border-radius:6px;}
'''

class HoverMenuBar(QMenuBar):
    def __init__(self,parent=None):
        super().__init__(parent);self.setMouseTracking(True);self.hover_action=None
        self.hover_timer=QTimer(self);self.hover_timer.setSingleShot(True);self.hover_timer.setInterval(130);self.hover_timer.timeout.connect(self.open_hover)
    def mouseMoveEvent(self,event):
        super().mouseMoveEvent(event);action=self.actionAt(event.position().toPoint())
        if action!=self.hover_action:self.hover_action=action;self.hover_timer.start()
    def leaveEvent(self,event):self.hover_timer.stop();super().leaveEvent(event)
    def open_hover(self):
        action=self.hover_action
        if self.isEnabled() and action and action.menu() and self.actionAt(self.mapFromGlobal(QCursor.pos()))==action:
            action.menu().popup(self.mapToGlobal(self.actionGeometry(action).bottomLeft()))

class MainWindow(QMainWindow):
    @property
    def busy(self):
        timer=getattr(self,'navigation_timer',None)
        return self._busy or bool(timer and timer.isActive())
    @busy.setter
    def busy(self,value):self._busy=value
    def __init__(self,store,base):
        super().__init__();self.store=store;self.base=Path(base);self.view=('all',None);self.busy=False;self.future=None;self.viewer_id=None;self.preview_id=None;self.preview_key=None;self.closing=False;self.progress_events=queue.Queue();self.save_label='';self.album_items={};self.tree_nodes={};self.search_mode='all';self.pending_search=False
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='MoaFileIO')
        self.setWindowTitle('모아 — 사진·영상 라이브러리');self.resize(store.settings['width'],store.settings['height']);self.setMinimumSize(1040,650);self.setStyleSheet(STYLE)
        self.tasks=MediaTasks(store.directory/'cache',self);self.model=MediaModel(store,self.tasks,self)
        self.setup_menus();self.setup_layout()
        self.tree_icons={name:self.style().standardIcon(kind) for name,kind in {'all':QStyle.StandardPixmap.SP_FileDialogContentsView,'folder':QStyle.StandardPixmap.SP_DirIcon,'album':QStyle.StandardPixmap.SP_DirOpenIcon}.items()}
        self.tasks.ready.connect(self.asset_ready)
        self.saver=LibrarySaver(store,self.executor,self);self.saver.changed.connect(self.save_changed);self.saver.failed.connect(self.save_failed);self.saver.idle.connect(self.save_idle)
        QApplication.instance().installEventFilter(self)
        self.poll_timer=QTimer(self);self.poll_timer.timeout.connect(self.poll_operations);self.poll_timer.start(100)
        self.search_control=SearchControl(self.search,self.store.snapshot,lambda:self.view,self.search_panel,self)
        self.search_control.chosen.connect(self.apply_search);self.search_control.edited.connect(self.search_edited)
        self.tree.itemExpanded.connect(self.expand_folder);self.tree.itemCollapsed.connect(self.collapse_folder)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu);self.tree.customContextMenuRequested.connect(self.tree_context_menu)
        self.tree.currentItemChanged.connect(self.navigation_changed);self.tree.filesDropped.connect(self.album_drop)
        self.selection=QItemSelectionModel(self.model,self);self.grid.setSelectionModel(self.selection);self.table.setSelectionModel(self.selection);self.selection.selectionChanged.connect(self.selection_changed)
        self.grid.doubleClicked.connect(lambda index:self.open_viewer(index.data(Qt.ItemDataRole.UserRole)));self.table.doubleClicked.connect(lambda index:self.open_viewer(index.data(Qt.ItemDataRole.UserRole)))
        self.grid.verticalScrollBar().valueChanged.connect(self.scrolled)
        self.scroll_timer=QTimer(self);self.scroll_timer.setSingleShot(True);self.scroll_timer.setInterval(120);self.scroll_timer.timeout.connect(lambda:self.grid.viewport().update())
        self.tree_timer=QTimer(self);self.tree_timer.setSingleShot(True);self.tree_timer.timeout.connect(self.tree_batch)
        self.expand_timer=QTimer(self);self.expand_timer.setSingleShot(True);self.expand_timer.timeout.connect(self.drain_expansions);self.expand_queue=[];self.loading_key=None;self.listing_revision=0
        self.navigation_timer=QTimer(self);self.navigation_timer.setSingleShot(True);self.navigation_timer.setInterval(45);self.navigation_timer.timeout.connect(self.refresh)
        self.rebuild_tree(done=self.refresh)
        for key,callback in [('Escape',self.escape_viewer),('F11',self.toggle_fullscreen),('Alt+Left',lambda:self.step_viewer(-1)),('Alt+Right',lambda:self.step_viewer(1)),('Ctrl+O',self.import_folder),('F5',self.reload_files),('F2',self.rename_selected_file)]:
            shortcut=QShortcut(QKeySequence(key),self);shortcut.activated.connect(callback)
        QTimer.singleShot(250,self.show_notices)
    def action(self,menu,text,callback,checkable=False,checked=False):
        action=QAction(text,self);action.setCheckable(checkable);action.setChecked(checked);action.triggered.connect(callback);menu.addAction(action);return action
    def setup_menus(self):
        self.setMenuBar(HoverMenuBar(self));bar=self.menuBar()
        file=bar.addMenu('파일');self.action(file,'폴더 불러오기…',self.import_folder);self.action(file,'ZIP 사진 불러오기…',self.import_zip);self.action(file,'새로고침 (F5)',self.reload_files);self.action(file,'선택 파일 열기',lambda:self.open_viewer());self.action(file,'탐색기에서 위치 열기',self.reveal_selected);self.rename_action=self.action(file,'실제 파일 이름 변경 (F2)…',self.rename_selected_file);file.addSeparator();self.move_action=self.action(file,'실제 파일 이동…',self.move_selected);self.action(file,'최근 이동·이름 변경 취소',self.undo_move);file.addSeparator();self.action(file,'종료',self.close)
        classify=bar.addMenu('분류');self.action(classify,'새 앨범…',self.new_album);self.action(classify,'현재 앨범 이름 변경…',self.rename_album);self.action(classify,'현재 앨범 삭제…',self.delete_album);self.action(classify,'선택 파일을 앨범에 추가…',self.add_to_album);self.action(classify,'현재 앨범에서 제외',self.remove_from_album);classify.addSeparator();self.action(classify,'태그 편집…',self.edit_tags)
        view=bar.addMenu('보기');self.paths_action=self.action(view,'왼쪽 실제 폴더 경로 표시',self.toggle_folders,True,self.store.settings['show_folders']);self.info_action=self.action(view,'오른쪽 미리보기 · 정보 표시',lambda checked:self.info.setVisible(checked),True,True)
        view.addSeparator();group=QActionGroup(self);group.setExclusive(True)
        for text,value in [('큰 아이콘',False),('자세히',True)]:
            a=self.action(view,text,lambda checked,v=value:self.change_mode(v),True,self.store.settings['details']==value);group.addAction(a)
        sort=view.addMenu('정렬 기준');group=QActionGroup(self);group.setExclusive(True)
        self.sort_actions={}
        for text,value in [('이름','name'),('날짜 (수정일)','date'),('확장자','type')]:
            a=self.action(sort,text,lambda checked,v=value:self.set_sort(v),True,self.store.settings['sort']==value);group.addAction(a);self.sort_actions[value]=a
        self.descending_action=self.action(view,'내림차순',self.set_descending,True,self.store.settings['descending'])
    def setup_layout(self):
        central=QWidget();layout=QVBoxLayout(central);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0);self.setCentralWidget(central)
        top=QWidget();top.setStyleSheet('background:#f7f9fc;border-bottom:1px solid #e4e9f0;');row=QHBoxLayout(top);row.setContentsMargins(20,15,20,15)
        brand=QLabel('모아');brand.setStyleSheet('font-size:21px;font-weight:600;color:#2865a7;border:0;');row.addWidget(brand);tagline=QLabel('사진 · 영상 라이브러리');tagline.setStyleSheet('color:#7c8999;border:0;');row.addSpacing(8);row.addWidget(tagline);row.addStretch()
        self.reload_button=QPushButton('↻ 새로고침');self.reload_button.setToolTip('현재 폴더 또는 등록된 폴더의 파일 변경을 확인합니다 (F5)');self.reload_button.clicked.connect(self.reload_files);row.addWidget(self.reload_button)
        self.search_kind=QLabel('');self.search_kind.setStyleSheet('color:#2865a7;border:0;');row.addWidget(self.search_kind)
        self.search=QLineEdit();self.search.setPlaceholderText('태그·이름 검색 → 제안 선택 또는 Enter');self.search.setMinimumWidth(260);self.search.setMaximumWidth(390);row.addWidget(self.search);layout.addWidget(top)
        self.search_panel=SearchPanel(central,self.search);self.search_bar=top
        self.splitter=QSplitter();layout.addWidget(self.splitter,1)
        self.tree=AlbumTree();self.tree.setMinimumWidth(180);self.tree.setMaximumWidth(420);self.splitter.addWidget(self.tree)
        center=QWidget();v=QVBoxLayout(center);v.setContentsMargins(20,18,20,14);v.setSpacing(14)
        self.location=QLabel('라이브러리 / 모든 파일');self.location.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred);self.location.setStyleSheet('color:#748195;font-size:11px;');v.addWidget(self.location)
        self.pages=QStackedWidget();v.addWidget(self.pages,1)
        self.library_page=QWidget();listing=QVBoxLayout(self.library_page);listing.setContentsMargins(0,0,0,0);listing.setSpacing(13)
        header=QHBoxLayout();self.heading=QLabel('모든 파일');self.heading.setStyleSheet('font-size:21px;font-weight:600;');header.addWidget(self.heading,1);self.count=QLabel();self.count.setStyleSheet('color:#748195;');header.addWidget(self.count);listing.addLayout(header)
        self.browser=QStackedWidget();listing.addWidget(self.browser,1)
        self.grid=QListView();self.grid.setModel(self.model);self.grid.setViewMode(QListView.ViewMode.IconMode);self.grid.setResizeMode(QListView.ResizeMode.Adjust);self.grid.setMovement(QListView.Movement.Static);self.grid.setWrapping(True);self.grid.setUniformItemSizes(True);self.grid.setLayoutMode(QListView.LayoutMode.Batched);self.grid.setBatchSize(250);self.grid.setGridSize(QSize(178,195));self.grid.setItemDelegate(ThumbnailDelegate(self.grid));self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection);self.grid.setDragEnabled(True);self.grid.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly);self.browser.addWidget(self.grid)
        self.table=QTableView();self.table.setModel(self.model);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection);self.table.setDragEnabled(True);self.table.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly);self.table.setShowGrid(False);self.table.verticalHeader().hide();self.table.horizontalHeader().setStretchLastSection(True);self.table.setColumnWidth(0,250);self.table.setColumnWidth(1,165);self.table.setColumnWidth(2,80);self.table.setColumnWidth(3,85);self.table.horizontalHeader().sectionClicked.connect(self.heading_sort);self.browser.addWidget(self.table)
        self.empty=QLabel('폴더를 불러와 사진과 영상을 정리해 보세요.\n\n파일 → 폴더 불러오기');self.empty.setWordWrap(True);self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter);self.empty.setStyleSheet('color:#7a8799;font-size:14px;');self.browser.addWidget(self.empty);self.pages.addWidget(self.library_page)
        self.viewer=Viewer(self.tasks,self.base/'vendor'/'mpv'/'libmpv-2.dll',self);self.viewer.back.connect(self.back_to_list);self.viewer.step.connect(self.step_viewer);self.viewer.fill.connect(self.fill_viewer);self.viewer.fullscreen.connect(self.toggle_fullscreen);self.viewer.playback.connect(self.playback_changed);self.pages.addWidget(self.viewer)
        self.splitter.addWidget(center)
        self.info=QWidget();self.info.setMinimumWidth(235);self.info.setMaximumWidth(350);info=QVBoxLayout(self.info);info.setContentsMargins(18,20,18,20);info.setSpacing(13)
        label=QLabel('미리보기 · 정보');label.setStyleSheet('color:#6f7e91;');info.addWidget(label)
        self.preview=QLabel('파일을 선택하세요');self.preview.setFixedHeight(175);self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter);self.preview.setWordWrap(True);self.preview.setStyleSheet('background:#f3f6fa;color:#8190a3;border-radius:5px;');info.addWidget(self.preview)
        self.open_button=QPushButton('내부 뷰어로 열기');self.open_button.clicked.connect(lambda:self.open_viewer());info.addWidget(self.open_button)
        buttons=QHBoxLayout();reveal=QPushButton('탐색기 열기');reveal.clicked.connect(self.reveal_selected);rename=QPushButton('이름 변경');self.rename_button=rename;rename.clicked.connect(self.rename_selected_file);buttons.addWidget(reveal);buttons.addWidget(rename);info.addLayout(buttons)
        self.resolution=QLabel();self.resolution.hide();info.addWidget(self.resolution)
        self.details=QLabel();self.details.setWordWrap(True);self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);info.addWidget(self.details)
        self.add_button=QPushButton('앨범에 추가');self.add_button.clicked.connect(self.add_to_album);info.addWidget(self.add_button)
        hint=QLabel('왼쪽 앨범에 파일을 드래그하면\n원본 위치를 유지하며 분류됩니다.');hint.setStyleSheet('color:#8190a3;font-size:11px;');hint.setWordWrap(True);info.addWidget(hint);info.addStretch();self.splitter.addWidget(self.info)
        self.splitter.setSizes([220,865,295]);self.statusBar().showMessage('준비');self.statusBar().setSizeGripEnabled(True)
        self.activity=QLabel();self.activity.setStyleSheet('background:transparent;color:#64758c;font-size:11px;');self.activity.hide()
        self.progress=QProgressBar();self.progress.setFixedSize(120,12);self.progress.setTextVisible(False);self.progress.hide()
        self.statusBar().addPermanentWidget(self.activity);self.statusBar().addPermanentWidget(self.progress)
    def show_notices(self):
        if self.store.notice:QMessageBox.information(self,'라이브러리 안내','\n\n'.join(self.store.notice));self.store.notice.clear()
    def rebuild_tree(self,done=None):
        data=self.store.snapshot();show=self.store.settings['show_folders']
        finish=lambda plan:self.start_tree_build(plan,done)
        if show or len(data['files'])>3000:
            self.begin_operation('폴더 목록 준비 중…',lambda:tree_plan(data,show,self.progress_events.put),finish)
        else:finish(tree_plan(data,show))

    def start_tree_build(self,plan,done=None):
        self.tree_timer.stop();self.expand_timer.stop();self.expand_queue=[];self.loading_key=None;self.tree_resume={}
        self.tree_children={};self.tree_entries={entry[0]:entry for entry in plan}
        for entry in plan:self.tree_children.setdefault(entry[1],[]).append(entry)
        selected=next((entry[0] for entry in plan if entry[3]==self.view),None)
        restore=set();parent=self.tree_entries.get(selected,(None,None))[1]
        while parent:
            if self.tree_entries[parent][4]=='folder':restore.add(parent)
            parent=self.tree_entries[parent][1]
        # Only roots and direct children of the selected folder's ancestors become widgets.
        initial=[entry for entry in plan if entry[4]!='folder' or entry[1] in ('folders','archives') or entry[1] in restore]
        self.tree_loaded=set(restore);self.tree_restore=restore;self.tree_is_reset=True
        self.busy=True;self.menuBar().setEnabled(False);self.splitter.setEnabled(False);self.reload_button.setEnabled(False)
        self.tree.blockSignals(True);self.tree.setUpdatesEnabled(False);self.tree.clear();self.tree_nodes={};self.album_items={};self.tree_plan=initial;self.tree_index=0;self.tree_selected=None
        self.tree_done=done;self.show_activity('경로 목록 표시',0,len(initial))
        if len(initial)<200:self.tree_batch()
        else:self.tree_timer.start(5)

    def expand_folder(self,item):
        key=item.data(0,Qt.ItemDataRole.UserRole+1)
        if not key or key in self.tree_loaded or key==self.loading_key or key in self.expand_queue:return
        if self.tree_children.get(key):self.expand_queue.append(key);self.expand_timer.start(0)

    def drain_expansions(self):
        if self.busy:self.expand_timer.start(30);return
        while self.expand_queue:
            key=self.expand_queue.pop(0)
            if key in self.tree_loaded or key not in self.tree_nodes or not self.tree_nodes[key].isExpanded():continue
            self.loading_key=key;self.tree_is_reset=False;self.tree_done=None;self.tree_selected=None
            self.busy=True;self.tree_plan=self.tree_children[key];self.tree_index=self.tree_resume.pop(key,0)
            self.show_activity('하위 폴더 표시',0,len(self.tree_plan));self.tree_timer.start(5);return

    def collapse_folder(self,item):
        key=item.data(0,Qt.ItemDataRole.UserRole+1)
        self.expand_queue=[queued for queued in self.expand_queue if queued!=key]

    def tree_batch(self):
        if self.loading_key and not self.tree_nodes[self.loading_key].isExpanded():
            self.tree_resume[self.loading_key]=self.tree_index;self.loading_key=None;self.tree_plan=[]
            self.busy=False;self.restore_activity()
            if self.pending_search:self.refresh()
            if self.expand_queue:self.expand_timer.start(5)
            return
        started=time.monotonic();count=0;plan=self.tree_plan
        while self.tree_index<len(plan) and count<100 and time.monotonic()-started<.004:
            key,parent,label,data,icon=plan[self.tree_index]
            if key in self.tree_nodes:self.tree_index+=1;continue
            item=QTreeWidgetItem(self.tree_nodes[parent],[label]) if parent else QTreeWidgetItem(self.tree,[label]);self.tree_nodes[key]=item
            item.setData(0,Qt.ItemDataRole.UserRole+1,key)
            if data:
                item.setData(0,Qt.ItemDataRole.UserRole,data)
                if data==self.view:self.tree_selected=item
                if data[0]=='album':self.album_items[data[1]]=item
                if data[0] in ('folder','zip','zipfolder'):
                    item.setToolTip(0,str(data[1]))
                    if self.tree_children.get(key):item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            else:item.setFlags(Qt.ItemFlag.ItemIsEnabled);item.setExpanded(True)
            if icon:item.setIcon(0,self.tree_icons[icon])
            self.tree_index+=1;count+=1
        self.show_activity('경로 목록 표시',self.tree_index,len(plan))
        if self.tree_index<len(plan):self.tree_timer.start(5);return
        if self.tree_is_reset:
            for key in self.tree_restore:
                if key in self.tree_nodes:self.tree_nodes[key].setExpanded(True)
            if self.tree_selected:self.tree.setCurrentItem(self.tree_selected)
            else:self.view=('all',None);self.tree.setCurrentItem(self.tree_nodes['all'])
        if self.loading_key:self.tree_loaded.add(self.loading_key);self.loading_key=None
        self.tree.setUpdatesEnabled(True);self.tree.blockSignals(False);self.tree_plan=[]
        self.busy=False;self.menuBar().setEnabled(True);self.splitter.setEnabled(True);self.reload_button.setEnabled(True);self.restore_activity()
        callback=self.tree_done;self.tree_done=None
        if callback:callback()
        elif self.pending_search:self.refresh()
        if self.expand_queue:self.expand_timer.start(0)

    def update_album_item(self,name):
        item=self.album_items.get(name)
        if item is None:
            item=QTreeWidgetItem(self.tree_nodes['albums'],['']);item.setData(0,Qt.ItemDataRole.UserRole,('album',name));item.setIcon(0,self.tree_icons['album']);self.album_items[name]=item
        item.setText(0,f"{name}   {len(self.store.data['albums'][name])}")

    def navigation_changed(self,item,previous=None):
        if not item:return
        data=item.data(0,Qt.ItemDataRole.UserRole)
        if not data:return
        self.back_to_list();self.view=tuple(data);self.search_control.invalidate();self.listing_revision+=1
        self.navigation_timer.start()
    def selected_ids(self):
        # QListView selects column zero, not every column of this table-shaped model.
        return list(dict.fromkeys(self.model.ids[index.row()] for index in self.selection.selectedIndexes() if index.isValid()))

    def refresh(self):
        self.navigation_timer.stop();self.listing_revision+=1;revision=self.listing_revision
        if self.busy:self.pending_search=True;return
        self.pending_search=False
        old=set(self.selected_ids());data=self.store.snapshot();scope=self.view;needle=self.search.text().strip().casefold()
        sort=self.store.settings['sort'];descending=self.store.settings['descending']
        mode=self.search_mode
        work=lambda:listing_ids(data,scope,needle,sort,descending,self.progress_events.put,mode)
        def finished(ids):
            if revision==self.listing_revision:self.apply_listing(ids,old)
            else:self.pending_search=True
        if len(data['files'])>500:self.begin_operation('파일 목록 준비 중…',work,finished,interactive=True)
        else:finished(work())

    def apply_listing(self,ids,old):
        self.tasks.new_generation();self.selection.blockSignals(True);self.model.reset(ids)
        for row,ident in enumerate(ids) if old else ():
            if ident in old:self.selection.select(self.model.index(row,0),QItemSelectionModel.SelectionFlag.Select|QItemSelectionModel.SelectionFlag.Rows)
        self.selection.blockSignals(False);category,value=self.view
        self.heading.setText(value if category=='album' else '모든 파일' if category=='all' else Path(value[1]).name if category=='zipfolder' else Path(value).name)
        self.location.setText('라이브러리 / 모든 파일' if category=='all' else '앨범 / '+str(value) if category=='album' else ('ZIP / '+str(value[0])+'!/'+str(value[1])) if category=='zipfolder' else ('ZIP / '+str(value)) if category=='zip' else str(value));self.location.setToolTip(self.location.text())
        self.empty.setText('검색 결과가 없습니다.' if self.search.text().strip() else '이 앨범에는 파일이 없습니다. 왼쪽 앨범에 파일을 드래그해 추가하세요.' if category=='album' else '폴더를 불러와 사진과 영상을 정리해 보세요.\n\n파일 → 폴더 불러오기')
        self.count.setText(f'{len(ids)}개 항목');self.change_mode(self.store.settings['details'],save=False);self.selection_changed()

    def item_sort_key(self,ident):
        item=self.store.data['files'][ident];path=Path(item['path']);name=natural(path.name);sort=self.store.settings['sort']
        return (item.get('modified',0),name) if sort=='date' else (path.suffix.lower(),name) if sort=='type' else name

    def change_mode(self,details,save=True):
        self.store.settings['details']=details
        if hasattr(self,'browser'):
            self.browser.setCurrentWidget(self.empty if not self.model.ids else self.table if details else self.grid)
        if save:self.store.save_settings()
    def set_sort(self,value):
        self.store.settings['sort']=value;self.sort_actions[value].setChecked(True);self.store.save_settings();self.refresh()
    def set_descending(self,checked):self.store.settings['descending']=checked;self.store.save_settings();self.refresh()
    def heading_sort(self,column):
        value={0:'name',1:'date',2:'type'}.get(column)
        if not value:return
        if self.store.settings['sort']==value:
            self.store.settings['descending']=not self.store.settings['descending'];self.descending_action.setChecked(self.store.settings['descending'])
        self.set_sort(value)
    def toggle_folders(self,checked):
        if self.busy:return
        self.store.settings['show_folders']=checked
        if not checked and self.view[0]=='folder':self.view=('all',None)
        self.store.save_settings();self.rebuild_tree(done=self.refresh)

    def scrolled(self):self.tasks.new_generation();self.asset_ready('');self.scroll_timer.start()
    def selection_changed(self,*_):
        ids=self.selected_ids();self.preview_id=ids[0] if ids else None;self.preview_key=None;self.resolution.hide()
        editable=bool(ids) and not any(self.store.data['files'][i].get('archive') for i in ids)
        self.rename_button.setEnabled(editable and len(ids)==1);self.rename_action.setEnabled(editable and len(ids)==1);self.move_action.setEnabled(editable)
        self.open_button.setEnabled(bool(ids));self.add_button.setEnabled(bool(ids))
        if not ids:self.preview.clear();self.preview.setText('파일을 선택하세요');self.details.clear()
        else:
            item=self.store.data['files'][ids[0]];albums=[name for name,members in self.store.data['albums'].items() if ids[0] in members]
            self.details.setText(Path(item['path']).name+f"\n\n{Path(item['path']).suffix.upper()} · {item.get('size',0)/1048576:.1f} MB\n\n앨범\n"+(', '.join(albums) or '아직 분류하지 않음')+'\n\n태그\n'+(', '.join(item['tags']) or '없음')+'\n\n실제 파일 위치\n'+'\n'.join(textwrap.wrap((item['archive']+'\n내부 경로: '+item['member']) if item.get('archive') else str(Path(item['path']).parent),width=32,break_long_words=True,break_on_hyphens=False))+(f'\n\n{len(ids)}개 선택' if len(ids)>1 else ''))
            self.asset_ready('')
        if not self.busy:self.statusBar().showMessage(f'{len(self.model.ids)}개 항목 · {len(ids)}개 선택  |  앨범 분류는 원본 위치 유지')
    def asset_ready(self,key):
        if not self.preview_id or self.preview_id not in self.store.data['files']:return
        item=self.store.data['files'][self.preview_id]
        if item.get('missing'):
            self.preview.clear();self.preview.setText('파일을 찾을 수 없습니다.\n새로고침으로 경로를 확인하세요.');return
        wanted=self.tasks.key(item,400)
        if key and key!=wanted:return
        pixmap=self.tasks.request(item,400,priority=1)
        dimensions=self.tasks.dimensions.get(wanted)
        self.resolution.setText(f'해상도  {dimensions}' if dimensions else '해상도 확인 불가' if wanted in self.tasks.errors or pixmap is not None else '해상도 확인 중…')
        self.resolution.show()
        if pixmap is not None:
            self.preview.setPixmap(pixmap.scaled(max(170,self.preview.width()-6),170,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation));self.preview_key=wanted
        else:self.preview.clear();self.preview.setText('미리보기 지원 없음\n내부 뷰어로 열어 보세요.' if wanted in self.tasks.errors else '미리보기 준비 중…')
    def open_viewer(self,ident=None):
        if self.busy:return
        if ident is None:
            ids=self.selected_ids();ident=ids[0] if ids else None
        if not ident or ident not in self.model.ids:return
        self.viewer_id=ident;self.pages.setCurrentWidget(self.viewer);self.tasks.new_generation();self.viewer.open(self.store.data['files'][ident],self.model.ids.index(ident),len(self.model.ids));self.asset_ready('');self.viewer.setFocus(Qt.FocusReason.OtherFocusReason)
    def back_to_list(self):
        if not hasattr(self,'viewer'):return
        if self.isFullScreen():self.toggle_fullscreen()
        self.viewer.stop();self.pages.setCurrentWidget(self.library_page);self.viewer_id=None;self.tree.show();self.info.setVisible(self.info_action.isChecked());self.viewer.fill_button.setChecked(False);self.viewer.fill_button.setText('화면 채우기');self.grid.viewport().update()
    def step_viewer(self,delta):
        if self.viewer_id not in self.model.ids:return
        index=self.model.ids.index(self.viewer_id)+delta
        if 0<=index<len(self.model.ids):
            ident=self.model.ids[index];self.selection.setCurrentIndex(self.model.index(index,0),QItemSelectionModel.SelectionFlag.ClearAndSelect|QItemSelectionModel.SelectionFlag.Rows);self.open_viewer(ident)
    def fill_viewer(self):
        fill=self.viewer.fill_button.isChecked();self.tree.setVisible(not fill);self.info.setVisible(not fill and self.info_action.isChecked());self.viewer.fill_button.setText('패널 다시 표시' if fill else '화면 채우기')
    def escape_viewer(self):
        if self.isFullScreen():
            self.toggle_fullscreen()
        else:
            self.back_to_list()

    def toggle_fullscreen(self):
        if self.pages.currentWidget() is not self.viewer:
            return
        if self.isFullScreen():
            if self.was_maximized:
                self.showMaximized()
            else:
                self.showNormal()
            self.menuBar().show()
            self.search_bar.show()
            self.statusBar().show()
            self.viewer.fill_button.show()
            self.viewer.fullscreen_button.setText('전체 화면 (F11)')
            self.fill_viewer()
        else:
            self.was_maximized=self.isMaximized()
            self.search_control.invalidate()
            for widget in (self.menuBar(),self.search_bar,self.statusBar(),self.tree,self.info,self.viewer.fill_button):
                widget.hide()
            self.viewer.fullscreen_button.setText('전체 화면 종료 (Esc)')
            self.showFullScreen()
        self.viewer.setFocus()

    def playback_changed(self,playing):self.tasks.playing=playing
    def require_selection(self):
        ids=self.selected_ids()
        if not ids:QMessageBox.information(self,'파일 선택','먼저 파일을 선택하세요. Ctrl/Shift로 여러 파일을 선택할 수 있습니다.')
        return ids
    def new_album(self):
        name,ok=QInputDialog.getText(self,'새 앨범','앨범 이름:')
        if ok and name.strip():self.store.album(name);self.update_album_item(name.strip())

    def add_to_album(self):
        ids=self.require_selection()
        if not ids:return
        name,ok=QInputDialog.getItem(self,'앨범에 추가','기존 앨범 선택 또는 새 이름 입력:',sorted(self.store.data['albums'],key=natural),0,True)
        if ok and name.strip():self.album_drop(name.strip(),ids)
    def album_drop(self,name,ids):
        if self.busy:return
        added=self.store.album(name,ids);self.search_control.invalidate();self.update_album_item(name)
        if self.view==('album',name):
            needle=self.search.text().strip().casefold()
            visible=[ident for ident in added if matches(self.store.data['files'][ident],needle,self.search_mode)]
            self.model.insert_sorted(visible,self.item_sort_key,self.store.settings['descending']);self.count.setText(f'{len(self.model.ids)}개 항목');self.change_mode(self.store.settings['details'],save=False)
        self.selection_changed();self.statusBar().showMessage(f'{len(added)}개 파일을 «{name}» 앨범에 추가했습니다 · 원본 위치 유지',7000)

    def remove_from_album(self):
        if self.view[0]!='album':QMessageBox.information(self,'앨범 선택','왼쪽에서 앨범을 선택하세요.');return
        ids=self.require_selection()
        if ids:self.store.remove_members(self.view[1],ids);self.update_album_item(self.view[1]);self.refresh()

    def edit_tags(self):
        ids=self.require_selection()
        if not ids:return
        initial=', '.join(self.store.data['files'][ids[0]]['tags']) if len(ids)==1 else ''
        value,ok=QInputDialog.getText(self,'태그 편집','쉼표로 구분합니다. 선택 파일의 기존 태그를 모두 교체합니다.\n빈칸으로 저장하면 태그를 지웁니다.',text=initial)
        if ok:self.store.tags(ids,[t.strip() for t in value.split(',') if t.strip()]);self.search_control.invalidate();self.refresh()
    def begin_operation(self,label,function,finished,interactive=False):
        if self.busy:return
        # A forced enqueue is a barrier: metadata snapshots always precede physical moves/imports.
        self.saver.flush(force=True)
        while not self.progress_events.empty():
            try:self.progress_events.get_nowait()
            except queue.Empty:break
        self.busy=True;self.menuBar().setEnabled(False)
        if not interactive:self.splitter.setEnabled(False)
        self.reload_button.setEnabled(False);self.show_activity(label)
        self.future=self.executor.submit(function);self.finished=finished

    def show_activity(self,label,current=None,total=None):
        self.activity.setText(label+(f' · {current:,}/{total:,}' if total is not None and current is not None else ''));self.activity.show();self.progress.show()
        if total is None:self.progress.setRange(0,0)
        else:self.progress.setRange(0,max(1,total));self.progress.setValue(current or 0)

    def restore_activity(self):
        if self.save_label:self.show_activity(self.save_label)
        else:self.activity.hide();self.progress.hide()

    def save_changed(self,label):
        self.save_label=label
        if not self.busy:self.restore_activity()

    def save_failed(self,message):
        self.closing=False
        QMessageBox.warning(self,'분류 정보 저장 실패','화면의 변경 사항은 남아 있지만 디스크에 저장하지 못했습니다.\n'+message+'\n\n종료할 때 다시 저장을 시도합니다.')

    def save_idle(self):
        if self.closing and not self.busy:QTimer.singleShot(0,self.close)

    def poll_operations(self):
        latest=None
        for _ in range(100):
            try:latest=self.progress_events.get_nowait()
            except queue.Empty:break
        if latest and self.busy:self.show_activity(*latest)
        if not self.future or not self.future.done():return
        future=self.future;self.future=None;self.busy=False;self.menuBar().setEnabled(True);self.splitter.setEnabled(True);self.reload_button.setEnabled(True);self.restore_activity()
        try:self.finished(future.result())
        except Exception as error:QMessageBox.critical(self,'작업 실패',str(error));self.refresh()
        if self.pending_search and not self.busy:self.refresh()

    def import_folder(self):
        if self.busy:return
        initial=self.store.settings.get('import_extensions') or None
        dialog=ExtensionDialog(initial,self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        folder=QFileDialog.getExistingDirectory(self,'선택한 확장자를 불러올 폴더')
        if folder:
            extensions=dialog.extensions();self.store.settings['import_extensions']=extensions;self.store.save_settings();self.import_path(folder,extensions)

    def import_path(self,folder,extensions=None):
        if self.busy:return
        allowed=set(EXTENSIONS if extensions is None else extensions)&EXTENSIONS
        if not allowed:raise ValueError('불러올 확장자를 하나 이상 선택하세요.')
        self.search_control.invalidate();snapshot=self.store.snapshot()
        def finished(result):
            data,count,errors=result;self.store.data=data;self.search_control.invalidate()
            if errors:QMessageBox.warning(self,'일부 항목을 불러오지 못했습니다','\n'.join(errors[:8]))
            self.rebuild_tree(done=self.refresh);self.statusBar().showMessage(f'{count}개 검색 완료 · 접근 오류 {len(errors)}개',8000)
        self.begin_operation('폴더 검색 중…',lambda:import_library(snapshot,folder,self.store.directory,self.progress_events.put,allowed),finished)

    def reload_files(self):
        if self.busy:return
        targets=[self.view[1][0]] if self.view[0]=='zipfolder' else [self.view[1]] if self.view[0] in ('folder','zip') else list(self.store.data['roots'])
        if not targets:QMessageBox.information(self,'새로고침','먼저 폴더를 불러오세요.');return
        self.back_to_list();self.search_control.invalidate();snapshot=self.store.snapshot()
        def finished(result):
            data,stats=result;self.store.data=data;self.search_control.invalidate();self.last_reload_stats=stats
            if any(stats[key] for key in ('added','modified','missing','restored')):self.rebuild_tree(done=self.refresh)
            else:self.refresh()
            self.statusBar().showMessage(f"새로고침 완료 · 추가 {stats['added']} · 변경 {stats['modified']} · 없음 {stats['missing']} · 복원 {stats['restored']} · 접근 오류 {len(stats['errors'])}",12000)
        self.begin_operation('등록 폴더의 변경 확인 중…',lambda:refresh_library(snapshot,targets,self.store.directory,self.progress_events.put),finished)

    def move_selected(self):
        ids=self.require_selection()
        if not ids:return
        if any(self.store.data['files'][i].get('archive') for i in ids):
            QMessageBox.information(self,'ZIP 사진','ZIP 내부 사진은 읽기 전용입니다. 일반 파일만 선택해 주세요.');return
        folder=QFileDialog.getExistingDirectory(self,'원본 파일을 이동할 폴더')
        if not folder:return
        if QMessageBox.question(self,'실제 파일 이동',f'{len(ids)}개 원본 파일을 다음 폴더로 이동할까요?\n\n{folder}\n\n같은 이름의 파일은 덮어쓰지 않습니다.\n앨범과 태그는 유지됩니다.')!=QMessageBox.StandardButton.Yes:return
        self.back_to_list()
        def work():
            errors=[];count=0
            for ident in ids:
                try:self.store.move(ident,Path(folder)/Path(self.store.data['files'][ident]['path']).name);count+=1
                except Exception as error:errors.append(str(error))
                self.progress_events.put(('파일 이동',count+len(errors),len(ids)))

            return count,errors
        def finished(result):
            count,errors=result;self.rebuild_tree(done=self.refresh);self.statusBar().showMessage(f'{count}개 이동 완료 · 실패 {len(errors)}개',8000)
            if errors:QMessageBox.warning(self,'이동하지 못한 파일','\n'.join(errors[:10]))
        self.begin_operation('파일을 이동하고 있습니다. 완료를 기다려 주세요…',work,finished)
    def undo_move(self):
        self.back_to_list()
        def finished(_):self.rebuild_tree(done=self.refresh);self.statusBar().showMessage('최근 파일 1개의 이동·이름 변경을 취소했습니다.',7000)
        self.begin_operation('최근 이동을 취소하고 있습니다…',self.store.undo,finished)
    def closeEvent(self,event):
        if self.busy:QMessageBox.information(self,'작업 중','파일 작업이 완료된 후 종료해 주세요.');event.ignore();return
        if self.saver.pending:
            self.closing=True;self.saver.flush(force=True);self.show_activity('분류 정보를 저장한 뒤 종료합니다…');event.ignore();return
        self.closing=False;self.tree_timer.stop();self.expand_timer.stop();self.navigation_timer.stop();QApplication.instance().removeEventFilter(self)
        geometry=self.normalGeometry() if self.isFullScreen() or self.isMaximized() else self.geometry();self.store.settings['width']=geometry.width();self.store.settings['height']=geometry.height();self.store.save_settings();self.poll_timer.stop();self.search_control.close();self.saver.close();self.viewer.close_service();self.tasks.close();self.executor.shutdown(wait=False,cancel_futures=True);event.accept()

    def eventFilter(self,watched,event):
        if event.type()==QEvent.Type.KeyPress and self.pages.currentWidget() is self.viewer and not self.busy and QApplication.activeModalWidget() is None and QApplication.activePopupWidget() is None:
            focus=QApplication.focusWidget()
            editing=isinstance(focus,(QLineEdit,QTextEdit,QPlainTextEdit,QAbstractSpinBox,QSlider))
            if not editing and event.modifiers() in (Qt.KeyboardModifier.NoModifier,Qt.KeyboardModifier.KeypadModifier):
                if event.key()==Qt.Key.Key_Left:self.step_viewer(-1);return True
                if event.key()==Qt.Key.Key_Right:self.step_viewer(1);return True
        return super().eventFilter(watched,event)

    def search_edited(self):
        self.search_mode='all';self.search_kind.clear()

    def apply_search(self,kind,query):
        self.search_control.invalidate();self.search.blockSignals(True);self.search.setText(query);self.search.blockSignals(False)
        self.search_mode=kind;self.search_kind.setText({'tag':'[태그]','name':'[이름]'}.get(kind,''));self.back_to_list();self.refresh()

    def selected_album(self):
        if self.view[0]!='album':QMessageBox.information(self,'앨범 선택','왼쪽에서 변경할 앨범을 선택하세요.');return None
        return self.view[1]

    def rename_album(self,name=None):
        if self.busy:return
        name=name if isinstance(name,str) else self.selected_album()
        if not name:return
        new_name,ok=QInputDialog.getText(self,'앨범 이름 변경','새 앨범 이름:',text=name)
        if ok:
            try:self.rename_album_to(name,new_name)
            except ValueError as error:QMessageBox.warning(self,'이름 변경',str(error))

    def rename_album_to(self,name,new_name):
        if not self.store.rename_album(name,new_name):return
        new_name=new_name.strip();item=self.album_items.pop(name)
        self.album_items[new_name]=item;item.setData(0,Qt.ItemDataRole.UserRole,('album',new_name));self.update_album_item(new_name)
        self.tree_nodes.pop('album:'+name,None);self.tree_nodes['album:'+new_name]=item
        if self.view==('album',name):self.view=('album',new_name);self.heading.setText(new_name);self.location.setText('앨범 / '+new_name)
        self.search_control.invalidate();self.selection_changed();self.statusBar().showMessage('앨범 이름을 변경했습니다.',5000)

    def delete_album(self,name=None):
        if self.busy:return
        name=name if isinstance(name,str) else self.selected_album()
        if not name:return
        answer=QMessageBox.question(self,'앨범 삭제',f'«{name}» 앨범을 삭제할까요?\n\n앨범 분류만 삭제합니다. 원본 사진·영상과 태그는 유지됩니다.')
        if answer==QMessageBox.StandardButton.Yes:self.delete_album_named(name)

    def delete_album_named(self,name):
        self.store.delete_album(name);item=self.album_items.pop(name);self.tree.blockSignals(True)
        item.parent().takeChild(item.parent().indexOfChild(item));self.tree_nodes.pop('album:'+name,None)
        changed=self.view==('album',name)
        if changed:self.view=('all',None);self.tree.setCurrentItem(self.tree_nodes['all'])
        self.tree.blockSignals(False);self.search_control.invalidate()
        if changed:self.back_to_list();self.refresh()
        else:self.selection_changed()
        self.statusBar().showMessage('앨범을 삭제했습니다. 원본 파일은 유지됩니다.',6000)

    def tree_context_menu(self,position):
        if self.busy:return
        item=self.tree.itemAt(position);data=item.data(0,Qt.ItemDataRole.UserRole) if item else None
        if not data or data[0]!='album':return
        menu=QMenu(self.tree);menu.addAction('앨범 이름 변경…',lambda:self.rename_album(data[1]));menu.addAction('앨범 삭제…',lambda:self.delete_album(data[1]));menu.exec(self.tree.viewport().mapToGlobal(position))

    def single_file(self):
        if self.busy:return None
        ids=[self.viewer_id] if self.pages.currentWidget() is self.viewer and self.viewer_id else self.selected_ids()
        if len(ids)!=1:
            QMessageBox.information(self,'파일 선택','파일 하나를 선택해 주세요.');return None
        return ids[0]

    def reveal_selected(self):
        ident=self.single_file()
        if not ident:return
        from moa.platform.explorer import reveal_file
        try:reveal_file(physical_path(self.store.data['files'][ident]))
        except (OSError,ValueError) as error:QMessageBox.warning(self,'탐색기 열기',str(error))

    def rename_selected_file(self):
        ident=self.single_file()
        if not ident:return
        if self.store.data['files'][ident].get('archive'):
            QMessageBox.information(self,'ZIP 사진','ZIP 내부 사진은 읽기 전용입니다.');return
        old=Path(self.store.data['files'][ident]['path'])
        name,ok=QInputDialog.getText(self,'실제 파일 이름 변경',f'새 이름 (확장자 {old.suffix}는 유지됩니다):',text=old.stem)
        if ok and name:self.rename_file_to(ident,name+old.suffix)

    def rename_file_to(self,ident,name):
        if self.busy:return
        writable(self.store.data['files'][ident])
        self.back_to_list()
        self.viewer.player.close_process()
        def finished(_):
            self.search_control.invalidate();self.refresh();self.statusBar().showMessage('실제 파일 이름을 변경했습니다. 앨범과 태그는 유지됩니다.',6000)
        self.begin_operation('파일 이름 변경 중…',lambda:self.store.rename_file(ident,name),finished)

    def import_zip(self):
        if self.busy:return
        path,_=QFileDialog.getOpenFileName(self,'사진을 볼 ZIP 선택','','ZIP 파일 (*.zip)')
        if path:self.import_path(path,IMAGES)
