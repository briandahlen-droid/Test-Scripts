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
# PINELLAS CITY NAME MAPPING
# ============================================================================

# Map Pinellas County tax district codes to full city names
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
    # Unincorporated area codes
    'LFPW': 'Unincorporated Pinellas (Lealman)',
    'LEALMAN': 'Unincorporated Pinellas (Lealman)',
    'UNINCORPORATED': 'Unincorporated Pinellas',
    'COUNTY': 'Unincorporated Pinellas'
}

def expand_city_name(city_abbr):
    """Expand Pinellas city abbreviation to full name."""
    if not city_abbr:
        return 'Unincorporated Pinellas'
    
    city_upper = city_abbr.strip().upper()
    return PINELLAS_CITY_MAP.get(city_upper, city_abbr)

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
# FLORIDA DOR LAND USE CODES (for Hillsborough)
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
    
    # Remove decimal point (84.0 -> 84)
    if '.' in code_str:
        code_str = code_str.split('.')[0]
    
    if code_str in DOR_LAND_USE_CODES:
        return DOR_LAND_USE_CODES[code_str]
    code_padded = code_str.zfill(4)
    if code_padded in DOR_LAND_USE_CODES:
        return DOR_LAND_USE_CODES[code_padded]
    return code_str

HILLSBOROUGH_FLU_CODES = {
    'A/M': 'Agricultural/Mining - 1/20', 'A-1/10': 'Agricultural - 1/10',
    'AR-1/5': 'Agricultural/Rural - 1/5', 'AE-1/2.5': 'Agricultural Estate - 1/2.5',
    'PEC-1/2': 'Planned Environmental Community - 1/2', 'RES-1': 'Residential - 1',
    'RES-2': 'Residential - 2', 'RP-2': 'Residential Planned - 2',
    'WVR-2': 'Wimauma Village Residential - 2', 'NMU-4(3)': 'Neighborhood Mixed-Use - 4(3)',
    'NMU-6': 'Neighborhood Mixed-Use - 6', 'RES-4': 'Residential - 4',
    'RES-6': 'Residential - 6', 'SMU-6': 'Suburban Mixed-Use - 6',
    'RES-9': 'Residential - 9', 'RES-12': 'Residential - 12',
    'CMU-12': 'Community Mixed-Use - 12', 'RES-16': 'Residential - 16',
    'RES-20': 'Residential - 20', 'OC-20': 'Office Commercial - 20',
    'RES-35': 'Residential - 35', 'UMU-20': 'Urban Mixed-Use - 20',
    'RMU-35': 'Regional Mixed-Use - 35', 'ICMU-35': 'Innovation Corridor Mixed-Use - 35',
    'RCP': 'Research/Corporate Park', 'LI-P': 'Light Industrial Planned',
    'LI': 'Light Industrial', 'HI': 'Heavy Industrial',
    'EIP': 'Energy Industrial Park', 'EIP-USA': 'Energy Industrial Park - Urban Service Area',
    'EPGF': 'Electrical Power Generating Facility',
    'P/Q-P': 'Public/Quasi-Public', 'P/QP': 'Public/Quasi-Public',
    'E': 'Environmentally Sensitive Area', 'N': 'Natural Preservation',
}

def get_hillsborough_flu_description(code):
    """Convert Hillsborough FLU code to description."""
    if not code:
        return ''
    return HILLSBOROUGH_FLU_CODES.get(str(code).strip(), code)

# ============================================================================
# HILLSBOROUGH COUNTY FUNCTIONS  
# ============================================================================

def lookup_hillsborough_parcel(folio):
    """Lookup Hillsborough parcel by folio from SWFWMD service."""
    try:
        parcel_url = "https://www25.swfwmd.state.fl.us/arcgis12/rest/services/BaseVector/parcel_search/MapServer/7/query"
        
        folio_formats = [folio, folio.replace('.', ''), folio.split('.')[0] if '.' in folio else folio]
        
        parcel_data = None
        for folio_format in folio_formats:
            parcel_params = {'where': f"FOLIONUM = '{folio_format}'", 'outFields': '*', 'returnGeometry': 'true', 'f': 'json'}
            parcel_resp = requests.get(parcel_url, params=parcel_params, timeout=15)
            data = parcel_resp.json()
            if data.get('features'):
                parcel_data = data
                break
        
        if not parcel_data or not parcel_data.get('features'):
            return {'success': False, 'error': f'Folio not found'}
        
        attrs = parcel_data['features'][0]['attributes']
        acres = attrs.get('ACRES') or attrs.get('AREANO')
        acres_str = f"{float(acres):.2f}" if acres and acres not in [None, 'None', ''] else ''
        
        # Always try DOR code first for full description
        dor_code = attrs.get('DORUSECODE') or attrs.get('DOR4CODE')
        land_use_desc = get_land_use_description(dor_code) if dor_code else attrs.get('PARUSEDESC', '')
        
        return {
            'success': True,
            'address': attrs.get('SITEADD', attrs.get('SITUSADD1', '')),
            'city': attrs.get('SCITY', 'Tampa'),
            'zip': attrs.get('SZIP', ''),
            'owner': attrs.get('OWNNAME', attrs.get('OWNERNAME', '')),
            'land_use': land_use_desc,
            'site_area_acres': acres_str,
            'site_area_sqft': '',
            'zoning': attrs.get('ZONING', '')
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}

