"""
Multi-County Property Lookup App
Supports: Pinellas County and Hillsborough County
Tests: City auto-fill, Address, Property Use, Future Land Use, Zoning, Land Area
"""
import streamlit as st
import re
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

st.set_page_config(page_title="FL Property Lookup", page_icon="🏠", layout="wide")

# ============================================================================
# COUNTY CONFIGURATION
# ============================================================================

SUPPORTED_COUNTIES = ["Pinellas", "Hillsborough"]

# ============================================================================
# PINELLAS CITY NAME MAPPING
# ============================================================================

PINELLAS_CITY_MAP = {
    'SP': 'St. Petersburg',
    'ST PETERSBURG': 'St. Petersburg',
    'ST. PETERSBURG': 'St. Petersburg',
    'CLEARWATER': 'Clearwater',
    'CW': 'Clearwater',
    'LARGO': 'Largo',
    'LA': 'Largo',
    'PINELLAS PARK': 'Pinellas Park',
    'PP': 'Pinellas Park',
    'DUNEDIN': 'Dunedin',
    'TARPON SPRINGS': 'Tarpon Springs',
    'TS': 'Tarpon Springs',
    'SEMINOLE': 'Seminole',
    'KENNETH CITY': 'Kenneth City',
    'GULFPORT': 'Gulfport',
    'MADEIRA BEACH': 'Madeira Beach',
    'REDINGTON BEACH': 'Redington Beach',
    'TREASURE ISLAND': 'Treasure Island',
    'ST PETE BEACH': 'St. Pete Beach',
    'SOUTH PASADENA': 'South Pasadena',
    'BELLEAIR': 'Belleair',
    'BELLEAIR BEACH': 'Belleair Beach',
    'BELLEAIR BLUFFS': 'Belleair Bluffs',
    'INDIAN ROCKS BEACH': 'Indian Rocks Beach',
    'INDIAN SHORES': 'Indian Shores',
    'NORTH REDINGTON BEACH': 'North Redington Beach',
    'OLDSMAR': 'Oldsmar',
    'SAFETY HARBOR': 'Safety Harbor',
    'LFPW': 'Unincorporated Pinellas (Lealman)',
    'LEALMAN': 'Unincorporated Pinellas (Lealman)',
    'UNINCORPORATED': 'Unincorporated Pinellas',
    'COUNTY': 'Unincorporated Pinellas'
}

def expand_pinellas_city(city_abbr):
    """Expand Pinellas city abbreviation to full name."""
    if not city_abbr:
        return 'Unincorporated Pinellas'
    city_upper = city_abbr.strip().upper()
    return PINELLAS_CITY_MAP.get(city_upper, city_abbr)

# ============================================================================
# HILLSBOROUGH COUNTY FUNCTIONS
# ============================================================================

