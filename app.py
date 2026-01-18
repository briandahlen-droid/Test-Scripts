"""
Florida Property Lookup - Pinellas & Hillsborough Counties
Two-step lookup: (1) Basic parcel info, (2) Detailed zoning/FLU from GIS
"""
import streamlit as st
import re
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

st.set_page_config(page_title="FL Property Lookup", page_icon="🏠", layout="wide")

# ============================================================================
# FLORIDA DOR LAND USE CODES
# ============================================================================

DOR_LAND_USE_CODES = {
    '0000': 'Vacant Residential', '0001': 'Single Family', '0002': 'Mobile Homes',
    '0003': 'Multi-Family (10+ units)', '0004': 'Condominiums', '0005': 'Cooperatives',
    '0006': 'Retirement Homes', '0007': 'Miscellaneous Residential',
    '0008': 'Multi-Family (Less than 10 units)', '0009': 'Residential Common Elements/Areas',
    '0010': 'Vacant Commercial', '0011': 'Stores, One Story', '0012': 'Mixed Use Store/Office',
    '0013': 'Department Stores', '0014': 'Supermarkets', '0015': 'Regional Shopping Centers',
    '0016': 'Community Shopping Centers', '0017': 'Office Buildings, One Story',
    '0018': 'Office Buildings, Multi-Story', '0019': 'Professional Service Buildings',
    '0020': 'Airports, Terminals, Marinas', '0021': 'Restaurants, Cafeterias',
    '0022': 'Drive-In Restaurants', '0023': 'Financial Institutions',
    '0024': 'Insurance Company Offices', '0025': 'Repair Service Shops',
    '0026': 'Service Stations', '0027': 'Auto Sales, Auto Repair',
    '0028': 'Parking Lots, Mobile Home Parks', '0029': 'Wholesale Outlets',
    '0030': 'Florists, Greenhouses', '0031': 'Drive-In Theaters',
    '0032': 'Enclosed Theaters', '0033': 'Nightclubs, Bars',
    '0034': 'Bowling Alleys, Skating Rinks', '0035': 'Tourist Attractions',
    '0036': 'Camps', '0037': 'Race Tracks', '0038': 'Golf Courses', '0039': 'Hotels, Motels',
    '0040': 'Vacant Industrial', '0041': 'Light Manufacturing', '0042': 'Heavy Industrial',
    '0043': 'Lumber Yards, Sawmills', '0044': 'Packing Plants', '0045': 'Canneries, Bottlers',
    '0046': 'Other Food Processing', '0047': 'Mineral Processing', '0048': 'Warehousing',
    '0049': 'Open Storage', '0050': 'Improved Agricultural', '0051': 'Cropland Class I',
    '0052': 'Cropland Class II', '0053': 'Cropland Class III', '0054': 'Timberland (Site Index 90+)',
    '0055': 'Timberland (Site Index 80-89)', '0056': 'Timberland (Site Index 70-79)',
    '0057': 'Timberland (Site Index 60-69)', '0058': 'Timberland (Site Index 50-59)',
    '0059': 'Timberland (Unclassified)', '0060': 'Grazing Land Class I',
    '0061': 'Grazing Land Class II', '0062': 'Grazing Land Class III',
    '0063': 'Grazing Land Class IV', '0064': 'Grazing Land Class V',
    '0065': 'Grazing Land Class VI', '0066': 'Orchard Groves, Citrus',
    '0067': 'Poultry, Bees, Fish', '0068': 'Dairies, Feed Lots',
    '0069': 'Ornamentals, Misc Agricultural', '0070': 'Vacant Institutional',
    '0071': 'Churches', '0072': 'Private Schools/Colleges', '0073': 'Private Hospitals',
    '0074': 'Homes for the Aged', '0075': 'Non-Profit/Charitable',
    '0076': 'Mortuaries, Cemeteries', '0077': 'Clubs, Lodges',
    '0078': 'Sanitariums, Convalescent Homes', '0079': 'Cultural Organizations',
    '0080': 'Vacant Governmental', '0081': 'Military', '0082': 'Forests, Parks, Recreational',
    '0083': 'Public Schools', '0084': 'Colleges (Government)', '0085': 'Hospitals (Government)',
    '0086': 'County Government', '0087': 'State Government', '0088': 'Federal Government',
    '0089': 'Municipal Government', '0090': 'Leasehold Interests', '0091': 'Utility',
    '0092': 'Mining Lands', '0093': 'Subsurface Rights', '0094': 'Right-of-Way',
    '0095': 'Rivers and Lakes', '0096': 'Sewage Disposal, Waste Land',
    '0097': 'Outdoor Recreational', '0098': 'Centrally Assessed',
    '0099': 'Acreage Not Zoned Agricultural',
    '8400': 'SCHOOLS/COLLEGE', '8300': 'PUBLIC SCHOOLS', '8500': 'HOSPITALS (GOVERNMENT)',
}

