import io
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from PySide6.QtCore import Qt, QItemSelectionModel
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from moa.application.library_jobs import import_library
from moa.image.gif_worker import render_gif_frame
from moa.sources.zip_source import index_zip
from moa.storage.json_store import Store
from moa.ui.main_window import MainWindow


def make_gif(path, loop=0):
    frames = [Image.new('RGB', (160, 100), color) for color in ('red', 'green', 'blue')]
    options = {'save_all': True, 'append_images': frames[1:], 'duration': [70, 100, 140], 'disposal': 2}
    if loop is not None:
        options['loop'] = loop
    frames[0].save(path, **options)


class GifWorkerTests(unittest.TestCase):
    def test_local_frames_durations_and_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gif = root / 'animation.gif'
            make_gif(gif)
            stat = gif.stat()
            item = {'path': str(gif), 'size': stat.st_size, 'modified': stat.st_mtime_ns}
            results = [render_gif_frame(item, str(root), frame, 80) for frame in range(3)]
            self.assertTrue(all(not result['error'] for result in results))
            self.assertEqual([result['duration'] for result in results], [70, 100, 140])
            self.assertEqual(len({result['data'] for result in results}), 3)
            self.assertEqual(Image.open(io.BytesIO(results[0]['data'])).size, (80, 50))
            self.assertEqual((results[0]['width'], results[0]['height']), (160, 100))
            archive = root / 'photos.zip'
            with ZipFile(archive, 'w') as source:
                source.write(gif, 'nested/a.gif')
            entries, errors = index_zip(archive)
            self.assertFalse(errors)
            zipped = render_gif_frame(entries[0], str(archive), 1, 80)
            self.assertEqual(zipped['data'], results[1]['data'])
            self.assertFalse((root / 'nested').exists())

    def test_corrupt_gif_returns_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.gif'
            path.write_bytes(b'bad gif')
            self.assertTrue(render_gif_frame({'path': str(path)}, str(path), 0, 100)['error'])


class MediaUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    def wait(self, predicate, seconds=25):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(.01)
        self.fail('Expected UI state did not arrive')

    @unittest.skipUnless(os.environ.get('MOA_TEST_VIDEO') and os.environ.get('MOA_TEST_MPV_DLL'), 'Optional real libmpv fixture')
    def test_video_search_clear_preserves_playback(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'data')
            video = Path(os.environ['MOA_TEST_VIDEO']).resolve()
            stat = video.stat()
            store.import_files([{'path': str(video), 'size': stat.st_size, 'modified': stat.st_mtime_ns}])
            w = MainWindow(store, Path(__file__).resolve().parents[1])
            w.viewer.player.dll = Path(os.environ['MOA_TEST_MPV_DLL']).resolve()
            states = []
            w.viewer.player.state.connect(states.append)
            w.show()
            self.wait(lambda: not w.busy)
            try:
                ident = next(iter(store.data['files']))
                w.open_viewer(ident)
                self.wait(lambda: bool(states) and states[-1]['duration'] > 0)
                token = w.viewer.player.token
                process = w.viewer.player.process.pid
                w.viewer.player.send('pause', value=False)
                self.wait(lambda: states[-1]['position'] > .2)
                w.search.setText('video')
                w.search.clear()
                self.wait(lambda: not w.busy)
                self.assertEqual(w.viewer_id, ident)
                self.assertEqual(w.viewer.player.token, token)
                self.assertEqual(w.viewer.player.process.pid, process)
                self.assertIs(w.pages.currentWidget(), w.viewer)
                self.assertTrue(w.viewer.player.active)
            finally:
                self.wait(lambda: not w.busy)
                w.close()
                self.wait(lambda: not w.isVisible())

    def test_gif_search_clear_album_remove_and_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gif = root / 'moving.gif'
            make_gif(gif)
            finite = root / 'finite.gif'
            make_gif(finite, loop=None)
            png = root / 'photo.png'
            Image.new('RGB', (320, 180), 'yellow').save(png)
            archive = root / 'photos.zip'
            with ZipFile(archive, 'w') as source:
                source.write(gif, 'a.gif')
            store = Store(root / 'data')
            store.data, _, errors = import_library(store.snapshot(), str(root), store.directory)
            self.assertFalse(errors)
            ids = {item['path']: ident for ident, item in store.data['files'].items()}
            moving = ids[str(gif)]
            still = ids[str(png)]
            store.album('test', [moving, still])
            store.album('other', [moving, still])
            w = MainWindow(store, Path(__file__).resolve().parents[1])
            w.show()
            w.activateWindow()
            self.wait(lambda: not w.busy)
            try:
                row = w.model.ids.index(moving)
                w.selection.setCurrentIndex(w.model.index(row, 0), QItemSelectionModel.SelectionFlag.ClearAndSelect)
                preview_frames = []
                w.preview_gif.frameReady.connect(lambda pixmap, width, height: preview_frames.append(pixmap.toImage().pixelColor(0, 0).name()))
                self.wait(lambda: len(set(preview_frames)) >= 3)
                self.assertNotEqual(w.preview_gif.worker_pid, os.getpid())
                self.assertIn('160 × 100', w.resolution.text())
                self.assertFalse(w.remove_button.isVisible())
                w.info_action.setChecked(False)
                w.toggle_info(False)
                self.assertIsNone(w.preview_gif.item)
                w.info_action.setChecked(True)
                w.toggle_info(True)
                w.open_viewer(moving)
                frames = []
                w.viewer.gif.frameReady.connect(lambda pixmap, width, height: frames.append(pixmap.toImage().pixelColor(0, 0).name()))
                self.wait(lambda: len(set(frames)) >= 3)
                self.assertIsNone(w.preview_gif.item)
                self.assertNotEqual(w.viewer.gif.worker_pid, os.getpid())
                w.viewer.photo.zoom(1.25)
                transform = w.viewer.photo.transform()
                w.viewer.photo.rotate()
                rotation = w.viewer.photo.item.rotation()
                frame_count = len(frames)
                self.wait(lambda: len(frames) > frame_count + 1)
                self.assertEqual(w.viewer.photo.item.rotation(), rotation)
                w.viewer.photo.zoom(1.25)
                transform = w.viewer.photo.transform()
                frame_count = len(frames)
                self.wait(lambda: len(frames) > frame_count)
                self.assertEqual(w.viewer.photo.transform(), transform)
                # Delete the final character while the GIF viewer is active.
                w.search.setFocus()
                w.search.setText('moving')
                w.search.selectAll()
                QTest.keyClick(w.search, Qt.Key.Key_Backspace)
                self.wait(lambda: not w.busy)
                self.assertEqual(w.viewer_id, moving)
                self.assertIs(w.pages.currentWidget(), w.viewer)
                self.assertIsNotNone(w.viewer.gif.item)
                self.assertEqual(w.search.text(), '')
                # The clear button follows the same signal path for a static image.
                original_request = w.tasks.request
                blocked = [True]
                def delayed_request(item, size, priority=10):
                    if size == 4096 and blocked[0]:
                        return None
                    return original_request(item, size, priority)
                with patch.object(w.tasks, 'request', delayed_request):
                    w.open_viewer(still)
                    self.assertIsNone(w.viewer.photo_key)
                    w.search.setText('photo')
                    blocked[0] = False
                    w.search.clear()
                    self.wait(lambda: w.viewer.photo_key is not None)
                w.search.setText('photo')
                w.search.clear()
                self.wait(lambda: not w.busy)
                self.assertEqual(w.viewer_id, still)
                w.back_to_list()
                w.tree.setCurrentItem(w.album_items['test'])
                self.wait(lambda: not w.busy and w.view == ('album', 'test'))
                rows = [w.model.ids.index(ident) for ident in (moving, still)]
                w.selection.clearSelection()
                for row in rows:
                    w.selection.select(w.model.index(row, 0), QItemSelectionModel.SelectionFlag.Select)
                self.assertTrue(w.remove_button.isVisible())
                self.assertTrue(w.remove_action.isEnabled())
                QTest.mouseClick(w.remove_button, Qt.MouseButton.LeftButton)
                self.wait(lambda: not w.busy)
                self.assertEqual(store.data['albums']['test'], [])
                self.assertEqual(store.data['albums']['other'], [moving, still])
                self.assertTrue(gif.exists() and png.exists())
                self.assertIn(moving, store.data['files'])
                self.wait(lambda: not w.saver.pending)
                self.assertEqual(Store(store.directory).data['albums']['test'], [])
                w.album_drop('test', [still])
                w.selection.setCurrentIndex(w.model.index(0, 0), QItemSelectionModel.SelectionFlag.ClearAndSelect)
                w.grid.setFocus()
                QTest.keyClick(w.grid, Qt.Key.Key_Delete)
                self.wait(lambda: not w.busy)
                self.assertEqual(store.data['albums']['test'], [])
                w.album_drop('test', [moving, still])
                row = w.model.ids.index(moving)
                w.selection.setCurrentIndex(w.model.index(row, 0), QItemSelectionModel.SelectionFlag.ClearAndSelect)
                w.open_viewer(moving)
                QTest.mouseClick(w.remove_button, Qt.MouseButton.LeftButton)
                self.wait(lambda: not w.busy)
                self.assertEqual(store.data['albums']['test'], [still])
                self.assertIs(w.pages.currentWidget(), w.library_page)
                w.change_mode(True)
                w.table.setFocus()
                w.selection.setCurrentIndex(w.model.index(0, 0), QItemSelectionModel.SelectionFlag.ClearAndSelect)
                QTest.keyClick(w.table, Qt.Key.Key_Delete)
                self.wait(lambda: not w.busy)
                self.assertEqual(store.data['albums']['test'], [])
                # ZIP GIFs use the same animation path.
                w.tree.setCurrentItem(w.tree_nodes['all'])
                self.wait(lambda: not w.busy)
                zipped = next(ident for ident, item in store.data['files'].items() if item.get('archive'))
                w.open_viewer(zipped)
                frames.clear()
                self.wait(lambda: len(set(frames)) >= 3)
                w.open_viewer(ids[str(finite)])
                self.wait(lambda: w.viewer.gif.finished)
                self.assertEqual(w.viewer.gif.cycles, 1)
                w.open_viewer(still)
                self.wait(lambda: w.viewer.photo_key is not None)
                self.assertIsNone(w.viewer.gif.item)
            finally:
                self.wait(lambda: not w.busy)
                w.close()
                self.wait(lambda: not w.isVisible())
                self.assertIsNone(w.tasks.gif_pool)


if __name__ == '__main__':
    unittest.main()
