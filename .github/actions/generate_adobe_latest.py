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
from email.utils import parsedate_to_datetime

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

# Adobe ARM (Adobe Release Manager) endpoints. The Last-Modified header on these
# files is set when Adobe publishes the update, so it doubles as a release date.
ADOBE_READER_VERSION_URL = "https://armmf.adobe.com/arm-manifests/mac/AcrobatDC/reader/current_version.txt"
ADOBE_ACROBAT_VERSION_URL = "https://armmf.adobe.com/arm-manifests/mac/AcrobatDC/acrobat/current_version.txt"

# Acrobat release notes URL (official Adobe source for release dates - Acrobat doesn't have timestamp in version)
ACROBAT_RELEASE_NOTES_URL = "https://www.adobe.com/devnet-docs/acrobatetk/tools/ReleaseNotesDC/index.html"

# Jamf Patch API. The software list only carries a lastModified stamp, but each
# title's patch definition lists every version with its own releaseDate.
JAMF_PATCH_API_URL = "https://jamf-patch.jamfcloud.com/v1/software"
JAMF_PATCH_DEFINITION_URL = "https://jamf-patch.jamfcloud.com/v1/patch/{id}"

# Map SAP codes to Jamf software title names. Jamf publishes both a rolling
# title ("Adobe Photoshop") and per-year titles ("Adobe Photoshop 2026"); the
# pattern matches both so older versions can be backfilled too.
JAMF_TITLE_PATTERNS = {
    'PHSP': r'^Adobe Photoshop( \d{4})?$',
    'ILST': r'^Adobe Illustrator( \d{4})?$',
    'IDSN': r'^Adobe InDesign( \d{4})?$',
    'AICY': r'^Adobe InCopy( \d{4})?$',
    'PPRO': r'^Adobe Premiere Pro( \d{4})?$',
    'AEFT': r'^Adobe After Effects( \d{4})?$',
    'AUDT': r'^Adobe Audition( \d{4})?$',
    'AME': r'^Adobe Media Encoder( \d{4})?$',
    'CHAR': r'^Adobe Character Animator( \d{4})?$',
    'FLPR': r'^Adobe Animate( \d{4})?$',
    'DRWV': r'^Adobe Dreamweaver( \d{4})?$',
    'KBRG': r'^Adobe Bridge( \d{4})?$',
    'LRCC': r'^Adobe Lightroom CC$',
    'LTRM': r'^Adobe Lightroom Classic$',
    'ESHR': r'^Adobe Dimension$',
    'SBSTD': r'^Adobe Substance 3D Designer$',
    'SBSTP': r'^Adobe Substance 3D Painter$',
    'SBSTA': r'^Adobe Substance 3D Sampler$',
    'STGR': r'^Adobe Substance 3D Stager$',
    'APRO': r'^Adobe Acrobat DC Continuous$',
    'ARDR': r'^Adobe Acrobat Reader DC Continuous$',
    'KCCC': r'^Adobe Creative Cloud$',
    'RUSH': r'^Adobe Premiere Rush$',
    'SPRK': r'^Adobe XD$',
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


def version_key(version):
    """
    Numeric sort key for version strings so that 27.11 > 27.9.
    Plain string comparison gets this wrong and picks stale versions.
    """
    parts = re.split(r'[.\-_]', str(version or ''))
    return tuple(int(x) if x.isdigit() else 0 for x in parts)


def parse_http_date(value):
    """Convert an HTTP date header (RFC 2822) to an ISO date string, or None."""
    try:
        return parsedate_to_datetime(value.strip()).strftime("%Y-%m-%d")
    except Exception:
        return None


def fetch_last_modified_date(url):
    """
    Return the Last-Modified header of a URL as an ISO date, or None.
    Used for Adobe ARM manifests, which are rewritten when an update ships.
    """
    try:
        result = subprocess.run(
            ["curl", "-sI", "-m", "20", url],
            capture_output=True, text=True, timeout=30
        )
        for line in result.stdout.splitlines():
            if line.lower().startswith('last-modified:'):
                return parse_http_date(line.split(':', 1)[1])
    except Exception as e:
        print(f"Warning: Could not read Last-Modified for {url}: {e}")
    return None


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


def _extract_json_payload(raw_bytes):
    """
    Jamf patch definitions are served as a CMS-signed blob with the JSON
    payload embedded. Pull out the first balanced JSON object.
    """
    start = raw_bytes.find(b'{"name"')
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(raw_bytes)):
        c = raw_bytes[i:i + 1]
        if in_string:
            if escape:
                escape = False
            elif c == b'\\':
                escape = True
            elif c == b'"':
                in_string = False
            continue
        if c == b'"':
            in_string = True
        elif c == b'{':
            depth += 1
        elif c == b'}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw_bytes[start:i + 1].decode('utf-8', 'replace'))
                except json.JSONDecodeError:
                    return None
    return None


