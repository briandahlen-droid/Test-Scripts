"""
Florida Property Lookup - Pinellas & Hillsborough Counties
Uses correct GIS endpoints and field names for both counties
"""
import streamlit as st
import re
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

st.set_page_config(page_title="FL Property Lookup", page_icon="🏠", layout="wide")

# ============================================================================
# PINELLAS COUNTY
# ============================================================================

PINELLAS_CITY_MAP = {
    'SP': 'St. Petersburg', 'ST PETERSBURG': 'St. Petersburg', 'CLEARWATER': 'Clearwater',
    'LARGO': 'Largo', 'PINELLAS PARK': 'Pinellas Park', 'DUNEDIN': 'Dunedin',
    'TARPON SPRINGS': 'Tarpon Springs', 'SEMINOLE': 'Seminole',
    'UNINCORPORATED': 'Unincorporated Pinellas', 'COUNTY': 'Unincorporated Pinellas'
}

def expand_pinellas_city(city_abbr):
    if not city_abbr:
        return 'Unincorporated Pinellas'
    return PINELLAS_CITY_MAP.get(city_abbr.strip().upper(), city_abbr)

def validate_pinellas_parcel_id(parcel_id):
    pattern = r'^\d{2}-\d{2}-\d{2}-\d{5}-\d{3}-\d{4}$'
    if not re.match(pattern, parcel_id):
        return False, "Format: XX-XX-XX-XXXXX-XXX-XXXX"
    return True, ""

def lookup_pinellas(parcel_id):
    try:
        url = f"https://www.pcpao.gov/api/v1/search?terms={parcel_id}&types=folio"
        session = requests.Session()
        retry = Retry(connect=3, backoff_factor=0.5)
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        
        response = session.get(url, timeout=15)
        if response.status_code != 200:
            return {'success': False, 'error': f'HTTP {response.status_code}'}
        
        data = response.json()
        if not data:
            return {'success': False, 'error': 'No results found'}
        
        property_data = data[0]
        return {
            'success': True,
            'address': property_data.get('siteAddress', ''),
            'city': expand_pinellas_city(property_data.get('siteCity', '')),
            'zip': property_data.get('siteZipCode', ''),
            'owner': property_data.get('ownerName', ''),
            'land_use': property_data.get('landUseDescription', ''),
            'zoning': property_data.get('zoning', ''),
            'site_area_sqft': property_data.get('siteAreaSqft', ''),
            'site_area_acres': property_data.get('siteAreaAcres', ''),
            'flu': ''
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}

# ============================================================================
# HILLSBOROUGH COUNTY
# ============================================================================

