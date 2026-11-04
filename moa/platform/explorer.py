import os
import subprocess
from pathlib import Path

def reveal_file(path):
    path=Path(path).absolute()
    explorer=Path(os.environ.get('WINDIR',r'C:\Windows'))/'explorer.exe'
    if path.is_file():args=[str(explorer),'/select,',str(path)]
    elif path.parent.is_dir():args=[str(explorer),str(path.parent)]
    else:raise ValueError('파일과 상위 폴더를 찾을 수 없습니다.')
    return subprocess.Popen(args,shell=False)
