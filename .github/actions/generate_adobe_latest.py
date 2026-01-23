#!/usr/bin/env python3
"""
AOFA - Adobe Overview Feed for Apple
Fetches latest Adobe product versions for macOS from Adobe's CDN API.
"""

import subprocess
import xml.etree.ElementTree as ET
from xml.dom import minidom
import json
from datetime import datetime, timezone as tz
import os
import re

# Try to import optional dependencies
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

try:
    from pytz import timezone
    HAS_PYTZ = True
except ImportError:
    HAS_PYTZ = False
    def timezone(tz_name):
        return tz.utc

# Adobe API Configuration
ADOBE_API_URL = "https://cdn-ffc.oobesaas.adobe.com/core/v5/products/all"
ADOBE_API_PARAMS = "channel=ccm&platform=osx10-64,osx10,macarm64,macuniversal"
ADOBE_API_HEADER = "x-adobe-app-id: accc-hdcore-desktop"

# Adobe Reader ARM (Adobe Release Manager) endpoint
ADOBE_READER_VERSION_URL = "https://armmf.adobe.com/arm-manifests/mac/AcrobatDC/reader/current_version.txt"

# Acrobat release notes URL (official Adobe source for release dates - Acrobat doesn't have timestamp in version)
ACROBAT_RELEASE_NOTES_URL = "https://www.adobe.com/devnet-docs/acrobatetk/tools/ReleaseNotesDC/index.html"

# Jamf Patch API for cross-referencing release dates
JAMF_PATCH_API_URL = "https://jamf-patch.jamfcloud.com/v1/software"

# Map SAP codes to Jamf software title IDs (partial matches work)
SAP_TO_JAMF_MAP = {
    'PHSP': 'AdobePhotoshop',
    'ILST': 'AdobeIllustrator',
    'IDSN': 'AdobeInDesign',
    'AICY': 'AdobeInCopy',
    'PPRO': 'AdobePremierePro',
    'AEFT': 'AdobeAfterEffects',
    'AUDT': 'AdobeAudition',
    'AME': 'AdobeMediaEncoder',
    'CHAR': 'AdobeCharacterAnimator',
    'FLPR': 'AdobeAnimate',
    'DRWV': 'AdobeDreamweaver',
    'LRCC': 'AdobeLightroom',
    'LTRM': 'AdobeLightroomClassic',
    'KBRG': 'AdobeBridge',
    'ESHR': 'AdobeDimension',
    'SBSTD': 'AdobeSubstance3DDesigner',
    'SBSTP': 'AdobeSubstance3DPainter',
    'SBSTA': 'AdobeSubstance3DSampler',
    'STGR': 'AdobeSubstance3DStager',
    'APRO': 'AdobeAcrobat',
    'ARDR': 'AdobeAcrobatReader',
    'RUSH': 'AdobePremiereRush',
}

# Friendly product names
PRODUCT_NAMES = {
    "PHSP": "Photoshop",
    "ILST": "Illustrator",
    "IDSN": "InDesign",
    "AICY": "InCopy",
    "PPRO": "Premiere Pro",
    "AEFT": "After Effects",
    "AUDT": "Audition",
    "AME": "Media Encoder",
    "CHAR": "Character Animator",
    "FLPR": "Animate",
    "DRWV": "Dreamweaver",
    "LRCC": "Lightroom",
    "LTRM": "Lightroom Classic",
    "KBRG": "Bridge",
    "ESHR": "Dimension",
    "SBSTD": "Substance 3D Designer",
    "SBSTP": "Substance 3D Painter",
    "SBSTA": "Substance 3D Sampler",
    "STGR": "Substance 3D Stager",
    "APRO": "Acrobat",
    "ARDR": "Acrobat Reader",
    "KCCC": "Creative Cloud",
    "RUSH": "Premiere Rush",
    "MUSE": "Muse CC",
    "FWKS": "Fireworks CS6",
    "FLBR": "Flash Builder",
    "KETK": "ExtendScript Toolkit",
    "KEMN": "Extension Manager"
}


def fetch_adobe_products():
    """
    Fetch Adobe product data from the CDN API.
    Returns the raw JSON response.
    """
    print("Fetching Adobe product data from CDN API...")
    url = f"{ADOBE_API_URL}?{ADOBE_API_PARAMS}"
    result = subprocess.run(
        ["curl", "-s", url, "-H", ADOBE_API_HEADER],
        capture_output=True, text=True
    )
    if not result.stdout:
        print("Error: No data received from Adobe API")
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(f"Error parsing Adobe API response: {e}")
        return None


