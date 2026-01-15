"""
Comprehensive Pinellas County Property Lookup Test App
Tests: City auto-fill, Address, Property Use, Future Land Use, Zoning, Land Area
"""
import streamlit as st
import re
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

st.set_page_config(page_title="Pinellas Property Lookup Test", page_icon="🏠", layout="wide")

# ============================================================================
# ST. PETERSBURG ZONING/FLU LOOKUP TABLES
# ============================================================================

# St. Petersburg Future Land Use code to description mapping
FLU_DESCRIPTIONS = {
    'CBD': 'Central Business District',
    'CRD': 'Community Redevelopment District',
    'PR-R': 'Planned Redevelopment Residential',
    'PR-MU': 'Planned Redevelopment Mixed-Use',
    'PR-C': 'Planned Redevelopment Commercial',
    'RU': 'Residential Urban',
    'RL': 'Residential Low',
    'RLM': 'Residential Low Medium',
    'RM': 'Residential Medium',
    'RH': 'Residential High',
    'RVH': 'Residential Very High',
    'R/OL': 'Residential/Office Limited',
    'R/OG': 'Residential/Office General',
    'RFH': 'Resort Facilities High',
    'CG': 'Commercial General',
    'IL': 'Industrial Limited',
    'IG': 'Industrial General',
    'P': 'Preservation',
    'R/OS': 'Recreation/Open Space',
    'I': 'Institutional',
    'T/U': 'Transportation/Utility'
}

# St. Petersburg Zoning code to description mapping
ZONING_DESCRIPTIONS = {
    'NT-1': 'NEIGHBORHOOD TRADITIONAL SINGLE-FAMILY-1',
    'NT-2': 'NEIGHBORHOOD TRADITIONAL SINGLE-FAMILY-2',
    'NT-3': 'NEIGHBORHOOD TRADITIONAL SINGLE-FAMILY-3',
    'NT-4': 'NEIGHBORHOOD TRADITIONAL SINGLE-FAMILY-4',
    'NS-1': 'NEIGHBORHOOD SUBURBAN SINGLE-FAMILY-1',
    'NS-2': 'NEIGHBORHOOD SUBURBAN SINGLE-FAMILY-2',
    'NSM-1': 'NEIGHBORHOOD SUBURBAN MULTI-FAMILY-1',
    'NSM-2': 'NEIGHBORHOOD SUBURBAN MULTI-FAMILY-2',
    'NPUD-1': 'NEIGHBORHOOD PLANNED UNIT DEVELOPMENT-1',
    'NPUD-2': 'NEIGHBORHOOD PLANNED UNIT DEVELOPMENT-2',
    'NPUD-3': 'NEIGHBORHOOD PLANNED UNIT DEVELOPMENT-3',
    'NTM-1': 'NEIGHBORHOOD TRADITIONAL MIXED-RESIDENTIAL-1',
    'NMH': 'NEIGHBORHOOD SUBURBAN MOBILE HOME',
    'NSE': 'NEIGHBORHOOD SUBURBAN SINGLE-FAMILY',
    'DC-C': 'DOWNTOWN CENTER-CORE',
    'DC-1': 'DOWNTOWN CENTER-1',
    'DC-2': 'DOWNTOWN CENTER-2',
    'DC-3': 'DOWNTOWN CENTER-3',
    'DC-P': 'DOWNTOWN CENTER-PRESERVATION',
    'CRT-1': 'CORRIDOR RESIDENTIAL TRADITIONAL-1',
    'CRT-2': 'CORRIDOR RESIDENTIAL TRADITIONAL-2',
    'CRS-1': 'CORRIDOR RESIDENTIAL SUBURBAN-1',
    'CRS-2': 'CORRIDOR RESIDENTIAL SUBURBAN-2',
    'CCT-1': 'CORRIDOR COMMERCIAL TRADITIONAL-1',
    'CCT-2': 'CORRIDOR COMMERCIAL TRADITIONAL-2',
    'CCS-1': 'CORRIDOR COMMERCIAL SUBURBAN-1',
    'CCS-2': 'CORRIDOR COMMERCIAL SUBURBAN-2',
    'RC-1': 'RETAIL CENTER-1',
    'RC-2': 'RETAIL CENTER-2',
    'RC-3': 'RETAIL CENTER-3',
    'EC-1': 'EMPLOYMENT CENTERS-1',
    'EC-2': 'EMPLOYMENT CENTERS-2',
    'IS': 'INDUSTRIAL SUBURBAN',
    'IT': 'INDUSTRIAL TRADITIONAL',
    'IC': 'INSTITUTIONAL CENTER',
    'P': 'PRESERVATION',
    'WATER': 'WATER'
}

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def validate_parcel_id(parcel_id: str):
    """Validate parcel/folio ID input."""
    if not parcel_id:
        return False, "Parcel ID cannot be empty"
    
    if len(parcel_id) > 30:
        return False, "Parcel ID must be 30 characters or less"
    
    # Allowlist: only alphanumeric, dashes, spaces, periods
    if not re.match(r'^[A-Za-z0-9\-\s\.]+$', parcel_id):
        return False, "Invalid characters in parcel ID"
    
    return True, ""

