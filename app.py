"""
Development Services Proposal Generator
Streamlit web application for generating professional proposal documents
With Kimley-Horn header and footer
"""

import streamlit as st
from datetime import date
from io import BytesIO
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_ROW_HEIGHT_RULE, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import re
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def strip_dor_code(land_use_text):
    """
    Remove Florida DOR (Department of Revenue) code prefix from land use descriptions.
    All Florida counties use standardized DOR codes (00-99) with descriptions.
    
    Examples:
        "1832 General Office Bldg - multi-story/campus" → "General Office Bldg - multi-story/campus"
        "01 Single Family" → "Single Family"
        "17 Office buildings, one story" → "Office buildings, one story"
        "Commercial" → "Commercial" (no change if no code)
    
    Args:
        land_use_text: Raw land use string from county API
        
    Returns:
        Clean description without DOR code prefix
    """
    if not land_use_text:
        return ''
    
    text = land_use_text.strip()
    
    # Check if starts with digits followed by space
    if text and text[0].isdigit():
        # Split on first space after digits
        parts = text.split(' ', 1)
        if len(parts) > 1:
            return parts[1].strip()  # Return description without code
    
    return text  # Return as-is if no code found


# ============================================================================
# COUNTY API CONFIGURATION
# ============================================================================

COUNTY_CONFIG = {
    "Hillsborough": {
        "url": "https://www25.swfwmd.state.fl.us/arcgis12/rest/services/BaseVector/parcel_search/MapServer/7/query",
        "field": "FOLIONUM",
        "id_type": "Folio",
        "timeout": 15
    },
    "Manatee": {
        "url": "https://www.mymanatee.org/gisits/rest/services/opendata/Planning/MapServer/22/query",
        "field": "PIN",
        "id_type": "Folio",
        "timeout": 10
    },
    "Pinellas": {
        "url": "https://egis.pinellas.gov/gis/rest/services/Accela/AccelaAddressParcel/MapServer/1/query",
        "field": "PGIS.PGIS.Parcels.PARCELID",
        "id_type": "Parcel",
        "timeout": 10
    },
    "Pasco": {
        "url": "https://egis.pascocountyfl.net/arcgis/rest/services/basemap/PropertyLayers/MapServer/0/query",
        "field": "PARCEL_ID",
        "id_type": "Parcel",
        "timeout": 10
    },
    "Sarasota": {
        "url": "https://gis1.scpafl.org/arcgis/rest/services/public/parcels/MapServer/0/query",
        "field": "PARCELNO",
        "id_type": "Parcel",
        "timeout": 10
    }
}

# ============================================================================
# INPUT VALIDATION & SECURITY
# ============================================================================

def validate_parcel_id(parcel_id: str) -> tuple[bool, str]:
    """
    Validate parcel/folio ID input to prevent SQL injection and invalid formats.
    
    Returns:
        tuple: (is_valid, error_message)
    """
    if not parcel_id:
        return False, "Parcel ID cannot be empty"
    
    if len(parcel_id) > 30:
        return False, "Parcel ID must be 30 characters or less"
    
    # Allowlist: only alphanumeric, dashes, spaces, periods
    if not re.match(r'^[A-Za-z0-9\-\s\.]+$', parcel_id):
        return False, "Invalid characters in parcel ID. Only letters, numbers, dashes, spaces, and periods allowed"
    
    # Block SQL injection patterns
    dangerous_patterns = ['--', '/*', '*/', 'DROP', 'DELETE', 'INSERT', 'UPDATE', 'UNION', 'SELECT']
    upper_parcel = parcel_id.upper()
    
    for pattern in dangerous_patterns:
        if pattern in upper_parcel:
            # Check if it's a standalone SQL keyword (not part of a street name)
            if pattern in ['OR', 'AND']:
                if re.search(rf'\b{pattern}\b', upper_parcel):
                    return False, f"Invalid pattern detected: {pattern}"
            else:
                return False, f"Invalid character sequence: {pattern}"
    
    return True, ""

def sanitize_for_sql(value: str) -> str:
    """
    Sanitize string for use in SQL WHERE clause.
    Escapes single quotes by doubling them.
    """
    return value.strip().replace("'", "''")

# ============================================================================
# HTTP SESSION WITH RETRY LOGIC
# ============================================================================

@st.cache_resource
def get_resilient_session() -> requests.Session:
    """
    Create HTTP session with automatic retry logic for failed requests.
    Uses exponential backoff: 1s, 2s, 4s delays.
    """
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
# TASK DESCRIPTIONS DATABASE
# ============================================================================

DEFAULT_FEES = {
    '110': {'name': 'Civil Engineering Design', 'amount': 40000, 'type': 'Hourly, Not-to-Exceed'},
    '120': {'name': 'Civil Schematic Design', 'amount': 35000, 'type': 'Hourly, Not-to-Exceed'},
    '130': {'name': 'Civil Design Development', 'amount': 45000, 'type': 'Hourly, Not-to-Exceed'},
    '140': {'name': 'Civil Construction Documents', 'amount': 50000, 'type': 'Hourly, Not-to-Exceed'},
    '150': {'name': 'Civil Permitting', 'amount': 40000, 'type': 'Hourly, Not-to-Exceed'},
    '210': {'name': 'Meetings and Coordination', 'amount': 20000, 'type': 'Hourly, Not-to-Exceed'},
    '310': {'name': 'Civil Construction Phase Services', 'amount': 35000, 'type': 'Lump Sum'}
}

TASK_DESCRIPTIONS = {
    '110': [
        "Kimley-Horn will prepare an onsite drainage report with supporting calculations showing the proposed development plan is consistent with the Southwest Florida Water Management District Basis of Review. This design will account for the stormwater design to support the development of the project site. The drainage report will include limited stormwater modeling to demonstrate that the Lot A site development will maintain the existing discharge rate and provide the required stormwater attenuation.",
        "The onsite drainage report will include calculations for 25-year 24-hour and 100-year 24-hour design storm conditions in accordance with Southwest Florida Water Management District Guidelines. A base stormwater design will be provided for the project site showing reasonable locations for stormwater conveyance features and stormwater management pond sizing."
    ],
    '120': [
        "Kimley-Horn will prepare Civil Schematic Design deliverables in accordance with the Client's Design Project Deliverables Checklist. For the Civil Schematic Design task, the deliverables that Kimley-Horn will provide consist of Civil Site Plan, Establish Finish Floor Elevations, Utility Will Serve Letters and Points of Service, Utility Routing and Easement Requirements."
    ],
    '130': [
        "Upon Client approval of the Schematic Design task, Kimley-Horn will prepare Design Development Plans of the civil design in accordance with the Client's Design Project Deliverables Checklist for Civil Design Development Deliverables. These documents will be approximately 50% complete and will include detail for City code review and preliminary pricing but will not include enough detail for construction bidding."
    ],
    '140': [
        "Based on the approved Development Plan, Kimley-Horn will provide engineering and design services for the preparation of site construction plans for on-site improvements.",
        "Cover Sheet",
        "The cover sheet includes plan contents, vicinity map, legal description and team identification.",
        "General Notes",
        "These sheets will provide general notes for the construction of the project.",
        "Existing Conditions / Demolition Plan",
        "Consisting of the boundary, topographic, and tree survey provided by others. This sheet will include and identify the required demolition of the existing items on the project site and facilities improvements prior to construction of the proposed site and facilities improvements.",
        "Stormwater Pollution Prevention Plan",
        "This sheet will include and identify stormwater best management practices for the construction of the proposed site including erosion control and stormwater management areas; applicable details, and specifications. This sheet may also be combined with the Existing Conditions/Demolition Plan sheets depending on the scope of the work.",
        "Site Plan (Horizontal Control & Signing and Marking Plan)",
        "Kimley-Horn shall prepare a Site Plan, as indicated above, with associated parking and infrastructure. Site Plan shall consist of the following: site geometry, building setbacks; roadway and parking dimensions including handicap spaces; landscape island locations and dimensions; storm water detention area locations and dimensions; boundary dimensions; dimensions and locations of pedestrian walks; signing and marking design. Signing and Marking within the structured parking as well as loading areas and compactors (if applicable) to be designed by the Architect.",
        "Paving, Grading, and Drainage Plan",
        "Kimley-Horn shall design and prepare a plan for the site paving, grading and drainage systems in accordance with the City, the FDOT, and the Water Management District (SWFWMD) to consist of: flood routing; pipe materials and sizing; grate and invert elevations; surface parking including pavement structural section (as provided by owner's geotechnical report); subgrade treatment; curbs; horizontal control; sidewalks; driveway connections; spot elevations and elevation contours; and construction details and specifications, and erosion and sedimentation control measures.",
        "**NOTE:**Any structural retaining walls are not included with this scope and shall be designed and permitted by others. Hardscape areas shall be designed by others, therefore paving, grading and drainage of these areas is not included. Stub-out connections for the hardscape drainage areas will be shown per direction from the Hardscape designer.",
        "Detailed grading and drainage design for any proposed pool deck or amenity area is to be designed and coordinated by the Architect and the MEP. Kimley-Horn can provide these services if requested by the client as additional services.",
        "Utility Plans",
        "Kimley-Horn shall prepare a plan for the site water distribution and sanitary sewer collection systems consisting of: sewer main locations; pipe sizing; manhole locations; rim and invert elevations; sewer lateral locations and size; existing sewer main connection; main location; materials and sizing; fire hydrant locations; water service locations; fire service locations and sizes; pipe materials; meter locations; sample points; existing water main connections; and construction details and specifications. Kimley-Horn will design the sanitary sewer to discharge to the adjacent development collection system. No upgrades to the off-site infrastructure. Should this be required during design and permitting, this will be submitted as an additional service.",
        "**NOTE:**Kimley-Horn's contract does not include the design of the fire lines from the designated point of service (P.O.S.) up to 1' above the building finished floor as those lines will need to be sized and designed by a licensed fire sprinkler engineer and permitted separately.",
        "Kimley-Horn has assumed utilities are available and have adequate capacity to accommodate the proposed development. Kimley-Horn assumes the utilities are located at the project boundary and will not require off-site utility extensions. If off-site extensions are needed, they will be provided as additional services. Lift station, force main, and pump design and permitting, if needed, is not included but can be provided as an Additional Service if needed.",
        "It is assumed a private lift station will not be required to serve this development, therefore lift station design is not included in this scope.",
        "Kimley-Horn shall show any existing utility locations on the utility plans as provided by the surveyor, and research applicable utility records for locations in accordance with best available information.",
        "Dedicated Fire Lines and Combination Domestic Water / Fire Lines, if needed, shall be designed and permitted by a licensed Fire Contractor Class I, II or V per NFPA 24 and is not included in this scope of services. Those lines will be shown on the Civil plans for permitting and reference only.",
        "Routing of proposed dry utilities such as gas, electric, telephone or cable service connections is not included in this scope of services and should be provided by others. Kimley-Horn will meet with the project team to incorporate dry utility routing as provided to us into our utility plans for coordination purposes.",
        "Street lighting design, photometrics and site electrical plans will be provided by the Client's Architect or Architect's MEP. Overhead electrical lines and transformers will be designed and located by the site electrical designer or local provider but will be placed on the Construction plans for coordination.",
        "Civil Details and Construction Specifications",
        "Kimley-Horn shall prepare construction details for site work improvements and erosion and sediment control measures. Typically, these details will correspond with City standard details. Standard FDOT details will not be provided but will be referenced throughout the plans.",
        "**NOTE:**A specifications package is not included in this scope of services as specifications are per authority having jurisdiction (AHJ). Preparation of detailed specifications to be supplied with the architect's specifications can be provided, per request, as additional services."
    ],
    '150': [
        "Prepare and submit on the Client's behalf the following permitting packages for review/approval of construction documents, and attend meetings required to obtain the following Agency approvals:",
        "Southwest Florida Water Management District Environmental Resource Permit – Minor Modification",
        "City of Tampa Water Department Commitment / Construction Plan Approval",
        "Hillsborough County Environmental Protection Commission",
        "Kimley-Horn will coordinate with the City of Tampa Development Review and coordination with the Florida Department of Transportation and the Hillsborough County departments as needed to obtain the necessary regulatory and utility approval of the site plans and associated drainage facilities. We will assist the Client with meetings necessary to gain site plan approval.",
        "This scope does not anticipate a Geotechnical or Environmental Assessment Report, Survey, Topographic Survey, or Arborist Report be required for this permit application.",
        "It is assumed Client will provide the needed information regarding the development program and requirements. Kimley-Horn will work with the Owner and their team to integrate the necessary design requirements into the Civil design to support entitlement, platting, and development approvals.",
        "These permit applications will be submitted using the electronic permitting submittal system (web-based system) for the respective jurisdictions where applicable."
    ],
    '210': [
        "Kimley-Horn will be available to provide miscellaneous project support at the direction of the Client. This task may include design meetings, additional permit support, permit research, or other miscellaneous tasks associated with the initial and future development of the project site. This task will also cover tasks such as design coordination meetings, scheduling, coordination with other client consultants, responses to additional rounds of agency comments."
    ],
    '310': [
        "Engineering construction phase services will be performed in connection with site improvements designed by Kimley-Horn. The scope of this task assumes construction phase services will be performed concurrent and in coordination with one General Contractor for the entire project. This task does not include constructing the project in multiple phases. Kimley-Horn construction phase services will include the following:",
        "Provide for review of shop drawings and submittals required for the site improvements controlled by our design documents. Kimley-Horn has included up to {shop_drawing_hours} hours for review of shop drawings and samples.",
        "Review and reply to Contractor's request(s) for information during construction phase. Kimley-Horn has included up to {rfi_hours} hours for response to RFI's.",
        "Attendance at up to {oac_meetings} one-hour each Owner-Architect-Contractor (OAC) virtual meetings.",
        "Kimley-Horn will visit the construction site during the duration of construction for an estimated total of up to {site_visits} site visits at two-hours each to observe the progress of the civil components of work completed.",
        "Provide up to two (2) reviews of 'as-built' documents, submitted by General Contractor's registered land surveyor.",
        "Kimley-Horn will prepare Record Drawings for potable water and sanitary sewer only. Kimley-Horn has included up to {record_drawing_hours} hours for record drawing preparation.",
        "Kimley-Horn will submit FDEP water and sewer clearance submittals based on as-built information provided by the Contractor.",
        "Kimley-Horn shall submit a Letter of General Compliance for the civil related components of construction to the AHJ.",
        "Submit Certification of Completion to the Water Management District (WMD).",
        "The above hours allocated to the respective construction phase services may be interchangeable amongst the construction phase services outlined in this task, however the total number of hours included within the entirety of the task is up to {total_hours} hours."
    ]
}

