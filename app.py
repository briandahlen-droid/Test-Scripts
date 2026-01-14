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
            
            # Build URL with ALL required parameters (matching working test script)
            url = (
                f"https://www.pcpao.gov/property-details?"
                f"basemap=BaseMapParcelAerials&"
                f"input={parcel_id}&"
                f"length=10&"
                f"order_column=5&"
                f"order_type=asc&"
                f"parcel={parcel_id}&"
                f"s={strap}&"
                f"sales=&"
                f"scale=2256.994353&"
                f"search_option=parcel_number&"
                f"start=0&"
                f"xmax=-9198733.675290285&"
                f"xmin=-9199288.440909712&"
                f"ymax=3220279.657774374&"
                f"ymin=3219932.705325626"
            )
            
            try:
                # Fetch the page - exact pattern from working script
                html = requests.get(url, timeout=30).text
                
                # Parse and extract text - exact pattern from working script
                soup = BeautifulSoup(html, "html.parser")
                text = soup.get_text(" ", strip=True)
                
                # Match pattern: "Land Area: ≅ 59,560 sf | ≅ 1.36 acres" - exact pattern from working script
                m = re.search(r"Land Area:\s*≅\s*([\d,]+)\s*sf\s*\|\s*≅\s*([\d.]+)\s*acres", text)
                
                if not m:
                    st.error("❌ 'Land Area' pattern not found on page")
                    
                    # Debug: Show ALL text containing "sf" or "acres"
                    st.subheader("Debug: All text containing 'sf' or 'acres'")
                    
                    # Find all occurrences of "sf" with context
                    sf_matches = re.finditer(r'.{0,50}sf.{0,50}', text, re.IGNORECASE)
                    sf_snippets = [match.group(0) for match in sf_matches]
                    if sf_snippets:
                        st.write(f"Found {len(sf_snippets)} occurrences of 'sf':")
                        for i, snippet in enumerate(sf_snippets[:10], 1):  # Show first 10
                            st.code(f"{i}. {snippet}")
                    else:
                        st.write("No 'sf' found in page text")
                    
                    # Find all occurrences of "acres" with context
                    acres_matches = re.finditer(r'.{0,50}acres.{0,50}', text, re.IGNORECASE)
                    acres_snippets = [match.group(0) for match in acres_matches]
                    if acres_snippets:
                        st.write(f"Found {len(acres_snippets)} occurrences of 'acres':")
                        for i, snippet in enumerate(acres_snippets[:10], 1):  # Show first 10
                            st.code(f"{i}. {snippet}")
                    else:
                        st.write("No 'acres' found in page text")
                else:
                    # Extract values - exact pattern from working script
                    land_sqft = int(m.group(1).replace(",", ""))
                    land_acres = float(m.group(2))
                    
                    # Store in session state
                    st.session_state['land_area_acres'] = f"{land_acres:.2f}"
                    st.session_state['land_area_sqft'] = f"{land_sqft:,}"
                    
                    st.success(f"✅ Land area found!")
                    st.info(f"**Square Feet:** {land_sqft:,} sf\n\n**Acres:** {land_acres:.2f}")
                    st.rerun()
                        
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
