"""Windows-first desktop workflow for part delivery."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QSettings, QThread, Signal
from PySide6.QtGui import QFont, QFontDatabase, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea,
    QSpinBox, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .ai_client import review_page
from .batch import collect_sources, make_bundle, read_manifest, run_batch, save_manifest
from .engine import inspect_score
from .quality import render_page_png


class BatchWorker(QThread):
    progress = Signal(int, int, str)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, sources, output_root, selected, scale, pattern):
        super().__init__()
        self.sources, self.output_root = sources, output_root
        self.selected, self.scale, self.pattern = selected, scale, pattern

    def run(self):
        try:
            batch = run_batch(self.sources, self.output_root, selected=self.selected,
                              scale=self.scale, filename_pattern=self.pattern,
                              on_event=lambda i, n, text: self.progress.emit(i, n, text))
            self.completed.emit(str(batch))
        except Exception as error:
            self.failed.emit(str(error))


class AiWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, batch_dir, relative_pdf, page, endpoint, token):
        super().__init__()
        self.args = (batch_dir, relative_pdf, page, endpoint, token)

    def run(self):
        try:
            batch_dir, relative_pdf, page, endpoint, token = self.args
            result = review_page(batch_dir, relative_pdf, page, endpoint=endpoint,
                                 trial_token=token, consent=True)
            self.completed.emit(result)
        except Exception as error:
            self.failed.emit(str(error))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        for font_file in ("msyh.ttc", "simsun.ttc", "msjh.ttc"):
            path = Path("C:/Windows/Fonts") / font_file
            if path.exists():
                font_id = QFontDatabase.addApplicationFont(str(path))
                if font_id >= 0:
                    families = QFontDatabase.applicationFontFamilies(font_id)
                    if families:
                        QApplication.instance().setFont(QFont(families[0], 10))
                        break
        self.setWindowTitle("AI 谱务助手 · 分谱交付")
        self.resize(1200, 820)
        self.setAcceptDrops(True)
        self.settings = QSettings("score-parts", "AI-score-librarian")
        self.batch_dir: Path | None = None
        self.manifest: dict | None = None
        self.worker: QThread | None = None
        self.current_part: dict | None = None
        self.ai_target: str | None = None

        root = QWidget()
        layout = QVBoxLayout(root)
        self.setCentralWidget(root)

        import_bar = QHBoxLayout()
        add_files = QPushButton("添加总谱")
        add_files.clicked.connect(self._choose_files)
        add_folder = QPushButton("添加文件夹")
        add_folder.clicked.connect(self._choose_folder)
        clear = QPushButton("清空列表")
        clear.clicked.connect(self.import_tree_clear)
        import_bar.addWidget(add_files)
        import_bar.addWidget(add_folder)
        import_bar.addWidget(clear)
        import_bar.addStretch()
        layout.addLayout(import_bar)

        self.import_tree = QTreeWidget()
        self.import_tree.setHeaderLabels(["曲目 / 声部", "小节数", "状态"])
        self.import_tree.setColumnWidth(0, 550)
        self.import_tree.setColumnWidth(1, 100)
        self.import_tree.setMinimumHeight(170)
        layout.addWidget(self.import_tree)

        settings_box = QGroupBox("交付规则")
        form = QFormLayout(settings_box)
        output_row = QHBoxLayout()
        self.output_edit = QLineEdit(self.settings.value("output", str(Path.home() / "Documents" / "分谱交付")))
        browse_output = QPushButton("选择")
        browse_output.clicked.connect(self._choose_output)
        output_row.addWidget(self.output_edit)
        output_row.addWidget(browse_output)
        form.addRow("输出根目录", output_row)
        self.pattern_edit = QLineEdit(self.settings.value("pattern", "{title} - {part}"))
        self.pattern_edit.setToolTip("可用变量：{title}、{part}、{id}")
        form.addRow("PDF 文件名", self.pattern_edit)
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(25, 100)
        self.scale_spin.setValue(int(self.settings.value("scale", 70)))
        form.addRow("谱面比例", self.scale_spin)
        preset_row = QHBoxLayout()
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("选择预设")
        self._refresh_presets()
        self.preset_combo.currentTextChanged.connect(self._load_preset)
        save_preset = QPushButton("保存当前预设")
        save_preset.clicked.connect(self._save_preset)
        preset_row.addWidget(self.preset_combo)
        preset_row.addWidget(save_preset)
        form.addRow("预设", preset_row)
        layout.addWidget(settings_box)

        action_row = QHBoxLayout()
        self.run_button = QPushButton("生成并检查分谱")
        self.run_button.clicked.connect(self._run_batch)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.status = QLabel("拖入 MXL/MusicXML，或点击“添加总谱”。")
        action_row.addWidget(self.run_button)
        action_row.addWidget(self.progress, 1)
        action_row.addWidget(self.status, 2)
        layout.addLayout(action_row)

        splitter = QSplitter()
        layout.addWidget(splitter, 1)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("交付结果与质检"))
        self.result_list = QListWidget()
        self.result_list.currentItemChanged.connect(self._select_pdf)
        left_layout.addWidget(self.result_list, 1)
        self.findings_list = QListWidget()
        self.findings_list.currentItemChanged.connect(self._select_finding)
        left_layout.addWidget(self.findings_list, 1)
        resolved = QPushButton("标记选中疑点为已处理")
        resolved.clicked.connect(self._resolve_finding)
        left_layout.addWidget(resolved)
        report = QPushButton("打开本地报告")
        report.clicked.connect(self._open_report)
        left_layout.addWidget(report)
        self.bundle_button = QPushButton("人工审阅后打包交付")
        self.bundle_button.clicked.connect(self._bundle)
        left_layout.addWidget(self.bundle_button)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        page_row = QHBoxLayout()
        page_row.addWidget(QLabel("PDF 页面"))
        self.page_spin = QSpinBox()
        self.page_spin.setRange(1, 1)
        self.page_spin.valueChanged.connect(self._show_page)
        page_row.addWidget(self.page_spin)
        page_row.addStretch()
        right_layout.addLayout(page_row)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.preview = QLabel("生成后可逐页预览")
        self.preview.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        scroll.setWidget(self.preview)
        right_layout.addWidget(scroll, 1)
        ai_box = QGroupBox("可选在线 AI 检查 · 仅上传当前页面 PNG、曲名、声部和页码")
        ai_form = QFormLayout(ai_box)
        self.endpoint_edit = QLineEdit(self.settings.value("ai_endpoint", os.environ.get("SCORE_PARTS_AI_URL", "")))
        self.endpoint_edit.setPlaceholderText("https://你的试用服务地址")
        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.token_edit.setPlaceholderText("试用令牌（本次使用，不保存）")
        self.consent = QCheckBox("我同意上传当前选定页面用于 AI 检查")
        self.ai_button = QPushButton("检查此页")
        self.ai_button.clicked.connect(self._ai_review)
        ai_form.addRow("服务地址", self.endpoint_edit)
        ai_form.addRow("试用令牌", self.token_edit)
        ai_form.addRow(self.consent)
        ai_form.addRow(self.ai_button)
        right_layout.addWidget(ai_box)
        splitter.addWidget(right)
        splitter.setSizes([390, 790])

    def _refresh_presets(self):
        self.preset_combo.clear()
        self.preset_combo.addItem("选择预设")
        self.settings.beginGroup("presets")
        self.preset_combo.addItems(self.settings.childKeys())
        self.settings.endGroup()

    def _save_preset(self):
        name, accepted = QInputDialog.getText(self, "保存预设", "预设名称")
        if accepted and name.strip():
            self.settings.setValue(f"presets/{name.strip()}", [self.output_edit.text(),
                                   self.pattern_edit.text(), self.scale_spin.value()])
            self._refresh_presets()
            self.preset_combo.setCurrentText(name.strip())

    def _load_preset(self, name):
        if name == "选择预设":
            return
        data = self.settings.value(f"presets/{name}")
        if isinstance(data, list) and len(data) == 3:
            self.output_edit.setText(str(data[0]))
            self.pattern_edit.setText(str(data[1]))
            self.scale_spin.setValue(int(data[2]))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self._add_paths([Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()])

    def _choose_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择总谱", "", "MusicXML (*.mxl *.musicxml *.xml);;所有文件 (*)")
        self._add_paths([Path(item) for item in files])

    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择总谱文件夹")
        if folder:
            self._add_paths([Path(folder)])

    def _choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, "选择输出目录", self.output_edit.text())
        if folder:
            self.output_edit.setText(folder)

    def import_tree_clear(self):
        self.import_tree.clear()

    def _add_paths(self, paths):
        existing = {self.import_tree.topLevelItem(i).data(0, Qt.UserRole)
                    for i in range(self.import_tree.topLevelItemCount())}
        for source in collect_sources(paths):
            absolute = str(source.resolve())
            if absolute in existing:
                continue
            existing.add(absolute)
            try:
                info = inspect_score(source)
                item = QTreeWidgetItem([f"{info['title']}  ·  {source.name}", "", "可处理"])
                item.setData(0, Qt.UserRole, absolute)
                for part in info["parts"]:
                    child = QTreeWidgetItem([part["name"], str(part["measures"]), part["id"]])
                    child.setData(0, Qt.UserRole, part["id"])
                    child.setCheckState(0, Qt.Checked)
                    item.addChild(child)
            except Exception as error:
                item = QTreeWidgetItem([source.name, "", f"无法读取：{error}"])
                item.setData(0, Qt.UserRole, absolute)
            self.import_tree.addTopLevelItem(item)
            if item.childCount():
                item.setExpanded(True)

    def _run_batch(self):
        paths, selected = [], {}
        for index in range(self.import_tree.topLevelItemCount()):
            item = self.import_tree.topLevelItem(index)
            source = item.data(0, Qt.UserRole)
            paths.append(Path(source))
            if item.childCount():
                ids = [item.child(i).data(0, Qt.UserRole) for i in range(item.childCount())
                       if item.child(i).checkState(0) == Qt.Checked]
                if not ids:
                    QMessageBox.warning(self, "未选声部", f"请为 {Path(source).name} 至少选择一个声部。")
                    return
                selected[source] = ids
        if not paths:
            QMessageBox.information(self, "没有总谱", "请先添加总谱文件。")
            return
        output = Path(self.output_edit.text()).expanduser()
        self.settings.setValue("output", str(output))
        self.settings.setValue("pattern", self.pattern_edit.text())
        self.settings.setValue("scale", self.scale_spin.value())
        self.run_button.setEnabled(False)
        self.ai_button.setEnabled(False)
        self.progress.setRange(0, len(paths))
        self.progress.setValue(0)
        self.worker = BatchWorker(paths, output, selected, self.scale_spin.value(), self.pattern_edit.text())
        self.worker.progress.connect(self._progress)
        self.worker.completed.connect(self._batch_done)
        self.worker.failed.connect(self._worker_error)
        self.worker.finished.connect(lambda: (self.run_button.setEnabled(True), self.ai_button.setEnabled(True)))
        self.worker.start()

    def _progress(self, index, total, message):
        self.progress.setValue(index - 1)
        self.status.setText(f"{index}/{total} · {message}")

    def _batch_done(self, directory):
        self.progress.setValue(self.progress.maximum())
        self.batch_dir = Path(directory)
        self._reload_results()
        failed = sum(item["status"] == "failed" for item in self.manifest["scores"])
        self.status.setText(f"已生成：{self.batch_dir}；失败 {failed} 份。请审阅报告。")

    def _worker_error(self, message):
        self.status.setText(message)
        QMessageBox.critical(self, "处理失败", message)

    def _reload_results(self):
        self.manifest = read_manifest(self.batch_dir)
        self.result_list.clear()
        for score in self.manifest["scores"]:
            if score["status"] == "failed":
                item = QListWidgetItem(f"失败 · {Path(score['source']).name} · {score['error']}")
                item.setFlags(Qt.ItemIsEnabled)
                self.result_list.addItem(item)
            for part in score["outputs"]:
                item = QListWidgetItem(f"{score['title']} · {part['name']} · {part['pages']} 页 · {len(part['findings'])} 项疑点")
                item.setData(Qt.UserRole, part["file"])
                self.result_list.addItem(item)
        if self.result_list.count():
            self.result_list.setCurrentRow(0)

    def _select_pdf(self, current, _previous):
        self.current_part = None
        self.findings_list.clear()
        self.preview.setText("选择一份 PDF 预览")
        if not current or not self.manifest:
            return
        relative = current.data(Qt.UserRole)
        for score in self.manifest["scores"]:
            for part in score["outputs"]:
                if part["file"] == relative:
                    self.current_part = part
                    self.page_spin.blockSignals(True)
                    self.page_spin.setRange(1, max(1, part["pages"]))
                    self.page_spin.setValue(1)
                    self.page_spin.blockSignals(False)
                    self._show_page()
                    self._list_findings()
                    return

    def _list_findings(self):
        self.findings_list.clear()
        if not self.current_part:
            return
        for index, issue in enumerate(self.current_part["findings"]):
            prefix = "AI 建议" if issue["source"] == "ai" else "程序检查"
            text = f"{prefix} · {issue['severity']} · 第 {issue['page'] or '?'} 页 · {issue['message']}"
            if issue["resolved"]:
                text += "  ✓ 已处理"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, index)
            self.findings_list.addItem(item)

    def _select_finding(self, item, _previous):
        if item and self.current_part:
            page = self.current_part["findings"][item.data(Qt.UserRole)].get("page")
            if page:
                self.page_spin.setValue(page)

    def _show_page(self):
        if not self.current_part or not self.batch_dir:
            return
        try:
            image = render_page_png(self.batch_dir / self.current_part["file"], self.page_spin.value(), width=850)
            pixmap = QPixmap()
            pixmap.loadFromData(image)
            self.preview.setPixmap(pixmap)
            self.preview.resize(pixmap.size())
        except Exception as error:
            self.preview.setText(f"无法预览：{error}")

    def _resolve_finding(self):
        item = self.findings_list.currentItem()
        if not item or not self.current_part:
            return
        self.current_part["findings"][item.data(Qt.UserRole)]["resolved"] = True
        save_manifest(self.batch_dir, self.manifest)
        self._list_findings()

    def _ai_review(self):
        if not self.current_part or not self.batch_dir:
            QMessageBox.information(self, "选择页面", "请先选择一份 PDF 和页码。")
            return
        if not self.consent.isChecked():
            QMessageBox.warning(self, "需要同意", "请先明确勾选同意上传当前选定页面。")
            return
        page = self.page_spin.value()
        response = QMessageBox.question(
            self, "确认上传此页", f"将仅上传当前 PDF 的第 {page} 页 PNG，以及曲名、声部和页码。原始总谱不会上传。继续吗？")
        if response != QMessageBox.Yes:
            return
        self.settings.setValue("ai_endpoint", self.endpoint_edit.text())
        self.ai_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self.consent.setChecked(False)
        self.ai_target = self.current_part["file"]
        self.worker = AiWorker(self.batch_dir, self.ai_target, page,
                               self.endpoint_edit.text(), self.token_edit.text())
        self.worker.completed.connect(self._ai_done)
        self.worker.failed.connect(self._worker_error)
        self.worker.finished.connect(lambda: (self.ai_button.setEnabled(True), self.run_button.setEnabled(True)))
        self.worker.start()

    def _ai_done(self, suggestions):
        relative = self.ai_target
        self.manifest = read_manifest(self.batch_dir)
        for score in self.manifest["scores"]:
            for part in score["outputs"]:
                if part["file"] == relative:
                    self.current_part = part
                    self._list_findings()
                    self.status.setText(f"AI 检查完成：{len(suggestions)} 项建议。请人工判断。")
                    return

    def _open_report(self):
        if not self.batch_dir:
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.batch_dir / "report.html")))

    def _bundle(self):
        if not self.batch_dir:
            return
        response = QMessageBox.question(self, "确认人工审阅", "请确认已查看总谱和分谱的关键页面。未处理的疑点仍会保留在报告中。现在打包吗？")
        if response == QMessageBox.Yes:
            try:
                destination = make_bundle(self.batch_dir, confirm_review=True)
                self.status.setText(f"交付包：{destination}")
            except Exception as error:
                self._worker_error(str(error))

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "仍在处理", "请等待当前任务完成。")
            event.ignore()
        else:
            event.accept()


def main() -> int:
    application = QApplication(sys.argv)
    application.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