# ============================================================================
# PERMIT CONFIGURATION BY COUNTY
# ============================================================================

PERMIT_MAPPING = {
    "Pinellas": {
        "ahj_name": "Pinellas County",
        "wmd": "Southwest Florida Water Management District",
        "wmd_short": "SWFWMD",
        "default_permits": ["ahj", "wmd_erp", "sewer", "water"]
    },
    "Hillsborough": {
        "ahj_name": "Hillsborough County",
        "wmd": "Southwest Florida Water Management District", 
        "wmd_short": "SWFWMD",
        "default_permits": ["ahj", "wmd_erp", "sewer", "water"]
    },
    "Pasco": {
        "ahj_name": "Pasco County",
        "wmd": "Southwest Florida Water Management District",
        "wmd_short": "SWFWMD", 
        "default_permits": ["ahj", "wmd_erp", "sewer", "water"]
    },
    "Manatee": {
        "ahj_name": "Manatee County",
        "wmd": "Southwest Florida Water Management District",
        "wmd_short": "SWFWMD",
        "default_permits": ["ahj", "wmd_erp", "sewer", "water"]
    },
    "Sarasota": {
        "ahj_name": "Sarasota County",
        "wmd": "Southwest Florida Water Management District",
        "wmd_short": "SWFWMD",
        "default_permits": ["ahj", "wmd_erp", "sewer", "water"]
    },
    "Polk": {
        "ahj_name": "Polk County",
        "wmd": "Southwest Florida Water Management District",
        "wmd_short": "SWFWMD",
        "default_permits": ["ahj", "wmd_erp", "sewer", "water"]
    }
}

# ============================================================================
# PROPERTY LOOKUP FUNCTIONS
# ============================================================================