def get_land_use_description(code_or_desc):
    """Convert DOR land use code to description. If already text, return as-is."""
    if not code_or_desc:
        return ''
    code_str = str(code_or_desc).strip()
    if any(c.isalpha() for c in code_str):
        return code_str
    if code_str in DOR_LAND_USE_CODES:
        return DOR_LAND_USE_CODES[code_str]
    code_padded = code_str.zfill(4)
    if code_padded in DOR_LAND_USE_CODES:
        return DOR_LAND_USE_CODES[code_padded]
    return code_str

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
    """Step 1: Get basic parcel info from Pinellas PCPAO API."""
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
            'site_area_acres': property_data.get('siteAreaAcres', '')
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}

# ============================================================================
# HILLSBOROUGH COUNTY
# ============================================================================

def lookup_hillsborough(folio):
    """Step 1: Get basic parcel info from SWFWMD parcel service."""
    try:
        parcel_url = "https://www25.swfwmd.state.fl.us/arcgis12/rest/services/BaseVector/parcel_search/MapServer/7/query"
        
        # Try different folio formats
        folio_formats = [
            folio,
            folio.replace('.', ''),
            folio.split('.')[0] if '.' in folio else folio,
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
            return {'success': False, 'error': f'Folio {folio} not found'}
        
        attrs = parcel_data['features'][0]['attributes']
        
        # Handle acres
        acres = attrs.get('ACRES') or attrs.get('AREANO')
        if acres and acres not in [None, 'None', '']:
            acres_str = f"{float(acres):.2f}" if isinstance(acres, (int, float)) else str(acres)
        else:
            acres_str = ''
        
        # Get land use - prefer description, fallback to code lookup
        land_use_raw = attrs.get('PARUSEDESC', '')
        if not land_use_raw:
            dor_code = attrs.get('DORUSECODE') or attrs.get('DOR4CODE')
            land_use_raw = get_land_use_description(dor_code) if dor_code else ''
        
        return {
            'success': True,
            'address': attrs.get('SITEADD', attrs.get('SITUSADD1', '')),
            'city': attrs.get('SCITY', 'Tampa'),
            'zip': attrs.get('SZIP', ''),
            'owner': attrs.get('OWNNAME', attrs.get('OWNERNAME', '')),
            'land_use': land_use_raw,
            'site_area_acres': acres_str,
            'site_area_sqft': '',
            'zoning': attrs.get('ZONING', ''),
            'geometry': parcel_data['features'][0].get('geometry')
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}

def lookup_hillsborough_zoning_flu(address):
    """Step 2: Get detailed zoning and FLU from Hillsborough GIS layers."""
    try:
        # Geocode address
        geocode_url = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
        geocode_params = {
            'SingleLine': address + ", Hillsborough County, FL",
            'f': 'json',
            'outSR': '102100',  # Web Mercator for zoning layer
            'maxLocations': 1
        }
        
        geocode_resp = requests.get(geocode_url, params=geocode_params, timeout=10)
        geocode_data = geocode_resp.json()
        
        if not geocode_data.get('candidates'):
            return {'success': False, 'error': 'Could not geocode address'}
        
        location = geocode_data['candidates'][0]['location']
        x, y = location['x'], location['y']
        
        result = {'success': True}
        
        # Query zoning layer (Layer 0 - correct layer!)
        zoning_url = "https://maps.hillsboroughcounty.org/arcgis/rest/services/DSD_Viewer_Services/DSD_Viewer_Zoning_Regulatory/MapServer/0/query"
        zoning_params = {
            'geometry': f'{x},{y}',
            'geometryType': 'esriGeometryPoint',
            'spatialRel': 'esriSpatialRelIntersects',
            'outFields': 'NZONE,NZONE_DESC',
            'returnGeometry': 'false',
            'f': 'json',
            'inSR': '102100'
        }
        
        zoning_resp = requests.get(zoning_url, params=zoning_params, timeout=10)
        zoning_data = zoning_resp.json()
        
        if zoning_data.get('features'):
            attrs = zoning_data['features'][0]['attributes']
            result['zoning_code'] = attrs.get('NZONE', '')
            result['zoning_description'] = attrs.get('NZONE_DESC', '')
        
        # Query FLU layer
        flu_url = "https://maps.hillsboroughcounty.org/arcgis/rest/services/DSD_Viewer_Services/DSD_Viewer_Planning/MapServer/1/query"
        flu_params = {
            'geometry': f'{x},{y}',
            'geometryType': 'esriGeometryPoint',
            'spatialRel': 'esriSpatialRelIntersects',
            'outFields': 'FLUE',
            'returnGeometry': 'false',
            'f': 'json',
            'inSR': '102100'
        }
        
        flu_resp = requests.get(flu_url, params=flu_params, timeout=10)
        flu_data = flu_resp.json()
        
        if flu_data.get('features'):
            result['future_land_use'] = flu_data['features'][0]['attributes'].get('FLUE', '')
        
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
st.subheader("Step 1: Parcel Lookup")

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
            help="Hillsborough County folio number",
            key="lookup_input"
        )