def scrape_hillsborough_property(folio_id):
    """Scrape Hillsborough County Property Appraiser for property details."""
    try:
        url = f"https://www.hcpafl.org/property-search/-/property/summary/{folio_id}"
        
        session = requests.Session()
        retry = Retry(connect=3, backoff_factor=0.5)
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = session.get(url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return {'success': False, 'error': f'HTTP {response.status_code}'}
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract fields
        result = {'success': True}
        
        # Address
        addr_elem = soup.find('th', string='Situs Address')
        if addr_elem:
            td = addr_elem.find_next_sibling('td')
            if td:
                result['address'] = td.get_text(strip=True)
        
        # City - usually part of address or separate
        city_elem = soup.find('th', string='Situs City')
        if city_elem:
            td = city_elem.find_next_sibling('td')
            if td:
                result['city'] = td.get_text(strip=True)
        
        # ZIP
        zip_elem = soup.find('th', string='Situs Zip Code')
        if zip_elem:
            td = zip_elem.find_next_sibling('td')
            if td:
                result['zip'] = td.get_text(strip=True)
        
        # Owner
        owner_elem = soup.find('th', string='Owner Name')
        if owner_elem:
            td = owner_elem.find_next_sibling('td')
            if td:
                result['owner'] = td.get_text(strip=True)
        
        # Land Use
        land_use_elem = soup.find('th', string='Current Use Description')
        if land_use_elem:
            td = land_use_elem.find_next_sibling('td')
            if td:
                result['land_use'] = td.get_text(strip=True)
        
        # Acreage
        acre_elem = soup.find('th', string='Acreage')
        if acre_elem:
            td = acre_elem.find_next_sibling('td')
            if td:
                result['site_area_acres'] = td.get_text(strip=True)
        
        # Square Feet
        sqft_elem = soup.find('th', string='Total Square Feet')
        if sqft_elem:
            td = sqft_elem.find_next_sibling('td')
            if td:
                result['site_area_sqft'] = td.get_text(strip=True)
        
        return result
        
    except Exception as e:
        return {'success': False, 'error': str(e)}

def lookup_hillsborough_zoning_flu(address):
    """
    Lookup Hillsborough County zoning and future land use via GIS REST API.
    Uses address geocoding.
    """
    try:
        # First geocode the address
        geocode_url = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
        geocode_params = {
            'SingleLine': address,
            'f': 'json',
            'outSR': '102659',  # Hillsborough's spatial reference
            'maxLocations': 1
        }
        
        geocode_resp = requests.get(geocode_url, params=geocode_params, timeout=10)
        geocode_data = geocode_resp.json()
        
        if not geocode_data.get('candidates'):
            return {'success': False, 'error': 'Could not geocode address'}
        
        location = geocode_data['candidates'][0]['location']
        x, y = location['x'], location['y']
        
        # Query zoning layer
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
        
        result = {'success': True}
        
        if zoning_data.get('features'):
            attrs = zoning_data['features'][0]['attributes']
            result['zoning_code'] = attrs.get('NZONE', '')
            result['zoning_description'] = attrs.get('NZONE_DESC', '')
        
        # Query future land use layer
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
            attrs = flu_data['features'][0]['attributes']
            result['future_land_use'] = attrs.get('FLUE', '')
        
        return result
        
    except Exception as e:
        return {'success': False, 'error': str(e)}

# ============================================================================
# PINELLAS COUNTY FUNCTIONS (keeping your existing ones)
# ============================================================================

def validate_pinellas_parcel_id(parcel_id):
    """Validate Pinellas County parcel ID format."""
    pattern = r'^\d{2}-\d{2}-\d{2}-\d{5}-\d{3}-\d{4}$'
    if not re.match(pattern, parcel_id):
        return False, "Format must be: XX-XX-XX-XXXXX-XXX-XXXX"
    return True, ""

def scrape_pinellas_property(parcel_id):
    """Scrape Pinellas County Property Appraiser for property details."""
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
        
        if not data or len(data) == 0:
            return {'success': False, 'error': 'No results found for this parcel ID'}
        
        property_data = data[0]
        
        result = {
            'success': True,
            'address': property_data.get('siteAddress', ''),
            'city': expand_pinellas_city(property_data.get('siteCity', '')),
            'zip': property_data.get('siteZipCode', ''),
            'owner': property_data.get('ownerName', ''),
            'land_use': property_data.get('landUseDescription', ''),
            'zoning': property_data.get('zoning', 'Contact City Planning'),
            'site_area_sqft': property_data.get('siteAreaSqft', ''),
            'site_area_acres': property_data.get('siteAreaAcres', '')
        }
        
        return result
        
    except Exception as e:
        return {'success': False, 'error': str(e)}

# [Your existing lookup_pinellas_zoning function would go here - truncated for brevity]

# ============================================================================
# STREAMLIT APP
# ============================================================================

st.title("Florida Property Lookup")
st.markdown("Multi-county property information lookup tool")

# County Selector
st.subheader("Step 1: Select County")
county = st.selectbox(
    "County",
    options=SUPPORTED_COUNTIES,
    key="county_selector"
)

st.markdown("---")

# Parcel ID / Folio Input
st.subheader("Step 2: Enter Parcel ID / Folio")

if county == "Pinellas":
    parcel_input = st.text_input(
        "Pinellas Parcel ID",
        placeholder="e.g., 19-31-17-73166-001-0010",
        help="Pinellas County parcel ID with dashes",
        key="parcel_input"
    )
elif county == "Hillsborough":
    parcel_input = st.text_input(
        "Hillsborough Folio ID",
        placeholder="e.g., 123456.0000",
        help="Hillsborough County folio number",
        key="parcel_input"
    )

# Lookup Button
if st.button("🔍 Lookup Property Info", type="primary"):
    if not parcel_input:
        st.error("Please enter a parcel ID / folio")
    else:
        if county == "Pinellas":
            # Validate Pinellas parcel ID
            is_valid, error_msg = validate_pinellas_parcel_id(parcel_input)
            if not is_valid:
                st.error(f"❌ {error_msg}")
            else:
                with st.spinner("Fetching property data from Pinellas PCPAO API..."):
                    result = scrape_pinellas_property(parcel_input)
                    
                    if result['success']:
                        st.session_state['api_address'] = result.get('address', '')
                        st.session_state['api_city'] = result.get('city', '')
                        st.session_state['api_zip'] = result.get('zip', '')
                        st.session_state['api_owner'] = result.get('owner', '')
                        st.session_state['api_land_use'] = result.get('land_use', '')
                        st.session_state['api_zoning'] = result.get('zoning', '')
                        st.session_state['land_area_sqft'] = result.get('site_area_sqft', '')
                        st.session_state['land_area_acres'] = result.get('site_area_acres', '')
                        st.session_state['api_flu'] = ''
                        
                        st.success("✅ Property data retrieved successfully!")
                        st.rerun()
                    else:
                        st.error(f"❌ {result['error']}")
                        
        elif county == "Hillsborough":
            with st.spinner("Fetching property data from Hillsborough HCPA..."):
                result = scrape_hillsborough_property(parcel_input)
                
                if result['success']:
                    st.session_state['api_address'] = result.get('address', '')
                    st.session_state['api_city'] = result.get('city', '')
                    st.session_state['api_zip'] = result.get('zip', '')
                    st.session_state['api_owner'] = result.get('owner', '')
                    st.session_state['api_land_use'] = result.get('land_use', '')
                    st.session_state['api_zoning'] = ''
                    st.session_state['land_area_sqft'] = result.get('site_area_sqft', '')
                    st.session_state['land_area_acres'] = result.get('site_area_acres', '')
                    st.session_state['api_flu'] = ''
                    
                    st.success("✅ Property data retrieved successfully!")
                    st.rerun()
                else:
                    st.error(f"❌ {result['error']}")

# Second button for zoning/FLU lookup
st.markdown("---")
if county == "Hillsborough":
    st.caption("🔍 **For Hillsborough County:** Lookup zoning and Future Land Use from GIS layers")
    
    if st.button("🗺️ Lookup Zoning & Future Land Use", type="secondary"):
        address = st.session_state.get('api_address', '')
        
        if not address:
            st.error("❌ Please run Property Lookup first to get the address")
        else:
            with st.spinner(f"Fetching zoning data for {address}..."):
                zoning_result = lookup_hillsborough_zoning_flu(address)
                
                if zoning_result.get('success'):
                    if zoning_result.get('zoning_code'):
                        if zoning_result.get('zoning_description'):
                            st.session_state['api_zoning'] = f"{zoning_result.get('zoning_code')} - {zoning_result.get('zoning_description')}"
                        else:
                            st.session_state['api_zoning'] = zoning_result.get('zoning_code', '')
                    
                    if zoning_result.get('future_land_use'):
                        st.session_state['api_flu'] = zoning_result.get('future_land_use', '')
                    
                    st.success(f"✅ Zoning/FLU data updated from Hillsborough County GIS!")
                    st.rerun()
                else:
                    st.error(f"❌ {zoning_result.get('error', 'Unable to fetch zoning data')}")

st.markdown("---")

# Results Section
st.subheader("Results - All Property Data")
st.caption("These fields auto-fill after successful lookup")

col_left, col_right = st.columns(2)

with col_left:
    st.text_input(
        "City (auto-filled)",
        key='api_city',
        placeholder="Will auto-fill",
        help="City name"
    )
    
    st.text_input(
        "Address (auto-filled)",
        key='api_address',
        placeholder="Will auto-fill",
        help="Property address"
    )
    
    st.text_input(
        "ZIP Code (auto-filled)",
        key='api_zip',
        placeholder="Will auto-fill",
        help="ZIP code"
    )
    
    st.text_input(
        "Property Use (auto-filled)",
        key='api_land_use',
        placeholder="Will auto-fill",
        help="Land use classification"
    )

with col_right:
    st.text_input(
        "Owner (auto-filled)",
        key='api_owner',
        placeholder="Will auto-fill",
        help="Property owner"
    )
    
    st.text_input(
        "Zoning (auto-filled)",
        key='api_zoning',
        placeholder="Will auto-fill",
        help="Zoning district"
    )
    
    st.text_input(
        "Future Land Use (auto-filled)",
        key='api_flu',
        placeholder="Will auto-fill",
        help="Future Land Use designation"
    )
    
    st.text_input(
        "Land Area (acres)",
        key='land_area_acres',
        placeholder="Will auto-fill",
        help="Acreage"
    )

st.text_input(
    "Land Area (square feet)",
    key='land_area_sqft',
    placeholder="Will auto-fill",
    help="Square footage"
)

# Summary
st.markdown("---")
st.subheader("Status")

if st.session_state.get('api_city'):
    st.success(f"✅ Property data retrieved for {county} County")
else:
    st.info("Enter a parcel ID/folio and click 'Lookup Property Info' to start")