@st.cache_data(ttl=3600, show_spinner=False)
def lookup_hillsborough_property(parcel_id):
    """
    Lookup property from Hillsborough County via SWFWMD regional service.
    FOLIO format: Remove dash (192605-0030 becomes 1926050030)
    """
    # Validate input
    is_valid, error_msg = validate_parcel_id(parcel_id)
    if not is_valid:
        return {'success': False, 'error': f'Invalid input: {error_msg}'}
    
    session = get_resilient_session()
    base_url = COUNTY_CONFIG["Hillsborough"]["url"]
    timeout = COUNTY_CONFIG["Hillsborough"]["timeout"]
    
    # Remove dash and sanitize
    folio_normalized = sanitize_for_sql(parcel_id.replace('-', ''))
    
    params = {
        'where': f"FOLIONUM='{folio_normalized}'",
        'outFields': '*',
        'returnGeometry': 'false',
        'f': 'json'
    }
    
    try:
        response = session.get(base_url, params=params, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        
        # Check for ArcGIS error in response body (HTTP 200 with error)
        if 'error' in data:
            error = data['error']
            return {
                'success': False,
                'error': f"GIS Error {error.get('code', 'Unknown')}: {error.get('message', 'Unknown error')}"
            }
        
        if data.get('features') and len(data['features']) > 0:
            attr = data['features'][0]['attributes']
            
            # Calculate acres from square feet if available
            acres = None
            sqft = attr.get('TOTLVAREA') or attr.get('ACSQFT')
            if sqft:
                try:
                    acres = float(sqft) / 43560
                except (ValueError, TypeError):
                    pass
            
            return {
                'success': True,
                'address': attr.get('SITUSADD1', ''),
                'city': attr.get('SCITY', 'TAMPA'),
                'zip': attr.get('SZIP', ''),
                'owner': attr.get('OWNERNAME', ''),
                'land_use': strip_dor_code(attr.get('PARUSEDESC', '')),
                'zoning': attr.get('ZONING') or 'Contact City/County for zoning info',
                'site_area_sqft': sqft,
                'site_area_acres': f"{acres:.2f}" if acres else None,
                'legal_description': attr.get('LEGALDESC', ''),
                'subdivision': attr.get('SUBDIVNAME', ''),
                'error': None
            }
        else:
            return {
                'success': False,
                'error': f'Folio {folio_normalized} not found in Hillsborough County database'
            }
    
    except requests.exceptions.Timeout:
        return {'success': False, 'error': 'Request timed out. The county GIS server may be slow. Please try again.'}
    except requests.exceptions.ConnectionError:
        return {'success': False, 'error': 'Could not connect to Hillsborough County GIS server. Please check your internet connection.'}
    except requests.exceptions.HTTPError as e:
        return {'success': False, 'error': f'HTTP Error {e.response.status_code}: {e.response.reason}'}
    except ValueError as e:
        return {'success': False, 'error': f'Invalid data format from server: {str(e)}'}
    except Exception as e:
        return {'success': False, 'error': f'Unexpected error: {str(e)}'}

@st.cache_data(ttl=3600, show_spinner=False)
def lookup_manatee_property(parcel_id):
    """
    Lookup property from Manatee County.
    Excellent data completeness - all fields in single layer.
    """
    # Validate input
    is_valid, error_msg = validate_parcel_id(parcel_id)
    if not is_valid:
        return {'success': False, 'error': f'Invalid input: {error_msg}'}
    
    session = get_resilient_session()
    base_url = COUNTY_CONFIG["Manatee"]["url"]
    timeout = COUNTY_CONFIG["Manatee"]["timeout"]
    
    # Sanitize input
    sanitized_id = sanitize_for_sql(parcel_id)
    
    params = {
        'where': f"PIN='{sanitized_id}'",
        'outFields': '*',
        'returnGeometry': 'false',
        'f': 'json'
    }
    
    try:
        response = session.get(base_url, params=params, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        
        # Check for ArcGIS error in response body
        if 'error' in data:
            error = data['error']
            return {
                'success': False,
                'error': f"GIS Error {error.get('code', 'Unknown')}: {error.get('message', 'Unknown error')}"
            }
        
        if data.get('features') and len(data['features']) > 0:
            attr = data['features'][0]['attributes']
            
            # Calculate acres from square feet if available
            acres = None
            sqft = attr.get('TOTAL_SQFT') or attr.get('CALC_ACRES')
            if sqft and 'SQFT' in str(sqft):
                try:
                    acres = float(sqft) / 43560
                except (ValueError, TypeError):
                    pass
            elif attr.get('CALC_ACRES'):
                try:
                    acres = float(attr.get('CALC_ACRES'))
                    sqft = acres * 43560
                except (ValueError, TypeError):
                    pass
            
            return {
                'success': True,
                'address': attr.get('PRIMARY_ADDRESS', ''),
                'city': attr.get('PROP_CITYNAME', ''),
                'zip': attr.get('PROP_ZIP', ''),
                'owner': attr.get('OWNER', ''),
                'land_use': strip_dor_code(attr.get('FUTURE_LAND_USE', '')),
                'zoning': attr.get('ZONING', ''),
                'site_area_sqft': sqft,
                'site_area_acres': f"{acres:.2f}" if acres else None,
                'legal_description': attr.get('LEGAL_DESCRIPTION', ''),
                'subdivision': attr.get('SUBDIVISION', ''),
                'error': None
            }
        else:
            return {'success': False, 'error': 'Folio ID not found in Manatee County database'}
    
    except requests.exceptions.Timeout:
        return {'success': False, 'error': 'Request timed out. The county GIS server may be slow. Please try again.'}
    except requests.exceptions.ConnectionError:
        return {'success': False, 'error': 'Could not connect to Manatee County GIS server. Please check your internet connection.'}
    except requests.exceptions.HTTPError as e:
        return {'success': False, 'error': f'HTTP Error {e.response.status_code}: {e.response.reason}'}
    except ValueError as e:
        return {'success': False, 'error': f'Invalid data format from server: {str(e)}'}
    except Exception as e:
        return {'success': False, 'error': f'Unexpected error: {str(e)}'}

def lookup_pinellas_acreage(parcel_id):
    """
    Get acreage from PcpaBaseMap Tax Parcels layer.
    This layer has numeric STATEDAREA field (not string like AccelaAddressParcel).
    
    Args:
        parcel_id: Parcel ID in format 19-31-17-73166-001-0010
        
    Returns:
        Float acres value or None if not found
    """
    session = get_resilient_session()
    url = "https://egis.pinellas.gov/pcpagis/rest/services/PcpaBaseMap/BaseMapParcelAerialsFlood/MapServer/75/query"
    
    params = {
        'where': f"PARCELID='{parcel_id}'",
        'outFields': 'STATEDAREA,STATEDAREAUNIT,CALCULATEDAREA',
        'returnGeometry': 'false',
        'f': 'json'
    }
    
    try:
        response = session.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        if data.get('features'):
            attrs = data['features'][0]['attributes']
            area = attrs.get('STATEDAREA')
            unit = attrs.get('STATEDAREAUNIT')
            
            if area:
                # Unit code 109402 = Acre, 109401 = Hectare
                if unit == 109401:  # Convert hectares to acres
                    return float(area) * 2.47105
                return float(area)  # Already in acres
        
        return None
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def lookup_pinellas_property(parcel_id):
    """
    Lookup property from Pinellas County.
    Uses Accela/AccelaAddressParcel layer per Property Lookup guide.
    Note: May require join with Site Address Points layer for complete data.
    """
    # Validate input
    is_valid, error_msg = validate_parcel_id(parcel_id)
    if not is_valid:
        return {'success': False, 'error': f'Invalid input: {error_msg}'}
    
    session = get_resilient_session()
    base_url = COUNTY_CONFIG["Pinellas"]["url"]
    timeout = COUNTY_CONFIG["Pinellas"]["timeout"]
    
    # Sanitize input
    sanitized_id = sanitize_for_sql(parcel_id)
    
    # Use correct field name from config
    field_name = COUNTY_CONFIG["Pinellas"]["field"]
    params = {
        'where': f"{field_name}='{sanitized_id}'",
        'outFields': '*',
        'returnGeometry': 'true',  # Changed to true to get geometry for zoning lookup
        'f': 'json'
    }
    
    try:
        response = session.get(base_url, params=params, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        
        # Check for ArcGIS error in response body
        if 'error' in data:
            error = data['error']
            return {
                'success': False,
                'error': f"GIS Error {error.get('code', 'Unknown')}: {error.get('message', 'Unknown error')}"
            }
        
        if data.get('features') and len(data['features']) > 0:
            feature = data['features'][0]
            attr = feature['attributes']
            geometry = feature.get('geometry', {})
            
            # Get acreage from web scraping ONLY
            scraped_result = scrape_pinellas_property(parcel_id)
            
            acres = None
            sqft = None
            debug_scrape_result = scraped_result.get('site_area_acres', 'NOT IN SCRAPE RESULT')
            
            if scraped_result.get('success') and scraped_result.get('site_area_acres'):
                try:
                    acres = float(scraped_result.get('site_area_acres'))
                    sqft = acres * 43560
                except (ValueError, TypeError):
                    pass  # Keep as None if conversion fails
            
            # Per Property Lookup guide, Pinellas fields are:
            # Address: LEGAL + join needed
            # City: JURISDICTION  
            # Owner: Join with RP_ALL_OWNERS needed
            # Future Land Use: PROPOSEDLANDUSE
            # Zoning: ZONECLASS
            
            address = attr.get('LEGAL') or attr.get('SITEADDRESS') or ''
            city = attr.get('JURISDICTION') or attr.get('CITY') or ''
            zip_code = attr.get('ZIP') or attr.get('ZIPCODE') or ''
            owner = attr.get('OWNERNAME') or attr.get('OWNER') or attr.get('NAME') or ''
            land_use = attr.get('PROPOSEDLANDUSE') or attr.get('LANDUSE') or ''
            zoning = attr.get('ZONECLASS') or attr.get('ZONING') or ''
            
            # Check if API returned empty/incomplete data (need at least address OR owner)
            has_useful_data = bool(address and city) or bool(owner and address)
            
            if not has_useful_data:
                # Fallback to PCPAO API for complete data
                scraped_result = scrape_pinellas_property(parcel_id)
                if scraped_result['success']:
                    return scraped_result
                # If PCPAO API also fails, return what we have from ArcGIS (even if empty)
            
            return {
                'success': True,
                'address': address,
                'city': city,
                'zip': str(zip_code) if zip_code else '',
                'owner': owner,
                'land_use': strip_dor_code(land_use),
                'zoning': zoning or 'Contact City/County for zoning info',
                'site_area_sqft': sqft,
                'site_area_acres': f"{acres:.2f}" if acres else None,
                'legal_description': attr.get('LEGAL_DESC') or attr.get('LEGALDESC') or '',
                'subdivision': attr.get('SUBDIVISION') or attr.get('SUBDIV') or '',
                'geometry': geometry,  # Store geometry for zoning lookup
                'error': None,
                '_debug_scrape_acres': debug_scrape_result
            }
        else:
            # Parcel not found in API - try web scraping
            scraped_result = scrape_pinellas_property(parcel_id)
            if scraped_result['success']:
                # Add debug info to scraped result before returning
                scraped_result['_debug_scrape_acres'] = scraped_result.get('site_area_acres', 'N/A')
                return scraped_result
            return {'success': False, 'error': 'Parcel ID not found in Pinellas County database'}
    
    except requests.exceptions.Timeout:
        return {'success': False, 'error': 'Request timed out. The county GIS server may be slow. Please try again.'}
    except requests.exceptions.ConnectionError:
        return {'success': False, 'error': 'Could not connect to Pinellas County GIS server. Please check your internet connection.'}
    except requests.exceptions.HTTPError as e:
        return {'success': False, 'error': f'HTTP Error {e.response.status_code}: {e.response.reason}'}
    except ValueError as e:
        return {'success': False, 'error': f'Invalid data format from server: {str(e)}'}
    except Exception as e:
        return {'success': False, 'error': f'Unexpected error: {str(e)}'}


def lookup_pinellas_zoning(city_name, address):
    """
    Lookup zoning for Pinellas County using the property address.
    For St. Petersburg: Queries St. Pete zoning API
    
    Args:
        city_name: City name (e.g., "St. Petersburg")
        address: Property address from property lookup (e.g., "200 CENTRAL AVE")
        
    Returns:
        dict with zoning_code, zoning_description, future_land_use, acreage
    """
    if not address:
        return {'success': False, 'error': 'Address required for zoning lookup'}
    
    session = get_resilient_session()
    
    # St. Petersburg zoning lookup
    if 'St. Petersburg' in city_name or 'St Petersburg' in city_name:
        try:
            # Use the Find/Search endpoint that the web map uses
            # Based on the map URL pattern: find=200%20CENTRAL%20AVE
            search_url = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
            
            # Geocode the address to get coordinates
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
            
            # Now query zoning layer with those coordinates
            zoning_url = "https://egis.stpete.org/arcgis/rest/services/ServicesDOTS/Zoning/MapServer/0/query"
            zoning_params = {
                'geometry': f"{x},{y}",
                'geometryType': 'esriGeometryPoint',
                'inSR': '4326',  # WGS84 from geocoder
                'spatialRel': 'esriSpatialRelIntersects',
                'outFields': 'ZONECLASS,ZONEDESC,SHAPE.AREA',
                'returnGeometry': 'false',
                'f': 'json'
            }
            
            zoning_response = session.get(zoning_url, params=zoning_params, timeout=15)
            zoning_data = zoning_response.json()
            
            if zoning_data.get('features'):
                attrs = zoning_data['features'][0]['attributes']
                
                # Query Future Land Use layer
                flu_url = "https://egis.stpete.org/arcgis/rest/services/ServicesDOTS/Zoning/MapServer/2/query"
                flu_params = {
                    'geometry': f"{x},{y}",
                    'geometryType': 'esriGeometryPoint',
                    'inSR': '4326',
                    'spatialRel': 'esriSpatialRelIntersects',
                    'outFields': '*',  # Get all fields to capture description if available
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
                    # Try common description field names
                    flu_desc = (flu_attrs.get('LANDUSEDESC') or 
                               flu_attrs.get('DESCRIPTION') or 
                               flu_attrs.get('DESC') or 
                               flu_attrs.get('LAND_USE_DESC') or '')
                
                return {
                    'success': True,
                    'zoning_code': attrs.get('ZONECLASS', ''),
                    'zoning_description': attrs.get('ZONEDESC', ''),
                    'future_land_use': flu_code,
                    'future_land_use_description': flu_desc,
                    'acreage': None,  # Use acreage from property lookup instead
                    'jurisdiction': 'St. Petersburg'
                }
            else:
                return {'success': False, 'error': 'No zoning found at address location'}
                
        except Exception as e:
            return {'success': False, 'error': f'Zoning lookup error: {str(e)}'}
    
    # Other cities
    return {
        'success': True,
        'zoning_code': 'Contact City/County for zoning',
        'zoning_description': None,
        'future_land_use': None,
        'acreage': None,
        'jurisdiction': city_name,
        'note': 'City-specific zoning data not available via API'
    }




def scrape_pinellas_property(parcel_id):
    """
    Query Pinellas County Property Appraiser searchProperty API.
    This is the backend API that the PCPAO website uses.
    URL: https://www.pcpao.gov/dal/quicksearch/searchProperty
    """
    session = get_resilient_session()
    
    url = "https://www.pcpao.gov/dal/quicksearch/searchProperty"
    
    # Normalize Pinellas parcel ID format
    # Input might be: 193117731660010010 (18 digits)
    # Need format: 19-31-17-73166-001-0010 (with dashes)
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
            return {'success': False, 'error': 'Parcel not found in PCPAO database', '_debug_api_response': data}
        
        # Parse the HTML response within the JSON
        # The API returns HTML snippets in the 'data' array
        if not data.get('data') or len(data['data']) == 0:
            return {'success': False, 'error': 'No property data returned', '_debug_api_response': data}
        
        # Get first result (data[0] contains array of HTML snippets for each column)
        result_row = data['data'][0]
        
        # Parse the HTML snippets to extract clean data
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return {'success': False, 'error': 'BeautifulSoup not installed - check requirements.txt'}
        
        # Extract data from HTML snippets
        # Column 2: Owner name
        owner_html = result_row[2] if len(result_row) > 2 else ''
        owner_soup = BeautifulSoup(owner_html, 'lxml')
        owner = owner_soup.get_text(strip=True)
        
        # Column 4: Parcel number (to verify)
        parcel_html = result_row[4] if len(result_row) > 4 else ''
        parcel_soup = BeautifulSoup(parcel_html, 'lxml')
        parcel = parcel_soup.get_text(strip=True)
        
        # Column 5: Address
        address_html = result_row[5] if len(result_row) > 5 else ''
        address_soup = BeautifulSoup(address_html, 'lxml')
        address = address_soup.get_text(strip=True)
        
        # Column 6: Tax District
        tax_dist_html = result_row[6] if len(result_row) > 6 else ''
        tax_dist_soup = BeautifulSoup(tax_dist_html, 'lxml')
        tax_district = tax_dist_soup.get_text(strip=True)
        
        # Column 7: Property Use / DOR Code
        use_html = result_row[7] if len(result_row) > 7 else ''
        use_soup = BeautifulSoup(use_html, 'lxml')
        property_use = use_soup.get_text(strip=True)
        
        # Column 8: Legal Description
        legal_html = result_row[8] if len(result_row) > 8 else ''
        legal_soup = BeautifulSoup(legal_html, 'lxml')
        legal_desc = legal_soup.get_text(strip=True)
        
        # Extract city from tax district or address
        # Pinellas cities: Clearwater, St. Petersburg, Largo, Pinellas Park, etc.
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
        
        # Get acreage from detail page - extract from "Land Area" text
        sqft = None
        acres = None
        detail_debug = "Not attempted"
        
        try:
            # Use property-details URL format matching the working test script
            strap = normalized_parcel.replace('-', '')
            detail_url = (
                f"https://www.pcpao.gov/property-details?"
                f"basemap=BaseMapParcelAerials&"
                f"input={normalized_parcel}&"
                f"parcel={normalized_parcel}&"
                f"s={strap}&"
                f"search_option=parcel_number"
            )
            detail_debug = f"URL: {detail_url}"
            
            detail_response = session.get(detail_url, timeout=15)
            detail_response.raise_for_status()
            detail_html = detail_response.text
            detail_debug = f"Page loaded, length: {len(detail_html)}"
            
            # Parse HTML and get all text
            soup = BeautifulSoup(detail_html, 'lxml')
            text = soup.get_text(" ", strip=True)
            
            # Check if "Land Area" text exists at all
            if "Land Area" in text:
                detail_debug = f"'Land Area' found in page text"
            else:
                detail_debug = f"'Land Area' NOT found in page text"
            
            # Match pattern: "Land Area: ≅ 59,560 sf | ≅ 1.36 acres"
            match = re.search(r"Land Area:\s*≅\s*([\d,]+)\s*sf\s*\|\s*≅\s*([\d.]+)\s*acres", text)
            if match:
                sqft = int(match.group(1).replace(",", ""))
                acres = float(match.group(2))
                detail_debug = f"Match found! sqft={sqft}, acres={acres}"
            else:
                detail_debug = f"Regex did not match. Text snippet around 'Land': {text[text.find('Land'):text.find('Land')+200] if 'Land' in text else 'N/A'}"
                    
        except Exception as e:
            detail_debug = f"Exception: {str(e)[:100]}"
            pass  # If detail page fails, sqft and acres remain None
        
        return {
            'success': True,
            'address': address,
            'city': city,
            'zip': '',  # Not provided in search results
            'owner': owner,
            'land_use': strip_dor_code(property_use),
            'zoning': 'Contact City/County for zoning info',  # Not in search results
            'site_area_sqft': sqft,
            'site_area_acres': f"{acres:.2f}" if acres else None,
            'legal_description': legal_desc,
            'subdivision': '',
            'error': None,
            '_debug_detail_scrape': detail_debug
        }
    
    except requests.exceptions.Timeout:
        return {'success': False, 'error': 'Request timed out accessing Pinellas Property Appraiser API.'}
    except requests.exceptions.ConnectionError:
        return {'success': False, 'error': 'Could not connect to Pinellas Property Appraiser API.'}
    except requests.exceptions.HTTPError as e:
        return {'success': False, 'error': f'HTTP Error {e.response.status_code}: {e.response.reason}'}
    except Exception as e:
        return {'success': False, 'error': f'Error querying PCPAO API: {str(e)}'}

@st.cache_data(ttl=3600, show_spinner=False)
def lookup_pasco_property(parcel_id):
    """
    Lookup property from Pasco County.
    Uses Pasco County GIS service.
    """
    # Validate input
    is_valid, error_msg = validate_parcel_id(parcel_id)
    if not is_valid:
        return {'success': False, 'error': f'Invalid input: {error_msg}'}
    
    session = get_resilient_session()
    base_url = COUNTY_CONFIG["Pasco"]["url"]
    timeout = COUNTY_CONFIG["Pasco"]["timeout"]
    
    # Sanitize input
    sanitized_id = sanitize_for_sql(parcel_id)
    
    params = {
        'where': f"PARCEL_ID='{sanitized_id}' OR FOLIO='{sanitized_id}'",
        'outFields': '*',
        'returnGeometry': 'false',
        'f': 'json'
    }
    
    try:
        response = session.get(base_url, params=params, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        
        # Check for ArcGIS error in response body
        if 'error' in data:
            error = data['error']
            return {
                'success': False,
                'error': f"GIS Error {error.get('code', 'Unknown')}: {error.get('message', 'Unknown error')}"
            }
        
        if data.get('features') and len(data['features']) > 0:
            attr = data['features'][0]['attributes']
            
            # Calculate acres from square feet if available
            acres = None
            sqft = attr.get('LANDAREA') or attr.get('TOTAL_AREA')
            if sqft:
                try:
                    acres = float(sqft) / 43560
                except (ValueError, TypeError):
                    pass
            
            return {
                'success': True,
                'address': attr.get('SITUS_ADDRESS', '') or attr.get('SITEADDR', ''),
                'city': attr.get('SITUS_CITY', ''),
                'zip': attr.get('SITUS_ZIP', ''),
                'owner': attr.get('OWNER_NAME', '') or attr.get('OWNER1', ''),
                'land_use': strip_dor_code(attr.get('LANDUSE_DESC', '')),
                'zoning': attr.get('ZONING') or 'Contact City/County for zoning info',
                'site_area_sqft': sqft,
                'site_area_acres': f"{acres:.2f}" if acres else None,
                'legal_description': attr.get('LEGAL_DESC', ''),
                'subdivision': attr.get('SUBDIVISION', ''),
                'error': None
            }
        else:
            return {'success': False, 'error': 'Parcel ID not found in Pasco County database'}
    
    except requests.exceptions.Timeout:
        return {'success': False, 'error': 'Request timed out. The county GIS server may be slow. Please try again.'}
    except requests.exceptions.ConnectionError:
        return {'success': False, 'error': 'Could not connect to Pasco County GIS server. Please check your internet connection.'}
    except requests.exceptions.HTTPError as e:
        return {'success': False, 'error': f'HTTP Error {e.response.status_code}: {e.response.reason}'}
    except ValueError as e:
        return {'success': False, 'error': f'Invalid data format from server: {str(e)}'}
    except Exception as e:
        return {'success': False, 'error': f'Unexpected error: {str(e)}'}

@st.cache_data(ttl=3600, show_spinner=False)
def lookup_sarasota_property(parcel_id):
    """
    Lookup property from Sarasota County.
    Uses Sarasota County Property Appraiser GIS service.
    """
    # Validate input
    is_valid, error_msg = validate_parcel_id(parcel_id)
    if not is_valid:
        return {'success': False, 'error': f'Invalid input: {error_msg}'}
    
    session = get_resilient_session()
    base_url = COUNTY_CONFIG["Sarasota"]["url"]
    timeout = COUNTY_CONFIG["Sarasota"]["timeout"]
    
    # Sanitize input
    sanitized_id = sanitize_for_sql(parcel_id)
    
    params = {
        'where': f"PARCELNO='{sanitized_id}' OR PARCEL_ID='{sanitized_id}'",
        'outFields': '*',
        'returnGeometry': 'false',
        'f': 'json'
    }
    
    try:
        response = session.get(base_url, params=params, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        
        # Check for ArcGIS error in response body
        if 'error' in data:
            error = data['error']
            return {
                'success': False,
                'error': f"GIS Error {error.get('code', 'Unknown')}: {error.get('message', 'Unknown error')}"
            }
        
        if data.get('features') and len(data['features']) > 0:
            attr = data['features'][0]['attributes']
            
            # Calculate acres from square feet if available
            acres = None
            sqft = attr.get('LOT_SIZE') or attr.get('TOTAL_AREA')
            if sqft:
                try:
                    acres = float(sqft) / 43560
                except (ValueError, TypeError):
                    pass
            
            return {
                'success': True,
                'address': attr.get('SITUS_ADDRESS', '') or attr.get('PHY_ADDR', ''),
                'city': attr.get('SITUS_CITY', '') or attr.get('PHY_CITY', ''),
                'zip': attr.get('SITUS_ZIP', '') or attr.get('PHY_ZIP', ''),
                'owner': attr.get('OWNER_NAME', '') or attr.get('OWNNAME1', ''),
                'land_use': strip_dor_code(attr.get('LANDUSE', '') or attr.get('DOR_UC', '')),
                'zoning': attr.get('ZONING') or 'Contact City/County for zoning info',
                'site_area_sqft': sqft,
                'site_area_acres': f"{acres:.2f}" if acres else None,
                'legal_description': attr.get('LEGAL', ''),
                'subdivision': attr.get('SUBDIVISION', '') or attr.get('SUBDIV', ''),
                'error': None
            }
        else:
            return {'success': False, 'error': 'Parcel ID not found in Sarasota County database'}
    
    except requests.exceptions.Timeout:
        return {'success': False, 'error': 'Request timed out. The county GIS server may be slow. Please try again.'}
    except requests.exceptions.ConnectionError:
        return {'success': False, 'error': 'Could not connect to Sarasota County GIS server. Please check your internet connection.'}
    except requests.exceptions.HTTPError as e:
        return {'success': False, 'error': f'HTTP Error {e.response.status_code}: {e.response.reason}'}
    except ValueError as e:
        return {'success': False, 'error': f'Invalid data format from server: {str(e)}'}
    except Exception as e:
        return {'success': False, 'error': f'Unexpected error: {str(e)}'}


def lookup_property_info(county, parcel_id):
    """Lookup property info based on county."""
    if county == "Hillsborough":
        return lookup_hillsborough_property(parcel_id)
    elif county == "Manatee":
        return lookup_manatee_property(parcel_id)
    elif county == "Pinellas":
        return lookup_pinellas_property(parcel_id)
    elif county == "Pasco":
        return lookup_pasco_property(parcel_id)
    elif county == "Sarasota":
        return lookup_sarasota_property(parcel_id)
    else:
        return {'success': False, 'error': f'{county} County lookup not yet implemented. Please enter information manually.'}

# ============================================================================
# DOCUMENT GENERATION FUNCTIONS
# ============================================================================

def set_cell_background(cell, color_hex):
    """Set cell background color."""
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    existing_shd = tcPr.find(qn('w:shd'))
    if existing_shd is not None:
        tcPr.remove(existing_shd)
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), color_hex)
    tcPr.append(shd)


def set_cell_margins(cell, top=20, bottom=20, start=40, end=40):
    """Set cell margins in twips."""
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    existing = tcPr.find(qn('w:tcMar'))
    if existing is not None:
        tcPr.remove(existing)
    tcMar = OxmlElement('w:tcMar')
    for margin_name, value in [('top', top), ('bottom', bottom), ('start', start), ('end', end)]:
        margin = OxmlElement(f'w:{margin_name}')
        margin.set(qn('w:w'), str(value))
        margin.set(qn('w:type'), 'dxa')
        tcMar.append(margin)
    tcPr.append(tcMar)


def remove_table_borders(table):
    """Remove all borders from table."""
    tbl = table._tbl
    tblPr = tbl.tblPr
    if tblPr is None:
        tblPr = OxmlElement('w:tblPr')
        tbl.insert(0, tblPr)
    existing = tblPr.find(qn('w:tblBorders'))
    if existing is not None:
        tblPr.remove(existing)
    tblBorders = OxmlElement('w:tblBorders')
    for border_name in ['top', 'left', 'bottom', 'right', 'insideH', 'insideV']:
        border = OxmlElement(f'w:{border_name}')
        border.set(qn('w:val'), 'nil')
        tblBorders.append(border)
    tblPr.append(tblBorders)


def create_header(section):
    """Create Kimley-Horn header."""
    header = section.header
    header.is_linked_to_previous = False
    
    header_table = header.add_table(rows=1, cols=2, width=Inches(6.5))
    header_table.autofit = False
    header_table.columns[0].width = Inches(5.0)
    header_table.columns[1].width = Inches(1.5)
    
    tbl = header_table._tbl
    tblPr = tbl.tblPr if tbl.tblPr is not None else OxmlElement('w:tblPr')
    tblBorders = OxmlElement('w:tblBorders')
    for border_name in ['top', 'left', 'bottom', 'right', 'insideH', 'insideV']:
        border = OxmlElement(f'w:{border_name}')
        border.set(qn('w:val'), 'none')
        tblBorders.append(border)
    tblPr.append(tblBorders)
    if tbl.tblPr is None:
        tbl.insert(0, tblPr)
    
    logo_cell = header_table.cell(0, 0)
    logo_cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    logo_para = logo_cell.paragraphs[0]
    logo_para.alignment = WD_ALIGN_PARAGRAPH.LEFT
    logo_para.clear()
    
    run1 = logo_para.add_run("Kimley")
    run1.font.size = Pt(28)
    run1.font.bold = False
    run1.font.color.rgb = RGBColor(88, 89, 91)
    run1.font.name = 'Arial Narrow'
    
    run2 = logo_para.add_run("»")
    run2.font.size = Pt(28)
    run2.font.bold = False
    run2.font.color.rgb = RGBColor(88, 89, 91)
    run2.font.name = 'Arial Narrow'
    
    run3 = logo_para.add_run("Horn")
    run3.font.size = Pt(28)
    run3.font.bold = False
    run3.font.color.rgb = RGBColor(166, 25, 46)
    run3.font.name = 'Arial Narrow'
    
    page_cell = header_table.cell(0, 1)
    page_cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    page_para = page_cell.paragraphs[0]
    page_para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    
    run = page_para.add_run('Page ')
    run.font.name = 'Arial'
    run.font.size = Pt(11)
    run.font.italic = True
    run.font.color.rgb = RGBColor(0, 0, 0)
    
    fldChar1 = OxmlElement('w:fldChar')
    fldChar1.set(qn('w:fldCharType'), 'begin')
    instrText = OxmlElement('w:instrText')
    instrText.set(qn('xml:space'), 'preserve')
    instrText.text = 'PAGE'
    fldChar2 = OxmlElement('w:fldChar')
    fldChar2.set(qn('w:fldCharType'), 'end')
    run._r.append(fldChar1)
    run._r.append(instrText)
    run._r.append(fldChar2)


def create_footer(section):
    """Create Kimley-Horn footer."""
    footer = section.footer
    footer.is_linked_to_previous = False
    
    widths = [Inches(1.1), Inches(0.01), Inches(4.23), Inches(0.01), Inches(0.96)]
    colors = ['5F5F5F', None, 'A20C33', None, 'A20C33']
    texts = ['kimley-horn.com', '', '200 Central Avenue Suite 600 St. Petersburg, FL 33701', '', '(727) 822-5150']
    
    table = footer.add_table(rows=1, cols=5, width=sum(widths))
    table.allow_autofit = False
    remove_table_borders(table)
    
    row = table.rows[0]
    row.height = Inches(0.22)
    row.height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
    
    for idx, cell in enumerate(row.cells):
        table.columns[idx].width = widths[idx]
        cell.width = widths[idx]
        
        if colors[idx]:
            set_cell_background(cell, colors[idx])
        
        # Only set margins for colored cells, not gap cells
        if colors[idx]:
            set_cell_margins(cell, top=20, bottom=20, start=40, end=40)
        else:
            # Gap cells get zero margins for precise 0.01" spacing
            set_cell_margins(cell, top=0, bottom=0, start=0, end=0)
        
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        
        if texts[idx]:
            para = cell.paragraphs[0]
            para.paragraph_format.space_before = Pt(0)
            para.paragraph_format.space_after = Pt(0)
            para.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
            para.clear()
            
            run = para.add_run(texts[idx])
            run.font.name = 'Arial'
            run.font.size = Pt(8)
            run.font.color.rgb = RGBColor(255, 255, 255)


def add_opening_section(doc, client_info, project_info):
    """Add opening section with proper letterhead format matching DS template."""
    
    # Date at top
    date_para = doc.add_paragraph()
    date_para.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = date_para.add_run(project_info['date'])
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    date_para.paragraph_format.space_after = Pt(0)
    date_para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()
    
    # Client Name (short name)
    para = doc.add_paragraph()
    run = para.add_run(client_info['name'])
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    
    # Legal Entity Name (exact per SunBiz)
    para = doc.add_paragraph()
    run = para.add_run(client_info.get('legal_entity', client_info['name']))
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    
    # Entity Address Line 1
    para = doc.add_paragraph()
    run = para.add_run(client_info['address1'])
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    
    # Entity Address Line 2
    para = doc.add_paragraph()
    run = para.add_run(client_info['address2'])
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()
    
    # "Re:" line with project info
    para = doc.add_paragraph()
    run = para.add_run('Re:\t' + project_info["name"])
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    
    # Project address (if available)
    if project_info.get('address'):
        para = doc.add_paragraph()
        run = para.add_run('\t' + project_info['address'])
        run.font.name = 'Arial'
        run.font.size = Pt(10)
        para.paragraph_format.space_after = Pt(0)
        para.paragraph_format.line_spacing = 1.0
    
    # City, State
    para = doc.add_paragraph()
    run = para.add_run('\t' + project_info.get('city_state_zip', project_info['city'] + ', Florida'))
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()
    
    # "Dear Client:" salutation
    para = doc.add_paragraph()
    run = para.add_run(f'Dear {client_info["contact"]}:')
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()
    
    # Opening paragraph
    para = doc.add_paragraph()
    opening_text = f'Kimley-Horn and Associates, Inc. ("Kimley-Horn") is pleased to submit this letter agreement (the "Agreement") to {client_info.get("legal_entity", client_info["name"])} ("the Client") for professional consulting services for the above referenced project.'
    run = para.add_run(opening_text)
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()


def add_project_understanding(doc, project_info, assumptions):
    """Add Project Understanding section with user's description and assumptions."""
    
    # Section heading - BOLD + CENTERED (no underline per template)
    para = doc.add_paragraph()
    run = para.add_run('PROJECT UNDERSTANDING')
    run.font.name = 'Arial'
    run.font.size = Pt(11)
    run.font.bold = True
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()
    
    # User's project description/understanding - JUSTIFIED
    if project_info.get('description'):
        para = doc.add_paragraph()
        run = para.add_run(project_info['description'])
        run.font.name = 'Arial'
        run.font.size = Pt(10)
        para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        para.paragraph_format.space_after = Pt(0)
        para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()
    
    # Assumptions intro
    para = doc.add_paragraph()
    run = para.add_run('Kimley-Horn understands the following in preparing this proposal:')
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()
    
    # Assumptions as bullet points
    for assumption in assumptions:
        para = doc.add_paragraph(style='List Bullet')
        run = para.add_run(assumption)
        run.font.name = 'Arial'
        run.font.size = Pt(10)
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        para.paragraph_format.space_after = Pt(0)
        para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()
    
    # Closing statement
    para = doc.add_paragraph()
    run = para.add_run('If any of these assumptions are not correct, then the scope and fee will change. Based on the above understanding, Kimley-Horn proposes the following scope of services:')
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()


def add_scope_of_services(doc, selected_tasks, permits, included_additional_services=None):
    """Add Scope of Services section."""
    
    if included_additional_services is None:
        included_additional_services = []
    
    # Section heading - BOLD + CENTERED (no underline per template)
    para = doc.add_paragraph()
    run = para.add_run('Scope of Services')
    run.font.name = 'Arial'
    run.font.size = Pt(11)
    run.font.bold = True
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()
    
    para = doc.add_paragraph()
    run = para.add_run('Kimley-Horn will provide the services specifically set forth below.')
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()
    
    sub_section_keywords = ['cover sheet', 'general notes', 'utility plan', 'site layout', 'site plan',
                           'grading plan', 'drainage plan', 'paving', 'erosion control',
                           'detail', 'existing conditions', 'demolition', 'stormwater pollution',
                           'civil details', 'construction specifications']
    
    for task_num in sorted(selected_tasks.keys()):
        task = selected_tasks[task_num]
        
        # Special handling for Task 310 - Construction Phase Services
        if task_num == '310' and 'hours' in task:
            hours = task['hours']
            descriptions = []
            for desc in TASK_DESCRIPTIONS[task_num]:
                # Replace hour placeholders
                desc = desc.replace('{shop_drawing_hours}', str(hours['shop_drawing']))
                desc = desc.replace('{rfi_hours}', str(hours['rfi']))
                desc = desc.replace('{oac_meetings}', str(hours['oac_meetings']))
                desc = desc.replace('{site_visits}', str(hours['site_visits']))
                desc = desc.replace('{record_drawing_hours}', str(hours['record_drawing']))
                desc = desc.replace('{total_hours}', str(hours['total']))
                descriptions.append(desc)
        # Special handling for Task 150 - Civil Permitting
        elif task_num == '150' and permits:
            descriptions = [
                "Kimley-Horn will prepare and submit on the Client's behalf the civil construction documents to the following agencies:"
            ]
            # Add permits as separate items for bullet point formatting
            descriptions.extend(permits)
            descriptions.extend([
                "Includes development of a Stormwater Ownership and Maintenance (O&M) Plan",
                "Kimley-Horn will respond to a maximum of three (3) requests for information during the agency review process for obtaining the above permits.",
                "**BOLD:**Permit fees and impact fees are not included. Kimley-Horn does not guarantee the issuance of permits or approvals."
            ])
        else:
            descriptions = TASK_DESCRIPTIONS[task_num]
        
        # Add blank line before task heading
        doc.add_paragraph()
        
        # Task heading - BOLD + UNDERLINED
        para = doc.add_paragraph()
        run = para.add_run(f'Task {task_num} – {task["name"].replace("Civil ", "")}')
        run.font.name = 'Arial'
        run.font.size = Pt(10)
        run.font.bold = True
        run.font.underline = True
        para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        para.paragraph_format.space_after = Pt(0)
        para.paragraph_format.line_spacing = 1.0
        
        # Removed: doc.add_paragraph() here - was creating double spacing
        
        permit_list_started = False
        
        for desc in descriptions:
            # Check if this is a permit item (short, from permits list)
            is_permit_bullet = (task_num == '150' and desc in permits)
            
            # Start bullet list after intro
            if task_num == '150' and 'following agencies:' in desc:
                para = doc.add_paragraph()
                run = para.add_run(desc)
                run.font.name = 'Arial'
                run.font.size = Pt(10)
                para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                para.paragraph_format.space_after = Pt(0)
                para.paragraph_format.line_spacing = 1.0
                doc.add_paragraph()
                permit_list_started = True
                continue
            
            if is_permit_bullet:
                # Permit as bullet point - INDENTED
                para = doc.add_paragraph(style='List Bullet')
                para.paragraph_format.left_indent = Inches(0.25)  # Indent for clarity
                run = para.add_run(desc)
                run.font.name = 'Arial'
                run.font.size = Pt(10)
                para.alignment = WD_ALIGN_PARAGRAPH.LEFT
                para.paragraph_format.space_after = Pt(0)
                para.paragraph_format.line_spacing = 1.0
                continue
            
            # End permit bullets, back to regular paragraphs
            if permit_list_started and not is_permit_bullet:
                permit_list_started = False
                doc.add_paragraph()
            
            # Check if bold text
            is_bold_para = desc.startswith('**BOLD:**')
            
            # Check if sub-section heading
            is_subsection = (len(desc) < 100 and 
                           any(kw in desc.lower() for kw in sub_section_keywords) and
                           not desc.endswith('.') and
                           not desc.startswith('**NOTE:**') and
                           not desc.startswith('**BOLD:**'))
            
            # Add one blank line before subsection headings OR notes
            if is_subsection or desc.startswith('**NOTE:**'):
                doc.add_paragraph()
            
            para = doc.add_paragraph()
            
            # Check if it's a note
            is_note = desc.startswith('**NOTE:**')
            
            if is_note:
                run = para.add_run(desc.replace('**NOTE:**', 'Note:'))
                run.font.name = 'Arial'
                run.font.size = Pt(10)
                run.font.bold = True
                run.font.italic = True
            elif is_bold_para:
                run = para.add_run(desc.replace('**BOLD:**', ''))
                run.font.name = 'Arial'
                run.font.size = Pt(10)
                run.font.bold = True
            else:
                run = para.add_run(desc)
                run.font.name = 'Arial'
                run.font.size = Pt(10)
                
                if is_subsection:
                    run.font.underline = True
            
            para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            para.paragraph_format.space_after = Pt(0)
            para.paragraph_format.line_spacing = 1.0
            
            # Add blank line after Note paragraphs
            if is_note:
                doc.add_paragraph()
    
    # Add included additional services (if any) as additional tasks
    if included_additional_services:
        doc.add_paragraph()
        
        # Add a note about additional services being included
        para = doc.add_paragraph()
        run = para.add_run('Additional Services Included in This Proposal:')
        run.font.name = 'Arial'
        run.font.size = Pt(10)
        run.font.bold = True
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        para.paragraph_format.space_after = Pt(6)
        para.paragraph_format.line_spacing = 1.0
        
        # List the included additional services as bullets
        for service in included_additional_services:
            para = doc.add_paragraph(style='List Bullet')
            run = para.add_run(service)
            run.font.name = 'Arial'
            run.font.size = Pt(10)
            para.alignment = WD_ALIGN_PARAGRAPH.LEFT
            para.paragraph_format.space_after = Pt(0)
            para.paragraph_format.line_spacing = 1.0
        
        doc.add_paragraph()


def add_scope_table(doc, selected_tasks, included_additional_services_with_fees=None):
    """Add Scope of Work table with optional additional services."""
    
    if included_additional_services_with_fees is None:
        included_additional_services_with_fees = {}
    
    # Calculate total including additional services
    total_fee = sum(task['fee'] for task in selected_tasks.values())
    total_fee += sum(included_additional_services_with_fees.values())
    
    # Calculate number of rows: header + regular tasks + additional services + total
    num_additional = len(included_additional_services_with_fees)
    num_rows = len(selected_tasks) + num_additional + 2
    
    table = doc.add_table(rows=num_rows, cols=4)
    table.style = 'Light Grid Accent 1'
    
    header_cells = table.rows[0].cells
    header_cells[0].text = 'Task Number & Name'
    header_cells[1].text = 'Task Number & Name'
    header_cells[2].text = 'Fee'
    header_cells[3].text = 'Type'
    
    for cell in header_cells:
        cell.paragraphs[0].runs[0].font.bold = True
        cell.paragraphs[0].runs[0].font.size = Pt(10)
        cell.paragraphs[0].runs[0].font.name = 'Arial'
    
    # Add regular tasks
    row_idx = 1
    for task_num, task in sorted(selected_tasks.items()):
        row = table.rows[row_idx]
        row.cells[0].text = task_num
        row.cells[1].text = task['name']
        row.cells[2].text = f'$ {task["fee"]:,}'
        row.cells[3].text = task['type']
        
        for cell in row.cells:
            cell.paragraphs[0].runs[0].font.size = Pt(10)
            cell.paragraphs[0].runs[0].font.name = 'Arial'
        
        row_idx += 1
    
    # Add included additional services as AS-1, AS-2, etc.
    as_num = 1
    for service_name, service_fee in included_additional_services_with_fees.items():
        row = table.rows[row_idx]
        row.cells[0].text = f'AS-{as_num}'
        row.cells[1].text = service_name
        row.cells[2].text = f'$ {service_fee:,}'
        row.cells[3].text = 'Hourly, Not-to-Exceed'
        
        for cell in row.cells:
            cell.paragraphs[0].runs[0].font.size = Pt(10)
            cell.paragraphs[0].runs[0].font.name = 'Arial'
        
        row_idx += 1
        as_num += 1
    
    # Total row
    total_row = table.rows[-1]
    total_row.cells[0].text = 'Total'
    total_row.cells[1].text = 'Total'
    total_row.cells[2].text = f'$ {total_fee:,}'
    total_row.cells[3].text = f'$ {total_fee:,}'
    
    for cell in total_row.cells:
        cell.paragraphs[0].runs[0].font.bold = True
        cell.paragraphs[0].runs[0].font.size = Pt(10)
        cell.paragraphs[0].runs[0].font.name = 'Arial'
    
    doc.add_paragraph()
    
    task_list = ', '.join(sorted(selected_tasks.keys()))
    para = doc.add_paragraph()
    run = para.add_run(f'Kimley-Horn will perform the services in Tasks {task_list} on a labor fee plus expense basis with the maximum labor fee shown above.')
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0


def add_additional_services_section(doc, excluded_additional_services):
    """Add ADDITIONAL SERVICES section per template - lists what's NOT included."""
    
    # Only add this section if there are excluded services to list
    if not excluded_additional_services:
        return
    
    # Section heading - BOLD + CENTERED + DARK RED (no underline per template)
    para = doc.add_paragraph()
    run = para.add_run('ADDITIONAL SERVICES')
    run.font.name = 'Arial'
    run.font.size = Pt(11)
    run.font.bold = True
    run.font.color.rgb = RGBColor(162, 12, 51)  # A20C33 - matches footer center column
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    
    # Opening paragraph
    para = doc.add_paragraph()
    text = 'Based on the information of which we are aware, we have prepared a proposal that we believe to be comprehensive. In the event that an unforeseen issue(s) should arise, we remain available to provide additional services, as requested by you, on the basis of our hourly rates or an agreed upon lump sum amount. Potential services not addressed in this proposal are:'
    run = para.add_run(text)
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    para.paragraph_format.space_after = Pt(6)
    para.paragraph_format.line_spacing = 1.0
    
    # List of excluded services (what's NOT included)
    for service in excluded_additional_services:
        para = doc.add_paragraph(style='List Bullet')
        run = para.add_run(service)
        run.font.name = 'Arial'
        run.font.size = Pt(10)
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        para.paragraph_format.space_after = Pt(0)
        para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()


def add_information_provided_section(doc):
    """Add INFORMATION PROVIDED BY THE CLIENT section per template."""
    
    # Section heading - BOLD + CENTERED + DARK RED (no underline per template)
    para = doc.add_paragraph()
    run = para.add_run('INFORMATION PROVIDED BY THE CLIENT')
    run.font.name = 'Arial'
    run.font.size = Pt(11)
    run.font.bold = True
    run.font.color.rgb = RGBColor(162, 12, 51)  # A20C33 - matches footer center column
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    
    # Opening paragraph
    para = doc.add_paragraph()
    text = 'The following information, upon which the consultant may rely, will be provided to Kimley-Horn by the Client or its representative:'
    run = para.add_run(text)
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    para.paragraph_format.space_after = Pt(6)
    para.paragraph_format.line_spacing = 1.0
    
    # List of items client must provide
    client_provided_items = [
        "Building footprints in AutoCAD format",
        "Boundary, Topographic, and Tree survey in AutoCAD format",
        "All Application/Permit Fees",
        "Geotechnical survey",
        "Building elevations"
    ]
    
    for item in client_provided_items:
        para = doc.add_paragraph(style='List Bullet')
        run = para.add_run(item)
        run.font.name = 'Arial'
        run.font.size = Pt(10)
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        para.paragraph_format.space_after = Pt(0)
        para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()


def add_client_responsibilities_section(doc):
    """Add CLIENT RESPONSIBILITIES section per template."""
    
    # Section heading - BOLD + CENTERED + DARK RED (no underline per template)
    para = doc.add_paragraph()
    run = para.add_run('CLIENT RESPONSIBILITIES')
    run.font.name = 'Arial'
    run.font.size = Pt(11)
    run.font.bold = True
    run.font.color.rgb = RGBColor(162, 12, 51)  # A20C33 - matches footer center column
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    
    # Opening paragraph
    para = doc.add_paragraph()
    text = 'In addition to other responsibilities set out in this Agreement, the Client shall:'
    run = para.add_run(text)
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    para.paragraph_format.space_after = Pt(6)
    para.paragraph_format.line_spacing = 1.0
    
    # List of client responsibilities
    client_responsibilities = [
        "Provide access to the project site(s) or other land which Kimley-Horn is conduct any field work in a timely manner.",
        "Provide prompt notice whenever it observes or otherwise becomes aware of any development that affects the scope or timing of Kimley-Horn's performance.",
        "Examine and provide comments and/or decisions with respect to any Kimley-Horn interim or final deliverables within a period mutually agreed upon."
    ]
    
    for responsibility in client_responsibilities:
        para = doc.add_paragraph(style='List Bullet')
        run = para.add_run(responsibility)
        run.font.name = 'Arial'
        run.font.size = Pt(10)
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        para.paragraph_format.space_after = Pt(0)
        para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()


def add_schedule_section(doc):
    """Add SCHEDULE section per template."""
    
    # Section heading - BOLD + CENTERED + DARK RED (no underline per template)
    para = doc.add_paragraph()
    run = para.add_run('SCHEDULE')
    run.font.name = 'Arial'
    run.font.size = Pt(11)
    run.font.bold = True
    run.font.color.rgb = RGBColor(162, 12, 51)  # A20C33 - matches footer center column
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    
    # Schedule paragraph
    para = doc.add_paragraph()
    text = 'Consultant shall provide the services described in the above scope as expeditiously as practical to meet a mutually agreed upon schedule. This Agreement is made in anticipation of continuous permitting conditions and orderly progress through completion of the services. The mutually agreed upon schedule shall be extended as necessary for delays or suspensions due to circumstances that the Consultant does not control.'
    run = para.add_run(text)
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    para.paragraph_format.space_after = Pt(6)
    para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()


def add_fee_and_billing_section(doc, selected_tasks):
    """Add FEE AND BILLING section per template - shows all applicable fee types."""
    
    # Section heading - BOLD + CENTERED + DARK RED (no underline per template)
    para = doc.add_paragraph()
    run = para.add_run('FEE AND BILLING')
    run.font.name = 'Arial'
    run.font.size = Pt(11)
    run.font.bold = True
    run.font.color.rgb = RGBColor(162, 12, 51)  # A20C33 - matches footer center column
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    
    # Group tasks by fee type
    lump_sum_tasks = []
    hourly_tasks = []
    hourly_nte_tasks = []
    
    for task_num, task in selected_tasks.items():
        fee_type = task.get('type', 'Hourly, Not-to-Exceed')
        if fee_type == 'Lump Sum':
            lump_sum_tasks.append(task_num)
        elif fee_type == 'Hourly':
            hourly_tasks.append(task_num)
        else:  # Hourly, Not-to-Exceed
            hourly_nte_tasks.append(task_num)
    
    # Add paragraph for each fee type that's used
    
    # Lump Sum paragraph
    if lump_sum_tasks:
        para = doc.add_paragraph()
        task_list = ', '.join(sorted(lump_sum_tasks))
        text = f'Kimley-Horn will perform the Services in Tasks {task_list} for the total lump sum labor fee shown in the table above.'
        run = para.add_run(text)
        run.font.name = 'Arial'
        run.font.size = Pt(10)
        para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        para.paragraph_format.space_after = Pt(6)
        para.paragraph_format.line_spacing = 1.0
    
    # Hourly (Cost Plus) paragraph
    if hourly_tasks:
        para = doc.add_paragraph()
        task_list = ', '.join(sorted(hourly_tasks))
        text = f'Kimley-Horn will perform the Services in Tasks {task_list} on a labor fee plus expense basis. Labor fee will be billed on an hourly basis according to Kimley-Horn\'s then-current rates.'
        run = para.add_run(text)
        run.font.name = 'Arial'
        run.font.size = Pt(10)
        para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        para.paragraph_format.space_after = Pt(6)
        para.paragraph_format.line_spacing = 1.0
    
    # Hourly Not-to-Exceed (Cost Plus Max) paragraph
    if hourly_nte_tasks:
        para = doc.add_paragraph()
        task_list = ', '.join(sorted(hourly_nte_tasks))
        text = f'Kimley-Horn will perform the services in Tasks {task_list} on a labor fee plus expense basis with the maximum labor fee shown in the table above. Labor fee will be billed on an hourly basis according to Kimley-Horn\'s then-current rates.'
        run = para.add_run(text)
        run.font.name = 'Arial'
        run.font.size = Pt(10)
        para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        para.paragraph_format.space_after = Pt(6)
        para.paragraph_format.line_spacing = 1.0
        
        # Add Not-to-exceed clause
        para = doc.add_paragraph()
        text = 'Kimley-Horn will not exceed the total maximum labor fee shown without authorization from the Client. However, Kimley-Horn reserves the right to reallocate amounts among tasks as necessary.'
        run = para.add_run(text)
        run.font.name = 'Arial'
        run.font.size = Pt(10)
        para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        para.paragraph_format.space_after = Pt(6)
        para.paragraph_format.line_spacing = 1.0
    
    # Direct reimbursable expenses paragraph (always included)
    para = doc.add_paragraph()
    text = 'Direct reimbursable expenses such as express delivery services, air travel, and other direct expenses are not included in the above fee table and will be billed at 1.15 times cost. A percentage of labor fee will be added to each invoice to cover certain other expenses such as telecommunications, in-house reproduction, postage, supplies, project related computer time, and local mileage. Administrative time related to the project will be billed hourly. All permitting, application, and similar project fees will be paid directly by the Client. Should the Client request Kimley-Horn to advance any such project fees on the Client\'s behalf, an invoice for such fees, with a fifteen percent (15%) markup, will be immediately issued to and paid by the Client.'
    run = para.add_run(text)
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    para.paragraph_format.space_after = Pt(6)
    para.paragraph_format.line_spacing = 1.0
    
    # Invoicing and payment terms
    para = doc.add_paragraph()
    text = 'Fees and expenses will be invoiced monthly based, as applicable, upon the percentage of services completed or actual services performed, plus expenses incurred as of the invoice date. Payment will be due within 25 days of the date of the invoice and should include the invoice number and Kimley-Horn project number.'
    run = para.add_run(text)
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    para.paragraph_format.space_after = Pt(6)
    para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()


def add_closure_section(doc, client_info, invoice_info):
    """Add CLOSURE section with signature blocks per template."""
    
    # Section heading - BOLD + CENTERED + DARK RED (no underline per template)
    para = doc.add_paragraph()
    run = para.add_run('CLOSURE')
    run.font.name = 'Arial'
    run.font.size = Pt(11)
    run.font.bold = True
    run.font.color.rgb = RGBColor(162, 12, 51)  # A20C33 - matches footer center column
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    
    # Standard Provisions reference
    para = doc.add_paragraph()
    text = f'In addition to the matters set forth herein, our Agreement shall include and be subject to, and only to, the terms and conditions in the attached Standard Provisions, which are incorporated by reference. As used in the Standard Provisions, the term "the Consultant" shall refer to Kimley-Horn and Associates, Inc., and the term "the Client" shall refer to {client_info.get("legal_entity", client_info.get("name", ""))}.'.strip()
    run = para.add_run(text)
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()
    
    # Electronic invoicing paragraph
    para = doc.add_paragraph()
    text = 'Kimley-Horn, in an effort to expedite invoices and reduce paper waste, offers its clients the option to receive electronic invoices. These invoices come via email in an Adobe PDF format. Please select a billing method from the choices below:'
    run = para.add_run(text)
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    para.paragraph_format.space_after = Pt(6)
    para.paragraph_format.line_spacing = 1.0
    
    # Invoice email line 1
    para = doc.add_paragraph()
    invoice_email = invoice_info.get('email', '_' * 60)
    run = para.add_run(f'____ Please email all invoices to {invoice_email}')
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.paragraph_format.space_after = Pt(3)
    para.paragraph_format.line_spacing = 1.0
    
    # Invoice CC email line 2
    para = doc.add_paragraph()
    invoice_cc_email = invoice_info.get('cc_email', '_' * 60)
    if invoice_cc_email:
        run = para.add_run(f'____ Please copy {invoice_cc_email}')
    else:
        run = para.add_run(f'____ Please copy {"_" * 60}')
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.paragraph_format.space_after = Pt(6)
    para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()
    
    # Closing paragraph with conditional retainer language
    para = doc.add_paragraph()
    
    # Build text based on whether retainer is required
    if invoice_info.get('use_retainer') and invoice_info.get('retainer_amount', 0) > 0:
        retainer_amt = invoice_info['retainer_amount']
        text = f'To proceed with the services, please have an authorized person sign this Agreement below and return to us with a retainer of ${retainer_amt:,}. We will commence services only after we have received a fully-executed agreement and a retainer in the amount of ${retainer_amt:,}. Fees and times stated in this Agreement are valid for sixty (60) days after the date of this letter.'
    else:
        text = 'To proceed with the services, please have an authorized person sign this Agreement below and return to us. We will commence services only after we have received a fully-executed agreement. Fees and times stated in this Agreement are valid for sixty (60) days after the date of this letter.'
    
    run = para.add_run(text)
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    para.paragraph_format.space_after = Pt(6)
    para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()
    
    # "We appreciate..." paragraph
    para = doc.add_paragraph()
    text = 'We appreciate the opportunity to provide these services to you. Please do not hesitate to contact me if you have any questions.'
    run = para.add_run(text)
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    para.paragraph_format.space_after = Pt(6)
    para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()
    
    # Sincerely
    para = doc.add_paragraph()
    run = para.add_run('Sincerely,')
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()
    
    # KIMLEY-HORN AND ASSOCIATES, INC.
    para = doc.add_paragraph()
    run = para.add_run('KIMLEY-HORN AND ASSOCIATES, INC.')
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    run.font.bold = True
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()
    doc.add_paragraph()
    
    # KH Signer Name
    para = doc.add_paragraph()
    kh_name = invoice_info.get('kh_signer_name', '[Name]')
    run = para.add_run(kh_name)
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    
    # KH Signer Title
    para = doc.add_paragraph()
    kh_title = invoice_info.get('kh_signer_title', '[Title]')
    run = para.add_run(kh_title)
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()
    doc.add_paragraph()
    
    # Client Name (legal entity)
    para = doc.add_paragraph()
    run = para.add_run(client_info.get('legal_entity', client_info.get('name', '')).upper())
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    run.font.bold = True
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()
    
    # Client signature lines
    para = doc.add_paragraph()
    run = para.add_run('SIGNED: _______________________________')
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.paragraph_format.space_after = Pt(6)
    para.paragraph_format.line_spacing = 1.0
    
    para = doc.add_paragraph()
    run = para.add_run('PRINTED NAME: _______________________')
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.paragraph_format.space_after = Pt(6)
    para.paragraph_format.line_spacing = 1.0
    
    para = doc.add_paragraph()
    run = para.add_run('TITLE:_________________________________')
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.paragraph_format.space_after = Pt(6)
    para.paragraph_format.line_spacing = 1.0
    
    para = doc.add_paragraph()
    run = para.add_run('DATE: _______________________________')
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    para.paragraph_format.space_after = Pt(6)
    para.paragraph_format.line_spacing = 1.0
    
    doc.add_paragraph()
    
    # Attachment reference
    para = doc.add_paragraph()
    run = para.add_run('Attachment – Standard Provisions')
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    run.font.italic = True
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0


def generate_proposal_document(client_info, project_info, selected_tasks, assumptions, permits, invoice_info, included_additional_services, included_additional_services_with_fees, excluded_additional_services, output_path):
    """Generate complete proposal document."""
    
    doc = Document()
    
    section = doc.sections[0]
    section.top_margin = Inches(1.0)
    section.bottom_margin = Inches(1.0)
    section.left_margin = Inches(1.0)
    section.right_margin = Inches(1.0)
    
    create_header(section)
    create_footer(section)
    
    add_opening_section(doc, client_info, project_info)
    add_project_understanding(doc, project_info, assumptions)
    add_scope_of_services(doc, selected_tasks, permits, included_additional_services)
    add_scope_table(doc, selected_tasks, included_additional_services_with_fees)
    add_information_provided_section(doc)
    add_client_responsibilities_section(doc)
    add_schedule_section(doc)
    add_fee_and_billing_section(doc, selected_tasks)
    add_additional_services_section(doc, excluded_additional_services)
    add_closure_section(doc, client_info, invoice_info)
    
    doc.save(output_path)
    return output_path

# ============================================================================
# STREAMLIT APP
# ============================================================================

st.set_page_config(
    page_title="Development Services Proposal Generator",
    page_icon="🏗️",
    layout="wide"
)

# ============================================================================
# STREAMLIT APP
# ============================================================================

st.set_page_config(
    page_title="Development Services Proposal Generator",
    page_icon="🏗️",
    layout="wide"
)

st.title("🏗️ Development Services Proposal Generator")
st.markdown("---")

# Create tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📍 Property & Client",
    "📋 Project & Assumptions",
    "✅ Scope of Services",
    "📧 Permitting & Summary",
    "💰 Invoice & Billing"
])

# TAB 1: Property & Client Information
with tab1:
    # Property lookup section
    def property_lookup_section():
        """Isolated property lookup section for better performance."""
        st.subheader("Property/Parcel Information")
        col_prop1, col_prop2, col_prop3 = st.columns(3)
        
        with col_prop1:
            county = st.selectbox(
                "County *",
                options=["", "Pinellas", "Hillsborough", "Pasco", "Manatee", "Sarasota", "Polk"],
                help="Select the county where the project is located",
                key="county"
            )
        
        with col_prop2:
            city = st.text_input(
                "City *",
                placeholder="e.g., St. Petersburg",
                key="city"
            )
        
        with col_prop3:
            # Determine correct ID type based on county
            selected_county = st.session_state.get('county', '')
            if selected_county in ['Hillsborough', 'Manatee']:
                id_label = "Folio ID"
                id_help = "Folio ID for Hillsborough/Manatee County (remove dashes, e.g., 1926050030)"
                id_placeholder = "e.g., 1926050030"
            else:
                id_label = "Parcel ID"
                id_help = "Property parcel identification number"
                id_placeholder = "e.g., 12-34-56-78900-000-0000"
            
            parcel_id = st.text_input(
                id_label,
                placeholder=id_placeholder,
                help=id_help,
                key="parcel_id"
            )
        
        # Lookup button
        if st.button("🔍 Lookup Property Info", disabled=not (st.session_state.get('county') and st.session_state.get('parcel_id'))):
            county = st.session_state.get('county', '')
            parcel_id = st.session_state.get('parcel_id', '')
            
            with st.spinner(f"Looking up property info in {county} County..."):
                result = lookup_property_info(county, parcel_id)
                
                if result['success']:
                    st.success(f"✅ Property found!")
                    
                    # Store all lookup data in session state
                    st.session_state['lookup_address'] = result.get('address', '')
                    st.session_state['lookup_city'] = result.get('city', '')
                    st.session_state['lookup_zip'] = result.get('zip', '')
                    st.session_state['lookup_owner'] = result.get('owner', '')
                    st.session_state['lookup_land_use'] = result.get('land_use', '')
                    st.session_state['lookup_zoning'] = result.get('zoning', '')
                    st.session_state['lookup_site_area_acres'] = result.get('site_area_acres', '')
                    st.session_state['lookup_site_area_sqft'] = result.get('site_area_sqft', '')
                    st.session_state['lookup_legal_description'] = result.get('legal_description', '')
                    st.session_state['lookup_subdivision'] = result.get('subdivision', '')
                    
                    # FOR PINELLAS: Store geometry for zoning lookup
                    if county == 'Pinellas':
                        st.session_state['lookup_geometry'] = result.get('geometry', {})
                    
                    # FOR PINELLAS: Override city based on user-entered City field if API returns wrong data
                    if county == 'Pinellas' and st.session_state.get('city'):
                        # Use the city the user typed instead of unreliable API city
                        st.session_state['lookup_city'] = st.session_state.get('city', '')
                    
                    # Auto-fill project address fields
                    st.session_state['project_address'] = result.get('address', '')
                    st.session_state['project_city_state_zip'] = f"{st.session_state['lookup_city']}, FL {result.get('zip', '')}"
                    
                    # Auto-fill editable property detail fields from property lookup
                    st.session_state['property_owner'] = result.get('owner', '')
                    st.session_state['property_use'] = result.get('land_use', '')  # Property Appraiser classification
                    st.session_state['property_zoning'] = result.get('zoning', '')
                    st.session_state['property_site_acres'] = result.get('site_area_acres', '')
                    
                    # Build property information display
                    info_lines = [
                        "**Found Property Information:**",
                        f"- **Address:** {result.get('address', 'N/A')}",
                        f"- **City:** {result.get('city', 'N/A')}, FL {result.get('zip', 'N/A')}",
                        f"- **Owner:** {result.get('owner', 'N/A')}",
                    ]
                    
                    # Add site area if available
                    if st.session_state.get('lookup_site_area_acres'):
                        info_lines.append(f"- **Site Area:** {st.session_state['lookup_site_area_acres']} acres")
                    elif result.get('site_area_sqft'):
                        info_lines.append(f"- **Site Area:** {result.get('site_area_sqft', 0):,.0f} sq ft")
                    
                    # DEBUG: Show acreage lookup flow
                    info_lines.append(f"- **DEBUG - Scrape returned acres:** {result.get('_debug_scrape_acres', 'N/A')}")
                    info_lines.append(f"- **DEBUG - Detail page scrape:** {result.get('_debug_detail_scrape', 'N/A')}")
                    info_lines.append(f"- **DEBUG - Final site_area_acres:** {result.get('site_area_acres', 'N/A')}")
                    info_lines.append(f"- **DEBUG - Stored in property_site_acres:** {st.session_state.get('property_site_acres', 'N/A')}")
                    
                    info_lines.extend([
                        f"- **Land Use:** {st.session_state.get('lookup_land_use', 'N/A')}",
                        f"- **Zoning:** {st.session_state.get('lookup_zoning', 'N/A')}",
                    ])
                    
                    # Add legal description if available
                    if result.get('legal_description'):
                        info_lines.append(f"- **Legal Description:** {result.get('legal_description', 'N/A')}")
                    
                    # Add subdivision if available
                    if result.get('subdivision'):
                        info_lines.append(f"- **Subdivision:** {result.get('subdivision', 'N/A')}")
                    
                    st.info("\n".join(info_lines))
                else:
                    st.error(f"❌ {result['error']}")
    
    # Call the property lookup section
    property_lookup_section()
    
    st.markdown("---")
    
    # Editable Property Details Section (always visible)
    st.subheader("Property Details (Editable)")
    st.caption("💡 These fields auto-fill from property lookup but can be edited manually.")
    
    # Show property address/city from lookup for reference
    if st.session_state.get('lookup_address'):
        st.text_input(
            "Property Address (from lookup)",
            value=f"{st.session_state.get('lookup_address', '')} - {st.session_state.get('lookup_city', '')}, FL {st.session_state.get('lookup_zip', '')}",
            disabled=True,
            help="Address found from property lookup. Use this to verify city for zoning lookup."
        )
    
    col_prop_detail1, col_prop_detail2 = st.columns(2)
    
    with col_prop_detail1:
        property_owner = st.text_input(
            "Owner Name",
            value=st.session_state.get('property_owner', ''),
            placeholder="e.g., ABC Development LLC",
            help="Auto-fills from property lookup"
        )
        # Store value back to session state when user edits
        st.session_state['property_owner'] = property_owner
        
        st.text_input(
            "Property Use",
            key='property_use',
            placeholder="e.g., General Office Bldg",
            help="Current property classification from Property Appraiser"
        )
        
        st.text_input(
            "Zoning",
            key='property_zoning',
            placeholder="e.g., C-2, PUD, RSF-4",
            help="Auto-fills from property lookup"
        )
    
    with col_prop_detail2:
        st.text_input(
            "Future Land Use",
            key='property_land_use',
            placeholder="e.g., Commercial, Residential",
            help="Auto-fills from property lookup"
        )
        
        st.text_input(
            "Site Area (acres)",
            key='property_site_acres',
            placeholder="e.g., 1.36",
            help="Auto-fills from property lookup"
        )
    
    # Zoning & Site Data Lookup Button (for Pinellas County)
    if st.session_state.get('county') == 'Pinellas' and st.session_state.get('parcel_id'):
        st.markdown("---")
        st.caption("🔍 **For Pinellas County:** Use the city shown above to lookup detailed zoning and site area data")
        
        def on_zoning_lookup():
            """Callback to handle zoning lookup - runs before widgets render"""
            city = st.session_state.get('city', '')
            address = st.session_state.get('lookup_address', '')
            
            if not address:
                st.session_state['zoning_error'] = "Please run Property Lookup first to get the address"
                return
            
            zoning_result = lookup_pinellas_zoning(city, address)
            
            if zoning_result.get('success'):
                # Update widget keys with zoning data
                if zoning_result.get('zoning_code'):
                    st.session_state['property_zoning'] = zoning_result.get('zoning_code', '')
                
                if zoning_result.get('future_land_use'):
                    st.session_state['property_land_use'] = zoning_result.get('future_land_use', '')
                
                # Store result for success message
                st.session_state['zoning_success'] = True
                st.session_state['zoning_description'] = zoning_result.get('zoning_description', '')
                st.session_state['zoning_code_display'] = zoning_result.get('zoning_code', '')
                st.session_state['flu_description'] = zoning_result.get('future_land_use_description', '')
                st.session_state['flu_code_display'] = zoning_result.get('future_land_use', '')
                st.session_state['zoning_note'] = zoning_result.get('note', '')
                st.session_state['zoning_error'] = None
            else:
                st.session_state['zoning_error'] = zoning_result.get('error', 'Unable to fetch zoning data')
                st.session_state['zoning_success'] = False
        
        st.button("🗺️ Lookup Zoning & Site Data", type="secondary", on_click=on_zoning_lookup)
        
        # Show messages after button
        if st.session_state.get('zoning_error'):
            st.error(f"❌ {st.session_state['zoning_error']}")
            st.session_state['zoning_error'] = None  # Clear for next run
        
        if st.session_state.get('zoning_success'):
            st.success("✅ Zoning data updated!")
            if st.session_state.get('zoning_description'):
                st.info(f"**Zoning:** {st.session_state.get('zoning_code_display', '')} - {st.session_state.get('zoning_description', '')}")
            if st.session_state.get('flu_description'):
                st.info(f"**Future Land Use:** {st.session_state.get('flu_code_display', '')} - {st.session_state.get('flu_description', '')}")
            if st.session_state.get('zoning_note'):
                st.info(f"ℹ️ {st.session_state.get('zoning_note', '')}")
            st.session_state['zoning_success'] = False  # Clear for next run
    
    st.markdown("---")
    
    st.subheader("Client Information")
    col1, col2 = st.columns(2)
    
    with col1:
        client_name = st.text_input("Client Name *", placeholder="e.g., ABC Development Corporation", key="client_name")
        legal_entity_name = st.text_input(
            "Legal Entity Name (per SunBiz) *",
            placeholder="e.g., ABC Development Corporation, Inc.",
            help="Entity name exactly as it appears in Florida SunBiz database",
            key="legal_entity_name"
        )
        address_line1 = st.text_input("Address Line 1 *", placeholder="e.g., 123 Main Street", key="address_line1")
        address_line2 = st.text_input("Address Line 2 *", placeholder="e.g., Tampa, FL 33602", key="address_line2")
    
    with col2:
        contact_person = st.text_input("Contact Person *", placeholder="e.g., Ms. Michelle Bach", key="contact_person")
        phone = st.text_input("Phone Number", placeholder="e.g., (813) 555-1234", key="phone")
        email = st.text_input("Email Address", placeholder="e.g., info@example.com", key="email")
    
    st.markdown("---")
    
    st.subheader("Project Details")
    col3, col4 = st.columns(2)
    
    with col3:
        proposal_date = st.date_input("Proposal Date *", value=date.today(), key="proposal_date")
        project_name = st.text_input("Project Name *", placeholder="e.g., Downtown Office Complex", key="project_name")
    
    with col4:
        # Auto-fill happens via callback after lookup button click
        project_address = st.text_input(
            "Project Address",
            placeholder="e.g., 7400 22nd Ave N",
            key="project_address"
        )
        project_city_state_zip = st.text_input(
            "City, State, Zip",
            placeholder="e.g., St. Petersburg, FL 33710",
            key="project_city_state_zip"
        )
    
    project_description = st.text_area(
        "Project Understanding *",
        placeholder="Start with: Kimley-Horn understands that the Client plans to develop [project name] on the property located at [address] (Parcel ID: [id]). The [X]-acre parcel has a Future Land Use designation of [FLU] and is zoned [zoning]. Then describe the project scope and requirements...",
        height=200,
        key="project_description",
        help="Write the complete Project Understanding paragraph. Include: project name, location, parcel ID, acreage, Future Land Use, zoning, and project scope."
    )
    
    # Show helper info with property data if available (from editable fields)
    if st.session_state.get('property_site_acres') or st.session_state.get('property_land_use') or st.session_state.get('property_zoning'):
        st.info(f"""
        **💡 Property data to include in your Project Understanding:**
        - Parcel ID: {st.session_state.get('parcel_id', 'N/A')}
        - Owner: {st.session_state.get('property_owner', 'N/A')}
        - Site Area: {st.session_state.get('property_site_acres', 'N/A')} acres
        - Future Land Use: {st.session_state.get('property_land_use', 'N/A')}
        - Zoning: {st.session_state.get('property_zoning', 'N/A')}
        """)


# TAB 2: Project Details (Assumptions)
with tab2:
    st.subheader("Project Understanding Assumptions")
    st.markdown("Check the assumptions that apply to this project. These will appear in the Project Understanding section.")
    
    col_assume1, col_assume2 = st.columns(2)
    
    with col_assume1:
        assume_survey = st.checkbox(
            "Boundary, topographic, and tree survey provided by Client",
            value=True
        )
        assume_environmental = st.checkbox(
            "Environmental/Biological assessment provided"
        )
        assume_geotech = st.checkbox(
            "Geotechnical investigation report provided"
        )
        assume_zoning = st.checkbox(
            "Use is consistent with future land use and zoning",
            value=True
        )
        assume_utilities = st.checkbox(
            "Utilities available at project boundary with adequate capacity",
            value=True
        )
    
    with col_assume2:
        assume_offsite = st.checkbox(
            "Offsite roadway improvements not included",
            value=True
        )
        assume_traffic = st.checkbox(
            "Traffic study provided by others or not required",
            value=True
        )
        assume_one_phase = st.checkbox(
            "Project constructed in one (1) phase",
            value=True
        )
        
        col_plan1, col_plan2 = st.columns([1, 2])
        with col_plan1:
            has_conceptual_plan = st.checkbox("Based on conceptual plan")
        with col_plan2:
            conceptual_plan_date = st.text_input(
                "Plan Date",
                placeholder="e.g., 10/15/2024",
                disabled=not has_conceptual_plan,
                label_visibility="collapsed"
            )


# TAB 3: Scope of Services
with tab3:
    st.subheader("Scope of Services")
    st.markdown("Select the tasks to include, enter the fee, and choose the fee type for each task.")
    
    selected_tasks = {}
    
    for task_num in sorted(DEFAULT_FEES.keys()):
        task = DEFAULT_FEES[task_num]
        
        col_check, col_name, col_fee, col_type = st.columns([0.5, 3, 1.5, 1.5])
        
        with col_check:
            task_selected = st.checkbox(
                f"{task_num}",
                value=(task_num == '310'),  # Auto-check Task 310
                key=f"check_{task_num}",
                label_visibility="collapsed"
            )
        
        with col_name:
            if task_num == '310':
                st.markdown(f"**Task {task_num}: {task['name']}** *(uncheck if not needed)*")
            else:
                st.markdown(f"**Task {task_num}: {task['name']}**")
        
        with col_fee:
            fee_amount = st.number_input(
                "Fee ($)",
                min_value=0,
                value=None,
                placeholder=f"{task['amount']:,}",
                key=f"fee_{task_num}",
                disabled=not task_selected,
                label_visibility="collapsed"
            )
        
        with col_type:
            fee_type_selection = st.selectbox(
                "Type",
                options=["Hourly, Not-to-Exceed", "Hourly", "Lump Sum"],
                index=0,  # Default to Hourly, Not-to-Exceed
                key=f"type_{task_num}",
                disabled=not task_selected,
                label_visibility="collapsed"
            )
        
        if task_selected:
            final_fee = fee_amount if fee_amount is not None else task['amount']
            selected_tasks[task_num] = {
                'name': task['name'],
                'fee': final_fee,
                'type': fee_type_selection  # Use per-task fee type
            }
            
            # Task 310 - Construction Phase Services selection
            if task_num == '310':
                st.markdown("**📋 Construction Phase Services:**")
                st.caption("Select services, enter hours/count, rate, and cost")
                
                # Header row
                col_h1, col_h2, col_h3, col_h4, col_h5 = st.columns([0.5, 3, 1.5, 1.5, 1.5])
                with col_h1:
                    st.write("")
                with col_h2:
                    st.markdown("**Service**")
                with col_h3:
                    st.markdown("**Hrs/Count**")
                with col_h4:
                    st.markdown("**$/hr**")
                with col_h5:
                    st.markdown("**Cost ($)**")
                
                # Services configuration
                services_list = [
                    ('shop_drawings', 'Shop Drawing Review', 30, 165, 4950),
                    ('rfi', 'RFI Response', 50, 165, 8250),
                    ('oac', 'OAC Meetings', 24, 0, 3000),
                    ('site_visits', 'Site Visits (2 hrs each)', 4, 0, 1000),
                    ('asbuilt', 'As-Built Reviews', 2, 0, 500),
                    ('inspection_tv', 'Inspection & TV Reports', 0, 165, 0),
                    ('record_drawings', 'Record Drawings (Water/Sewer)', 40, 165, 6600),
                    ('fdep', 'FDEP Clearance Submittals', 0, 0, 0),
                    ('compliance', 'Letter of General Compliance', 0, 0, 0),
                    ('wmd', 'WMD Certification', 0, 0, 0)
                ]
                
                service_data = {}
                
                for svc_key, svc_name, default_hrs, default_rate, default_cost in services_list:
                    col_chk, col_nm, col_hrs, col_rate, col_cost = st.columns([0.5, 3, 1.5, 1.5, 1.5])
                    
                    with col_chk:
                        is_selected = st.checkbox(
                            "✓",
                            value=(svc_key in ['shop_drawings', 'rfi', 'oac', 'site_visits', 'asbuilt', 'fdep', 'compliance', 'wmd']),
                            key=f"svc310_{svc_key}",
                            label_visibility="collapsed"
                        )
                    
                    with col_nm:
                        st.markdown(f"{svc_name}")
                    
                    with col_hrs:
                        if default_hrs > 0 or svc_key in ['inspection_tv', 'record_drawings']:
                            hrs_value = st.number_input(
                                "Hrs",
                                min_value=0,
                                value=default_hrs,
                                key=f"hrs310_{svc_key}",
                                disabled=not is_selected,
                                label_visibility="collapsed"
                            )
                        else:
                            hrs_value = 0
                            st.write("—")
                    
                    with col_rate:
                        if default_rate > 0 or svc_key in ['inspection_tv', 'record_drawings']:
                            rate_value = st.number_input(
                                "Rate",
                                min_value=0,
                                value=default_rate,
                                key=f"rate310_{svc_key}",
                                disabled=not is_selected,
                                label_visibility="collapsed"
                            )
                        else:
                            rate_value = 0
                            st.write("—")
                    
                    with col_cost:
                        if is_selected:
                            cost_value = st.number_input(
                                "Cost",
                                min_value=0,
                                value=default_cost,
                                key=f"cost310_{svc_key}",
                                disabled=not is_selected,
                                label_visibility="collapsed"
                            )
                        else:
                            cost_value = 0
                            st.write("—")
                    
                    service_data[svc_key] = {
                        'included': is_selected,
                        'name': svc_name,
                        'hours': hrs_value if is_selected else 0,
                        'rate': rate_value if is_selected else 0,
                        'cost': cost_value if is_selected else 0
                    }
                
                st.markdown("---")
                total_hrs = st.number_input(
                    "**Total Task 310 Hours**",
                    min_value=0,
                    value=180,
                    key="total_construction_hours"
                )
                
                selected_tasks[task_num]['services'] = service_data
                selected_tasks[task_num]['total_hours'] = total_hrs
                
                # Create hours dictionary for placeholder replacement in document generation
                selected_tasks[task_num]['hours'] = {
                    'shop_drawing': service_data['shop_drawings']['hours'],
                    'rfi': service_data['rfi']['hours'],
                    'oac_meetings': service_data['oac']['hours'],
                    'site_visits': service_data['site_visits']['hours'],
                    'record_drawing': service_data['record_drawings']['hours'],
                    'total': total_hrs
                }




# TAB 4: Permitting & Summary
with tab4:
    st.subheader("Permitting Requirements")
    st.markdown("Select the permits/approvals required for this project (applies to Task 150 - Civil Permitting):")
    
    permit_config = PERMIT_MAPPING.get(st.session_state.get('county', ''), {})
    default_permits = permit_config.get('default_permits', [])
    ahj_name = permit_config.get('ahj_name', 'Authority Having Jurisdiction')
    wmd_name = permit_config.get('wmd_short', 'Water Management District')
    
    col_permit1, col_permit2, col_permit3 = st.columns(3)
    
    with col_permit1:
        permit_ahj = st.checkbox(f"{ahj_name}", value=("ahj" in default_permits), help="Primary permitting authority")
        permit_sewer = st.checkbox("Sewer Provider", value=("sewer" in default_permits))
        permit_water = st.checkbox("Water Provider", value=("water" in default_permits))
    
    with col_permit2:
        permit_wmd_erp = st.checkbox(f"{wmd_name} ERP", value=("wmd_erp" in default_permits), help="Environmental Resources Permit")
        permit_fdep = st.checkbox("FDEP Potable Water/Wastewater", value=("fdep" in default_permits))
        permit_fdot_drainage = st.checkbox("FDOT Drainage Connection", value=("fdot_drainage" in default_permits))
    
    with col_permit3:
        permit_fdot_driveway = st.checkbox("FDOT Driveway Connection", value=("fdot_driveway" in default_permits))
        permit_fdot_utility = st.checkbox("FDOT Utility Connection", value=("fdot_utility" in default_permits))
        permit_fema = st.checkbox("FEMA", value=("fema" in default_permits))
    
    st.markdown("---")
    
    # Additional Services Configuration
    st.subheader("Additional Services")
    st.markdown("**Check the services you ARE providing** in this proposal and enter the fee. Unchecked services will be listed as 'Additional Services' (not included).")
    
    # Default list of additional services with suggested default fees
    additional_services_list = [
        ("offsite_roadway", "Off-site roadway, traffic signal design or utility improvements", False, 25000),
        ("offsite_utility", "Off-site utility capacity analysis and extensions", False, 15000),
        ("utility_relocation", "Utility relocation design and plans", False, 12000),
        ("cost_opinions", "Preparation of opinions of probable construction costs", False, 5000),
        ("dewatering", "Dewatering permitting (to be provided by Contractor)", False, 3000),
        ("site_lighting", "Site lighting, photometric, and site electrical plan", False, 8000),
        ("dry_utility", "Dry utility coordination and design", False, 10000),
        ("landscape", "Landscape, irrigation, hardscape design and tree mitigation", False, 20000),
        ("fire_line", "Fire line design", False, 6000),
        ("row_permitting", "Right-of-way permitting", False, 8000),
        ("concurrency", "Concurrency application assistance", False, 5000),
        ("3d_modeling", "3D modeling and graphic/presentations", False, 8000),
        ("leed", "LEED certification and review", False, 20000),
        ("schematic_dd", "Schematic and design development plans", False, 15000),
        ("extra_meetings", "Meetings other than those described in the tasks above", False, 5000),
        ("surveying", "Boundary, topographic and tree surveying, platting and subsurface utility exploration", False, 25000),
        ("platting", "Platting or easement assistance", False, 8000),
        ("traffic_studies", "Traffic studies, analysis, property share agreement", False, 30000),
        ("mot_plans", "Maintenance of traffic plans", False, 12000),
        ("structural", "Structural engineering (including retaining walls)", False, 35000),
        ("signage", "Signage design", False, 4000),
        ("extra_design", "Design elements beyond those outlined in the above project understanding", False, 10000),
        ("peer_review", "Responding to comments from third-party peer review", False, 8000)
    ]
    
    st.caption("💡 Tip: Check services you ARE including and enter fees. Unchecked items appear in 'Additional Services (Not Included)' section.")
    
    # Create 2-column layout: Service name (left) + Fee (right)
    included_additional_services = []
    excluded_additional_services = []
    included_additional_services_with_fees = {}  # Store as dict with fees
    
    for key, service_name, default_checked, default_fee in additional_services_list:
        col_service, col_fee = st.columns([3, 1])
        
        with col_service:
            is_checked = st.checkbox(
                service_name,
                value=default_checked,
                key=f"addl_svc_{key}"
            )
        
        with col_fee:
            fee_amount = st.number_input(
                "Fee ($)",
                min_value=0,
                value=None,
                placeholder=f"{default_fee:,}",
                key=f"addl_fee_{key}",
                disabled=not is_checked,
                label_visibility="collapsed"
            )
        
        if is_checked:
            final_fee = fee_amount if fee_amount is not None else default_fee
            included_additional_services.append(service_name)
            included_additional_services_with_fees[service_name] = final_fee
        else:
            excluded_additional_services.append(service_name)
    
    st.markdown("---")
    
    # Summary
    st.subheader("Selected Tasks Summary")
    if selected_tasks or included_additional_services_with_fees:
        total_fee = 0
        
        # Show regular tasks
        for task_num in sorted(selected_tasks.keys()):
            task = selected_tasks[task_num]
            st.write(f"✓ Task {task_num}: {task['name']} — **${task['fee']:,}**")
            total_fee += task['fee']
        
        # Show included additional services
        if included_additional_services_with_fees:
            st.markdown("**Additional Services Included:**")
            for service_name, service_fee in included_additional_services_with_fees.items():
                st.write(f"✓ {service_name} — **${service_fee:,}**")
                total_fee += service_fee
        
        st.markdown("---")
        st.markdown(f"### **Total Fee: ${total_fee:,}**")
    else:
        st.info("👆 Select at least one task in the Scope of Services tab")


# TAB 5: Invoice/Billing & Generate
with tab5:
    st.subheader("Invoice & Billing Information")
    col_inv1, col_inv2 = st.columns(2)
    
    with col_inv1:
        invoice_email = st.text_input(
            "Invoice Email Address",
            placeholder="e.g., accounting@company.com",
            help="Primary email for invoices"
        )
        kh_signer_name = st.text_input(
            "Kimley-Horn Signer Name",
            placeholder="e.g., John Smith, PE"
        )
        
        # Retainer checkbox and amount
        use_retainer = st.checkbox(
            "Require Retainer",
            value=False,
            help="Check if this proposal requires an upfront retainer fee"
        )
    
    with col_inv2:
        invoice_cc_email = st.text_input(
            "CC Email (optional)",
            placeholder="e.g., manager@company.com",
            help="Additional recipient for invoices"
        )
        kh_signer_title = st.text_input(
            "Kimley-Horn Signer Title",
            placeholder="e.g., Senior Project Manager"
        )
        
        # Retainer amount (disabled if not using retainer)
        retainer_amount = st.number_input(
            "Retainer Amount ($)",
            min_value=0,
            value=0,
            disabled=not use_retainer,
            help="Upfront retainer fee required before work begins"
        )
    
    st.markdown("---")
    st.markdown("---")
    
    # Generate Document Section
    st.subheader("📄 Generate Proposal Document")
    
    required_fields = {
        'County': st.session_state.get('county', ''),
        'City': st.session_state.get('city', ''),
        'Client Name': st.session_state.get('client_name', ''),
        'Legal Entity Name': st.session_state.get('legal_entity_name', ''),
        'Contact Person': st.session_state.get('contact_person', ''),
        'Address Line 1': st.session_state.get('address_line1', ''),
        'Address Line 2': st.session_state.get('address_line2', ''),
        'Project Name': st.session_state.get('project_name', ''),
        'Project Description': st.session_state.get('project_description', '')
    }
    
    missing_fields = [field for field, value in required_fields.items() if not value]
    
    if missing_fields:
        st.warning(f"⚠️ Please fill in: {', '.join(missing_fields)}")
    
    if not selected_tasks:
        st.warning("⚠️ Please select at least one task in the Scope of Services tab")
    
    can_generate = not missing_fields and bool(selected_tasks)
    
    if st.button("🚀 Generate Proposal Document", type="primary", disabled=not can_generate):
        with st.spinner("Generating proposal document..."):
            try:
                # Collect assumptions
                assumptions = []
                if assume_survey:
                    assumptions.append("Boundary, topographic, and tree survey will be provided by the Client.")
                if assume_environmental:
                    assumptions.append("An Environmental/Biological assessment and Geotechnical investigation report will be provided by the Client.")
                if assume_geotech:
                    assumptions.append("A Geotechnical investigation report will be provided by the Client.")
                if assume_zoning:
                    assumptions.append("The proposed use is consistent with the property's future land use and zoning designations.")
                if has_conceptual_plan and conceptual_plan_date:
                    assumptions.append(f"This proposal is based on the conceptual site plan dated {conceptual_plan_date}.")
                if assume_utilities:
                    assumptions.append("Utilities are available at the project boundary and have the capacity to serve the proposed development.")
                if assume_offsite:
                    assumptions.append("Offsite roadway improvements or right-of-way permitting is not included.")
                if assume_traffic:
                    assumptions.append("Traffic Study, impact analysis, and traffic counts, if required, will be provided by others.")
                if assume_one_phase:
                    assumptions.append("The project will be constructed in one (1) phase.")
                
                # Collect permitting requirements
                permit_config = PERMIT_MAPPING.get(st.session_state.get('county', ''), {})
                ahj_name = permit_config.get('ahj_name', 'Authority Having Jurisdiction')
                wmd_full = permit_config.get('wmd', 'Water Management District')
                
                permits = []
                if permit_ahj:
                    permits.append(ahj_name)
                if permit_sewer:
                    permits.append(f"{ahj_name} Sewer")
                if permit_water:
                    permits.append(f"{ahj_name} Water")
                if permit_wmd_erp:
                    permits.append(f"{wmd_full} Environmental Resources Permit (ERP)")
                if permit_fdep:
                    permits.append("Florida Department of Environmental Protection (FDEP) Potable Water and Wastewater Permit")
                if permit_fdot_drainage:
                    permits.append("FDOT Drainage Connection Permit")
                if permit_fdot_driveway:
                    permits.append("FDOT Driveway Connection Permit")
                if permit_fdot_utility:
                    permits.append("FDOT Utility Connection Permit")
                if permit_fema:
                    permits.append("FEMA")
                
                client_info = {
                    'name': st.session_state.get('client_name', ''),
                    'legal_entity': st.session_state.get('legal_entity_name', ''),
                    'contact': st.session_state.get('contact_person', ''),
                    'address1': st.session_state.get('address_line1', ''),
                    'address2': st.session_state.get('address_line2', ''),
                    'phone': st.session_state.get('phone', ''),
                    'email': st.session_state.get('email', '')
                }
                
                project_info = {
                    'date': st.session_state.get('proposal_date', date.today()).strftime("%B %d, %Y"),
                    'name': st.session_state.get('project_name', ''),
                    'address': st.session_state.get('project_address', ''),
                    'city_state_zip': st.session_state.get('project_city_state_zip', ''),
                    'description': st.session_state.get('project_description', ''),
                    'county': st.session_state.get('county', ''),
                    'city': st.session_state.get('city', ''),
                    'parcel_id': st.session_state.get('parcel_id', ''),
                    'permits': permits,
                    # Property lookup data for Project Understanding paragraph
                    'site_acres': st.session_state.get('lookup_site_area_acres', ''),
                    'future_land_use': st.session_state.get('lookup_land_use', ''),
                    'zoning': st.session_state.get('lookup_zoning', '')
                }
                
                invoice_info = {
                    'email': invoice_email,
                    'cc_email': invoice_cc_email,
                    'kh_signer_name': kh_signer_name,
                    'kh_signer_title': kh_signer_title,
                    'use_retainer': use_retainer,
                    'retainer_amount': retainer_amount if use_retainer else 0
                }
                
                buffer = BytesIO()
                temp_path = '/tmp/temp_proposal.docx'
                generate_proposal_document(client_info, project_info, selected_tasks, assumptions, permits, invoice_info, included_additional_services, included_additional_services_with_fees, excluded_additional_services, temp_path)
                
                with open(temp_path, 'rb') as f:
                    buffer.write(f.read())
                buffer.seek(0)
                
                filename = f"Proposal_{st.session_state.get('project_name', 'Document').replace(' ', '_')[:30]}_{st.session_state.get('proposal_date', date.today()).strftime('%Y%m%d')}.docx"
                
                st.success("✅ **Proposal document generated successfully!**")
                
                st.download_button(
                    label="📥 Download Word Document",
                    data=buffer.getvalue(),
                    file_name=filename,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    type="primary",
                    use_container_width=True
                )
                
            except Exception as e:
                st.error(f"❌ **Error:** {str(e)}")
                with st.expander("Show Error Details"):
                    st.exception(e)

st.markdown("---")
st.caption("Development Services Proposal Generator | Kimley-Horn")