def fetch_adobe_reader_version():
    """
    Fetch Adobe Reader version from ARM (Adobe Release Manager) endpoint.
    Reader is distributed separately from Creative Cloud.
    """
    print("Fetching Adobe Reader version from ARM...")
    result = subprocess.run(
        ["curl", "-s", ADOBE_READER_VERSION_URL],
        capture_output=True, text=True
    )
    if result.stdout:
        return result.stdout.strip()
    return None


def fetch_jamf_patch_data():
    """
    Fetch Adobe product patch data from Jamf's patch management catalog.
    Returns a dict mapping (product_name, version) to release date.
    Uses the lastModified date from the public API as the release indicator.
    """
    print("Fetching Jamf patch definitions...")
    jamf_data = {}

    try:
        result = subprocess.run(
            ["curl", "-s", JAMF_PATCH_API_URL],
            capture_output=True, text=True, timeout=30
        )
        if result.stdout:
            software_list = json.loads(result.stdout)

            # Filter for Adobe products and extract version info
            adobe_count = 0
            for item in software_list:
                if not isinstance(item, dict):
                    continue

                name = item.get('name', '')
                if 'Adobe' not in name:
                    continue

                adobe_count += 1
                version = item.get('currentVersion', '')
                last_modified = item.get('lastModified', '')

                if version and last_modified:
                    # Convert lastModified (ISO format) to date only
                    # Format: "2025-09-25T16:37:38Z" -> "2025-09-25"
                    release_date = last_modified.split('T')[0] if 'T' in last_modified else last_modified
                    jamf_data[(name, version)] = release_date

            print(f"Loaded {len(jamf_data)} Jamf entries for {adobe_count} Adobe products")
    except Exception as e:
        print(f"Warning: Could not fetch Jamf data: {e}")

    return jamf_data


def lookup_jamf_release_date(sap_code, full_version, display_name, jamf_data):
    """
    Look up a release date from Jamf patch data.
    Returns (release_date, True) if found, (None, False) if not.
    """
    # Try to match by product name patterns
    search_terms = []

    # Add SAP code mapping if available
    jamf_pattern = SAP_TO_JAMF_MAP.get(sap_code, '')
    if jamf_pattern:
        search_terms.append(jamf_pattern)

    # Also try the display name
    if display_name:
        # Convert "Photoshop" to search for "Adobe Photoshop"
        search_terms.append(f"Adobe {display_name}")
        search_terms.append(display_name)

    for (jamf_name, jamf_version), release_date in jamf_data.items():
        # Check if any search term matches the Jamf product name
        name_match = False
        for term in search_terms:
            if term.lower() in jamf_name.lower() or jamf_name.lower() in term.lower():
                name_match = True
                break

        if not name_match:
            continue

        # Try version matching
        # Exact match
        if jamf_version == full_version:
            return release_date, True

        # Jamf might have shorter version (e.g., "27.2" vs "27.2.0.15")
        if full_version.startswith(jamf_version):
            return release_date, True

        # Or we might have shorter version
        version_base = full_version.rsplit('.', 1)[0]
        if jamf_version.startswith(version_base):
            return release_date, True

    return None, False


def fetch_acrobat_release_dates():
    """
    Fetch release dates for Acrobat/Reader from Adobe's official release notes page.
    Returns a dict mapping version numbers to release dates (ISO format YYYY-MM-DD).
    """
    print("Fetching Acrobat release dates from Adobe...")
    result = subprocess.run(
        ["curl", "-sL", ACROBAT_RELEASE_NOTES_URL],
        capture_output=True, text=True
    )

    release_dates = {}
    if result.stdout:
        # Pattern: "25.001.21111 Planned update, Jan 20, 2026"
        matches = re.findall(r'([\d.]+)\s+(?:Planned|Optional|Out of cycle)\s+update,\s+([A-Z][a-z]{2})\s+(\d+),\s+(\d{4})', result.stdout)
        # Convert short month to month number
        month_map = {
            'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04',
            'May': '05', 'Jun': '06', 'Jul': '07', 'Aug': '08',
            'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'
        }
        for version, month_short, day, year in matches:
            month_num = month_map.get(month_short, '01')
            release_dates[version] = f"{year}-{month_num}-{day.zfill(2)}"

    return release_dates


