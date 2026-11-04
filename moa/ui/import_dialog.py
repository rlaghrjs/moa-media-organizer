from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QGroupBox,QGridLayout,QCheckBox,QPushButton,QDialogButtonBox
from moa.contracts import IMAGES,VIDEOS,EXTENSIONS

class ExtensionDialog(QDialog):
    def __init__(self,selected=None,parent=None):
        super().__init__(parent);self.setWindowTitle('불러올 확장자 선택');self.setMinimumWidth(530);self.checks={}
        initial=EXTENSIONS if selected is None else set(selected)
        layout=QVBoxLayout(self);layout.setSpacing(15)
        label=QLabel('선택한 확장자의 사진·영상만 등록합니다. 하위 폴더와 ZIP 내부 사진에도 적용됩니다.');label.setWordWrap(True);layout.addWidget(label)
        for title,values in [('사진',IMAGES),('영상',VIDEOS)]:
            group=QGroupBox(title);grid=QGridLayout(group)
            for index,extension in enumerate(sorted(values)):
                check=QCheckBox(extension.upper());check.setChecked(extension in initial);self.checks[extension]=check;grid.addWidget(check,index//5,index%5)
            layout.addWidget(group)
        controls=QHBoxLayout()
        for title,values in [('전체 선택',EXTENSIONS),('사진만',IMAGES),('영상만',VIDEOS),('선택 해제',set())]:
            button=QPushButton(title);button.clicked.connect(lambda checked=False,v=values:self.select(v));controls.addWidget(button)
        layout.addLayout(controls)
        self.notice=QLabel();self.notice.setStyleSheet('color:#b34a3b;');layout.addWidget(self.notice)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('폴더 선택…');self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('취소');self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject);layout.addWidget(self.buttons)
        for check in self.checks.values():check.toggled.connect(self.update_validity)
        self.update_validity()
    def extensions(self):return sorted(ext for ext,check in self.checks.items() if check.isChecked())
    def select(self,values):
        for ext,check in self.checks.items():check.setChecked(ext in values)
    def update_validity(self):
        valid=bool(self.extensions());self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valid);self.notice.setText('확장자를 하나 이상 선택하세요.' if not valid else '')