def lookup_hillsborough_zoning_flu(address):
    """Lookup Hillsborough zoning/FLU from GIS (secondary button)."""
    try:
        geocode_url = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
        geocode_params = {'SingleLine': address + ", Hillsborough County, FL", 'f': 'json', 'outSR': '4326', 'maxLocations': 1}
        geocode_resp = requests.get(geocode_url, params=geocode_params, timeout=10)
        geocode_data = geocode_resp.json()
        if not geocode_data.get('candidates'):
            return {'success': False, 'error': 'Could not geocode address'}
        location = geocode_data['candidates'][0]['location']
        x, y = location['x'], location['y']
        result = {'success': True}
        
        # Try Tampa City zoning first (separate from Hillsborough County)
        tampa_zoning_url = "https://arcgis.tampagov.net/arcgis/rest/services/Planning/ZoningDistrict/FeatureServer/0/query"
        tampa_zoning_params = {
            'geometry': f'{x},{y}',
            'geometryType': 'esriGeometryPoint',
            'spatialRel': 'esriSpatialRelIntersects',
            'outFields': 'ZONECLASS,ZONEDESC',
            'returnGeometry': 'false',
            'f': 'json',
            'inSR': '4326'
        }
        
        tampa_zoning_resp = requests.get(tampa_zoning_url, params=tampa_zoning_params, timeout=10)
        tampa_zoning_data = tampa_zoning_resp.json()
        
        # Debug: Check if Tampa query returned anything
        if 'error' in tampa_zoning_data:
            # Tampa query had an error, try county
            pass
        elif tampa_zoning_data.get('features'):
            # Found in Tampa
            attrs = tampa_zoning_data['features'][0]['attributes']
            result['zoning_code'] = attrs.get('ZONECLASS', '')
            result['zoning_description'] = attrs.get('ZONEDESC', '')
            result['source'] = 'Tampa City'
        
        # If no Tampa zoning found, try Hillsborough County
        if not result.get('zoning_code'):
            county_zoning_url = "https://maps.hillsboroughcounty.org/arcgis/rest/services/DSD_Viewer_Services/DSD_Viewer_Zoning_Regulatory/FeatureServer/1/query"
            county_zoning_params = {
                'geometry': f'{x},{y}',
                'geometryType': 'esriGeometryPoint',
                'spatialRel': 'esriSpatialRelIntersects',
                'outFields': 'NZONE,NZONE_DESC,CATEGORY',
                'returnGeometry': 'false',
                'f': 'json',
                'inSR': '4326'
            }
            county_zoning_resp = requests.get(county_zoning_url, params=county_zoning_params, timeout=10)
            county_zoning_data = county_zoning_resp.json()
            if county_zoning_data.get('features'):
                attrs = county_zoning_data['features'][0]['attributes']
                result['zoning_code'] = attrs.get('NZONE', '')
                result['zoning_description'] = attrs.get('NZONE_DESC', '')
                result['source'] = 'Hillsborough County'
        
        # Query FLU layer (county-wide, includes Tampa)
        flu_url = "https://maps.hillsboroughcounty.org/arcgis/rest/services/DSD_Viewer_Services/DSD_Viewer_Planning/MapServer/1/query"
        flu_params = {
            'geometry': f'{x},{y}',
            'geometryType': 'esriGeometryPoint',
            'spatialRel': 'esriSpatialRelIntersects',
            'outFields': 'FLUE',
            'returnGeometry': 'false',
            'f': 'json',
            'inSR': '4326'
        }
        flu_resp = requests.get(flu_url, params=flu_params, timeout=10)
        flu_data = flu_resp.json()
        if flu_data.get('features'):
            flu_code = flu_data['features'][0]['attributes'].get('FLUE', '')
            result['future_land_use'] = get_hillsborough_flu_description(flu_code)
        
        return result
    except Exception as e:
        return {'success': False, 'error': str(e)}

# NOTE: Unincorporated Pinellas zoning and FLU coded values are now fetched 
# dynamically from layer metadata using fetch_coded_values() function.
# Hardcoded fallbacks kept below in case metadata fetch fails.