def fetch_jamf_patch_data():
    """
    Fetch per-version release dates from Jamf's patch definitions.
    Returns {sap_code: {jamf_version: release_date}}.
    """
    print("Fetching Jamf patch definitions...")
    jamf_data = {}

    try:
        result = subprocess.run(
            ["curl", "-s", "-m", "30", JAMF_PATCH_API_URL],
            capture_output=True, text=True, timeout=45
        )
        software_list = json.loads(result.stdout) if result.stdout else []
    except Exception as e:
        print(f"Warning: Could not fetch Jamf software list: {e}")
        return jamf_data

    # Only titles touched in the last few years; older ones predate the history
    cutoff = f"{datetime.now().year - 3}-01-01"
    titles = []
    for item in software_list:
        if not isinstance(item, dict):
            continue
        if item.get('lastModified', '') < cutoff:
            continue
        name = item.get('name', '')
        for sap_code, pattern in JAMF_TITLE_PATTERNS.items():
            if re.match(pattern, name):
                titles.append((sap_code, item.get('id'), name))
                break

    fetched = 0
    for sap_code, title_id, name in titles:
        if not title_id:
            continue
        try:
            result = subprocess.run(
                ["curl", "-s", "-m", "30", JAMF_PATCH_DEFINITION_URL.format(id=title_id)],
                capture_output=True, timeout=45
            )
            definition = _extract_json_payload(result.stdout)
        except Exception as e:
            print(f"Warning: Could not fetch Jamf definition for {name}: {e}")
            continue
        if not definition:
            continue
        fetched += 1
        versions = jamf_data.setdefault(sap_code, {})
        for patch in definition.get('patches', []):
            version = patch.get('version', '')
            release_date = patch.get('releaseDate', '')
            if version and release_date:
                date_only = release_date.split('T')[0]
                # Keep the earliest date if two titles list the same version
                if version not in versions or date_only < versions[version]:
                    versions[version] = date_only

    total = sum(len(v) for v in jamf_data.values())
    print(f"Loaded {total} Jamf version dates from {fetched} titles")
    return jamf_data