def parse_build_timestamp(full_version):
    """
    Extract and format the build timestamp from a full version string.
    Format: 15.1.1.202601141538 -> 2026-01-14
    Returns ISO date string or None if not found.
    """
    # Look for 12-digit timestamp pattern (YYYYMMDDHHmm)
    match = re.search(r'(\d{12})$', full_version.replace('.', ''))
    if not match:
        # Try to find it in the version string directly
        match = re.search(r'(\d{4})(\d{2})(\d{2})(\d{4})$', full_version.replace('.', ''))
        if match:
            year, month, day, time = match.groups()
            return f"{year}-{month}-{day}"

    # Try alternate pattern where timestamp is after last dot
    parts = full_version.split('.')
    for part in reversed(parts):
        if len(part) >= 12 and part.isdigit():
            year = part[0:4]
            month = part[4:6]
            day = part[6:8]
            return f"{year}-{month}-{day}"

    return None


def format_file_size(size_bytes):
    """
    Convert bytes to human-readable format (MB or GB).
    """
    if not size_bytes or size_bytes == 0:
        return None

    gb = size_bytes / (1024 * 1024 * 1024)
    if gb >= 1:
        return f"{gb:.2f} GB"
    else:
        mb = size_bytes / (1024 * 1024)
        return f"{mb:.1f} MB"


def extract_product_info(data):
    """
    Extract relevant product information from the API response.
    Returns a dict of products with their details.
    """
    products = {}

    if not data or 'channel' not in data:
        return products

    for channel in data.get('channel', []):
        for product in channel.get('products', {}).get('product', []):
            sap_code = product.get('id', '')
            display_name = product.get('displayName', '')
            version = product.get('version', '')

            # Get detailed version info from platform data
            full_version = version
            license_mode = ''

            download_size = 0
            min_macos_version = ''

            platforms = product.get('platforms', {}).get('platform', [])
            if platforms:
                # Search all platforms for the best data
                for plat in platforms:
                    lang_set = plat.get('languageSet', [])
                    if lang_set:
                        ls = lang_set[0]
                        # Get full version from first platform with data
                        if not full_version or full_version == version:
                            full_version = ls.get('productVersion', version)
                        # Get license mode from NGL licensing info
                        if not license_mode:
                            ngl_info = ls.get('nglLicensingInfo', {})
                            license_mode = ngl_info.get('licenseMode', '')
                        # Get download size from esdData (search all platforms)
                        if not download_size:
                            esd_data = ls.get('esdData', {})
                            download_size = esd_data.get('size', 0)

                    # Get min macOS version from systemCompatibility
                    if not min_macos_version:
                        sys_compat = plat.get('systemCompatibility', {})
                        os_info = sys_compat.get('operatingSystem', {})
                        os_range = os_info.get('range', [])
                        if os_range:
                            # Format is ["14.0.0-"] meaning 14.0.0 and above
                            min_macos_version = os_range[0].rstrip('-')

            # Get product icons
            icons = product.get('productIcons', {}).get('icon', [])
            icon_url = ''
            for icon in icons:
                if icon.get('size') == '96x96':
                    icon_url = icon.get('value', '')
                    break

            # Get categories
            categories = [c.get('value', '') for c in product.get('categories', {}).get('category', [])]

            # Get product info page
            product_page = product.get('productInfoPage', '')

            # Get custom-data entries for additional info
            custom_data = product.get('custom-data', {}).get('custom-entry', [])
            whats_new_url = ''
            system_requirements_url = ''

            for entry in custom_data:
                key = entry.get('key', '')
                value = entry.get('value', [''])[0] if entry.get('value') else ''

                if key == 'prodWhatsNewPage':
                    whats_new_url = value
                elif key == 'systemRequirementURL':
                    system_requirements_url = value

            # Extract release date from build timestamp in full_version
            release_date = parse_build_timestamp(full_version) or 'N/A'

            # Store only the latest version per product
            if display_name not in products or version > products[display_name]['version']:
                products[display_name] = {
                    'display_name': display_name,
                    'sap_code': sap_code,
                    'version': version or 'N/A',
                    'full_version': full_version or 'N/A',
                    'release_date': release_date,
                    'license_mode': license_mode or 'N/A',
                    'min_macos_version': min_macos_version or 'N/A',
                    'download_size': format_file_size(download_size) or 'N/A',
                    'icon_url': icon_url or 'N/A',
                    'product_page': product_page or 'N/A',
                    'whats_new_url': whats_new_url or 'N/A',
                    'system_requirements_url': system_requirements_url or 'N/A',
                    'categories': categories if categories else []
                }

    return products


def convert_to_json(products, include_timestamp=True):
    """
    Convert products dict to JSON string.
    """
    output = {}
    if include_timestamp:
        output['last_updated'] = datetime.now(timezone('US/Eastern')).strftime("%B %d, %Y %I:%M %p %Z")

    output['products'] = sorted(products.values(), key=lambda x: x['display_name'])
    return json.dumps(output, indent=2)


