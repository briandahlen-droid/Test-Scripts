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
# PINELLAS PROPERTY API LOOKUP
# ============================================================================

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

@st.cache_data(ttl=3600, show_spinner=False)
def lookup_pinellas_property(parcel_id):
    """
    Lookup property from Pinellas County ArcGIS API.
    Returns: dict with property data (address, city, owner, land_use, zoning, etc.)
    """
    session = get_resilient_session()
    base_url = "https://egis.pinellas.gov/gis/rest/services/Accela/AccelaAddressParcel/MapServer/1/query"
    
    # Sanitize parcel ID
    parcel_id = parcel_id.strip().replace("'", "''")
    
    params = {
        'where': f"PGIS.PGIS.Parcels.PARCELID='{parcel_id}'",
        'outFields': '*',
        'returnGeometry': 'true',
        'f': 'json'
    }
    
    try:
        response = session.get(base_url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        if 'error' in data:
            error = data['error']
            return {
                'success': False,
                'error': f"API Error {error.get('code', 'Unknown')}: {error.get('message', 'Unknown error')}"
            }
        
        if data.get('features') and len(data['features']) > 0:
            feature = data['features'][0]
            attr = feature['attributes']
            geometry = feature.get('geometry', {})
            
            # Extract fields from API
            address = attr.get('LEGAL') or attr.get('SITEADDRESS') or ''
            city = attr.get('JURISDICTION') or attr.get('CITY') or ''
            zip_code = attr.get('ZIP') or attr.get('ZIPCODE') or ''
            owner = attr.get('OWNERNAME') or attr.get('OWNER') or attr.get('NAME') or ''
            land_use = attr.get('PROPOSEDLANDUSE') or attr.get('LANDUSE') or ''
            zoning = attr.get('ZONECLASS') or attr.get('ZONING') or ''
            
            return {
                'success': True,
                'address': address,
                'city': city,
                'zip': str(zip_code) if zip_code else '',
                'owner': owner,
                'land_use': strip_dor_code(land_use),
                'zoning': zoning or 'Not available in API',
                'geometry': geometry,
                'error': None
            }
        else:
            return {'success': False, 'error': 'Parcel ID not found in Pinellas County database'}
    
    except requests.exceptions.Timeout:
        return {'success': False, 'error': 'Request timed out'}
    except requests.exceptions.HTTPError as e:
        return {'success': False, 'error': f'HTTP Error {e.response.status_code}'}
    except Exception as e:
        return {'success': False, 'error': f'Unexpected error: {str(e)}'}

# ============================================================================
# LAND AREA WEB SCRAPING (from existing test app)
# ============================================================================

def scrape_pinellas_land_area(parcel_id):
    """
    Scrape land area from PCPAO website.
    Returns: dict with land_area_sqft and land_area_acres
    """
    # Strap transformation: swap first and third segments
    parts = parcel_id.split('-')
    if len(parts) == 6:
        parts[0], parts[2] = parts[2], parts[0]
        strap = ''.join(parts)
    else:
        strap = parcel_id.replace('-', '')
    
    url = (
        f"https://www.pcpao.gov/property-details?"
        f"s={strap}&"
        f"input={parcel_id}&"
        f"search_option=parcel_number"
    )
    
    try:
        html = requests.get(url, timeout=30).text
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)
        
        # Match pattern: "Land Area: ≅ 59,560 sf | ≅ 1.36 acres"
        m = re.search(r"Land Area:\s*≅\s*([\d,]+)\s*sf\s*\|\s*≅\s*([\d.]+)\s*acres", text)
        
        if m:
            land_sqft = int(m.group(1).replace(",", ""))
            land_acres = float(m.group(2))
            
            return {
                'success': True,
                'land_area_sqft': f"{land_sqft:,}",
                'land_area_acres': f"{land_acres:.2f}",
                'error': None
            }
        else:
            return {'success': False, 'error': 'Land Area pattern not found on page'}
    
    except Exception as e:
        return {'success': False, 'error': f'Scraping failed: {str(e)}'}

# ============================================================================
# STREAMLIT UI
# ============================================================================

st.title("🏠 Pinellas County Property Lookup - Comprehensive Test")
st.caption("Testing all property data fields: City, Address, Owner, Property Use, Future Land Use, Zoning, Land Area")
st.markdown("---")

