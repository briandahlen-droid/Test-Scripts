"""
Multi-County Property Lookup App
Supports: Pinellas County and Hillsborough County
User inputs Folio/Parcel ID + County → Auto-fills all fields
"""
import streamlit as st
import re
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

st.set_page_config(page_title="FL Property Lookup", page_icon="🏠", layout="wide")

# ============================================================================
# PINELLAS COUNTY FUNCTIONS
# ============================================================================

PINELLAS_CITY_MAP = {
    'SP': 'St. Petersburg', 'ST PETERSBURG': 'St. Petersburg', 'ST. PETERSBURG': 'St. Petersburg',
    'CLEARWATER': 'Clearwater', 'CW': 'Clearwater', 'LARGO': 'Largo', 'LA': 'Largo',
    'PINELLAS PARK': 'Pinellas Park', 'PP': 'Pinellas Park', 'DUNEDIN': 'Dunedin',
    'TARPON SPRINGS': 'Tarpon Springs', 'TS': 'Tarpon Springs', 'SEMINOLE': 'Seminole',
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
    """Lookup Pinellas property via PCPAO API."""
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
# HILLSBOROUGH COUNTY FUNCTIONS
# ============================================================================

def lookup_hillsborough(folio):
    """
    Lookup Hillsborough property by querying GIS layers with folio ID.
    Returns zoning and future land use based on parcel geometry.
    """
    try:
        # Step 1: Query parcel layer to get geometry
        # Use Hillsborough County's property appraiser parcel layer
        # The folio field varies - try common field names
        parcel_url = "https://maps.hillsboroughcounty.org/arcgis/rest/services/DSD_Viewer_Services/DSD_Viewer_Zoning_Regulatory/MapServer/0/query"
        
        # Try to find the parcel by folio
        parcel_params = {
            'where': f"FOLIO = '{folio}' OR PARCEL_ID = '{folio}' OR FOLIO_NO = '{folio}'",
            'outFields': '*',
            'returnGeometry': 'true',
            'f': 'json',
            'outSR': '102659'
        }
        
        parcel_resp = requests.get(parcel_url, params=parcel_params, timeout=10)
        parcel_data = parcel_resp.json()
        
        if not parcel_data.get('features'):
            # Folio not found in parcel layer - return basic error
            return {
                'success': False,
                'error': 'Folio not found. Note: Hillsborough lookups require valid folio from tax records.'
            }
        
        # Get centroid of parcel
        parcel_feature = parcel_data['features'][0]
        geom = parcel_feature['geometry']
        
        # Calculate centroid if polygon
        if 'rings' in geom:
            # Simple centroid calculation
            ring = geom['rings'][0]
            x_coords = [pt[0] for pt in ring]
            y_coords = [pt[1] for pt in ring]
            x = sum(x_coords) / len(x_coords)
            y = sum(y_coords) / len(y_coords)
        else:
            x = geom.get('x', 0)
            y = geom.get('y', 0)
        
        result = {'success': True}
        
        # Get address from parcel attributes if available
        attrs = parcel_feature.get('attributes', {})
        result['address'] = attrs.get('SITUS_ADDRESS', attrs.get('ADDRESS', ''))
        result['owner'] = attrs.get('OWNER_NAME', '')
        result['land_use'] = attrs.get('LAND_USE', '')
        result['site_area_acres'] = attrs.get('ACRES', attrs.get('ACREAGE', ''))
        
        # Step 2: Query zoning layer with point
        zoning_url = "https://maps.hillsboroughcounty.org/arcgis/rest/services/DSD_Viewer_Services/DSD_Viewer_Zoning_Regulatory/FeatureServer/1/query"
        zoning_params = {
            'geometry': f'{x},{y}',
            'geometryType': 'esriGeometryPoint',
            'spatialRel': 'esriSpatialRelIntersects',
            'outFields': 'NZONE,NZONE_DESC',
            'returnGeometry': 'false',
            'f': 'json',
            'inSR': '102659'
        }
        
        zoning_resp = requests.get(zoning_url, params=zoning_params, timeout=10)
        zoning_data = zoning_resp.json()
        
        if zoning_data.get('features'):
            z_attrs = zoning_data['features'][0]['attributes']
            result['zoning'] = z_attrs.get('NZONE', '')
            result['zoning_desc'] = z_attrs.get('NZONE_DESC', '')
        
        # Step 3: Query FLU layer
        flu_url = "https://maps.hillsboroughcounty.org/arcgis/rest/services/DSD_Viewer_Services/DSD_Viewer_Planning/MapServer/1/query"
        flu_params = {
            'geometry': f'{x},{y}',
            'geometryType': 'esriGeometryPoint',
            'spatialRel': 'esriSpatialRelIntersects',
            'outFields': 'FLUE',
            'returnGeometry': 'false',
            'f': 'json',
            'inSR': '102659'
        }
        
        flu_resp = requests.get(flu_url, params=flu_params, timeout=10)
        flu_data = flu_resp.json()
        
        if flu_data.get('features'):
            result['flu'] = flu_data['features'][0]['attributes'].get('FLUE', '')
        
        return result
        
    except Exception as e:
        return {'success': False, 'error': str(e)}

# ============================================================================
# STREAMLIT APP
# ============================================================================

st.title("🏠 Florida Property Lookup")
st.markdown("**Multi-county property lookup tool** • Pinellas & Hillsborough Counties")

# Initialize session state
if 'api_address' not in st.session_state:
    st.session_state['api_address'] = ''
if 'api_city' not in st.session_state:
    st.session_state['api_city'] = ''
if 'api_zip' not in st.session_state:
    st.session_state['api_zip'] = ''
if 'api_owner' not in st.session_state:
    st.session_state['api_owner'] = ''
if 'api_land_use' not in st.session_state:
    st.session_state['api_land_use'] = ''
if 'api_zoning' not in st.session_state:
    st.session_state['api_zoning'] = ''
if 'api_flu' not in st.session_state:
    st.session_state['api_flu'] = ''
if 'land_area_acres' not in st.session_state:
    st.session_state['land_area_acres'] = ''
if 'land_area_sqft' not in st.session_state:
    st.session_state['land_area_sqft'] = ''

# Input Section
st.subheader("Property Information Input")

col1, col2 = st.columns(2)

with col1:
    county = st.selectbox(
        "County",
        options=["Pinellas", "Hillsborough"],
        key="county_selector"
    )

with col2:
    if county == "Pinellas":
        parcel_input = st.text_input(
            "Parcel ID",
            placeholder="XX-XX-XX-XXXXX-XXX-XXXX",
            help="Format: 19-31-17-73166-001-0010",
            key="parcel_input"
        )
    else:
        parcel_input = st.text_input(
            "Folio Number",
            placeholder="123456.0000",
            help="Hillsborough County folio number",
            key="parcel_input"
        )

# Lookup Button
if st.button("🔍 Lookup Property", type="primary"):
    if not parcel_input:
        st.error("Please enter a parcel ID or folio number")
    else:
        if county == "Pinellas":
            is_valid, error_msg = validate_pinellas_parcel_id(parcel_input)
            if not is_valid:
                st.error(f"❌ {error_msg}")
            else:
                with st.spinner("Fetching Pinellas County data..."):
                    result = lookup_pinellas(parcel_input)
                    
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
                        
                        st.success("✅ Pinellas County data retrieved!")
                        st.rerun()
                    else:
                        st.error(f"❌ {result['error']}")
                        
        else:  # Hillsborough
            with st.spinner("Fetching Hillsborough County data..."):
                result = lookup_hillsborough(parcel_input)
                
                if result['success']:
                    st.session_state['api_address'] = result.get('address', '')
                    st.session_state['api_city'] = 'Hillsborough County'
                    st.session_state['api_zip'] = ''
                    st.session_state['api_owner'] = result.get('owner', '')
                    st.session_state['api_land_use'] = result.get('land_use', '')
                    
                    # Format zoning
                    zoning_code = result.get('zoning', '')
                    zoning_desc = result.get('zoning_desc', '')
                    if zoning_code and zoning_desc:
                        st.session_state['api_zoning'] = f"{zoning_code} - {zoning_desc}"
                    elif zoning_code:
                        st.session_state['api_zoning'] = zoning_code
                    else:
                        st.session_state['api_zoning'] = ''
                    
                    st.session_state['api_flu'] = result.get('flu', '')
                    st.session_state['land_area_acres'] = result.get('site_area_acres', '')
                    st.session_state['land_area_sqft'] = ''
                    
                    st.success("✅ Hillsborough County data retrieved!")
                    st.rerun()
                else:
                    st.error(f"❌ {result['error']}")

# Results Section
st.markdown("---")
st.subheader("Property Data Results")

col_left, col_right = st.columns(2)

with col_left:
    st.text_input("City", key='api_city', disabled=True)
    st.text_input("Address", key='api_address', disabled=True)
    st.text_input("ZIP Code", key='api_zip', disabled=True)
    st.text_input("Property Use", key='api_land_use', disabled=True)

with col_right:
    st.text_input("Owner", key='api_owner', disabled=True)
    st.text_input("Zoning", key='api_zoning', disabled=True)
    st.text_input("Future Land Use", key='api_flu', disabled=True)
    st.text_input("Land Area (acres)", key='land_area_acres', disabled=True)

st.text_input("Land Area (sq ft)", key='land_area_sqft', disabled=True)

# Footer
st.markdown("---")
if st.session_state.get('api_address'):
    st.success(f"✅ Property data loaded for {county} County")
else:
    st.info("ℹ️ Enter a parcel ID/folio and click 'Lookup Property' to start")
