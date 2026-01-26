from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, Optional, Tuple

import streamlit as st

from arcgis_utils import (
    arcgis_query,
    discover_city_layers,
    extract_first_attributes,
    extract_first_geometry,
    layer_metadata,
    pick_best_code_field,
    coded_value_map,
)

BASE_DIR = pathlib.Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

CORE_CFG_PATH = DATA_DIR / "core_services.json"
PINELLAS_CITY_APPS_PATH = DATA_DIR / "pinellas_city_apps.json"


def load_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@st.cache_data(show_spinner=False)
def get_core_cfg() -> dict:
    return load_json(CORE_CFG_PATH)


@st.cache_data(show_spinner=False)
def get_pinellas_city_apps() -> dict:
    if PINELLAS_CITY_APPS_PATH.exists():
        return load_json(PINELLAS_CITY_APPS_PATH)
    return {}


def pinellas_get_parcel_geometry(parcel_id: str, cfg: dict) -> Tuple[Optional[dict], Optional[dict], str]:
    parcels_layer = cfg["parcels_layer"]
    pid_field = cfg["parcel_id_field"]

    safe_pid = parcel_id.replace("'", "''")
    where = f"{pid_field} = '{safe_pid}'"

    fs = arcgis_query(
        parcels_layer,
        where=where,
        out_fields="*",
        return_geometry=True,
        out_sr=4326,
        result_record_count=1,
    )

    attrs = extract_first_attributes(fs)
    geom = extract_first_geometry(fs)
    if not geom:
        return None, None, "Parcel geometry not found in county parcel layer."
    return geom, attrs, ""


def pinellas_get_jurisdiction(parcel_geom: dict, cfg: dict) -> Tuple[str, Optional[dict]]:
    muni_layer = cfg["municipal_boundary_layer"]
    name_field = cfg["municipal_name_field"]

    fs = arcgis_query(
        muni_layer,
        where="1=1",
        out_fields="*",
        return_geometry=False,
        geometry=parcel_geom,
        geometry_type="esriGeometryPolygon",
        in_sr=4326,
        out_sr=4326,
        result_record_count=5,
    )
    attrs = extract_first_attributes(fs) or {}
    name = (attrs.get(name_field) or "").strip()
    if name:
        return name, attrs
    return "Unincorporated Pinellas County", None


def query_zoning_or_flu(layer_url: str, parcel_geom: dict, kind: str) -> Dict[str, Any]:
    out = {"ok": False, "code": "", "description": "", "layer_url": layer_url, "kind": kind, "raw": None, "error": ""}

    if not layer_url:
        out["error"] = "Missing layer URL."
        return out

    try:
        meta = layer_metadata(layer_url)
    except Exception as e:
        out["error"] = f"Layer metadata fetch failed: {e}"
        return out

    field_def = pick_best_code_field(meta, kind=kind)
    if not field_def:
        out["error"] = "Could not identify a likely code field from layer metadata."
        return out

    code_field = field_def["name"]
    domain_map = coded_value_map(field_def)

    try:
        fs = arcgis_query(
            layer_url,
            where="1=1",
            out_fields="*",
            return_geometry=False,
            geometry=parcel_geom,
            geometry_type="esriGeometryPolygon",
            in_sr=4326,
            out_sr=4326,
            result_record_count=5,
        )
    except Exception as e:
        out["error"] = f"Layer query failed: {e}"
        return out

    attrs = extract_first_attributes(fs)
    if not attrs:
        out["error"] = "No intersecting feature returned."
        return out

    code = attrs.get(code_field)
    desc = ""
    if domain_map and code in domain_map:
        desc = domain_map.get(code, "")
    else:
        for k in ("ZONEDESC", "ZONE_DESC", "DESCRIPTION", "DESC", "LANDUSE_DESC", "FLU_DESC", "FUTURE_LAND_USE_DESC"):
            if k in attrs and attrs.get(k):
                desc = str(attrs.get(k))
                break

    out.update({
        "ok": True,
        "code_field": code_field,
        "code": "" if code is None else str(code),
        "description": desc,
        "raw": attrs
    })
    return out


@st.cache_data(show_spinner=False)
def cached_discover_city_layers(app_url: str) -> dict:
    return discover_city_layers(app_url)


def pick_best_layer_from_candidates(candidates: list) -> Optional[str]:
    if not candidates:
        return None

    def score(title: str) -> int:
        t = (title or "").lower()
        s = 0
        if "zoning" in t or "zone" in t:
            s += 50
        if "future" in t:
            s += 25
        if "land use" in t or "landuse" in t or "flum" in t or "flu" in t:
            s += 25
        if "overlay" in t:
            s -= 10
        if "historic" in t:
            s -= 5
        return s

    best = max(candidates, key=lambda c: score(c.get("title", "")))
    return best.get("url")


