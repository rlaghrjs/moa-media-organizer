"""GIF decoding in a dedicated image process, with one retained source."""
import io
import os
from pathlib import Path

from PIL import Image

_source_key = None
_source_image = None
_source_bytes = None
_frame_count = 0
_loop_count = None
MAX_BYTES = 128 * 1024 * 1024
MAX_PIXELS = 32 * 1024 * 1024


def render_gif_frame(item, source_key, frame_number, size):
    global _source_key, _source_image, _source_bytes, _frame_count, _loop_count
    try:
        if source_key != _source_key:
            if _source_image is not None:
                _source_image.close()
            _source_key = None
            _source_image = None
            if item.get('archive'):
                from moa.sources.zip_source import read_member
                data = read_member(item)
            else:
                path = Path(item['path'])
                if path.stat().st_size > MAX_BYTES:
                    raise ValueError('GIF 파일 크기가 읽기 제한을 초과합니다.')
                with path.open('rb') as source:
                    data = source.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError('GIF 파일 크기가 읽기 제한을 초과합니다.')
            _source_bytes = io.BytesIO(data)
            _source_image = Image.open(_source_bytes)
            if _source_image.width * _source_image.height > MAX_PIXELS:
                raise ValueError('GIF 해상도가 읽기 제한을 초과합니다.')
            _loop_count = _source_image.info.get('loop')
            _frame_count = _source_image.n_frames
            _source_key = source_key
        _source_image.seek(frame_number % _frame_count)
        width, height = _source_image.size
        duration = max(20, int(_source_image.info.get('duration', 100)))
        frame = _source_image.convert('RGBA')
        frame.thumbnail((size, size))
        encoded = io.BytesIO()
        frame.save(encoded, 'PNG')
        return {
            'data': encoded.getvalue(), 'duration': duration,
            'frames': _frame_count, 'loop': _loop_count,
            'width': width, 'height': height, 'pid': os.getpid(), 'error': '',
        }
    except Exception as error:
        return {'error': str(error), 'pid': os.getpid()}
