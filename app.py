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

# Single Lookup Button (PCPAO API gets everything)
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
                    # Store ALL results in session state
                    st.session_state['api_address'] = result.get('address', '')
                    st.session_state['api_city'] = result.get('city', '')
                    st.session_state['api_zip'] = result.get('zip', '')
                    st.session_state['api_owner'] = result.get('owner', '')
                    st.session_state['api_land_use'] = result.get('land_use', '')
                    st.session_state['api_zoning'] = result.get('zoning', '')
                    st.session_state['land_area_sqft'] = result.get('site_area_sqft', '')
                    st.session_state['land_area_acres'] = result.get('site_area_acres', '')
                    
                    st.success("✅ Property data retrieved successfully!")
                    st.rerun()
                else:
                    st.error(f"❌ {result['error']}")

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
        "Land Area (acres)",
        key='land_area_acres',
        placeholder="Will auto-fill from PCPAO",
        help="Acreage from PCPAO website"
    )

with col_right:
    st.text_input(
        "Owner (auto-filled)",
        key='api_owner',
        placeholder="Will auto-fill from PCPAO",
        help="Property owner from PCPAO API"
    )
    
    st.text_input(
        "Property Use (auto-filled)",
        key='api_land_use',
        placeholder="Will auto-fill from PCPAO",
        help="Property Appraiser land use classification"
    )
    
    st.text_input(
        "Zoning (auto-filled)",
        key='api_zoning',
        placeholder="Will auto-fill from PCPAO",
        help="Zoning district"
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
    st.success("✅ PCPAO API Lookup completed successfully")
    
    # Show what was retrieved
    retrieved = []
    if st.session_state.get('api_city'): retrieved.append("City")
    if st.session_state.get('api_address'): retrieved.append("Address")
    if st.session_state.get('api_owner'): retrieved.append("Owner")
    if st.session_state.get('api_land_use'): retrieved.append("Property Use")
    if st.session_state.get('land_area_acres'): retrieved.append("Land Area")
    
    st.info(f"**Retrieved:** {', '.join(retrieved)}")
else:
    st.info("Click 'Lookup Property Info' to test PCPAO API data retrieval")
