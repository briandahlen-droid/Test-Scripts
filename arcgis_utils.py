from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests


def resilient_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "parcel-lookup-test-app/1.0"})
    return s


def get_json(url: str, params: Optional[dict] = None, timeout: int = 20) -> dict:
    s = resilient_session()
    r = s.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def arcgis_query(
    layer_url: str,
    *,
    where: str = "1=1",
    out_fields: str = "*",
    return_geometry: bool = False,
    geometry: Optional[dict] = None,
    geometry_type: Optional[str] = None,
    in_sr: Optional[int] = 4326,
    out_sr: Optional[int] = 4326,
    spatial_rel: str = "esriSpatialRelIntersects",
    result_record_count: int = 5,
    timeout: int = 20
) -> dict:
    url = layer_url.rstrip("/") + "/query"
    params: Dict[str, Any] = {
        "f": "json",
        "where": where,
        "outFields": out_fields,
        "returnGeometry": "true" if return_geometry else "false",
        "outSR": out_sr,
        "resultRecordCount": result_record_count,
    }

    if geometry is not None:
        params.update({
            "geometry": json.dumps(geometry),
            "geometryType": geometry_type or "esriGeometryPolygon",
            "inSR": in_sr,
            "spatialRel": spatial_rel
        })

    return get_json(url, params=params, timeout=timeout)


def layer_metadata(layer_url: str) -> dict:
    return get_json(layer_url.rstrip("/") + "?f=json")


def extract_first_geometry(feature_set: dict) -> Optional[dict]:
    feats = feature_set.get("features") or []
    if not feats:
        return None
    return feats[0].get("geometry")


def extract_first_attributes(feature_set: dict) -> Optional[dict]:
    feats = feature_set.get("features") or []
    if not feats:
        return None
    return feats[0].get("attributes") or {}


_ZONE_NAME_RE = re.compile(r"(zone|zoning)", re.IGNORECASE)
_FLU_NAME_RE = re.compile(r"(future|land\s*use|flum|flu)", re.IGNORECASE)


def _score_field(name: str, alias: str, kind: str) -> int:
    text = f"{name} {alias}".lower()
    if kind == "zoning":
        if "zoneclass" in text or "zoning" in text:
            return 100
        if "zone" in text:
            return 80
        return 0
    if kind == "flu":
        if "future" in text and "use" in text:
            return 100
        if "landuse" in text or "land use" in text or "flum" in text or "flu" in text:
            return 80
        return 0
    return 0


def pick_best_code_field(meta: dict, kind: str) -> Optional[dict]:
    fields = meta.get("fields") or []
    best = None
    best_score = -1

    for f in fields:
        name = f.get("name", "") or ""
        alias = f.get("alias", "") or ""
        domain = f.get("domain")
        has_coded = bool(domain and domain.get("type") == "codedValue")
        score = _score_field(name, alias, kind)
        if has_coded:
            score += 50
        if score > best_score:
            best_score = score
            best = f

    if best_score <= 0:
        return None
    return best


def coded_value_map(field_def: dict) -> Dict[Any, str]:
    domain = field_def.get("domain") or {}
    if domain.get("type") != "codedValue":
        return {}
    out: Dict[Any, str] = {}
    for cv in domain.get("codedValues") or []:
        out[cv.get("code")] = cv.get("name")
    return out


@dataclass
class DiscoveredLayer:
    title: str
    url: str


def parse_webappviewer_id(app_url: str) -> Optional[str]:
    m = re.search(r"[?&]id=([0-9a-f]{32})", app_url, flags=re.IGNORECASE)
    return m.group(1) if m else None


def arcgis_host_from_url(app_url: str) -> str:
    m = re.match(r"https?://([^/]+)/", app_url.strip(), flags=re.IGNORECASE)
    if not m:
        raise ValueError("Could not parse host from URL")
    return m.group(1)


def try_item_json(host: str, item_id: str) -> Tuple[Optional[dict], Optional[dict]]:
    base = f"https://{host}/sharing/rest/content/items/{item_id}"
    meta = None
    data = None
    try:
        meta = get_json(base, params={"f": "json"})
    except Exception:
        meta = None
    try:
        data = get_json(base + "/data", params={"f": "json"})
    except Exception:
        data = None
    return meta, data


def extract_webmap_id(item_meta: Optional[dict], item_data: Optional[dict]) -> Optional[str]:
    for src in (item_data or {}, item_meta or {}):
        if not isinstance(src, dict):
            continue
        if "webmap" in src and isinstance(src["webmap"], str) and len(src["webmap"]) == 32:
            return src["webmap"]
        values = src.get("values")
        if isinstance(values, dict):
            wm = values.get("webmap")
            if isinstance(wm, str) and len(wm) == 32:
                return wm
            cfg = values.get("config")
            if isinstance(cfg, dict):
                wm = cfg.get("webmap")
                if isinstance(wm, str) and len(wm) == 32:
                    return wm
    return None


def extract_operational_layers_from_webmap(host: str, webmap_id: str) -> List[DiscoveredLayer]:
    wm_base = f"https://{host}/sharing/rest/content/items/{webmap_id}"
    wm_data = get_json(wm_base + "/data", params={"f": "json"})
    layers = []
    for lyr in wm_data.get("operationalLayers") or []:
        url = lyr.get("url")
        title = lyr.get("title") or lyr.get("layerType") or "Layer"
        if url:
            layers.append(DiscoveredLayer(title=title, url=url))
    return layers


def pick_candidate_layers(layers: List[DiscoveredLayer]) -> Dict[str, List[DiscoveredLayer]]:
    zoning = []
    flu = []
    for l in layers:
        t = l.title or ""
        if _ZONE_NAME_RE.search(t):
            zoning.append(l)
        if _FLU_NAME_RE.search(t):
            flu.append(l)
    return {"zoning": zoning, "flu": flu}


def discover_city_layers(app_url: str) -> Dict[str, Any]:
    item_id = parse_webappviewer_id(app_url)
    if not item_id:
        return {"ok": False, "error": "Could not parse ?id=... from app URL", "candidates": {"zoning": [], "flu": []}}

    host = arcgis_host_from_url(app_url)
    meta, data = try_item_json(host, item_id)

    webmap_id = extract_webmap_id(meta, data)
    if not webmap_id:
        return {"ok": False, "error": "Could not locate a webmap id in app item JSON", "candidates": {"zoning": [], "flu": []}}

    layers = extract_operational_layers_from_webmap(host, webmap_id)
    cands = pick_candidate_layers(layers)

    return {
        "ok": True,
        "host": host,
        "app_item_id": item_id,
        "webmap_id": webmap_id,
        "operational_layers_count": len(layers),
        "candidates": {
            "zoning": [l.__dict__ for l in cands["zoning"]],
            "flu": [l.__dict__ for l in cands["flu"]],
        }
    }
