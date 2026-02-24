import os
from typing import Union, TypeAlias
from pathlib import Path

PathLike: TypeAlias = Union[str, Path, os.PathLike]

class FileQueue:
# Use 'PathLike' here instead of 'AnyPath'
    def __init__(self, file: PathLike) -> None:
        self.file = file

    def queue(self, buffer: bytes) -> None:
        with open(self.file, "ab") as fp:
            fp.write(buffer + b"\x1E")

    def dequeue(self) -> bytes | None:
        if not os.path.exists(self.file) or os.path.getsize(self.file) == 0:
            return None
        with open(self.file, "rb+") as fp:
            fp.seek(0, os.SEEK_END)
            pos = fp.tell() - 1
            while pos > 0 and fp.read(1) != b"\x1E":
                pos -= 1
                fp.seek(pos, os.SEEK_SET)
            pos = pos + 1 if pos > 0 else 0
            fp.seek(pos, os.SEEK_SET)
            fp.truncate()
            if pos == 0:
                return None
            end_pos = pos
            pos -= 2
            fp.seek(pos, os.SEEK_SET)
            while pos > 0 and fp.read(1) != b"\x1E":
                pos -= 1
                fp.seek(pos, os.SEEK_SET)
            end_pos -= 1 if pos == 0 else 2
            return fp.read(end_pos - pos)
        return None
