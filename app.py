"""Application entry point. Importing this module never starts UI or workers."""
import multiprocessing
import os
import sys
from pathlib import Path

def main():
    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QApplication,QMessageBox
    from moa.storage.json_store import Store
    from moa.ui.main_window import MainWindow
    base=Path(__file__).resolve().parent
    application=QApplication(sys.argv);application.setStyle('Fusion');application.setApplicationName('Moa');application.setOrganizationName('Moa')
    data=Path(os.environ.get('MOA_DATA_DIR',str(base/'data')));data.mkdir(parents=True,exist_ok=True)
    lock=QLockFile(str(data/'application.lock'));lock.setStaleLockTime(30000)
    if not lock.tryLock(100):
        QMessageBox.information(None,'모아','이미 같은 라이브러리를 사용하는 모아가 실행 중입니다. 기존 창을 확인하세요.');return 0
    def report_exception(kind,error,traceback_object):
        import traceback
        (data/'error.log').write_text(''.join(traceback.format_exception(kind,error,traceback_object)),encoding='utf-8')
        QMessageBox.warning(None,'모아 작업 오류',str(error)+'\n\n상세 기록: '+str(data/'error.log'))
    sys.excepthook=report_exception
    try:
        legacy=None if os.environ.get('MOA_SKIP_MIGRATION') else Path(os.environ.get('LOCALAPPDATA','.'))/'MoaMediaOrganizer'/'library.sqlite3'
        store=Store(data,legacy)
        window=MainWindow(store,base)
        screen=application.primaryScreen()
        if screen:
            area=screen.availableGeometry()
            window.setMinimumSize(min(1040,area.width()-20),min(650,area.height()-45))
            window.resize(min(window.width(),area.width()-20),min(window.height(),area.height()-45))
            window.move(area.x()+(area.width()-window.width())//2,area.y()+15)
        window.show()
        code=application.exec();lock.unlock();return code
    except Exception as error:
        import traceback
        (data/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
        QMessageBox.critical(None,'모아 실행 오류',str(error)+'\n\n상세 기록: '+str(data/'error.log'));lock.unlock();return 1

if __name__=='__main__':
    multiprocessing.freeze_support()
    raise SystemExit(main())
