"""Scaffolded backends: verify they fail loudly and generate honestly."""

import os
import platform

import pytest

from revit_bridge.backends import REGISTRY, ConversionContext
from revit_bridge.errors import BackendUnavailableError, ConversionError


def test_local_revit_unavailable_off_windows():
    be = REGISTRY["local-revit"]
    assert be.status == "scaffolded"
    if platform.system() != "Windows":
        with pytest.raises(BackendUnavailableError, match="[Ww]indows.*Revit"):
            be.check_available()


def test_local_revit_dry_run_generates_bundle(tmp_path):
    be = REGISTRY["local-revit"]
    bundle = be.generate_bundle(str(tmp_path))
    src = open(bundle["addin_source"]).read()
    assert "IFCExportOptions" in src
    assert "IFCVersion.IFC4" in src
    assert "doc.Export" in src
    # family-first: the X->Revit application ships its own command
    fam = open(bundle["family_import_source"]).read()
    assert "NewFamilyDocument" in fam
    assert "TessellatedShapeBuilder" in fam
    assert ".rfa" in fam
    assert (tmp_path / "revit-export-bundle").exists()


def test_x_to_rfa_is_honest_about_limits(tmp_path):
    """Family import refuses to pretend it is proven, same as project import."""
    import unittest.mock as mock

    be = REGISTRY["local-revit"]
    ctx = ConversionContext(src="m.obj", dst="m.rfa", src_fmt="obj", dst_fmt="rfa",
                            workdir=str(tmp_path))
    with mock.patch.object(be, "check_available", lambda: None):
        with pytest.raises(ConversionError, match="[Ss]caffolded|family|prove"):
            be.convert(ctx)


def test_local_revit_convert_dry_run(tmp_path):
    be = REGISTRY["local-revit"]
    ctx = ConversionContext(src="m.rvt", dst="m.ifc", src_fmt="rvt", dst_fmt="ifc",
                            dry_run=True, workdir=str(tmp_path))
    out = be.convert(ctx)
    assert out.endswith(".journal.txt")


def test_local_revit_convert_no_windows_errors(tmp_path):
    be = REGISTRY["local-revit"]
    ctx = ConversionContext(src="m.rvt", dst="m.ifc", src_fmt="rvt", dst_fmt="ifc",
                            workdir=str(tmp_path))
    if platform.system() != "Windows":
        with pytest.raises(BackendUnavailableError):
            be.convert(ctx)


def test_x_to_rvt_is_honest_about_limits(tmp_path):
    """Even where Revit exists, X->RVT refuses to pretend it is proven."""
    import unittest.mock as mock

    be = REGISTRY["local-revit"]
    ctx = ConversionContext(src="m.obj", dst="m.rvt", src_fmt="obj", dst_fmt="rvt",
                            workdir=str(tmp_path))
    with mock.patch.object(be, "check_available", lambda: None):
        with pytest.raises(ConversionError, match="[Ss]caffolded|[Dd]irectShape|prove"):
            be.convert(ctx)


def test_aps_cloud_missing_creds():
    be = REGISTRY["aps-cloud"]
    assert be.status == "scaffolded"
    env = {k: v for k, v in os.environ.items()
           if k not in ("APS_CLIENT_ID", "APS_CLIENT_SECRET", "APS_ACTIVITY_ID")}
    import unittest.mock as mock

    with mock.patch.dict(os.environ, env, clear=True):
        with pytest.raises(BackendUnavailableError, match="APS_CLIENT_ID"):
            be.check_available()


def test_aps_cloud_no_network_in_tests(tmp_path):
    """convert() must fail on validation, before any network touch."""
    be = REGISTRY["aps-cloud"]
    import unittest.mock as mock

    fake = {"APS_CLIENT_ID": "x", "APS_CLIENT_SECRET": "y", "APS_ACTIVITY_ID": "z"}
    with mock.patch.dict(os.environ, fake, clear=False):
        ctx = ConversionContext(src="m.rvt", dst="m.ifc", src_fmt="rvt", dst_fmt="ifc",
                                workdir=str(tmp_path))
        with pytest.raises(BackendUnavailableError, match="[Ss]igned URL"):
            be.convert(ctx)