# Unincorporated Pinellas County Zoning code to description mapping (FALLBACK)
UNINCORPORATED_ZONING_DESCRIPTIONS = {
    'AL': 'Aquatic Lands',
    'AL-CO': 'Aquatic Lands - Conditional Overlay',
    'AL-W': 'Aquatic Lands - Wellhead Protection Overlay',
    'AL-W-CO': 'Aquatic Lands - Wellhead Protection Overlay - Conditional Overlay',
    'C-1': 'Neighborhood Commercial',
    'C-1-CO': 'Neighborhood Commercial - Conditional Overlay',
    'C-1-H': 'Neighborhood Commerical - Historic District',
    'C-1-W': 'Neighborhood Commercial - Wellhead Protection Overlay',
    'C-1-W-CO': 'Neighborhood Commercial - Wellhead Protection Overlay - Conditional Overlay',
    'CP': 'Commercial Parkway',
    'CP-CO': 'Commercial Parkway - Conditional Overlay',
    'CP-W': 'Commercial Parkway - Wellhead Protection Overlay',
    'CP-W-CO': 'Commercial Parkway - Wellhead Protection Overlay - Conditional Overlay',
    'CR': 'Commercial Recreation',
    'CR-CO': 'Commercial Recreation - Conditional Overlay',
    'CR-W': 'Commercial Recreation - Wellhead Protection Overlay',
    'CR-W-CO': 'Commercial Recreation - Wellhead Protection Overlay - Conditional Overlay',
    'E-1': 'Employment 1',
    'E-1-CO': 'Employment 1 - Conditional Overlay',
    'E-1-W': 'Employment 1 - Wellhead Protection Overlay',
    'E-1-W-CO': 'Employment 1 - Wellhead Protection Overlay - Conditional Overlay',
    'E-2': 'Employment 2',
    'E-2-CO': 'Employment 2 - Conditional Overlay',
    'E-2-W': 'Employment 2 - Wellhead Protection Overlay',
    'E-2-W-CO': 'Employment 2 - Wellhead Protection Overlay - Conditional Overlay',
    'FBC': 'Form Based Code District',
    'FBC-CO': 'Form Based Code District - Conditional Overlay',
    'FBC-W': 'Form Based Code District - Wellhead Protection Overlay',
    'FBC-W-CO': 'Form Based Code District - Wellhead Protection Overlay - Conditional Overlay',
    'FBR': 'Facilities-Based Recreation',
    'FBR-CO': 'Facilities-Based Recreation - Conditional Overlay',
    'FBR-W': 'Facilities-Based Recreation - Wellhead Protection Overlay',
    'FBR-W-CO': 'Facilities-Based Recreation - Wellhead Protection Overlay - Conditional Overlay',
    'GI': 'General Institutional',
    'GI-CO': 'General Institutional - Conditional Overlay',
    'GI-W': 'General Institutional - Wellhead Protection Overlay',
    'GI-W-CO': 'General Institutional - Wellhead Protection Overlay - Conditional Overlay',
    'GO': 'General Office',
    'GO-CO': 'General Office - Conditional Overlay',
    'GO-W': 'General Office - Wellhead Protection Overlay',
    'GO-W-CO': 'General Office - Wellhead Protection Overlay - Conditional Overlay',
    'I': 'Industrial',
    'I-CO': 'Industrial - Conditional Overlay',
    'I-W': 'Industrial - Wellhead Protection Overlay',
    'I-W-CO': 'Industrial - Wellhead Protection Overlay',
    'IPD': 'Industrial Planned Development',
    'IPD-CO': 'Industrial Planned Development - Conditional Overlay',
    'IPD-W': 'Industrial Planned Development - Wellhead Protection Overlay',
    'IPD-W-CO': 'Industrial Planned Development - Wellhead Protection Overlay - Conditional Overlay',
    'LI': 'Limited Institutional',
    'LI-CO': 'Limited Institutional - Conditional Overlay',
    'LI-W': 'Limited Institutional - Wellhead Protection Overlay',
    'LI-W-CO': 'Limited Institutional - Wellhead Protection Overlay - Conditional Overlay',
    'LO': 'Limited Office',
    'LO-CO': 'Limited Office - Conditional Overlay',
    'LO-W': 'Limited Office - Wellhead Protection Overlay',
    'LO-W-CO': 'Limited Office - Wellhead Protection Overlay - Conditional Overlay',
    'MXD': 'Mixed-Use District',
    'MXD-CO': 'Mixed-Use District - Conditional Overlay',
    'MXD-W': 'Mixed-Use District - Wellhead Protection Overlay',
    'MXD-W-CO': 'Mixed-Use District - Wellhead Protection Overlay - Conditional Overlay',
    'OPH-D': 'Old Palm Harbor Downtown',
    'OPH-D-CO': 'Old Palm Harbor Downtown - Conditional Overlay',
    'OPH-D-H': 'Old Palm Harbor Downtown - Historic District',
    'OPH-D-W': 'Old Palm Harbor Downtown - Wellhead Protection Overlay',
    'OPH-D-W-CO': 'Old Palm Harbor Downtown - Wellhead Protection Overlay - Conditional Overlay',
    'P-C': 'Preservation Conservation',
    'P-C-CO': 'Preservation Conservation - Conditional Overlay',
    'P-C-W': 'Preservation Conservation - Wellhead Protection Overlay',
    'P-C-W-CO': 'Preservation Conservation - Wellhead Protection Overlay - Conditional Overlay',
    'P-RM': 'Preservation Resource Management',
    'P-RM-CO': 'Preservation Resource Management - Conditional Overlay',
    'P-RM-W': 'Preservation Resource Management - Wellhead Protection Overlay',
    'P-RM-W-CO': 'Preservation Resource Management - Wellhead Protection Overlay - Conditional Overlay',
    'P.C.AIRPORT': 'PC Airport',
    'P.C.AIRPORT-CO': 'PC Airport - Conditional Overlay',
    'P.C.AIRPORT-W': 'PC Airport - Wellhead Protection Overlay',
    'P.C.AIRPORT-W-CO': 'PC Airport- Wellhead Protection Overlay - Conditional Overlay',
    'R-1': 'Single Family Residential (9,500 SF Min)',
    'R-1-CO': 'Single Family Residential (9,500 SF Min) - Conditional Overlay',
    'R-1-W': 'Single Family Residential (9,500 SF Min) - Wellhead Protection Overlay',
    'R-1-W-CO': 'Single Family Residential (9,500 SF Min) - Wellhead Protection Overlay - Conditional Overlay',
    'R-2': 'Single Family Residential (7,500 SF Min)',
    'R-2-CO': 'Single Family Residential (7,500 SF Min) - Conditional Overlay',
    'R-2-W': 'Single Family Residential (7,500 SF Min) - Wellhead Protection Overlay',
    'R-2-W-CO': 'Single Family Residential (7,500 SF Min) - Wellhead Protection Overlay - Conditional Overlay',
    'R-3': 'Single Family Residential (6,000 SF Min)',
    'R-3-CO': 'Single Family Residential (6,000 SF Min) - Conditional Overlay',
    'R-3-H': 'Single Family Residential (6,000 SF Min) - Historic District',
    'R-3-W': 'Single Family Residential (6,000 SF Min) - Wellhead Protection Overlay',
    'R-3-W-CO': 'Single Family Residential (6,000 SF Min) - Wellhead Protection Overlay - Conditional Overlay',
    'R-4': 'One, Two and Three Family Residential',
    'R-4-CO': 'One, Two and Three Family Residential - Conditional Overlay',
    'R-4-W': 'One, Two and Three Family Residential - Wellhead Protection Overlay',
    'R-4-W-CO': 'One, Two and Three Family Residential - Wellhead Protection Overlay - Conditional Overlay',
    'R-5': 'Urban Residential District',
    'R-5-CO': 'Urban Residential District - Conditional Overlay',
    'R-5-W': 'Urban Residential District - Wellhead Protection Overlay',
    'R-5-W-CO': 'Urban Residential District - Wellhead Protection Overlay - Conditional Overlay',
    'R-A': 'Residential Agriculture',
    'R-A-CO': 'Residential Agriculture - Conditional Overlay',
    'R-A-W': 'Residential Agriculture - Wellhead Protection Overlay',
    'R-A-W-CO': 'Residential Agriculture - Wellhead Protection Overlay - Conditional Overlay',
    'R-E': 'Residential Estate',
    'R-E-C-T': 'Residential Estate - Transient Accommodation Overlay',
    'R-E-CO': 'Residential Estate - Conditional Overlay',
    'R-E-W': 'Residential Estate - Wellhead Protection Overlay',
    'R-E-W-CO': 'Residential Estate - Wellhead Protection Overlay - Conditional Overlay',
    'R-R': 'Rural Residential',
    'R-R-CO': 'Rural Residential - Conditional Overlay',
    'R-R-H': 'Rural Residential - Historic District',
    'R-R-W': 'Rural Residnetial - Wellhead Protection Overlay',
    'R-R-W-CO': 'Rural Residential - Wellhead Protection Overlay - Conditional Overlay',
    'RBR': 'Resource-Based Recreation',
    'RBR-CO': 'Resource-Based Recreation - Conditional Overlay',
    'RBR-W': 'Resource-Based Recreation - Wellhead Protection Overlay',
    'RBR-W-CO': 'Resource-Based Recreation - Wellhead Protection Overlay - Conditional Overlay',
    'RM': 'Multi-Family Residential (see FLUM for density)',
    'RM-CO': 'Multi-Family Residential (see FLUM for density) - Conditional Overlay',
    'RM-W': 'Multi-Family Residential (see FLUM for density) - Wellhead Protection Overlay',
    'RM-W-CO': 'Multi-Family Residential (see FLUM for density) - Wellhead Protection Overlay - Conditional Overlay',
    'RMH': 'Residential Mobile/Manufactured Home',
    'RMH-CO': 'Residential Mobile/Manufactured Home - Conditional Overlay',
    'RMH-W': 'Residential Mobile/Manufactured Home - Wellhead Protection Overlay',
    'RMH-W-CO': 'Residential Mobile/Manufactured Home - Wellhead Protection Overlay - Conditional Overlay',
    'RPD': 'Residential Planned Development (see FLUM for density)',
    'RPD-CO': 'Residential Planned Development (see FLUM for density) - Conditional Overlay',
    'RPD-W': 'Residential Planned Developlment (see FLUM for density) - Wellhead Protection Overlay',
    'RPD-W-CO': 'Residential Planned Development (see FLUM for density) - Wellhead Protection Overlay - Conditional Overlay',
    'UZ': 'Unknown Zoning',
    'UZ-CO': 'Unknown Zoning - Conditional Overlay',
    'UZ-W': 'Unknown Zoning - Wellhead Protection Overlay',
    'UZ-W-CO': 'Unknown Zoning - Wellhead Protection Overlay - Conditional Overlay',
    'OPH-D-W': 'Old Palm Harbor Downtown - Wellhead Protection Overlay',
    'C-T': 'Transient Accommodation Overlay',
    'HPO': 'Historic Preservation Overlay',
    'E-1-C-T': 'Employment 1 - Transient Accommodation Overlay',
    'C-2': 'General Commercial and Services',
    'DPH-FBC': 'Downtown Palm Harbor Form Based Code',
    'C-2-C-T': 'General Commercial and Services Transient Accommodations Overlay',
    'L-FBC': 'Lealman - Form Based Code',
    'C-2-CO': 'General Commercial and Services - Conditional Overlay',
    'C-2-H': 'General Commercial and Services - Historic District',
    'C-2-W': 'General Commercial and Services - Wellhead Protection Overlay',
    'C-2-W-CO': 'General Commercial and Services - Wellhead Proteciton Overlay - Conditional Overlay',
}

