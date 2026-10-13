"""Shared fixtures for the RevitBridge test suite."""

import sys
from pathlib import Path

import pytest

# top-level service packages: web/, worker/, billing/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def sample_ifc(tmp_path):
    from revit_bridge.fixtures import build_sample_ifc

    return build_sample_ifc(str(tmp_path / "sample.ifc"))
