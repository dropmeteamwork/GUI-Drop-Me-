import sys
import os
from pathlib import Path
from argparse import ArgumentParser

import PySide6.scripts

sys.path.append(os.path.dirname(PySide6.scripts.__file__))

from PySide6.scripts.project import ClOptions, Project
from gui import PROJECT_DIR


PROJECT_FILE = PROJECT_DIR / "gui.pyproject"
QML_MODULE_DIR = PROJECT_DIR.joinpath("qml/DropMe")


class CustomProject(Project):
    def __init__(self, project_file: Path) -> None:
        super().__init__(project_file)
        self._qml_module_dir = QML_MODULE_DIR
        self._qml_dir_file = QML_MODULE_DIR / "qmldir"


def get_project() -> CustomProject:
    parser = ArgumentParser()
    parser.add_argument("--quiet", "-q", action="store_true", help="Quiet")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Only print commands")
    parser.add_argument("--force", "-f", action="store_true", help="Force rebuild")
    parser.add_argument("--qml-module", "-Q", action="store_true", help="Perform check for QML module")
    args = parser.parse_args()
    cl_options = ClOptions(dry_run=args.dry_run, quiet=args.quiet, force=args.force, qml_module=args.qml_module)
    return CustomProject(PROJECT_FILE)


def build() -> None:
    project = get_project()
    project.build()


def lint() -> None:
    project = get_project()
    project.qmllint()