def pinellas_lookup(parcel_id: str) -> Dict[str, Any]:
    cfg = get_core_cfg()["pinellas"]
    city_apps = get_pinellas_city_apps()

    geom, parcel_attrs, err = pinellas_get_parcel_geometry(parcel_id, cfg)
    if err:
        return {"status": "not_found", "error": err}

    jurisdiction, muni_attrs = pinellas_get_jurisdiction(geom, cfg)

    overrides = cfg.get("known_city_overrides") or {}
    if jurisdiction in overrides:
        z_layer = overrides[jurisdiction]["zoning_layer"]
        f_layer = overrides[jurisdiction]["flu_layer"]
        z = query_zoning_or_flu(z_layer, geom, "zoning")
        f = query_zoning_or_flu(f_layer, geom, "flu")
        return {"status": "ok", "county": "Pinellas", "parcel_id": parcel_id, "jurisdiction": jurisdiction, "zoning": z, "future_land_use": f}

    if jurisdiction.lower().startswith("unincorporated"):
        z_layer = cfg["unincorporated"]["zoning_layer"]
        f_layer = cfg["unincorporated"]["flu_layer"]
        z = query_zoning_or_flu(z_layer, geom, "zoning")
        f = query_zoning_or_flu(f_layer, geom, "flu")
        return {"status": "ok", "county": "Pinellas", "parcel_id": parcel_id, "jurisdiction": jurisdiction, "zoning": z, "future_land_use": f}

    app_info = city_apps.get(jurisdiction) or {}
    app_url = (
        app_info.get("zoning_flu_app")
        or app_info.get("gis_viewer_app")
        or app_info.get("zoning_flu_lookup_app")
        or app_info.get("zoning_lookup_app")
        or app_info.get("future_land_use_2045_app")
        or app_info.get("zoning_app")
    )

    if not app_url:
        return {"status": "not_found", "county": "Pinellas", "parcel_id": parcel_id, "jurisdiction": jurisdiction, "error": "No app URL configured for this jurisdiction."}

    discovery = cached_discover_city_layers(app_url)
    if not discovery.get("ok"):
        return {"status": "service_unavailable", "county": "Pinellas", "parcel_id": parcel_id, "jurisdiction": jurisdiction, "error": discovery.get("error", "Discovery failed."), "discovery": discovery}

    z_best = pick_best_layer_from_candidates(discovery["candidates"]["zoning"])
    f_best = pick_best_layer_from_candidates(discovery["candidates"]["flu"])

    z = query_zoning_or_flu(z_best, geom, "zoning") if z_best else {"ok": False, "error": "No zoning candidate layers found.", "candidates": discovery["candidates"]["zoning"]}
    f = query_zoning_or_flu(f_best, geom, "flu") if f_best else {"ok": False, "error": "No FLU candidate layers found.", "candidates": discovery["candidates"]["flu"]}

    return {"status": "ok", "county": "Pinellas", "parcel_id": parcel_id, "jurisdiction": jurisdiction, "zoning": z, "future_land_use": f, "discovery": discovery}


st.set_page_config(page_title="Parcel Zoning/FLU Lookup Test", layout="wide")
st.title("Parcel Zoning + Future Land Use (Test App)")

left, right = st.columns([1, 1])
with left:
    st.subheader("Inputs")
    county = st.selectbox("County", options=["Pinellas", "Hillsborough", "Pasco"], index=0)
    parcel_id = st.text_input("Parcel ID", placeholder="03-31-15-25128-001-0010")
    run_lookup = st.button("Lookup", type="primary", use_container_width=True)
    st.caption("Pinellas is implemented. Hillsborough/Pasco are stubs in data/core_services.json.")

with right:
    st.subheader("Result")
    if run_lookup:
        if not parcel_id.strip():
            st.error("Enter a parcel ID.")
        elif county != "Pinellas":
            st.warning("Only Pinellas is wired in this test app. Add endpoints to data/core_services.json to extend.")
        else:
            with st.spinner("Querying parcel geometry + zoning/FLU..."):
                result = pinellas_lookup(parcel_id.strip())
            st.json(result, expanded=True)

st.divider()
st.subheader("Debug: City App Discovery (optional)")
city_apps = get_pinellas_city_apps()
city_names = sorted([k for k,v in city_apps.items() if isinstance(v, dict)])
if city_names:
    city_name = st.selectbox("Pinellas City", options=city_names)
    app_info = city_apps.get(city_name, {})
    app_url = (
        app_info.get("zoning_flu_app")
        or app_info.get("gis_viewer_app")
        or app_info.get("zoning_flu_lookup_app")
        or app_info.get("zoning_lookup_app")
        or app_info.get("future_land_use_2045_app")
        or app_info.get("zoning_app")
    )
    st.write("App URL:", app_url or "(none)")
    if st.button("Discover Layers for Selected City", use_container_width=True) and app_url:
        with st.spinner("Discovering operational layers from webmap..."):
            st.json(cached_discover_city_layers(app_url), expanded=False)
else:
    st.info("No cities found in data/pinellas_city_apps.json")
