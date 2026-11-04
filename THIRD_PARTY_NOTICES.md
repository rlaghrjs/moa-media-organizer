# Third-party components

- PySide6-Essentials / Shiboken6 6.12.0: https://pypi.org/project/PySide6-Essentials/6.12.0/ and https://doc.qt.io/qtforpython-6/
- Pillow 13.0.0: https://pypi.org/project/pillow/13.0.0/ and https://github.com/python-pillow/Pillow
- libmpv: Windows x86_64 build 20261102, git 2137d21b2e, by shinchiro. The mpv project's installation page lists this Windows build provider: https://mpv.io/installation/
- Downloaded archive: https://github.com/shinchiro/mpv-winbuild-cmake/releases/download/20261102/mpv-dev-x86_64-20261102-git-2137d21b2e.7z
- Build recipe and pinned dependency sources: https://github.com/shinchiro/mpv-winbuild-cmake/tree/20261102
- Upstream mpv: https://github.com/mpv-player/mpv
- Archive SHA-256 (verified against GitHub release metadata): 5ca801552661c18fa0b1edfd41dba6e5d9aa9d6d3d6c42dbe3fb91a45eb79f16

Package license texts are included in their distributions under .venv/Lib/site-packages. The libmpv build incorporates additional third-party libraries; its source/build information is linked above. These are independently licensed components, not original Moa code.
