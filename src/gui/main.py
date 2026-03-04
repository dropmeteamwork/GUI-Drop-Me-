import sys
import os
from pathlib import Path

import gui.server      # registers Server
import gui.autoserial  # registers AutoSerial
import gui.app_state   # registers AppState singleton

# Force-add project root to sys.path so 'from gui import ...' works
script_dir = Path(__file__).resolve().parent  # src/gui
root_dir = script_dir.parent.parent  # D:\dropme-gui-new-main
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import argparse
import subprocess

from PySide6.QtCore import QLoggingCategory, QStandardPaths, QStandardPaths, QDir, QFile
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonType

#from gui import QML_DIR, VERSION
from gui import QML_DIR, VERSION
from gui.system_info import SystemInfo



def main() -> None:
    parser = argparse.ArgumentParser(description="A script with development and simulation flags.")
    
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Enable development mode."
    )
    
    args = parser.parse_args()

    QLoggingCategory.setFilterRules("qt.multimedia.ffmpeg=false")

    app = QGuiApplication(sys.argv)
    app.setOrganizationName("dropme")
    app.setOrganizationDomain("dropmeeg.com")
    app.setApplicationDisplayName("GUI")
    app.setApplicationVersion("v1.0.0")
    app.setApplicationName("gui")

    appDataLocation = QDir(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
    appDataLocation.mkpath("captures")
    pidFile = QFile(appDataLocation.filePath("gui.pid"))
    if pidFile.open(QFile.OpenModeFlag.WriteOnly):
        pidFile.write(str(os.getpid()).encode() + b"\n")
        pidFile.close()

    engine = QQmlApplicationEngine()
    engine.addImportPath(QML_DIR)
    engine.loadFromModule("DropMeQML", "MainWindow")

    if not engine.rootObjects():
        sys.exit(-1)

    # Singleton is created when QML loads; get it after load to set dev_mode (use property so QML updates)
    system_info = engine.singletonInstance("DropMe", "SystemInfo")
    if system_info is not None:
        system_info.dev = args.dev

    app_state = engine.singletonInstance("DropMe", "AppState")
    if app_state is not None:
        app_state.resetWorkflowFlags()
        
    exit_code = app.exec()
    del engine
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
