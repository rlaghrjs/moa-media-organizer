import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication
from moa.storage.json_store import Store, empty_library, validate
from moa.application.library_jobs import listing_ids, search_suggestions, tree_plan, import_library, refresh_library
from moa.ui.main_window import MainWindow
from moa.ui.photo_canvas import PhotoCanvas


class FolderStoreTests(unittest.TestCase):
    def test_legacy_snapshot_rename_delete_and_depth(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / 'photo.jpg'
            file.write_bytes(b'original')
            data = empty_library()
            data['files']['id'] = {'path':str(file), 'tags':['tag'], 'size':8, 'modified':1}
            data['albums']['old'] = ['id']
            (root/'library.json').write_text(json.dumps(data), encoding='utf-8')
            store = Store(root)
            self.assertEqual(store.data['albums']['old'], ['id'])
            parent = store.album_folder('여행')
            child = store.album_folder('제주', parent)
            with self.assertRaises(ValueError):store.album_folder('3단계', child)
            with self.assertRaises(ValueError):store.album_folder('여행')
            with self.assertRaises(ValueError):store.album_folder('자기자신', parent, parent)
            store.move_album('old', child)
            snapshot = store.snapshot()
            store.rename_album('old', 'new')
            self.assertEqual(store.data['album_locations'], {'new':child})
            self.assertEqual(snapshot['album_locations'], {'old':child})
            store.album_folder('제주도', parent, child)
            self.assertEqual(snapshot['album_folders'][child]['name'], '제주')
            self.assertEqual(Store(root).data['album_locations'], {'new':child})
            store.delete_album_folder(parent)
            self.assertFalse(store.data['album_folders'])
            self.assertFalse(store.data['album_locations'])
            self.assertEqual(store.data['albums']['new'], ['id'])
            self.assertEqual(file.read_bytes(), b'original')
            self.assertEqual(store.data['files']['id']['tags'], ['tag'])

    def test_invalid_folder_metadata(self):
        for folders in ({'child':{'name':'child','parent':'bad'}, 'bad':[]}, {'a':{'name':'a','parent':[]}}):
            data=empty_library()
            data['album_folders']=folders
            with self.assertRaises(ValueError):validate(data)
        data=empty_library()
        data['albums']['a']=[]
        data['album_locations']={'a':[]}
        with self.assertRaises(ValueError):validate(data)

    def test_folder_query_deduplicates_and_survives_scan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root/'media'
            media.mkdir()
            Image.new('RGB', (30,20), 'red').save(media/'a.jpg')
            store = Store(root/'data')
            store.data, _, _ = import_library(store.snapshot(), str(media), store.directory)
            ident = next(iter(store.data['files']))
            store.tags([ident], ['바다'])
            parent = store.album_folder('여행')
            child = store.album_folder('제주', parent)
            store.album('a', [ident]);store.album('b', [ident])
            store.move_album('a', parent);store.move_album('b', child)
            self.assertEqual(listing_ids(store.data, ('albumfolder',parent), '', 'name',False), [ident])
            self.assertTrue(any(row['kind']=='tag' for row in search_suggestions(store.data, ('albumfolder',child), '바다')))
            entries = {entry[0]:entry for entry in tree_plan(store.data,False)}
            self.assertEqual(entries['album:b'][1], 'albumfolder:'+child)
            refreshed, stats = refresh_library(store.snapshot(), [str(media)], store.directory)
            self.assertFalse(stats['errors'])
            self.assertEqual(refreshed['album_locations'], store.data['album_locations'])
            store.delete_album('a')
            self.assertNotIn('a', store.data['album_locations'])
            validate(store.snapshot())


class FolderUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    def wait(self, predicate):
        end=time.monotonic()+25
        while time.monotonic()<end:
            self.app.processEvents()
            if predicate():return
            time.sleep(.01)
        self.fail('UI state timeout')

    def test_default_image_scale(self):
        canvas=PhotoCanvas();canvas.resize(800,600);canvas.show();self.app.processEvents()
        try:
            small=QPixmap(160,100);canvas.set_photo(small)
            self.app.processEvents()
            self.assertEqual(canvas.transform().m11(), 1)
            canvas.resize(1200,800);self.app.processEvents()
            self.assertEqual(canvas.transform().m11(), 1)
            big=QPixmap(2400,1600);canvas.set_photo(big);self.app.processEvents()
            scale=canvas.transform().m11()
            self.assertGreater(scale,0);self.assertLess(scale,1)
            self.assertLessEqual(2400*scale,canvas.viewport().width())
            self.assertLessEqual(1600*scale,canvas.viewport().height())
            canvas.set_photo(small);canvas.zoom(2)
            self.assertEqual(canvas.transform().m11(),2)
            canvas.fit();self.assertEqual(canvas.transform().m11(),1)
            canvas.rotate();self.assertEqual(canvas.transform().m11(),1)
        finally:canvas.close()

    def test_folder_tree_move_rename_delete_and_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);photo=root/'small.jpg';Image.new('RGB',(160,100),'red').save(photo)
            store=Store(root/'data');store.import_files([{'path':str(photo),'size':photo.stat().st_size,'modified':1}])
            ident=next(iter(store.data['files']));store.album('old',[ident])
            w=MainWindow(store,Path(__file__).resolve().parents[1]);w.show();self.wait(lambda:not w.busy)
            try:
                parent=w.create_album_folder('여행')
                child=w.create_album_folder('제주',parent)
                other=w.create_album_folder('기타')
                w.move_album_to('old',child)
                self.assertIs(w.album_items['old'].parent(),w.tree_nodes['albumfolder:'+child])
                w.tree.setCurrentItem(w.tree_nodes['albumfolder:'+parent])
                self.wait(lambda:not w.busy and w.model.ids==[ident])
                self.assertEqual(w.heading.text(),'여행')
                with patch('moa.ui.main_window.QInputDialog.getText',return_value=('제주도',True)):
                    w.rename_album_folder(child)
                self.wait(lambda:not w.busy)
                w.rename_album_to('old','renamed')
                self.assertEqual(store.data['album_locations']['renamed'],child)
                w.move_album_folder_to(child,other)
                self.wait(lambda:not w.busy and not w.model.ids)
                self.assertIs(w.tree_nodes['albumfolder:'+child].parent(),w.tree_nodes['albumfolder:'+other])
                w.tree.setCurrentItem(w.tree_nodes['albumfolder:'+other])
                self.wait(lambda:not w.busy and w.model.ids==[ident])
                w.rebuild_tree(done=w.refresh)
                self.wait(lambda:not w.busy)
                self.assertEqual(w.view,('albumfolder',other))
                self.assertIs(w.album_items['renamed'].parent(),w.tree_nodes['albumfolder:'+child])
                w.open_viewer(ident);self.wait(lambda:w.viewer.photo_key is not None)
                self.assertEqual(w.viewer.photo.transform().m11(),1)
                w.back_to_list()
                w.delete_album_folder_named(other)
                self.wait(lambda:not w.busy)
                self.assertNotIn(child,store.data['album_folders'])
                self.assertIs(w.album_items['renamed'].parent(),w.tree_nodes['albums'])
                self.assertEqual(store.data['albums']['renamed'],[ident])
                self.assertTrue(photo.exists())
                self.wait(lambda:not w.saver.pending)
                restored=Store(store.directory)
                self.assertIn(parent,restored.data['album_folders'])
                self.assertFalse(restored.data['album_locations'])
            finally:
                self.wait(lambda:not w.busy);w.close();self.wait(lambda:not w.isVisible())


if __name__=='__main__':unittest.main()
