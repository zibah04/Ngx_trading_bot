"""Nonblocking process lock for a single engine per local SQLite database."""
import os
from pathlib import Path


class InstanceLock:
    def __init__(self, database_path):
        self.path = None if database_path == ':memory:' else Path(str(Path(database_path).expanduser().resolve()) + '.lock')
        self.file = None

    def acquire(self):
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                self.file.seek(0)
                if self.file.read(1) == b'':
                    self.file.write(b'0')
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            self.file = None
            raise RuntimeError('Another engine owns this database; only one instance is allowed.') from exc

    def release(self):
        if self.file is not None:
            self.file.close()
            self.file = None
        # Never unlink the file: waiters must lock the same inode.
