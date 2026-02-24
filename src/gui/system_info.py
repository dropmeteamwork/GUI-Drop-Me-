from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import (
    QByteArray,
    QDateTime,
    QDir,
    QFile,
    QObject,
    Property,
    QStandardPaths,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtQml import QmlElement, QmlSingleton

from gui import PROJECT_DIR, MACHINE_ID_FILENAME, CAPTURES_DIRNAME
from gui.machine_id import generate_machine_id
from gui.logging import getLogger

QML_IMPORT_NAME = "DropMe"
QML_IMPORT_MAJOR_VERSION = 1
QML_IMPORT_MINOR_VERSION = 0


def _to_file_url(path: str) -> str:
    return QUrl.fromLocalFile(path).toString()


@QmlElement
@QmlSingleton
class SystemInfo(QObject):
    """
    Provides stable filesystem/URL paths to QML.

    Key rule: NEVER depend on current working directory.
    Always derive from PROJECT_DIR (assets) and AppDataLocation (runtime data).
    """

    devModeChanged = Signal()

    def __init__(self) -> None:
        super().__init__()

        self.logger = getLogger("dropme.system_info")

        # Runtime data location (captures, videos, machine_id, etc.)
        self.data_dir = QDir(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))

        # Static assets shipped with the app (images/fonts)
        # PROJECT_DIR is assumed to be repo/app root (as in your code)
        self._project_dir = Path(PROJECT_DIR)
        self._images_dir = self._project_dir / "images"
        self._fonts_dir = self._project_dir / "fonts"

        # Expose folders to QML as file:// URLs
        self.video_ads_folder = QUrl(self.data_dir.filePath("videos"))
        self.video_ads_folder.setScheme("file")

        self.slides_folder = QUrl(str(self._images_dir / "slides"))
        self.slides_folder.setScheme("file")

        self.machine_id = self._load_or_create_machine_id()

        self.dev_mode = False

    def _load_or_create_machine_id(self) -> QByteArray:
        path = self.data_dir.filePath(MACHINE_ID_FILENAME)
        f = QFile(path)

        # 1) Read if exists
        if f.open(QFile.OpenModeFlag.ReadOnly):
            data = f.readAll()
            f.close()
            if data:
                return data

        # 2) Create new
        if f.open(QFile.OpenModeFlag.WriteOnly | QFile.OpenModeFlag.Truncate):
            f.write(QByteArray.fromStdString(generate_machine_id()))
            f.close()

        # 3) Read again
        if f.open(QFile.OpenModeFlag.ReadOnly):
            data = f.readAll()
            f.close()
            if data:
                return data

        # 4) Fallback
        self.logger.warning("Failed to read/create machine ID; using UNKWN")
        return QByteArray.fromStdString("UNKWN")

    # ---------- QML helpers ----------

    @Slot(str, result=str)
    def getFontPath(self, name: str) -> str:
        # Return a file URL (QML-friendly)
        p = self._fonts_dir / name
        return _to_file_url(str(p))

    @Slot(str, result=str)
    def getImagePath(self, name: str) -> str:
        # If caller passed no extension, default to .png like your original intent
        if "." not in name:
            name = f"{name}.png"
        p = self._images_dir / name
        return _to_file_url(str(p))

    @Slot(result=str)
    def getNextCapturePath(self) -> str:
        file_name = QDateTime.currentDateTime().toString("yyyyMMdd_hh_mm_ss.jpg")
        captures_dir = QDir(self.data_dir.filePath(CAPTURES_DIRNAME))
        return captures_dir.filePath(file_name)

    @Property(QUrl, constant=True)
    def videoAdsFolder(self) -> QUrl:
        return self.video_ads_folder

    @Property(QUrl, constant=True)
    def slidesFolder(self) -> QUrl:
        return self.slides_folder

    @Property(QByteArray, constant=True)
    def machineID(self) -> QByteArray:
        return self.machine_id

    def _get_dev(self) -> bool:
        return self.dev_mode

    def _set_dev(self, value: bool) -> None:
        if self.dev_mode != value:
            self.dev_mode = value
            self.devModeChanged.emit()

    dev = Property(bool, _get_dev, _set_dev, notify=devModeChanged)
