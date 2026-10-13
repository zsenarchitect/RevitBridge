"""Backend interface. Every backend declares what it can do and fails loudly
with a fix-it message when its environment is not ready."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
import tempfile


@dataclass
class ConversionContext:
    src: str
    dst: str
    src_fmt: str
    dst_fmt: str
    dry_run: bool = False
    workdir: str = ""
    options: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.workdir:
            self.workdir = tempfile.mkdtemp(prefix="revitbridge-")
        Path(self.workdir).mkdir(parents=True, exist_ok=True)


class Backend(ABC):
    #: machine name used by --backend
    name: str = ""
    #: human title
    title: str = ""
    #: "proven" (tested) or "scaffolded" (code complete, needs env/creds)
    status: str = "scaffolded"
    #: one-line honesty note shown by --list-backends
    note: str = ""

    @abstractmethod
    def supports(self, src_fmt: str, dst_fmt: str) -> bool: ...

    def check_available(self) -> None:
        """Raise BackendUnavailableError if this backend cannot run here."""

    @abstractmethod
    def convert(self, ctx: ConversionContext) -> str:
        """Run src -> dst. Returns the output path."""