def sanitize_for_sql(value: str) -> str:
    """Sanitize string for use in SQL WHERE clause."""
    return value.strip().replace("'", "''")

def strip_dor_code(land_use_text):
    """Remove Florida DOR code prefix from land use descriptions."""
    if not land_use_text:
        return ''
    
    text = land_use_text.strip()
    
    if text and text[0].isdigit():
        parts = text.split(' ', 1)
        if len(parts) > 1:
            return parts[1].strip()
    
    return text

# ============================================================================
# HTTP SESSION WITH RETRY LOGIC
# ============================================================================

@st.cache_resource
def get_resilient_session():
    """Create HTTP session with automatic retry logic."""
    session = requests.Session()
    
    retry_strategy = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )
    
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session

# ============================================================================
# PCPAO API LOOKUP (THE KEY FUNCTION!)
# ============================================================================

def scrape_pinellas_property(parcel_id):
    """
    Query Pinellas County Property Appraiser searchProperty API.
    This is the backend API that the PCPAO website uses.
    """
    session = get_resilient_session()
    
    url = "https://www.pcpao.gov/dal/quicksearch/searchProperty"
    
    # Normalize Pinellas parcel ID format
    normalized_parcel = parcel_id.strip()
    
    # If no dashes and 18 digits, add dashes in Pinellas format
    if '-' not in normalized_parcel and len(normalized_parcel) == 18:
        # Format: XX-XX-XX-XXXXX-XXX-XXXX
        normalized_parcel = f"{normalized_parcel[0:2]}-{normalized_parcel[2:4]}-{normalized_parcel[4:6]}-{normalized_parcel[6:11]}-{normalized_parcel[11:14]}-{normalized_parcel[14:18]}"
    
    # Build the POST data - mimics the DataTables request format
    payload = {
        'draw': '1',
        'start': '0',
        'length': '10',
        'search[value]': '',
        'search[regex]': 'false',
        'input': normalized_parcel,
        'searchsort': 'parcel_number',
        'url': 'https://www.pcpao.gov'
    }
    
    # Add column definitions (required by DataTables API)
    for i in range(11):
        payload[f'columns[{i}][data]'] = str(i)
        payload[f'columns[{i}][name]'] = ''
        payload[f'columns[{i}][searchable]'] = 'true'
        payload[f'columns[{i}][orderable]'] = 'true' if i >= 2 else 'false'
        payload[f'columns[{i}][search][value]'] = ''
        payload[f'columns[{i}][search][regex]'] = 'false'
    
    try:
        response = session.post(url, data=payload, timeout=15)
        response.raise_for_status()
        
        data = response.json()
        
        # Check if we got results
        if data.get('recordsTotal', 0) == 0:
            return {'success': False, 'error': 'Parcel not found in PCPAO database'}
        
        # Parse the HTML response within the JSON
        if not data.get('data') or len(data['data']) == 0:
            return {'success': False, 'error': 'No property data returned'}
        
        # Get first result
        result_row = data['data'][0]
        
        # Extract data from HTML snippets
        # Column 2: Owner name
        owner_html = result_row[2] if len(result_row) > 2 else ''
        owner_soup = BeautifulSoup(owner_html, 'lxml')
        owner = owner_soup.get_text(strip=True)
        
        # Column 5: Address
        address_html = result_row[5] if len(result_row) > 5 else ''
        address_soup = BeautifulSoup(address_html, 'lxml')
        address = address_soup.get_text(strip=True)
        
        # Column 7: Property Use / DOR Code
        use_html = result_row[7] if len(result_row) > 7 else ''
        use_soup = BeautifulSoup(use_html, 'lxml')
        property_use = use_soup.get_text(strip=True)
        
        # Column 8: Legal Description
        legal_html = result_row[8] if len(result_row) > 8 else ''
        legal_soup = BeautifulSoup(legal_html, 'lxml')
        legal_desc = legal_soup.get_text(strip=True)
        
        # Extract city from address
        city = ''
        if 'CLEARWATER' in address.upper():
            city = 'Clearwater'
        elif 'ST. PETERSBURG' in address.upper() or 'ST PETERSBURG' in address.upper():
            city = 'St. Petersburg'
        elif 'LARGO' in address.upper():
            city = 'Largo'
        elif 'PINELLAS PARK' in address.upper():
            city = 'Pinellas Park'
        else:
            city = 'Unincorporated Pinellas'
        
        # Get acreage from detail page
        sqft = None
        acres = None
        
        try:
            # Strap transformation: swap first and third segments
            parts = normalized_parcel.split('-')
            if len(parts) == 6:
                parts[0], parts[2] = parts[2], parts[0]
                strap = ''.join(parts)
            else:
                strap = normalized_parcel.replace('-', '')
            
            # Build detail URL
            detail_url = (
                f"https://www.pcpao.gov/property-details?"
                f"s={strap}&"
                f"input={normalized_parcel}&"
                f"search_option=parcel_number"
            )
            
            # Fetch and parse
            html = session.get(detail_url, timeout=30).text
            soup = BeautifulSoup(html, "html.parser")
            text = soup.get_text(" ", strip=True)
            
            # Match pattern: "Land Area: ≅ 59,560 sf | ≅ 1.36 acres"
            m = re.search(r"Land Area:\s*≅\s*([\d,]+)\s*sf\s*\|\s*≅\s*([\d.]+)\s*acres", text)
            if m:
                sqft = int(m.group(1).replace(",", ""))
                acres = float(m.group(2))
        except Exception:
            pass  # If detail page fails, sqft and acres remain None
        
        return {
            'success': True,
            'address': address,
            'city': city,
            'zip': '',
            'owner': owner,
            'land_use': strip_dor_code(property_use),
            'zoning': 'Contact City/County for zoning info',
            'site_area_sqft': f"{sqft:,}" if sqft else None,
            'site_area_acres': f"{acres:.2f}" if acres else None,
            'legal_description': legal_desc,
            'error': None
        }
    
    except Exception as e:
        return {'success': False, 'error': f'Error querying PCPAO API: {str(e)}'}