def convert_to_yaml(products):
    """
    Convert products dict to YAML string.
    """
    output = {
        'last_updated': datetime.now(timezone('US/Eastern')).strftime("%B %d, %Y %I:%M %p %Z"),
        'products': sorted(products.values(), key=lambda x: x['display_name'])
    }
    if HAS_YAML:
        return yaml.dump(output, default_flow_style=False, sort_keys=False, allow_unicode=True)
    else:
        # Simple YAML-like output without pyyaml
        return json.dumps(output, indent=2)


def convert_to_xml(products):
    """
    Convert products dict to XML string.
    """
    root = ET.Element("adobe_products")

    # Add metadata
    last_updated = ET.SubElement(root, "last_updated")
    last_updated.text = datetime.now(timezone('US/Eastern')).strftime("%B %d, %Y %I:%M %p %Z")

    # Add products (sorted alphabetically)
    products_elem = ET.SubElement(root, "products")

    for product in sorted(products.values(), key=lambda x: x['display_name']):
        prod_elem = ET.SubElement(products_elem, "product")

        for key, value in product.items():
            if key == 'categories':
                cats_elem = ET.SubElement(prod_elem, "categories")
                for cat in value:
                    cat_elem = ET.SubElement(cats_elem, "category")
                    cat_elem.text = cat
            else:
                elem = ET.SubElement(prod_elem, key)
                elem.text = str(value) if value else ''

    return minidom.parseString(ET.tostring(root, encoding='unicode')).toprettyxml(indent="  ")


def load_version_history(output_dir):
    """
    Load existing version history from JSON file.
    """
    history_path = os.path.join(output_dir, "adobe_version_history.json")
    if os.path.exists(history_path):
        with open(history_path, 'r') as f:
            return json.load(f)
    return {'versions': []}


def update_version_history(products, output_dir, jamf_data=None):
    """
    Update version history with any new versions detected.
    Records: display_name, sap_code, version, full_version, release_date, date_source
    Uses product's release_date if available, checks Jamf, otherwise uses current date.
    date_source indicates where the date came from: 'api', 'jamf', 'manual', or 'first_seen'
    """
    history = load_version_history(output_dir)
    today = datetime.now(timezone('US/Eastern')).strftime("%Y-%m-%d")

    # Build a set of existing version entries for quick lookup
    existing_versions = set()
    for entry in history.get('versions', []):
        key = f"{entry['sap_code']}_{entry['full_version']}"
        existing_versions.add(key)

    new_entries = []
    for name, info in products.items():
        sap_code = info['sap_code']
        full_version = info['full_version']
        key = f"{sap_code}_{full_version}"

        if key not in existing_versions:
            # Determine the release date to use
            release_date = info.get('release_date', 'N/A')

            if release_date != 'N/A':
                # API provided a date
                date_source = 'api'
            else:
                # Try Jamf as a fallback source
                if jamf_data:
                    jamf_date, found = lookup_jamf_release_date(sap_code, full_version, name, jamf_data)
                    if found and jamf_date:
                        release_date = jamf_date
                        date_source = 'jamf'
                    else:
                        # No Jamf date found, use first_seen
                        release_date = today
                        date_source = 'first_seen'
                else:
                    # No Jamf data available, use first_seen
                    release_date = today
                    date_source = 'first_seen'

            new_entry = {
                'display_name': name,
                'sap_code': sap_code,
                'version': info['version'],
                'full_version': full_version,
                'release_date': release_date,
                'date_source': date_source
            }
            new_entries.append(new_entry)
            print(f"New version detected: {name} {full_version} ({release_date} - {date_source})")

    if new_entries:
        # Add new entries to history
        history['versions'].extend(new_entries)
        # Sort by release date (newest first), then by name
        history['versions'].sort(key=lambda x: (x['release_date'], x['display_name']), reverse=True)
        history['last_updated'] = datetime.now(timezone('US/Eastern')).strftime("%B %d, %Y %I:%M %p %Z")

        # Save version history in all formats
        save_version_history(history, output_dir)
        print(f"Updated version history with {len(new_entries)} new entries")
    else:
        print("No new versions detected")

    return len(new_entries)


