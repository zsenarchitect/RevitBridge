"""APS cloud backend (Autodesk Platform Services Design Automation).

Status: scaffolded. Implements the real Design Automation v3 REST flow:
2-legged auth -> submit workitem -> poll -> download result. Credentials come
ONLY from the environment; nothing secret is ever written to the repo.

Required env:
  APS_CLIENT_ID, APS_CLIENT_SECRET  (APS app credentials)
  APS_ACTIVITY_ID                   (your Design Automation activity that runs
                                     the revit-ifc export, e.g. built from
                                     https://github.com/yiskang/aps-revit-ifc-exporter-appbundle)
  APS_INPUT_SIGNED_URL              (signed GET URL for the input .rvt)
  APS_OUTPUT_SIGNED_URL             (signed PUT URL for the resulting .ifc)

Optional env:
  APS_ARG_INPUT / APS_ARG_OUTPUT     (workitem argument names your activity
                                     expects; defaults: inputFile / outputFile)
  APS_BASE_URL                       (default https://developer.api.autodesk.com)
  APS_SCOPES                         (default "data:read data:write";
                                     widen if your activity demands it)

No network is touched until convert() runs with credentials present, so the
test suite only exercises the validation layer.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

from ..errors import BackendUnavailableError, ConversionError
from .base import Backend, ConversionContext

_TOKEN_URL = "/authentication/v2/token"
_WORKITEMS_URL = "/da/us-east/v3/workitems"


class ApsCloudBackend(Backend):
    name = "aps-cloud"
    title = "APS Design Automation (cloud)"
    status = "scaffolded"
    note = (
        "RVT->IFC in Autodesk's cloud via Design Automation. Code complete; "
        "needs APS app credentials + a DA activity. Never runs in CI."
    )

    def supports(self, src_fmt: str, dst_fmt: str) -> bool:
        return (src_fmt, dst_fmt) == ("rvt", "ifc")

    # -- availability ------------------------------------------------------
    def _creds(self) -> dict[str, str]:
        cid = os.environ.get("APS_CLIENT_ID", "")
        secret = os.environ.get("APS_CLIENT_SECRET", "")
        activity = os.environ.get("APS_ACTIVITY_ID", "")
        missing = [k for k, v in
                   (("APS_CLIENT_ID", cid), ("APS_CLIENT_SECRET", secret),
                    ("APS_ACTIVITY_ID", activity)) if not v]
        if missing:
            raise BackendUnavailableError(
                "The 'aps-cloud' backend needs Autodesk Platform Services credentials. "
                f"Missing: {', '.join(missing)}. Create an app at "
                "https://aps.autodesk.com/myapps, build a Design Automation activity "
                "that runs the revit-ifc export (see module docstring), and export the vars. "
                "Nothing secret goes in the repo."
            )
        return {"client_id": cid, "client_secret": secret, "activity": activity}

    def check_available(self) -> None:
        self._creds()

    # -- REST helpers -------------------------------------------------------
    def _base(self) -> str:
        return os.environ.get("APS_BASE_URL", "https://developer.api.autodesk.com").rstrip("/")

    def _post(self, url: str, payload: dict | None, headers: dict) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)

    def _get(self, url: str, headers: dict) -> dict:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)

    def _token(self, creds: dict) -> str:
        scopes = os.environ.get("APS_SCOPES", "data:read data:write")
        body = (
            f"client_id={urllib.parse.quote(creds['client_id'])}"
            f"&client_secret={urllib.parse.quote(creds['client_secret'])}"
            "&grant_type=client_credentials"
            f"&scope={urllib.parse.quote(scopes)}"
        )
        req = urllib.request.Request(
            self._base() + _TOKEN_URL, data=body.encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            tok = json.load(resp)
        if "access_token" not in tok:
            raise ConversionError(f"APS auth failed: {str(tok)[:200]}")
        return tok["access_token"]

    # -- conversion ----------------------------------------------------------
    def convert(self, ctx: ConversionContext) -> str:
        creds = self._creds()
        in_url = ctx.options.get("aps_input_url") or os.environ.get("APS_INPUT_SIGNED_URL", "")
        out_url = ctx.options.get("aps_output_url") or os.environ.get("APS_OUTPUT_SIGNED_URL", "")
        if not in_url or not out_url:
            raise BackendUnavailableError(
                "aps-cloud needs signed URLs for the input .rvt and output .ifc: "
                "pass --opt aps_input_url=... --opt aps_output_url=... or set "
                "APS_INPUT_SIGNED_URL / APS_OUTPUT_SIGNED_URL."
            )
        token = self._token(creds)
        auth = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        arg_in = os.environ.get("APS_ARG_INPUT", "inputFile")
        arg_out = os.environ.get("APS_ARG_OUTPUT", "outputFile")
        wi = self._post(self._base() + _WORKITEMS_URL, {
            "activityId": creds["activity"],
            "arguments": {
                arg_in: {"url": in_url, "verb": "get"},
                arg_out: {"url": out_url, "verb": "put"},
            },
        }, auth)
        wid = wi.get("id")
        if not wid:
            raise ConversionError(f"Workitem submission failed: {str(wi)[:300]}")
        deadline = time.time() + int(ctx.options.get("aps_timeout_s", "1800"))
        while time.time() < deadline:
            st = self._get(f"{self._base()}{_WORKITEMS_URL}/{wid}", auth)
            status = st.get("status")
            if status == "success":
                break
            if status in ("failed", "cancelled"):
                raise ConversionError(f"APS workitem {wid} {status}: {str(st.get('reportUrl'))}")
            time.sleep(10)
        else:
            raise ConversionError(f"APS workitem {wid} timed out.")
        # The activity PUT the .ifc to out_url; fetch it to ctx.dst.
        req = urllib.request.Request(out_url, method="GET")
        with urllib.request.urlopen(req, timeout=600) as resp, open(ctx.dst, "wb") as fh:
            fh.write(resp.read())
        return ctx.dst