# ============================================================================
# ST. PETERSBURG ZONING LAYER LOOKUP
# ============================================================================

def lookup_pinellas_zoning(city_name, address):
    """
    Lookup zoning for Pinellas County using the property address.
    For St. Petersburg: Queries St. Pete zoning layers using spatial query.
    
    Args:
        city_name: City name (e.g., "St. Petersburg")
        address: Property address (e.g., "200 CENTRAL AVE")
        
    Returns:
        dict with zoning_code, zoning_description, future_land_use, future_land_use_description
    """
    if not address:
        return {'success': False, 'error': 'Address required for zoning lookup'}
    
    session = get_resilient_session()
    
    # St. Petersburg zoning lookup
    if 'St. Petersburg' in city_name or 'St Petersburg' in city_name:
        try:
            # Step 1: Geocode the address to get coordinates
            search_url = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
            geocode_params = {
                'SingleLine': f"{address}, St. Petersburg, FL",
                'f': 'json',
                'outFields': '*'
            }
            
            geocode_response = session.get(search_url, params=geocode_params, timeout=15)
            geocode_data = geocode_response.json()
            
            if not geocode_data.get('candidates'):
                return {'success': False, 'error': 'Could not geocode address'}
            
            # Get coordinates from first candidate
            location = geocode_data['candidates'][0]['location']
            x, y = location['x'], location['y']
            
            # Step 2: Query zoning layer with coordinates (spatial query)
            zoning_url = "https://egis.stpete.org/arcgis/rest/services/ServicesDSD/Zoning/MapServer/2/query"
            zoning_params = {
                'geometry': f"{x},{y}",
                'geometryType': 'esriGeometryPoint',
                'inSR': '4326',  # WGS84 from geocoder
                'spatialRel': 'esriSpatialRelIntersects',
                'outFields': 'ZONECLASS,ZONEDESC',
                'returnGeometry': 'false',
                'f': 'json'
            }
            
            zoning_response = session.get(zoning_url, params=zoning_params, timeout=15)
            zoning_data = zoning_response.json()
            
            if zoning_data.get('features'):
                attrs = zoning_data['features'][0]['attributes']
                zoning_code = attrs.get('ZONECLASS', '')
                zoning_desc = ZONING_DESCRIPTIONS.get(zoning_code, attrs.get('ZONEDESC', ''))
                
                # Step 3: Query Future Land Use layer with same coordinates
                flu_url = "https://egis.stpete.org/arcgis/rest/services/ServicesDSD/Zoning/MapServer/4/query"
                flu_params = {
                    'geometry': f"{x},{y}",
                    'geometryType': 'esriGeometryPoint',
                    'inSR': '4326',
                    'spatialRel': 'esriSpatialRelIntersects',
                    'outFields': '*',
                    'returnGeometry': 'false',
                    'f': 'json'
                }
                
                flu_response = session.get(flu_url, params=flu_params, timeout=15)
                flu_data = flu_response.json()
                flu_code = ''
                flu_desc = ''
                if flu_data.get('features'):
                    flu_attrs = flu_data['features'][0].get('attributes', {})
                    flu_code = flu_attrs.get('LANDUSECODE', '')
                    flu_desc = FLU_DESCRIPTIONS.get(flu_code, '')
                
                return {
                    'success': True,
                    'zoning_code': zoning_code,
                    'zoning_description': zoning_desc,
                    'future_land_use': flu_code,
                    'future_land_use_description': flu_desc
                }
            else:
                return {'success': False, 'error': 'No zoning found at address location'}
                
        except Exception as e:
            return {'success': False, 'error': f'Zoning lookup error: {str(e)}'}
    
    # Other cities (not St. Petersburg)
    return {
        'success': True,
        'zoning_code': 'Contact City/County for zoning',
        'zoning_description': None,
        'future_land_use': None,
        'future_land_use_description': None,
        'note': 'City-specific zoning data not available via API'
    }

