from pathlib import Path
import re
VIDEOS={'.mp4','.mov','.avi','.mkv','.wmv','.webm','.m4v','.mpeg','.mpg'}
IMAGES={'.jpg','.jpeg','.png','.gif','.webp','.heic','.heif','.bmp','.tif','.tiff','.avif'}
EXTENSIONS=VIDEOS|IMAGES
MIME='application/x-moa-file-ids'
def natural(text):
    return tuple((0,int(s)) if s.isdigit() else (1,s.casefold()) for s in re.split(r'(\d+)',str(text)))
def is_video(path):
    return Path(path).suffix.lower() in VIDEOS
