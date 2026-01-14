"""
Minimal Test App - Pinellas County Land Area Lookup
Tests ONLY the web scraping for acreage auto-fill
"""
import streamlit as st
import re
import requests
from bs4 import BeautifulSoup

st.set_page_config(page_title="Land Area Test", page_icon="🏠")

st.title("Pinellas County Land Area Lookup Test")
st.caption("Testing web scraping for acreage auto-fill")

# Input fields
parcel_id = st.text_input(
    "Parcel ID",
    value="19-31-17-73166-001-0010",
    placeholder="e.g., 19-31-17-73166-001-0010",
    help="Pinellas County parcel ID with dashes"
)

if st.button("Lookup Land Area", type="primary"):
    if not parcel_id:
        st.error("Please enter a parcel ID")
    else:
        with st.spinner("Fetching land area from PCPAO..."):
            # Remove dashes for strap parameter
            strap = parcel_id.replace('-', '')
            
            # Build URL with required parameters
            url = (
                f"https://www.pcpao.gov/property-details?"
                f"basemap=BaseMapParcelAerials&"
                f"input={parcel_id}&"
                f"parcel={parcel_id}&"
                f"s={strap}&"
                f"search_option=parcel_number"
            )
            
            try:
                # Fetch the page
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                html = response.text
                
                # Parse and extract text
                soup = BeautifulSoup(html, "html.parser")
                text = soup.get_text(" ", strip=True)
                
                # Debug: Check if Land Area exists
                if "Land Area" not in text:
                    st.error("❌ 'Land Area' text not found on page")
                    st.info(f"**Debug:** Page loaded with {len(html)} characters but no 'Land Area' text found")
                else:
                    # Match pattern: "Land Area: ≅ 59,560 sf | ≅ 1.36 acres"
                    match = re.search(r"Land Area:\s*≅\s*([\d,]+)\s*sf\s*\|\s*≅\s*([\d.]+)\s*acres", text)
                    
                    if match:
                        land_sqft = int(match.group(1).replace(",", ""))
                        land_acres = float(match.group(2))
                        
                        # Store in session state
                        st.session_state['land_area_acres'] = f"{land_acres:.2f}"
                        st.session_state['land_area_sqft'] = f"{land_sqft:,}"
                        
                        st.success(f"✅ Land area found!")
                        st.info(f"**Square Feet:** {land_sqft:,} sf\n\n**Acres:** {land_acres:.2f}")
                        st.rerun()
                    else:
                        st.error("❌ Regex pattern did not match")
                        # Show snippet for debugging
                        land_pos = text.find("Land Area")
                        if land_pos >= 0:
                            snippet = text[land_pos:land_pos+300]
                            st.code(snippet, language=None)
                        
            except requests.exceptions.HTTPError as e:
                st.error(f"❌ HTTP Error: {e.response.status_code}")
            except requests.exceptions.Timeout:
                st.error("❌ Request timed out")
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")

st.markdown("---")

# Auto-filled land area field
st.subheader("Result")
st.text_input(
    "Land Area (acres)",
    key='land_area_acres',
    placeholder="Will auto-fill after lookup",
    help="This field auto-fills from the web scraping"
)

# Show raw data for debugging
if st.session_state.get('land_area_acres'):
    st.success(f"✅ Field contains: {st.session_state.get('land_area_acres')} acres")
    st.caption(f"Square feet: {st.session_state.get('land_area_sqft', 'N/A')}")