# Unincorporated Pinellas County Future Land Use code to description mapping (FALLBACK)
UNINCORPORATED_FLU_DESCRIPTIONS = {
    'RR': 'Residential Rural',
    'RE': 'Residential Estate',
    'RS': 'Residential Suburban',
    'RL': 'Residential Low',
    'RU': 'Residential Urban',
    'RLM': 'Residential Low Medium',
    'RM': 'Residential Medium',
    'RH': 'Residential High',
    'PR-I': 'Planned Redevelopment - Industrial',
    'RFO': 'Resort Facilities',
    'PR-C': 'Planned Redevelopment - Commercial',
    'NO-DES': 'No Designation',
    'CN': 'Commercial Neighborhood',
    'CG': 'Commercial General',
    'CR': 'Commercial Recreation',
    'IL': 'Industrial Limited',
    'IG': 'Industrial General',
    'P': 'Preservation',
    'PR-MU': 'Planned Redevelopment - Mixed Use',
    'I': 'Institutional',
    'PR-R': 'Planned Redevelopment - Residential',
    'TU': 'Transportation/Utilities',
    'ROR': 'Residential/Office/Retail',
    'ROL': 'Residential/Office/Limited',
    'ROG': 'Residential/Office/General',
    'ROS': 'Recreation/Open Space',
    'PSP': 'Public/Semi-Public',
    'RVH': 'Residential Very High',
    'RFM': 'Resort Facilities Medium',
    'RFH': 'Resort Facilities High',
    'CRD': 'Community Redevelopment Dist',
    'CBD': 'Central Business District',
    'CL': 'Commercial Limited',
    'RFO-P': 'Resort Facilities Overlay/Perm',
    'RFO-T': 'Resort Facilities Overlay/Temp',
    'WDF': 'Water Drainage Feature',
    'WF': 'Water Feature',
    'WATER': 'WATER',
    'ROAD': 'ROAD',
    'P-RM': 'Preservation - Resource Management',
    'MUNI': 'MUNICIPALITY',
    'NO-D-W': 'No Designation Uninc Water',
    'MUNI-W': 'Municipal Open Water',
    'CRD-AC': 'Community Redevelop-Activity Ctr',
    'AC': 'AC',
    'AC-P': 'AC-P',
    'RM-12.5': 'RM-12.5',
    'TU-O': 'Transportation/Utility Overlay',
    'E': 'Employment',
    'AC-N': 'Activity Center - Neighborhood',
    'AC-C': 'Activity Center - Community',
    'AC-M': 'Activity Center - Major',
    'MUC-P': 'Mixed Use Corridor - Primary',
    'MUC-S': 'Mixed Use Corridor - Secondary',
    'MUC-P-C': 'Mixed Use Corridor - Primary - Commerce',
    'MUC-SU-NP': 'Mixed Use Corridor - Supporting - Neighborhood Park',
    'MUC-SU-LT': 'Mixed Use Corridor - Supporting - Local Trade',
}

