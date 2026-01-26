# Parcel Lookup Test App (Zoning + Future Land Use)

Standalone Streamlit test app to validate **automated** parcel-based zoning + FLU lookup.

Workflow:
1) Parcel ID -> parcel geometry (county parcels layer)
2) Parcel geometry -> jurisdiction (municipal boundary intersect)
3) Jurisdiction -> zoning + FLU via:
   - known fixed endpoints (unincorporated Pinellas, St. Pete), OR
   - auto-discovery from a city ArcGIS web app URL (Web AppViewer / Experience Builder)

## Run

```bash
cd parcel_lookup_test_app
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Files
- streamlit_app.py
- arcgis_utils.py
- data/core_services.json
- data/pinellas_city_apps.json