def lookup_jamf_release_date(sap_code, full_version, jamf_data):
    """
    Find the Jamf release date for a version. Jamf versions are usually
    shorter than Adobe's full build ("27.11.0" vs "27.11.0.26") and may
    drop leading zeros ("21.6.0.57" vs "21.6.0.057"), so compare numeric
    tuples and take the longest prefix match.
    """
    versions = jamf_data.get(sap_code) if jamf_data else None
    if not versions:
        return None

    full_key = version_key(full_version)
    best_len = 0
    best_date = None
    reverse_date = None
    for jamf_version, release_date in versions.items():
        jamf_key = version_key(jamf_version)
        if len(jamf_key) < 2:
            continue
        if len(jamf_key) <= len(full_key):
            # Jamf version is a prefix of Adobe's full build
            if full_key[:len(jamf_key)] == jamf_key and len(jamf_key) > best_len:
                best_len = len(jamf_key)
                best_date = release_date
        elif len(full_key) >= 3 and jamf_key[:len(full_key)] == full_key:
            # Adobe's version is the shorter one; take the earliest matching build
            if reverse_date is None or release_date < reverse_date:
                reverse_date = release_date
    return best_date or reverse_date


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

            # Store only the latest version per SAP code. Adobe renames products
            # over time (Premiere Pro -> Premiere, Substance Painter -> Substance
            # 3D Painter) so keying by display name would show duplicates.
            if sap_code not in products or version_key(full_version) > version_key(products[sap_code]['full_version']):
                products[sap_code] = {
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


def choose_release_date(info, sap_code, full_version, today, jamf_data):
    """
    Pick the best release date for a newly seen version.
    Order: Adobe-provided date (build timestamp, release notes, ARM) ->
    Jamf patch definition when it predates today -> first seen (today).
    """
    release_date = info.get('release_date', 'N/A')
    if release_date != 'N/A':
        return release_date, 'api'

    jamf_date = lookup_jamf_release_date(sap_code, full_version, jamf_data)
    if jamf_date and jamf_date < today:
        return jamf_date, 'jamf'

    return today, 'first_seen'


def backfill_history_dates(history, jamf_data):
    """
    Replace 'first_seen' dates with Jamf's release date when Jamf says the
    version shipped more than a day earlier. A first-seen date within a day
    of Jamf's is kept, since hourly polling of Adobe's CDN is just as accurate.
    """
    if not jamf_data:
        return 0
    changed = 0
    for entry in history.get('versions', []):
        if entry.get('date_source') != 'first_seen':
            continue
        jamf_date = lookup_jamf_release_date(entry['sap_code'], entry['full_version'], jamf_data)
        if not jamf_date:
            continue
        try:
            seen = datetime.strptime(entry['release_date'], "%Y-%m-%d")
            shipped = datetime.strptime(jamf_date, "%Y-%m-%d")
        except ValueError:
            continue
        if (seen - shipped).days > 1:
            print(f"Backfilled {entry['display_name']} {entry['full_version']}: {entry['release_date']} -> {jamf_date} (jamf)")
            entry['release_date'] = jamf_date
            entry['date_source'] = 'jamf'
            changed += 1
    return changed


def update_version_history(products, output_dir, jamf_data=None):
    """
    Update version history with any new versions detected.
    Records: display_name, sap_code, version, full_version, release_date, date_source
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
    for info in products.values():
        name = info['display_name']
        sap_code = info['sap_code']
        full_version = info['full_version']
        key = f"{sap_code}_{full_version}"

        if key not in existing_versions:
            release_date, date_source = choose_release_date(info, sap_code, full_version, today, jamf_data)
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

    backfilled = backfill_history_dates(history, jamf_data)

    if new_entries or backfilled:
        history['versions'].extend(new_entries)
        # Sort by release date (newest first), then by name
        history['versions'].sort(key=lambda x: (x['release_date'], x['display_name']), reverse=True)
        history['last_updated'] = datetime.now(timezone('US/Eastern')).strftime("%B %d, %Y %I:%M %p %Z")

        save_version_history(history, output_dir)
        print(f"Updated version history: {len(new_entries)} new entries, {backfilled} dates backfilled")
    else:
        print("No new versions detected")

    return len(new_entries)


def download_product_icon(sap_code, version, icon_url, icons_dir=".github/icons"):
    """Download a product icon to the local icons directory."""
    if not icon_url or icon_url == 'N/A':
        return False

    os.makedirs(icons_dir, exist_ok=True)

    # Create filename: SAP_VERSION.png (e.g., PHSP_27_2.png)
    version_str = version.replace('.', '_')
    filename = f"{sap_code}_{version_str}.png"
    filepath = os.path.join(icons_dir, filename)

    # Skip if already exists
    if os.path.exists(filepath):
        return True

    try:
        result = subprocess.run(
            ["curl", "-s", "-o", filepath, icon_url],
            capture_output=True, timeout=30
        )
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            print(f"Downloaded icon: {filename}")
            return True
        else:
            print(f"Failed to download icon: {filename}")
            return False
    except Exception as e:
        print(f"Error downloading icon {filename}: {e}")
        return False


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
        acrobat_icon = products.get('APRO', {}).get('icon_url', 'N/A')
        products['ARDR'] = {
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

    # Acrobat/Reader have no timestamp in their version. Use Adobe's release
    # notes first, then fall back to the Last-Modified date of the ARM manifest
    # that Adobe rewrites when an update ships.
    acrobat_release_dates = fetch_acrobat_release_dates()
    arm_urls = {'APRO': ADOBE_ACROBAT_VERSION_URL, 'ARDR': ADOBE_READER_VERSION_URL}
    for sap_code, arm_url in arm_urls.items():
        product_info = products.get(sap_code)
        if not product_info:
            continue
        full_version = product_info['full_version']
        if full_version in acrobat_release_dates:
            product_info['release_date'] = acrobat_release_dates[full_version]
            print(f"Added release date for {product_info['display_name']}: {product_info['release_date']} (release notes)")
        else:
            arm_date = fetch_last_modified_date(arm_url)
            if arm_date:
                product_info['release_date'] = arm_date
                print(f"Added release date for {product_info['display_name']}: {arm_date} (ARM Last-Modified)")

    print(f"Found {len(products)} unique products")

    # Download icons for all products (will skip existing ones)
    print("Checking product icons...")
    for info in products.values():
        download_product_icon(
            info['sap_code'],
            info['version'],
            info.get('icon_url', '')
        )

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

    # Flat SAP -> version map for scripts that only need the number
    simple = {
        sap: {'display_name': info['display_name'], 'version': info['full_version']}
        for sap, info in sorted(products.items())
    }
    with open(os.path.join(output_dir, "adobe_simple_versions.json"), "w") as f:
        json.dump({'last_updated': json.loads(json_data)['last_updated'], 'products': simple}, f, indent=2)
    print("Wrote: adobe_simple_versions.json")

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