# Step 1: Primary Lookup Button
if st.button("🔍 Lookup Property Info", type="primary"):
    if not lookup_input:
        st.error("Please enter property information")
    else:
        if county == "Pinellas":
            is_valid, error_msg = validate_pinellas_parcel_id(lookup_input)
            if not is_valid:
                st.error(f"❌ {error_msg}")
            else:
                with st.spinner("Fetching Pinellas data from PCPAO..."):
                    result = lookup_pinellas(lookup_input)
                    
                    if result['success']:
                        st.session_state['api_address'] = result.get('address', '')
                        st.session_state['api_city'] = result.get('city', '')
                        st.session_state['api_zip'] = result.get('zip', '')
                        st.session_state['api_owner'] = result.get('owner', '')
                        st.session_state['api_land_use'] = result.get('land_use', '')
                        st.session_state['api_zoning'] = result.get('zoning', '')
                        st.session_state['api_flu'] = ''  # Will be filled by Step 2
                        st.session_state['land_area_sqft'] = result.get('site_area_sqft', '')
                        st.session_state['land_area_acres'] = result.get('site_area_acres', '')
                        
                        st.success("✅ Property data retrieved!")
                        st.rerun()
                    else:
                        st.error(f"❌ {result['error']}")
                        
        else:  # Hillsborough
            with st.spinner("Fetching Hillsborough parcel data..."):
                result = lookup_hillsborough(lookup_input)
                
                if result['success']:
                    st.session_state['api_address'] = result.get('address', '')
                    st.session_state['api_city'] = result.get('city', 'Hillsborough County')
                    st.session_state['api_zip'] = result.get('zip', '')
                    st.session_state['api_owner'] = result.get('owner', '')
                    st.session_state['api_land_use'] = result.get('land_use', '')
                    st.session_state['api_zoning'] = result.get('zoning', '')  # Basic zoning
                    st.session_state['api_flu'] = ''  # Will be filled by Step 2
                    st.session_state['land_area_acres'] = result.get('site_area_acres', '')
                    st.session_state['land_area_sqft'] = ''
                    
                    st.success("✅ Property data retrieved!")
                    st.rerun()
                else:
                    st.error(f"❌ {result['error']}")

# Step 2: Secondary Zoning/FLU Lookup Button (only show after address is retrieved)
if st.session_state.get('api_address'):
    st.markdown("---")
    st.subheader("Step 2: Detailed Zoning & Future Land Use Lookup")
    st.caption("🔍 Query GIS layers for detailed zoning and Future Land Use information")
    
    if st.button("🗺️ Lookup Zoning & Future Land Use", type="secondary"):
        address = st.session_state.get('api_address', '')
        
        if county == "Hillsborough":
            with st.spinner(f"Fetching zoning/FLU data for {address}..."):
                zoning_result = lookup_hillsborough_zoning_flu(address)
                
                if zoning_result.get('success'):
                    # Update zoning with detailed info
                    if zoning_result.get('zoning_code'):
                        if zoning_result.get('zoning_description'):
                            st.session_state['api_zoning'] = f"{zoning_result.get('zoning_code')} - {zoning_result.get('zoning_description')}"
                        else:
                            st.session_state['api_zoning'] = zoning_result.get('zoning_code', '')
                    
                    # Update FLU
                    if zoning_result.get('future_land_use'):
                        st.session_state['api_flu'] = zoning_result.get('future_land_use', '')
                    
                    st.success(f"✅ Zoning/FLU data updated from Hillsborough County GIS!")
                    st.rerun()
                else:
                    st.error(f"❌ {zoning_result.get('error', 'Unable to fetch zoning data')}")

st.markdown("---")

# Results Section
st.subheader("Property Information Results")

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

# Status Summary
st.markdown("---")
st.subheader("Status")

if st.session_state.get('api_address'):
    st.success(f"✅ Step 1: Parcel data retrieved for {county} County")
    
    if st.session_state.get('api_flu'):
        st.success("✅ Step 2: Zoning/FLU data updated from GIS layers")
    else:
        st.info("ℹ️ Click 'Lookup Zoning & Future Land Use' button to get detailed zoning data")
else:
    st.info("💡 Enter Parcel ID or Folio and click 'Lookup Property Info' to start")
