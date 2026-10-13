"""Shared fixtures for the RevitBridge test suite."""

import pytest


@pytest.fixture()
def sample_ifc(tmp_path):
    from revit_bridge.fixtures import build_sample_ifc

    return build_sample_ifc(str(tmp_path / "sample.ifc"))