# ============================================================================
# STREAMLIT UI
# ============================================================================

st.title("🏠 Pinellas County Property Lookup - Comprehensive Test")
st.caption("Testing all property data fields: City, Address, Owner, Property Use, Zoning, Land Area")
st.markdown("---")

# Input Section
st.subheader("Input")
parcel_id_input = st.text_input(
    "Parcel ID",
    value="19-31-17-73166-001-0010",
    placeholder="e.g., 19-31-17-73166-001-0010",
    help="Pinellas County parcel ID with dashes",
    key="parcel_input"
)

# Lookup Buttons
if st.button("🔍 Lookup Property Info", type="primary"):
    if not parcel_id_input:
        st.error("Please enter a parcel ID")
    else:
        # Validate
        is_valid, error_msg = validate_parcel_id(parcel_id_input)
        if not is_valid:
            st.error(f"❌ {error_msg}")
        else:
            with st.spinner("Fetching property data from PCPAO API..."):
                result = scrape_pinellas_property(parcel_id_input)
                
                if result['success']:
                    # Store basic property info
                    st.session_state['api_address'] = result.get('address', '')
                    st.session_state['api_city'] = result.get('city', '')
                    st.session_state['api_zip'] = result.get('zip', '')
                    st.session_state['api_owner'] = result.get('owner', '')
                    st.session_state['api_land_use'] = result.get('land_use', '')
                    st.session_state['api_zoning'] = result.get('zoning', '')  # Fallback zoning
                    st.session_state['land_area_sqft'] = result.get('site_area_sqft', '')
                    st.session_state['land_area_acres'] = result.get('site_area_acres', '')
                    st.session_state['api_flu'] = ''  # Will be filled by zoning lookup button
                    
                    st.success("✅ Property data retrieved successfully!")
                    st.rerun()
                else:
                    st.error(f"❌ {result['error']}")

