import json

from revit_bridge.cli import main


def test_list_backends(capsys):
    assert main(["--list-backends"]) == 0
    out = capsys.readouterr().out
    for name in ("mock", "ifcopenshell", "local-revit", "aps-cloud"):
        assert name in out
    assert "scaffolded" in out and "proven" in out


def test_missing_input():
    assert main([]) == 2


def test_missing_to(tmp_path):
    src = tmp_path / "m.ifc"
    src.write_text("x")
    assert main([str(src)]) == 2


def test_mock_conversion_via_cli(tmp_path):
    src = tmp_path / "m.rvt"
    src.write_bytes(b"fake")
    dst = tmp_path / "m.glb"
    assert main([str(src), "--to", "glb", "--backend", "mock", "--out", str(dst)]) == 0
    assert json.loads(dst.read_text())["mock"] is True


def test_rvt_to_glb_without_backend_shows_plan_and_fails_loudly(tmp_path, capsys):
    src = tmp_path / "m.rvt"
    src.write_bytes(b"fake")
    rc = main([str(src), "--to", "glb", "--out", str(tmp_path / "m.glb")])
    assert rc == 1
    err = capsys.readouterr()
    assert "local-revit" in err.out  # plan printed
    assert "Windows" in err.err      # honest failure, not a traceback