def save_version_history(history, output_dir):
    """Save version history in JSON, YAML, and XML formats with last_updated at top."""
    from collections import OrderedDict

    # Ensure last_updated is at the top
    ordered_history = OrderedDict([
        ('last_updated', history.get('last_updated', '')),
        ('versions', history.get('versions', []))
    ])

    # Save JSON
    json_path = os.path.join(output_dir, "adobe_version_history.json")
    with open(json_path, 'w') as f:
        json.dump(ordered_history, f, indent=2)

    # Save YAML
    yaml_path = os.path.join(output_dir, "adobe_version_history.yaml")
    with open(yaml_path, 'w') as f:
        f.write(f'last_updated: "{ordered_history["last_updated"]}"\n')
        f.write('versions:\n')
        for v in ordered_history['versions']:
            f.write(f'  - display_name: "{v["display_name"]}"\n')
            f.write(f'    sap_code: "{v["sap_code"]}"\n')
            f.write(f'    version: "{v["version"]}"\n')
            f.write(f'    full_version: "{v["full_version"]}"\n')
            f.write(f'    release_date: "{v["release_date"]}"\n')
            f.write(f'    date_source: "{v["date_source"]}"\n')

    # Save XML
    xml_path = os.path.join(output_dir, "adobe_version_history.xml")
    with open(xml_path, 'w') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<version_history>\n')
        f.write(f'  <last_updated>{ordered_history["last_updated"]}</last_updated>\n')
        f.write('  <versions>\n')
        for v in ordered_history['versions']:
            f.write('    <version>\n')
            for key, value in v.items():
                escaped = str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                f.write(f'      <{key}>{escaped}</{key}>\n')
            f.write('    </version>\n')
        f.write('  </versions>\n')
        f.write('</version_history>\n')


def main():
    """
    Main function to fetch and save Adobe product data.
    """
    output_dir = "latest_adobe_files"
    os.makedirs(output_dir, exist_ok=True)
    print(f"Output directory: {output_dir}")

    # Fetch data from Adobe API
    raw_data = fetch_adobe_products()
    if not raw_data:
        print("Failed to fetch Adobe product data")
        return

    # Extract product information
    products = extract_product_info(raw_data)

    # Fetch Adobe Reader separately (distributed via ARM, not Creative Cloud)
    reader_version = fetch_adobe_reader_version()
    if reader_version:
        # Use same icon as Acrobat
        acrobat_icon = products.get('Acrobat', {}).get('icon_url', 'N/A')
        products['Acrobat Reader'] = {
            'display_name': 'Acrobat Reader',
            'sap_code': 'ARDR',
            'version': reader_version.split('.')[0] + '.' + reader_version.split('.')[1],
            'full_version': reader_version,
            'release_date': 'N/A',
            'license_mode': 'FREE',
            'min_macos_version': 'N/A',
            'download_size': 'N/A',
            'icon_url': acrobat_icon,
            'product_page': 'https://www.adobe.com/acrobat/pdf-reader.html',
            'whats_new_url': 'https://helpx.adobe.com/acrobat/release-note/release-notes-acrobat-reader.html',
            'system_requirements_url': 'https://helpx.adobe.com/reader/system-requirements.html',
            'categories': ['pdf-document']
        }
        print(f"Added Adobe Reader version {reader_version}")

    # Fetch Acrobat release dates from official Adobe release notes (Acrobat doesn't have timestamp in version)
    acrobat_release_dates = fetch_acrobat_release_dates()
    if acrobat_release_dates:
        # Apply release dates to Acrobat and Reader products
        for product_name, product_info in products.items():
            if product_info['sap_code'] in ['APRO', 'ARDR']:
                full_version = product_info['full_version']
                if full_version in acrobat_release_dates:
                    product_info['release_date'] = acrobat_release_dates[full_version]
                    print(f"Added release date for {product_name}: {acrobat_release_dates[full_version]}")

    print(f"Found {len(products)} unique products")

    # Save full product data in multiple formats
    json_data = convert_to_json(products)
    yaml_data = convert_to_yaml(products)
    xml_data = convert_to_xml(products)

    # Write full data files
    with open(os.path.join(output_dir, "adobe_latest_versions.json"), "w") as f:
        f.write(json_data)
    print("Wrote: adobe_latest_versions.json")

    with open(os.path.join(output_dir, "adobe_latest_versions.yaml"), "w") as f:
        f.write(yaml_data)
    print("Wrote: adobe_latest_versions.yaml")

    with open(os.path.join(output_dir, "adobe_latest_versions.xml"), "w") as f:
        f.write(xml_data)
    print("Wrote: adobe_latest_versions.xml")

    # Fetch Jamf patch data for cross-referencing release dates
    jamf_data = fetch_jamf_patch_data()

    # Update version history (track new versions)
    update_version_history(products, output_dir, jamf_data)

    # Save raw API response for debugging
    with open(os.path.join(output_dir, "adobe_raw_api_response.json"), "w") as f:
        json.dump(raw_data, f, indent=2)
    print("Wrote: adobe_raw_api_response.json")

    print("\nAdobe product data updated successfully!")


if __name__ == "__main__":
    main()
