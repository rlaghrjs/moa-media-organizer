import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from PySide6.QtCore import Qt,QMimeData,QPointF
from PySide6.QtGui import QDragEnterEvent,QDragMoveEvent,QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from moa.storage.json_store import Store
from moa.ui.main_window import MainWindow
from moa.ui.media_model import HIERARCHY_MIME


class ReleaseUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    def wait(self,predicate,seconds=20):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            self.app.processEvents()
            if predicate():return
            time.sleep(.01)
        self.fail('UI state timeout')

    def make_window(self,root):
        photo=root/'photo.jpg';Image.new('RGB',(160,100),'#4488aa').save(photo)
        store=Store(root/'data');store.import_files([{'path':str(photo),'size':photo.stat().st_size,'modified':1}])
        ident=next(iter(store.data['files']));store.album('사진',[ident]);store.album('빈 앨범')
        w=MainWindow(store,Path(__file__).resolve().parents[1]);w.show();w.activateWindow();self.wait(lambda:not w.busy)
        return w,store,ident

    def close_window(self,w):
        self.wait(lambda:not w.busy);w.close();self.wait(lambda:not w.isVisible())

    def drop(self,w,kind,ident,target):
        mime=QMimeData();mime.setData(HIERARCHY_MIME,json.dumps({'kind':kind,'id':ident}).encode())
        w.tree.scrollToItem(target);self.app.processEvents();point=w.tree.visualItemRect(target).center()
        enter=QDragEnterEvent(point,Qt.DropAction.MoveAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(w.tree.viewport(),enter)
        move=QDragMoveEvent(point,Qt.DropAction.MoveAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(w.tree.viewport(),move)
        drop=QDropEvent(QPointF(point),Qt.DropAction.MoveAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(w.tree.viewport(),drop)
        return drop.isAccepted()

    def test_album_icons_context_creation_and_drag(self):
        with tempfile.TemporaryDirectory() as directory:
            w,store,ident=self.make_window(Path(directory))
            try:
                first=w.create_album_folder('여행');second=w.create_album_folder('가족')
                self.assertNotEqual(w.album_items['사진'].icon(0).cacheKey(),w.tree_nodes['albumfolder:'+first].icon(0).cacheKey())
                self.assertTrue(self.drop(w,'album','사진',w.tree_nodes['albumfolder:'+first]))
                self.assertEqual(store.data['album_locations']['사진'],first)
                self.assertTrue(self.drop(w,'albumfolder',first,w.tree_nodes['albumfolder:'+second]))
                self.assertEqual(store.data['album_folders'][first]['parent'],second)
                self.assertFalse(self.drop(w,'albumfolder',second,w.tree_nodes['albumfolder:'+first]))
                self.assertIsNone(store.data['album_folders'][second]['parent'])
                self.assertFalse(self.drop(w,'albumfolder',first,w.tree_nodes['albumfolder:'+first]))
                self.assertTrue(self.drop(w,'album','사진',w.tree_nodes['albums']))
                self.assertNotIn('사진',store.data['album_locations'])
                w.tree.setCurrentItem(w.album_items['사진']);self.wait(lambda:not w.busy)
                with patch('moa.ui.media_model.QDrag') as drag:
                    w.tree.startDrag(Qt.DropAction.MoveAction)
                    payload=drag.return_value.setMimeData.call_args.args[0]
                    self.assertEqual(json.loads(bytes(payload.data(HIERARCHY_MIME))),{'kind':'album','id':'사진'})
                def create_from_menu(item, name):
                    w.tree.scrollToItem(item)
                    self.app.processEvents()
                    actions=[]
                    with patch('moa.ui.main_window.QMenu') as menus,patch('moa.ui.main_window.QInputDialog') as prompt:
                        prompt.getText.return_value=(name,True)
                        menus.return_value.addAction.side_effect=lambda text,callback:actions.append((text,callback))
                        menus.return_value.exec.side_effect=lambda point:next(callback for text,callback in actions if text=='새 앨범…')()
                        w.tree_context_menu(w.tree.visualItemRect(item).center())
                        self.assertTrue(menus.return_value.exec.called)
                create_from_menu(w.tree_nodes['albumfolder:'+second],'새 앨범')
                self.assertEqual(store.data['album_locations']['새 앨범'],second)
                self.wait(lambda:not w.busy)
                create_from_menu(w.tree_nodes['albums'],'최상위 앨범')
                self.assertIn('최상위 앨범',store.data['albums'])
                self.assertNotIn('최상위 앨범',store.data['album_locations'])
                self.assertEqual(store.data['albums']['사진'],[ident])
            finally:self.close_window(w)

    def test_fullscreen_overlay_activity_and_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            w,store,ident=self.make_window(Path(directory))
            try:
                w.open_viewer(ident);self.wait(lambda:w.viewer.photo_key is not None)
                self.assertEqual(w.viewer.photo.transform().m11(),1)
                QTest.keyClick(w.viewer,Qt.Key.Key_F11)
                self.wait(lambda:w.isFullScreen() and not w.viewer.top_bar.isVisible())
                self.assertFalse(w.viewer.bottom_bar.isVisible())
                self.assertFalse(w.location.isVisible())
                self.wait(lambda:w.viewer.stack.geometry()==w.viewer.rect())
                self.assertGreater(w.viewer.photo.transform().m11(),1)
                area=w.viewer.stack.geometry()
                QTest.mouseMove(w.viewer,w.viewer.rect().center())
                self.wait(lambda:w.viewer.top_bar.isVisible())
                self.assertEqual(w.viewer.stack.geometry(),area)
                # Isolate the idle interval from physical mouse input on the test machine.
                with patch.object(w.viewer,'pointer_activity',return_value=None):
                    self.wait(lambda:not w.viewer.top_bar.isVisible(),5)
                self.assertEqual(w.viewer.stack.geometry(),area)
                QTest.keyClick(w.viewer,Qt.Key.Key_Up)
                self.assertTrue(w.viewer.top_bar.isVisible())
                w.viewer.volume.setValue(42)
                self.assertEqual(w.viewer.volume_value.text(),'42')
                QTest.keyClick(w.viewer,Qt.Key.Key_Escape)
                self.wait(lambda:not w.isFullScreen())
                self.assertTrue(w.viewer.top_bar.isVisible())
                self.assertTrue(w.viewer.bottom_bar.isVisible())
                self.assertFalse(w.viewer.cursor_timer.isActive())
                self.assertFalse(w.viewer.photo.allow_upscale)
                self.assertEqual(w.viewer_id,ident)
            finally:self.close_window(w)

    @unittest.skipUnless(os.environ.get('MOA_TEST_VIDEO') and os.environ.get('MOA_TEST_MPV_DLL'),'Optional real libmpv fixture')
    def test_space_volume_eof_and_fullscreen_video(self):
        with tempfile.TemporaryDirectory() as directory:
            w,store,_=self.make_window(Path(directory))
            video=Path(os.environ['MOA_TEST_VIDEO']).resolve();stat=video.stat()
            store.import_files([{'path':str(video),'size':stat.st_size,'modified':stat.st_mtime_ns}]);w.refresh();self.wait(lambda:not w.busy)
            ident=next(ident for ident,item in store.data['files'].items() if item['path']==str(video))
            w.viewer.player.dll=Path(os.environ['MOA_TEST_MPV_DLL']).resolve()
            states=[];ended=[];w.viewer.player.state.connect(states.append);w.viewer.player.ended.connect(lambda:ended.append(True))
            try:
                w.open_viewer(ident);self.wait(lambda:bool(states) and states[-1]['duration']>0)
                self.assertTrue(states[-1]['paused'])
                QTest.keyClick(w.viewer,Qt.Key.Key_Space)
                self.wait(lambda:not states[-1]['paused'] and states[-1]['position']>.1)
                QTest.keyClick(w.viewer.play,Qt.Key.Key_Space)
                self.wait(lambda:states[-1]['paused'])
                w.viewer.volume.setValue(37);self.wait(lambda:int(states[-1]['volume'])==37)
                self.assertEqual(w.viewer.volume_value.text(),'37')
                w.toggle_fullscreen();self.wait(lambda:w.isFullScreen())
                self.wait(lambda:abs(states[-1]['output_width']-w.viewer.video_host.width()*w.devicePixelRatioF())<5)
                w.viewer.activity();self.assertTrue(w.viewer.bottom_bar.isVisible())
                w.viewer.player.send('seek',value=max(.1,states[-1]['duration']-.4))
                w.viewer.setFocus();QTest.keyClick(w.viewer,Qt.Key.Key_Space)
                self.wait(lambda:bool(ended) and states[-1]['paused'] and states[-1]['position']<.15,10)
                self.assertEqual(w.viewer_id,ident)
                self.assertEqual(w.viewer.play.text(),'재생')
                first_count=len(ended)
                QTest.keyClick(w.viewer,Qt.Key.Key_Space)
                self.wait(lambda:not states[-1]['paused'] and states[-1]['position']>.15)
                self.assertEqual(len(ended),first_count)
                QTest.keyClick(w.viewer,Qt.Key.Key_Escape);self.wait(lambda:not w.isFullScreen())
                self.assertEqual(w.viewer_id,ident)
            finally:self.close_window(w)


if __name__=='__main__':unittest.main()
