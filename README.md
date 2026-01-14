# Development Services Proposal Generator

Streamlit web application for generating professional proposal documents for civil engineering projects.

## Features

- Property lookup for 6 Florida counties (Hillsborough, Pinellas, Manatee, Sarasota, Pasco, Polk)
- Automatic property data retrieval (owner, address, property use, zoning, acreage)
- St. Petersburg zoning and future land use lookup
- Customizable task selection and fee structure
- Professional DOCX proposal generation with Kimley-Horn branding

## Installation

### Local Development

```bash
# Clone the repository
git clone https://github.com/yourusername/ds-proposal-app-fresh.git
cd ds-proposal-app-fresh

# Install dependencies
pip install -r requirements.txt

# Run the app
streamlit run app.py
```

### Streamlit Cloud Deployment

1. Push this repository to GitHub
2. Go to share.streamlit.io
3. Click "New app"
4. Select your repository and branch
5. Set main file path to: `app.py`
6. Click "Deploy"

## Usage

1. Select county and enter parcel ID
2. Click "Lookup Property Info" to auto-fill property details
3. For Pinellas County St. Petersburg properties, click "Lookup Zoning & Site Data" for detailed zoning information
4. Fill in project and client information
5. Select applicable tasks and permits
6. Click "Generate Proposal" to download the DOCX file

## County-Specific Notes

### Pinellas County
- Property data from PCPAO API and ArcGIS
- Acreage extracted from property detail pages
- St. Petersburg zoning lookup via city GIS services
- Other cities: manual zoning entry required

### Other Counties
- Direct ArcGIS REST API integration
- Single query provides all property data

## Requirements

- Python 3.8+
- Internet connection for county API access
- Web browser for Streamlit interface

## License

Internal Kimley-Horn use only.