# Input Section
st.subheader("Input")
parcel_id = st.text_input(
    "Parcel ID",
    value="19-31-17-73166-001-0010",
    placeholder="e.g., 19-31-17-73166-001-0010",
    help="Pinellas County parcel ID with dashes"
)

# Lookup Buttons
col1, col2 = st.columns(2)

with col1:
    if st.button("🔍 Lookup Property Info (API)", type="primary"):
        if not parcel_id:
            st.error("Please enter a parcel ID")
        else:
            with st.spinner("Fetching property data from Pinellas County API..."):
                result = lookup_pinellas_property(parcel_id)
                
                if result['success']:
                    # Store in session state
                    st.session_state['api_address'] = result.get('address', '')
                    st.session_state['api_city'] = result.get('city', '')
                    st.session_state['api_zip'] = result.get('zip', '')
                    st.session_state['api_owner'] = result.get('owner', '')
                    st.session_state['api_land_use'] = result.get('land_use', '')
                    st.session_state['api_zoning'] = result.get('zoning', '')
                    
                    st.success("✅ Property data retrieved from API!")
                    st.rerun()
                else:
                    st.error(f"❌ {result['error']}")

with col2:
    if st.button("🔍 Lookup Land Area (Web Scraping)"):
        if not parcel_id:
            st.error("Please enter a parcel ID")
        else:
            with st.spinner("Scraping land area from PCPAO website..."):
                result = scrape_pinellas_land_area(parcel_id)
                
                if result['success']:
                    st.session_state['land_area_sqft'] = result.get('land_area_sqft', '')
                    st.session_state['land_area_acres'] = result.get('land_area_acres', '')
                    
                    st.success("✅ Land area retrieved from web scraping!")
                    st.rerun()
                else:
                    st.error(f"❌ {result['error']}")

st.markdown("---")

# Results Section
st.subheader("Results - Property Data")
st.caption("These fields auto-fill after successful lookup")

col_left, col_right = st.columns(2)

with col_left:
    st.text_input(
        "City (auto-filled)",
        key='api_city',
        placeholder="Will auto-fill from API",
        help="City name from Pinellas County API"
    )
    
    st.text_input(
        "Address (auto-filled)",
        key='api_address',
        placeholder="Will auto-fill from API",
        help="Property address from Pinellas County API"
    )
    
    st.text_input(
        "ZIP Code (auto-filled)",
        key='api_zip',
        placeholder="Will auto-fill from API",
        help="ZIP code from Pinellas County API"
    )

with col_right:
    st.text_input(
        "Owner (auto-filled)",
        key='api_owner',
        placeholder="Will auto-fill from API",
        help="Property owner from Pinellas County API"
    )
    
    st.text_input(
        "Property Use (auto-filled)",
        key='api_land_use',
        placeholder="Will auto-fill from API",
        help="Property Appraiser land use classification"
    )
    
    st.text_input(
        "Zoning (auto-filled)",
        key='api_zoning',
        placeholder="Will auto-fill from API",
        help="Zoning district from Pinellas County API"
    )

st.markdown("---")

st.subheader("Results - Land Area (from Web Scraping)")
col_area1, col_area2 = st.columns(2)

with col_area1:
    st.text_input(
        "Land Area (acres)",
        key='land_area_acres',
        placeholder="Will auto-fill from web scraping",
        help="Acreage from PCPAO website"
    )

with col_area2:
    st.text_input(
        "Land Area (square feet)",
        key='land_area_sqft',
        placeholder="Will auto-fill from web scraping",
        help="Square footage from PCPAO website"
    )

# Summary
st.markdown("---")
st.subheader("Test Summary")

if st.session_state.get('api_city'):
    st.success("✅ API Lookup completed successfully")
    st.info(f"**Retrieved:** City, Address, ZIP, Owner, Property Use, Zoning")
else:
    st.info("Click 'Lookup Property Info (API)' to test API data retrieval")

if st.session_state.get('land_area_acres'):
    st.success("✅ Web Scraping completed successfully")
    st.info(f"**Retrieved:** {st.session_state.get('land_area_acres')} acres ({st.session_state.get('land_area_sqft')} sf)")
else:
    st.info("Click 'Lookup Land Area (Web Scraping)' to test land area retrieval")