def lookup_hillsborough(folio):
    """
    Lookup Hillsborough property by folio using SWFWMD parcel service.
    Field name: FOLIONUM
    Service: https://www25.swfwmd.state.fl.us/arcgis12/rest/services/BaseVector/parcel_search/MapServer/7
    """
    try:
        # Query parcel by FOLIONUM
        parcel_url = "https://www25.swfwmd.state.fl.us/arcgis12/rest/services/BaseVector/parcel_search/MapServer/7/query"
        
        # Try different folio formats
        folio_formats = [
            folio,  # As entered
            folio.replace('.', ''),  # Remove decimals
            folio.split('.')[0] if '.' in folio else folio,  # Just the number before decimal
        ]
        
        parcel_data = None
        for folio_format in folio_formats:
            parcel_params = {
                'where': f"FOLIONUM = '{folio_format}'",
                'outFields': '*',
                'returnGeometry': 'true',
                'f': 'json'
            }
            
            parcel_resp = requests.get(parcel_url, params=parcel_params, timeout=15)
            data = parcel_resp.json()
            
            if data.get('features'):
                parcel_data = data
                break
        
        if not parcel_data or not parcel_data.get('features'):
            return {
                'success': False,
                'error': f'Folio {folio} not found in Hillsborough County parcel database'
            }
        
        # Extract parcel info
        attrs = parcel_data['features'][0]['attributes']
        geom = parcel_data['features'][0].get('geometry')
        
        # Calculate centroid for spatial queries
        if geom and 'rings' in geom:
            ring = geom['rings'][0]
            x_coords = [pt[0] for pt in ring]
            y_coords = [pt[1] for pt in ring]
            x = sum(x_coords) / len(x_coords)
            y = sum(y_coords) / len(y_coords)
        else:
            x = geom.get('x', 0) if geom else 0
            y = geom.get('y', 0) if geom else 0
        
        # Handle acres - try multiple fields and format properly
        acres = attrs.get('ACRES') or attrs.get('AREANO')
        if acres and acres not in [None, 'None', '']:
            acres_str = f"{float(acres):.2f}" if isinstance(acres, (int, float)) else str(acres)
        else:
            acres_str = ''
        
        result = {
            'success': True,
            'address': attrs.get('SITEADD', attrs.get('SITUSADD1', '')),
            'city': attrs.get('SCITY', 'Tampa'),
            'zip': attrs.get('SZIP', ''),
            'owner': attrs.get('OWNNAME', attrs.get('OWNERNAME', '')),
            'land_use': attrs.get('PARUSEDESC', ''),
            'site_area_acres': acres_str,
            'site_area_sqft': '',
            'zoning': attrs.get('ZONING', ''),
            'flu': ''
        }
        
        # Query zoning and FLU layers with coordinates
        if x and y:
            try:
                # Try querying zoning with the parcel's coordinate system first
                zoning_url = "https://maps.hillsboroughcounty.org/arcgis/rest/services/DSD_Viewer_Services/DSD_Viewer_Zoning_Regulatory/FeatureServer/1/query"
                
                # Try with original coordinates
                zoning_params = {
                    'geometry': f'{x},{y}',
                    'geometryType': 'esriGeometryPoint',
                    'spatialRel': 'esriSpatialRelIntersects',
                    'outFields': 'NZONE,NZONE_DESC',
                    'returnGeometry': 'false',
                    'f': 'json',
                    'inSR': '2882'  # Parcel layer spatial reference
                }
                
                zoning_resp = requests.get(zoning_url, params=zoning_params, timeout=10)
                zoning_data = zoning_resp.json()
                
                if zoning_data.get('features'):
                    z_attrs = zoning_data['features'][0]['attributes']
                    zoning_code = z_attrs.get('NZONE', '')
                    zoning_desc = z_attrs.get('NZONE_DESC', '')
                    if zoning_code and zoning_desc:
                        result['zoning'] = f"{zoning_code} - {zoning_desc}"
                    elif zoning_code:
                        result['zoning'] = zoning_code
                
                # Query FLU layer
                flu_url = "https://maps.hillsboroughcounty.org/arcgis/rest/services/DSD_Viewer_Services/DSD_Viewer_Planning/MapServer/1/query"
                flu_params = {
                    'geometry': f'{x},{y}',
                    'geometryType': 'esriGeometryPoint',
                    'spatialRel': 'esriSpatialRelIntersects',
                    'outFields': 'FLUE',
                    'returnGeometry': 'false',
                    'f': 'json',
                    'inSR': '2882'
                }
                
                flu_resp = requests.get(flu_url, params=flu_params, timeout=10)
                flu_data = flu_resp.json()
                
                if flu_data.get('features'):
                    result['flu'] = flu_data['features'][0]['attributes'].get('FLUE', '')
                    
            except Exception as e:
                # Keep parcel data even if zoning/FLU query fails
                pass
        
        return result
        
    except Exception as e:
        return {'success': False, 'error': str(e)}

# ============================================================================
# STREAMLIT APP
# ============================================================================

st.title("🏠 Florida Property Lookup")
st.markdown("**Multi-county property information tool**")