# Second button for zoning/FLU lookup (for St. Petersburg only)
if st.session_state.get('api_address'):
    st.markdown("---")
    st.caption("🔍 **Optional:** For St. Petersburg properties, lookup detailed zoning and Future Land Use from GIS layers")
    
    if st.button("🗺️ Lookup Zoning & Future Land Use", type="secondary"):
        city = st.session_state.get('api_city', '')
        address = st.session_state.get('api_address', '')
        
        if not address:
            st.error("❌ Please run Property Lookup first to get the address")
        else:
            with st.spinner(f"Fetching zoning data for {address} in {city}..."):
                zoning_result = lookup_pinellas_zoning(city, address)
                
                if zoning_result.get('success'):
                    # Update zoning with detailed info
                    if zoning_result.get('zoning_code'):
                        if zoning_result.get('zoning_description'):
                            st.session_state['api_zoning'] = f"{zoning_result.get('zoning_code')} - {zoning_result.get('zoning_description')}"
                        else:
                            st.session_state['api_zoning'] = zoning_result.get('zoning_code', '')
                    
                    # Update FLU
                    if zoning_result.get('future_land_use'):
                        if zoning_result.get('future_land_use_description'):
                            st.session_state['api_flu'] = f"{zoning_result.get('future_land_use')} - {zoning_result.get('future_land_use_description')}"
                        else:
                            st.session_state['api_flu'] = zoning_result.get('future_land_use', '')
                    
                    st.success(f"✅ Zoning data updated!")
                    st.rerun()
                else:
                    if 'St. Petersburg' in city or 'St Petersburg' in city:
                        st.error(f"❌ {zoning_result.get('error', 'Unable to fetch zoning data')}")
                    else:
                        st.info(f"ℹ️ City-specific zoning data not available via API for {city}")

st.markdown("---")

# Results Section
st.subheader("Results - All Property Data")
st.caption("These fields auto-fill after successful lookup")

col_left, col_right = st.columns(2)

with col_left:
    st.text_input(
        "City (auto-filled)",
        key='api_city',
        placeholder="Will auto-fill from PCPAO",
        help="City name from PCPAO API"
    )
    
    st.text_input(
        "Address (auto-filled)",
        key='api_address',
        placeholder="Will auto-fill from PCPAO",
        help="Property address from PCPAO API"
    )
    
    st.text_input(
        "ZIP Code (auto-filled)",
        key='api_zip',
        placeholder="Will auto-fill from PCPAO",
        help="ZIP code from PCPAO API"
    )
    
    st.text_input(
        "Property Use (auto-filled)",
        key='api_land_use',
        placeholder="Will auto-fill from PCPAO",
        help="Property Appraiser land use classification"
    )

with col_right:
    st.text_input(
        "Owner (auto-filled)",
        key='api_owner',
        placeholder="Will auto-fill from PCPAO",
        help="Property owner from PCPAO API"
    )
    
    st.text_input(
        "Zoning (auto-filled)",
        key='api_zoning',
        placeholder="Will auto-fill from GIS layers",
        help="Zoning district from St. Pete GIS layers"
    )
    
    st.text_input(
        "Future Land Use (auto-filled)",
        key='api_flu',
        placeholder="Will auto-fill from GIS layers",
        help="Future Land Use from St. Pete GIS layers"
    )
    
    st.text_input(
        "Land Area (acres)",
        key='land_area_acres',
        placeholder="Will auto-fill from PCPAO",
        help="Acreage from PCPAO website"
    )

st.text_input(
    "Land Area (square feet)",
    key='land_area_sqft',
    placeholder="Will auto-fill from PCPAO",
    help="Square footage from PCPAO website"
)

# Summary
st.markdown("---")
st.subheader("Test Summary")

if st.session_state.get('api_city'):
    st.success("✅ Step 1: PCPAO API Lookup completed")
    
    # Show what was retrieved
    retrieved = []
    if st.session_state.get('api_city'): retrieved.append("City")
    if st.session_state.get('api_address'): retrieved.append("Address")
    if st.session_state.get('api_owner'): retrieved.append("Owner")
    if st.session_state.get('api_land_use'): retrieved.append("Property Use")
    if st.session_state.get('land_area_acres'): retrieved.append("Land Area")
    
    st.info(f"**Retrieved from PCPAO:** {', '.join(retrieved)}")
    
    # Check if zoning/FLU have been looked up
    if st.session_state.get('api_flu'):
        st.success("✅ Step 2: GIS Layer Lookup completed")
        zoning_retrieved = []
        if st.session_state.get('api_zoning') and 'Contact City' not in st.session_state.get('api_zoning', ''): 
            zoning_retrieved.append("Zoning")
        if st.session_state.get('api_flu'): 
            zoning_retrieved.append("Future Land Use")
        if zoning_retrieved:
            st.info(f"**Retrieved from GIS Layers:** {', '.join(zoning_retrieved)}")
    else:
        st.info("ℹ️ Click '🗺️ Lookup Zoning & Future Land Use' button to get detailed zoning data (St. Petersburg only)")
else:
    st.info("Click '🔍 Lookup Property Info' to start")