# ============================================================================
# AUTOMATED CODED VALUE EXTRACTION FROM ARCGIS LAYERS
# ============================================================================

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_coded_values(layer_url, field_name):
    """
    Automatically fetch coded value domain from an ArcGIS layer.
    
    Args:
        layer_url: Base layer URL (e.g., "https://...MapServer/1")
        field_name: Field with coded values (e.g., "ZONEDESC")
    
    Returns:
        dict: {code: description} mapping, or empty dict if not found
    """
    session = get_resilient_session()
    
    try:
        # Fetch layer metadata
        metadata_url = f"{layer_url}?f=json"
        response = session.get(metadata_url, timeout=15)
        response.raise_for_status()
        metadata = response.json()
        
        # Find the field with coded values
        for field in metadata.get('fields', []):
            if field.get('name') == field_name:
                domain = field.get('domain')
                if domain and domain.get('type') == 'codedValue':
                    # Extract code -> name mappings
                    coded_values = domain.get('codedValues', [])
                    return {item['code']: item['name'] for item in coded_values}
        
        return {}
    
    except Exception as e:
        # Return empty dict on error - calling code should handle
        return {}

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
        
        # Column 6: Current Tax District (this IS the city, but may be abbreviated)
        tax_dist_html = result_row[6] if len(result_row) > 6 else ''
        tax_dist_soup = BeautifulSoup(tax_dist_html, 'lxml')
        tax_district = tax_dist_soup.get_text(strip=True)
        
        # Expand abbreviated city name (e.g., "SP" -> "St. Petersburg")
        city = expand_city_name(tax_district)
        
        # Column 7: Property Use / DOR Code
        use_html = result_row[7] if len(result_row) > 7 else ''
        use_soup = BeautifulSoup(use_html, 'lxml')
        property_use = use_soup.get_text(strip=True)
        
        # Column 8: Legal Description
        legal_html = result_row[8] if len(result_row) > 8 else ''
        legal_soup = BeautifulSoup(legal_html, 'lxml')
        legal_desc = legal_soup.get_text(strip=True)
        
        # Get acreage from detail page
        sqft = None
        acres = None
        zip_code = None
        
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
            
            # Extract ZIP code from detail page (format: "FL 33703" or "FL33703")
            zip_match = re.search(r'FL\s*(\d{5})', text)
            if zip_match:
                zip_code = zip_match.group(1)
        except Exception:
            pass  # If detail page fails, sqft, acres, and zip_code remain None
        
        return {
            'success': True,
            'address': address,
            'city': city,
            'zip': zip_code or '',
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

def is_unincorporated(city_name):
    """Check if city is unincorporated Pinellas."""
    if not city_name:
        return True
    
    unincorporated_indicators = [
        'UNINCORPORATED',
        'LFPW',  # Lealman area
        'LEALMAN',
        'COUNTY',
        'PINELLAS COUNTY'
    ]
    
    city_upper = city_name.upper()
    return any(indicator in city_upper for indicator in unincorporated_indicators)

def lookup_unincorporated_zoning(address):
    """
    Lookup zoning and FLU for unincorporated Pinellas County areas.
    Uses PublicWebGIS/Landuse_Zoning/MapServer with automated coded value extraction.
    
    Returns: dict with zoning_code, zoning_description, future_land_use, future_land_use_description
    """
    if not address:
        return {'success': False, 'error': 'Address required for zoning lookup'}
    
    session = get_resilient_session()
    
    try:
        # Fetch coded value domains dynamically (cached for 24 hours)
        zoning_lookup = fetch_coded_values(
            "https://egis.pinellas.gov/gis/rest/services/PublicWebGIS/Landuse_Zoning/MapServer/1",
            "ZONEDESC"
        )
        flu_lookup = fetch_coded_values(
            "https://egis.pinellas.gov/gis/rest/services/PublicWebGIS/Landuse_Zoning/MapServer/0",
            "LANDUSEDESC"
        )
        
        # Fallback to hardcoded if fetch failed
        if not zoning_lookup:
            zoning_lookup = UNINCORPORATED_ZONING_DESCRIPTIONS
        if not flu_lookup:
            flu_lookup = UNINCORPORATED_FLU_DESCRIPTIONS
        
        # Step 1: Geocode the address
        search_url = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
        geocode_params = {
            'SingleLine': f"{address}, Pinellas County, FL",
            'f': 'json',
            'outFields': '*'
        }
        
        geocode_response = session.get(search_url, params=geocode_params, timeout=15)
        geocode_data = geocode_response.json()
        
        if not geocode_data.get('candidates'):
            return {'success': False, 'error': 'Could not geocode address'}
        
        # Get coordinates
        location = geocode_data['candidates'][0]['location']
        x, y = location['x'], location['y']
        
        # Step 2: Query Zoning layer (Layer 1 - Zoning - Unincorporated)
        zoning_url = "https://egis.pinellas.gov/gis/rest/services/PublicWebGIS/Landuse_Zoning/MapServer/1/query"
        zoning_params = {
            'geometry': f"{x},{y}",
            'geometryType': 'esriGeometryPoint',
            'inSR': '4326',
            'spatialRel': 'esriSpatialRelIntersects',
            'outFields': 'ZONEDESC',
            'returnGeometry': 'false',
            'f': 'json'
        }
        
        zoning_response = session.get(zoning_url, params=zoning_params, timeout=15)
        zoning_data = zoning_response.json()
        
        zoning_code = ''
        zoning_desc = ''
        if zoning_data.get('features'):
            zoning_attrs = zoning_data['features'][0]['attributes']
            zoning_code = zoning_attrs.get('ZONEDESC', '')  # This returns the CODE
            # Look up the description from fetched or fallback dictionary
            zoning_desc = zoning_lookup.get(zoning_code, '')
        
        # Step 3: Query Future Land Use layer (Layer 0)
        flu_url = "https://egis.pinellas.gov/gis/rest/services/PublicWebGIS/Landuse_Zoning/MapServer/0/query"
        flu_params = {
            'geometry': f"{x},{y}",
            'geometryType': 'esriGeometryPoint',
            'inSR': '4326',
            'spatialRel': 'esriSpatialRelIntersects',
            'outFields': 'LANDUSECODE,LANDUSEDESC',
            'returnGeometry': 'false',
            'f': 'json'
        }
        
        flu_response = session.get(flu_url, params=flu_params, timeout=15)
        flu_data = flu_response.json()
        
        flu_code = ''
        flu_desc = ''
        if flu_data.get('features'):
            flu_attrs = flu_data['features'][0]['attributes']
            # Get the code from either field (they both return the code)
            flu_code = flu_attrs.get('LANDUSECODE') or flu_attrs.get('LANDUSEDESC', '')
            # Look up the description from fetched or fallback dictionary
            flu_desc = flu_lookup.get(flu_code, '')
        
        return {
            'success': True,
            'zoning_code': zoning_code,
            'zoning_description': zoning_desc,
            'future_land_use': flu_code,
            'future_land_use_description': flu_desc
        }
        
    except Exception as e:
        return {'success': False, 'error': f'Unincorporated zoning lookup error: {str(e)}'}

def lookup_clearwater_zoning(address):
    """
    Lookup zoning and FLU for Clearwater properties.
    Uses Clearwater's own GIS services.
    
    Returns: dict with zoning_code, zoning_description, future_land_use, future_land_use_description
    """
    if not address:
        return {'success': False, 'error': 'Address required for zoning lookup'}
    
    session = get_resilient_session()
    
    try:
        # Step 1: Geocode the address
        search_url = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
        geocode_params = {
            'SingleLine': f"{address}, Clearwater, FL",
            'f': 'json',
            'outFields': '*'
        }
        
        geocode_response = session.get(search_url, params=geocode_params, timeout=15)
        geocode_data = geocode_response.json()
        
        if not geocode_data.get('candidates'):
            return {'success': False, 'error': 'Could not geocode address'}
        
        # Get coordinates
        location = geocode_data['candidates'][0]['location']
        x, y = location['x'], location['y']
        
        # Step 2: Query Zoning layer
        zoning_url = "https://gis.myclearwater.com/arcgis/rest/services/ArcGISMapServices/Zoning_WGS84/MapServer/1/query"
        zoning_params = {
            'geometry': f"{x},{y}",
            'geometryType': 'esriGeometryPoint',
            'inSR': '4326',
            'spatialRel': 'esriSpatialRelIntersects',
            'outFields': 'ZONING,ZONING_DESC',
            'returnGeometry': 'false',
            'f': 'json'
        }
        
        zoning_response = session.get(zoning_url, params=zoning_params, timeout=15)
        zoning_data = zoning_response.json()
        
        zoning_code = ''
        zoning_desc = ''
        if zoning_data.get('features'):
            zoning_attrs = zoning_data['features'][0]['attributes']
            zoning_code = zoning_attrs.get('ZONING', '')
            zoning_desc = zoning_attrs.get('ZONING_DESC', '')
        
        # Step 3: Query Future Land Use layer (Layer 0 confirmed)
        # Fetch coded values for FLU
        flu_lookup = fetch_coded_values(
            "https://gis.myclearwater.com/arcgis/rest/services/ArcGISMapServices/FLU_w_PPC_Colors_WGS84/MapServer/0",
            "LU"
        )
        
        flu_url = "https://gis.myclearwater.com/arcgis/rest/services/ArcGISMapServices/FLU_w_PPC_Colors_WGS84/MapServer/0/query"
        flu_params = {
            'geometry': f"{x},{y}",
            'geometryType': 'esriGeometryPoint',
            'inSR': '4326',
            'spatialRel': 'esriSpatialRelIntersects',
            'outFields': 'LU',  # The actual field name!
            'returnGeometry': 'false',
            'f': 'json'
        }
        
        flu_response = session.get(flu_url, params=flu_params, timeout=15)
        flu_data = flu_response.json()
        
        flu_code = ''
        flu_desc = ''
        if flu_data.get('features'):
            flu_attrs = flu_data['features'][0]['attributes']
            flu_code = flu_attrs.get('LU', '')
            # Look up description from coded values
            flu_desc = flu_lookup.get(flu_code, '')
        
        return {
            'success': True,
            'zoning_code': zoning_code,
            'zoning_description': zoning_desc,
            'future_land_use': flu_code,
            'future_land_use_description': flu_desc
        }
        
    except Exception as e:
        return {'success': False, 'error': f'Clearwater zoning lookup error: {str(e)}'}

def lookup_largo_zoning(address, parcel_data=None):
    """
    Lookup zoning and FLU for Largo properties.
    Largo uses Future Land Use classification instead of traditional zoning.
    Queries Largo's parcel layer for Countywide_Plan_Map_Category_1.
    
    Args:
        address: Property address
        parcel_data: Not used (kept for compatibility)
    
    Returns: dict with zoning_code, future_land_use, descriptions
    """
    if not address:
        return {'success': False, 'error': 'Address required'}
    
    session = get_resilient_session()
    
    try:
        # Step 1: Geocode the address
        search_url = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
        geocode_params = {
            'SingleLine': f"{address}, Largo, FL",
            'f': 'json',
            'outFields': '*'
        }
        
        geocode_response = session.get(search_url, params=geocode_params, timeout=15)
        geocode_data = geocode_response.json()
        
        if not geocode_data.get('candidates'):
            return {'success': False, 'error': 'Could not geocode address'}
        
        # Get coordinates
        location = geocode_data['candidates'][0]['location']
        x, y = location['x'], location['y']
        
        # Step 2: Query Largo parcel layer for Countywide Plan category
        parcel_url = "https://maps.largo.com/arcgis/rest/services/Largo_GIS_Viewer_Map/MapServer/247/query"
        parcel_params = {
            'geometry': f"{x},{y}",
            'geometryType': 'esriGeometryPoint',
            'inSR': '4326',
            'spatialRel': 'esriSpatialRelIntersects',
            'outFields': 'Countywide_Plan_Map_Category_1',
            'returnGeometry': 'false',
            'f': 'json'
        }
        
        parcel_response = session.get(parcel_url, params=parcel_params, timeout=15)
        parcel_data_result = parcel_response.json()
        
        flu_value = ''
        if parcel_data_result.get('features'):
            attrs = parcel_data_result['features'][0]['attributes']
            flu_value = attrs.get('Countywide_Plan_Map_Category_1', '')
        
        if flu_value:
            return {
                'success': True,
                'zoning_code': flu_value,  # Largo uses FLU as zoning
                'zoning_description': None,  # Already combined in flu_value
                'future_land_use': flu_value,  # Same as zoning for Largo
                'future_land_use_description': None  # Already combined
            }
        else:
            return {
                'success': False,
                'error': 'Could not retrieve Countywide Plan category from Largo parcel layer'
            }
        
    except Exception as e:
        return {'success': False, 'error': f'Largo lookup error: {str(e)}'}

def lookup_pinellas_zoning(city_name, address, parcel_data=None):
    """
    Router function: Lookup zoning for Pinellas County based on city.
    Routes to appropriate lookup function based on jurisdiction.
    
    Args:
        city_name: City name (e.g., "St. Petersburg", "Lealman", "Clearwater", "Largo")
        address: Property address (e.g., "200 CENTRAL AVE")
        parcel_data: Optional parcel data from PCPAO lookup (used for Largo)
        
    Returns:
        dict with zoning_code, zoning_description, future_land_use, future_land_use_description
    """
    if not address:
        return {'success': False, 'error': 'Address required for zoning lookup'}
    
    # Route based on jurisdiction
    if 'St. Petersburg' in city_name or 'St Petersburg' in city_name:
        # St. Petersburg has its own GIS layers
        return lookup_stpete_zoning(address)
    elif 'Clearwater' in city_name:
        # Clearwater has its own GIS services
        return lookup_clearwater_zoning(address)
    elif 'Largo' in city_name:
        # Largo uses FLU instead of traditional zoning
        return lookup_largo_zoning(address, parcel_data)
    elif is_unincorporated(city_name):
        # Unincorporated areas use Pinellas County layers
        return lookup_unincorporated_zoning(address)
    else:
        # Other municipalities - not yet implemented
        return {
            'success': True,
            'zoning_code': 'Contact City for zoning',
            'zoning_description': None,
            'future_land_use': None,
            'future_land_use_description': None,
            'note': f'City-specific zoning data for {city_name} not yet implemented'
        }

def lookup_stpete_zoning(address):
    """
    Lookup zoning for St. Petersburg properties using St. Pete GIS layers.
    (Renamed from original lookup_pinellas_zoning St. Pete section)
    
    Args:
        address: Property address (e.g., "200 CENTRAL AVE")
        
    Returns:
        dict with zoning_code, zoning_description, future_land_use, future_land_use_description
    """
    session = get_resilient_session()
    
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
        return {'success': False, 'error': f'St. Pete zoning lookup error: {str(e)}'}
    
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

st.title("🏠 Florida Property Lookup - Multi-County")
st.caption("Lookup property data for Pinellas and Hillsborough Counties")
st.markdown("---")

# County Selector
st.subheader("Input")
county = st.selectbox("County", ["Pinellas", "Hillsborough"], key="county_selector")

# Input field changes based on county
if county == "Pinellas":
    parcel_id_input = st.text_input(
        "Parcel ID",
        placeholder="e.g., 19-31-17-73166-001-0010",
        help="Pinellas County parcel ID with dashes",
        key="parcel_input"
    )
else:  # Hillsborough
    parcel_id_input = st.text_input(
        "Folio Number",
        placeholder="e.g., 109054.1000",
        help="Hillsborough County folio number",
        key="parcel_input"
    )

# Lookup Buttons
if st.button("🔍 Lookup Property Info", type="primary"):
    if not parcel_id_input:
        st.error("Please enter a parcel ID or folio")
    else:
        if county == "Pinellas":
            # Validate
            is_valid, error_msg = validate_parcel_id(parcel_id_input)
            if not is_valid:
                st.error(f"❌ {error_msg}")
            else:
                with st.spinner("Fetching property data from PCPAO API..."):
                    result = scrape_pinellas_property(parcel_id_input)
                    
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
        
        else:  # Hillsborough
            with st.spinner("Fetching property data from Hillsborough County..."):
                result = lookup_hillsborough_parcel(parcel_id_input)
                
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

# Second button for zoning/FLU lookup (always show after parcel ID entered)
st.markdown("---")

if county == "Pinellas":
    st.caption("🔍 **For Pinellas County properties:** Lookup detailed zoning and Future Land Use from GIS layers (St. Petersburg, Clearwater, Largo, and unincorporated areas)")
else:
    st.caption("🔍 **For Hillsborough County properties:** Lookup detailed zoning and Future Land Use from GIS layers")

if st.button("🗺️ Lookup Zoning & Future Land Use", type="secondary"):
    city = st.session_state.get('api_city', '')
    address = st.session_state.get('api_address', '')
    
    if not address:
        st.error("❌ Please run Property Lookup first to get the address")
    else:
        if county == "Pinellas":
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
                
                # Show which jurisdiction was queried
                if 'St. Petersburg' in city or 'St Petersburg' in city:
                    st.success(f"✅ Zoning data updated from St. Petersburg GIS layers!")
                elif 'Clearwater' in city:
                    st.success(f"✅ Zoning data updated from Clearwater GIS layers!")
                elif 'Largo' in city:
                    st.success(f"✅ Zoning/FLU data updated (Largo uses Future Land Use classification)!")
                elif 'Unincorporated' in city:
                    st.success(f"✅ Zoning data updated from Pinellas County (unincorporated) layers!")
                else:
                    st.success(f"✅ Zoning data updated!")
                
                st.rerun()
            else:
                st.error(f"❌ {zoning_result.get('error', 'Unable to fetch zoning data')}")
        
        else:  # Hillsborough
            with st.spinner(f"Fetching zoning/FLU data for {address}..."):
                zoning_result = lookup_hillsborough_zoning_flu(address)
                
                if zoning_result.get('success'):
                    # Update zoning
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
st.subheader("Results - All Property Data")
st.caption("These fields auto-fill after successful lookup")

col_left, col_right = st.columns(2)

with col_left:
    st.text_input(
        "City (auto-filled)",
        key='api_city',
        placeholder="Will auto-fill",
        help="City name from Property Appraiser"
    )
    
    st.text_input(
        "Address (auto-filled)",
        key='api_address',
        placeholder="Will auto-fill",
        help="Property address from Property Appraiser"
    )
    
    st.text_input(
        "ZIP Code (auto-filled)",
        key='api_zip',
        placeholder="Will auto-fill",
        help="ZIP code from Property Appraiser"
    )
    
    st.text_input(
        "Property Use (auto-filled)",
        key='api_land_use',
        placeholder="Will auto-fill",
        help="Property land use classification"
    )

with col_right:
    st.text_input(
        "Owner (auto-filled)",
        key='api_owner',
        placeholder="Will auto-fill",
        help="Property owner from Property Appraiser"
    )
    
    st.text_input(
        "Zoning (auto-filled)",
        key='api_zoning',
        placeholder="Will auto-fill from GIS layers",
        help="Zoning district from county GIS layers"
    )
    
    st.text_input(
        "Future Land Use (auto-filled)",
        key='api_flu',
        placeholder="Will auto-fill from GIS layers",
        help="Future Land Use from county GIS layers"
    )
    
    st.text_input(
        "Land Area (acres)",
        key='land_area_acres',
        placeholder="Will auto-fill",
        help="Acreage from Property Appraiser"
    )

st.text_input(
    "Land Area (square feet)",
    key='land_area_sqft',
    placeholder="Will auto-fill (Pinellas only)",
    help="Square footage from Property Appraiser"
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
