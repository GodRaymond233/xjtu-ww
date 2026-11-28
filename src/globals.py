import os.path
import sys

import cv2

from ok import Config, Logger, get_path_relative_to_exe, og

logger = Logger.get_logger(__name__)


class Globals:

    def __init__(self, exit_event):
        self._yolo_model = None
        self.mini_map_arrow = None
        self.logged_in = False
        self.portable_update = None
        self._startup_report_started = False

    def on_show_main_window(self, window):
        from ok.ui.qt.about.AboutTab import ProjectCard

        about = window.about_tab
        for section in list(about.sections):
            if section.findChildren(ProjectCard):
                about.vBoxLayout.removeWidget(section)
                about.sections.remove(section)
                section.deleteLater()

        frozen = getattr(sys, 'frozen', False)
        if frozen or os.environ.get('XJTU_WW_TELEMETRY_FORCE') == '1':
            import threading
            from pathlib import Path
            from PySide6.QtCore import QTimer
            from src.portable_update import finish_startup, installed_version, parse_post_update_arg
            from src.telemetry import report_startup_telemetry

            root = Path(sys.executable).resolve().parent if frozen else Path.cwd()
            post_update = parse_post_update_arg(sys.argv)
            version = installed_version(root)
            if not self._startup_report_started:
                self._startup_report_started = True

                def on_ready():
                    if not frozen or finish_startup(root, post_update):
                        report_startup_telemetry(root, version, og.config.get('_had_prior_configs', False))

                QTimer.singleShot(0, lambda: threading.Thread(target=on_ready, name='XJTU-WW startup',
                                                             daemon=True).start())
            if frozen and version:
                from src.gui.PortableUpdate import PortableUpdate

                if self.portable_update is None:
                    self.portable_update = PortableUpdate(root, version)
                self.portable_update.attach(window)

    @property
    def yolo_model(self):
        if self._yolo_model is None:
            weights = get_path_relative_to_exe(os.path.join("assets", "echo_model", "echo.onnx"))
            if og.config.get("ocr").get("params").get("use_openvino"):
                logger.info("yolo_model Using OpenVinoYolo8Detect")
                from src.OpenVinoYolo8Detect import OpenVinoYolo8Detect
                self._yolo_model = OpenVinoYolo8Detect(
                    weights=weights)
            else:
                logger.info("yolo_model Using OnnxYolo8Detect")
                from src.OnnxYolo8Detect import OnnxYolo8Detect
                self._yolo_model = OnnxYolo8Detect(
                    weights=weights)
        return self._yolo_model

    def yolo_detect(self, image, threshold=0.6, label=-1):
        return self.yolo_model.detect(image, threshold=threshold, label=label)


if __name__ == "__main__":
    glbs = Globals(exit_event=None)