# Initialize session state
for key in ['api_address', 'api_city', 'api_zip', 'api_owner', 'api_land_use', 
            'api_zoning', 'api_flu', 'land_area_acres', 'land_area_sqft']:
    if key not in st.session_state:
        st.session_state[key] = ''

st.markdown("---")

# Input Section
col1, col2 = st.columns([1, 2])

with col1:
    county = st.selectbox("County", ["Pinellas", "Hillsborough"], key="county")

with col2:
    if county == "Pinellas":
        lookup_input = st.text_input(
            "Parcel ID",
            placeholder="19-31-17-73166-001-0010",
            help="Format: XX-XX-XX-XXXXX-XXX-XXXX",
            key="lookup_input"
        )
    else:
        lookup_input = st.text_input(
            "Folio Number",
            placeholder="109054.1000",
            help="Hillsborough County folio number (e.g., 109054.1000)",
            key="lookup_input"
        )

# Lookup Button
if st.button("🔍 Lookup Property", type="primary"):
    if not lookup_input:
        st.error("Please enter property information")
    else:
        if county == "Pinellas":
            is_valid, error_msg = validate_pinellas_parcel_id(lookup_input)
            if not is_valid:
                st.error(f"❌ {error_msg}")
            else:
                with st.spinner("Fetching Pinellas data..."):
                    result = lookup_pinellas(lookup_input)
                    
                    if result['success']:
                        st.session_state['api_address'] = result.get('address', '')
                        st.session_state['api_city'] = result.get('city', '')
                        st.session_state['api_zip'] = result.get('zip', '')
                        st.session_state['api_owner'] = result.get('owner', '')
                        st.session_state['api_land_use'] = result.get('land_use', '')
                        st.session_state['api_zoning'] = result.get('zoning', '')
                        st.session_state['api_flu'] = result.get('flu', '')
                        st.session_state['land_area_sqft'] = result.get('site_area_sqft', '')
                        st.session_state['land_area_acres'] = result.get('site_area_acres', '')
                        
                        st.success("✅ Pinellas data retrieved!")
                        st.rerun()
                    else:
                        st.error(f"❌ {result['error']}")
                        
        else:  # Hillsborough
            with st.spinner("Fetching Hillsborough data..."):
                result = lookup_hillsborough(lookup_input)
                
                if result['success']:
                    st.session_state['api_address'] = result.get('address', '')
                    st.session_state['api_city'] = result.get('city', 'Hillsborough County')
                    st.session_state['api_zip'] = result.get('zip', '')
                    st.session_state['api_owner'] = result.get('owner', '')
                    st.session_state['api_land_use'] = result.get('land_use', '')
                    st.session_state['api_zoning'] = result.get('zoning', '')
                    st.session_state['api_flu'] = result.get('flu', '')
                    st.session_state['land_area_acres'] = result.get('site_area_acres', '')
                    st.session_state['land_area_sqft'] = result.get('site_area_sqft', '')
                    
                    st.success("✅ Hillsborough data retrieved!")
                    st.rerun()
                else:
                    st.error(f"❌ {result['error']}")

# Results Section
st.markdown("---")
st.subheader("Property Information")

col_left, col_right = st.columns(2)

with col_left:
    st.text_input("Address", key='api_address', disabled=True)
    st.text_input("City", key='api_city', disabled=True)
    st.text_input("ZIP Code", key='api_zip', disabled=True)
    st.text_input("Owner", key='api_owner', disabled=True)

with col_right:
    st.text_input("Property Use", key='api_land_use', disabled=True)
    st.text_input("Zoning", key='api_zoning', disabled=True)
    st.text_input("Future Land Use", key='api_flu', disabled=True)
    st.text_input("Land Area (acres)", key='land_area_acres', disabled=True)

st.text_input("Land Area (sq ft)", key='land_area_sqft', disabled=True)

# Footer
st.markdown("---")
if st.session_state.get('api_address'):
    st.success(f"✅ Property data loaded for {county} County")
else:
    st.info("💡 Select county and enter Parcel ID or Folio to begin")
