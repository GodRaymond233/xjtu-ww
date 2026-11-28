import shutil
import threading

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QWidget

from ok import Logger, og
from ok.ui.qt.about.AboutTab import AboutSection
from ok.ui.qt.kit.buttons import Button
from ok.ui.qt.kit.feedback import show_toast
from ok.ui.qt.kit.labels import Label

from src.portable_update import find_update, stage_update, start_installer


logger = Logger.get_logger(__name__)


class PortableUpdate(QObject):
    finished = Signal(object, object, object)
    progress = Signal(int)

    def __init__(self, root, version):
        super().__init__()
        self.root = root
        self.version = version
        self.latest = None
        self.staging = None
        self.window = None
        self.busy = False
        self.status = ('', '')
        self.finished.connect(self._complete)
        self.progress.connect(self._show_progress)
        self.install_timer = QTimer(self)
        self.install_timer.setInterval(1500)
        self.install_timer.timeout.connect(self._install)

    @property
    def chinese(self):
        return self.window.app.locale.name().startswith('zh')

    def attach(self, window):
        first = self.window is None
        self.window = window
        about = window.about_tab
        panel = QWidget(about)
        layout = QHBoxLayout(panel)
        self.label = Label('', 'body', panel, word_wrap=True)
        self.check_button = Button(self._text('Check for updates', '检查更新'), 'refresh', parent=panel)
        self.update_button = Button(self._text('Download and install', '下载并安装'), 'download', 'primary', parent=panel)
        self.check_button.clicked.connect(lambda: self.check())
        self.update_button.clicked.connect(self._update_clicked)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.check_button)
        layout.addWidget(self.update_button)
        section = AboutSection(self._text('App update', '软件更新'), panel)
        about.sections.append(section)
        about.vBoxLayout.insertWidget(1, section)
        self._refresh()
        if first:
            window.app.app.aboutToQuit.connect(self._discard_staged_update)
            QTimer.singleShot(2400, lambda: self.check(automatic=True))

    def _text(self, english, chinese):
        return chinese if self.chinese else english

    def _set_status(self, english, chinese):
        self.status = (english, chinese)
        self._refresh()

    def _refresh(self):
        self.label.setText(self._text(*self.status))
        self.check_button.setEnabled(not self.busy and self.staging is None)
        self.update_button.setVisible(bool(self.latest))
        self.update_button.setEnabled(not self.busy)
        self.update_button.setText(self._text('Install update', '安装更新') if self.staging
                                   else self._text('Download and install', '下载并安装'))

    def _background(self, operation, callback):
        self.busy = True
        self._refresh()

        def work():
            try:
                result = operation()
            except Exception as error:
                logger.warning(f'Portable update failed: {error}')
                self.finished.emit(callback, None, str(error))
            else:
                self.finished.emit(callback, result, None)

        threading.Thread(target=work, name='XJTU-WW update', daemon=True).start()

    def _complete(self, callback, result, error):
        self.busy = False
        callback(result, error)

    def check(self, automatic=False):
        if self.busy or self.staging or self.window.exit_event.is_set():
            return
        self._set_status('Checking for updates…', '正在检查更新…')
        self._background(lambda: find_update(self.version),
                         lambda release, error: self._checked(release, error, automatic))

    def _checked(self, release, error, automatic):
        if error:
            self._set_status('Unable to check for updates. Try again later.', '暂时无法检查更新，请稍后重试。')
            return
        self.latest = release
        self.window.navigation.set_badge(self.window.about_tab.objectName(), bool(release))
        if not release:
            self._set_status('You have the latest version.', '已是最新版本。')
            return
        version = release.version
        self._set_status(f'Version {version} is available.', f'发现新版 {version}。')
        if automatic:
            show_toast(self.window, self._text(*self.status), title=self._text('XJTU-WW update', 'XJTU-WW 更新'),
                       tone='accent', duration=0,
                       actions=[(self._text('Download and install', '下载并安装'), self._update_clicked, 'primary'),
                                (self._text('Later', '稍后'), None)])

    def _update_clicked(self):
        if self.busy or not self.latest:
            return
        if self.staging:
            self._install()
            return
        release = self.latest
        version = release.version
        question = self._text(
            f'Download and install {version}? XJTU-WW will close when the update is ready. '
            'The updated app will reopen automatically.',
            f'下载并安装 {version}？更新准备好后，XJTU-WW 将自动退出，并在安装完成后重新打开。',
        )
        yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
        if QMessageBox.question(self.window, 'XJTU-WW', question, yes | no, no) != yes:
            return
        self.window.switch_to(self.window.about_tab)
        self._set_status('Downloading the update…', '正在下载更新…')
        cancelled = self.window.exit_event.is_set
        self._background(lambda: stage_update(self.root, release, self.progress.emit, cancelled),
                         self._downloaded)

    def _show_progress(self, percent):
        if percent == 100:
            self._set_status('Verifying and unpacking…', '正在校验并解压…')
        else:
            self._set_status(f'Downloading the update… {percent}%', f'正在下载更新… {percent}%')

    def _downloaded(self, staging, error):
        if error:
            self._set_status('Download or verification failed. You can try again.', '下载或校验失败，可以重试。')
            return
        self.staging = staging
        if self.window.exit_event.is_set():
            self._discard_staged_update()
            return
        self.install_timer.start()
        self._install()

    def _install(self):
        from src.gui.CharacterCodeTab import CharacterCodeTab

        executor = self.window.executor
        if executor and (executor.current_task or any(task.enabled for task in executor.onetime_tasks)):
            self._set_status('Update ready. Installation will start when your tasks finish.',
                             '更新已下载，任务结束后将自动安装。')
            return
        if any(tab._has_unsaved_changes() for tab in self.window.findChildren(CharacterCodeTab)):
            self._set_status('Update ready. Save your workshop edits to continue.',
                             '更新已下载，保存工坊编辑后将自动安装。')
            return
        self.install_timer.stop()
        try:
            start_installer(self.root, self.staging, self.chinese)
        except OSError as error:
            logger.warning(f'Could not start update installer: {error}')
            self._set_status('Unable to start installation. You can try again.', '无法开始安装，可以重试。')
            return
        self.staging = None
        from ok.util.process import start_exit_watchdog

        start_exit_watchdog()
        og.ok.quit()

    def _discard_staged_update(self):
        self.install_timer.stop()
        if self.staging is not None:
            shutil.rmtree(self.staging, ignore_errors=True)
            self.staging = None
