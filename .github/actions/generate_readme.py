#!/usr/bin/env python3
"""
AOFA - Generate README.md with latest Adobe product versions.
"""

import json
import os
from datetime import datetime, timezone as tz

try:
    from pytz import timezone
except ImportError:
    def timezone(tz_name):
        return tz.utc

def load_product_data():
    """Load the latest Adobe product data."""
    json_path = "latest_adobe_files/adobe_latest_versions.json"
    if not os.path.exists(json_path):
        print(f"Error: {json_path} not found")
        return None
    with open(json_path, 'r') as f:
        return json.load(f)

def load_version_history():
    """Load the version history data."""
    json_path = "latest_adobe_files/adobe_version_history.json"
    if not os.path.exists(json_path):
        return {}
    with open(json_path, 'r') as f:
        data = json.load(f)
    # Build lookup by sap_code + full_version
    lookup = {}
    for entry in data.get('versions', []):
        key = f"{entry['sap_code']}_{entry['full_version']}"
        lookup[key] = entry
    return lookup

def get_product_by_sap(products, sap_code):
    """Get a product by its SAP code."""
    for product in products:
        if product.get('sap_code') == sap_code:
            return product
    return None

def format_date_source(source):
    """Format the date source for display."""
    source_map = {
        'api': 'Official Adobe Source',
        'jamf': 'Jamf Patch',
        'manual': 'Manual Research',
        'first_seen': 'First Seen Date',
        'N/A': 'N/A'
    }
    return source_map.get(source, source)

def get_local_icon_path(sap_code, version):
    """Get the local icon path for a product."""
    # Convert version to filename format: 27.2 -> 27_2
    version_str = version.replace('.', '_')
    return f".github/icons/{sap_code}_{version_str}.png"

def generate_readme():
    """Generate the README.md file."""
    data = load_product_data()
    if not data:
        return

    products = data.get('products', [])
    last_updated = data.get('last_updated', 'Unknown')

    # Load version history for release dates
    version_history = load_version_history()

    # Build full product table
    product_rows = []
    for product in sorted(products, key=lambda x: x.get('display_name', '')):
        sap = product.get('sap_code', '')
        name = product.get('display_name', '')
        full_version = product.get('full_version', '')
        icon_url = product.get('icon_url', '')
        whats_new_url = product.get('whats_new_url', '')
        system_req_url = product.get('system_requirements_url', '')

        # Skip beta apps for main table
        if 'Beta' in name or 'BETA' in sap:
            continue

        # Get release date and source from version history
        history_key = f"{sap}_{full_version}"
        history_entry = version_history.get(history_key, {})
        release_date = history_entry.get('release_date', 'N/A')
        date_source = history_entry.get('date_source', 'N/A')

        # Build product cell (icon + name + space + sap code below title)
        # Use local icon path instead of CDN URL
        local_icon = get_local_icon_path(sap, product.get('version', ''))
        icon_html = f"<img src=\"{local_icon}\" alt=\"{name}\" width=\"80\"><br>"
        product_cell = f"{icon_html}**{name}**<br><br>**SAP Code:**<br>`{sap}`"

        # Format date source for display
        formatted_source = format_date_source(date_source)

        # Build version info cell (values below titles with spaces between sections)
        version_cell = f"**Version:**<br>`{full_version}`<br><br>**Release Date:**<br>`{release_date}`<br><br>**Release Date Source:**<br>`{formatted_source}`"

        # Build links cell
        links = []
        if whats_new_url and whats_new_url != 'N/A':
            links.append(f"[Release Notes]({whats_new_url})")
        if system_req_url and system_req_url != 'N/A':
            links.append(f"[System Requirements]({system_req_url})")
        links_cell = "<br>".join(links) if links else "N/A"

        product_rows.append(
            f"| {product_cell} | {version_cell} | {links_cell} |"
        )

    # Build beta apps table (no links column for beta apps)
    beta_rows = []
    for product in sorted(products, key=lambda x: x.get('display_name', '')):
        sap = product.get('sap_code', '')
        name = product.get('display_name', '')
        full_version = product.get('full_version', '')
        icon_url = product.get('icon_url', '')

        if 'Beta' not in name and 'BETA' not in sap:
            continue

        # Get release date and source from version history
        history_key = f"{sap}_{full_version}"
        history_entry = version_history.get(history_key, {})
        release_date = history_entry.get('release_date', 'N/A')
        date_source = history_entry.get('date_source', 'N/A')

        # Build product cell (icon + name + space + sap code below title)
        # Use local icon path instead of CDN URL
        local_icon = get_local_icon_path(sap, product.get('version', ''))
        icon_html = f"<img src=\"{local_icon}\" alt=\"{name}\" width=\"80\"><br>"
        product_cell = f"{icon_html}**{name}**<br><br>**SAP Code:**<br>`{sap}`"

        # Format date source for display
        formatted_source = format_date_source(date_source)

        # Build version info cell (values below titles with spaces between sections)
        version_cell = f"**Version:**<br>`{full_version}`<br><br>**Release Date:**<br>`{release_date}`<br><br>**Release Date Source:**<br>`{formatted_source}`"

        beta_rows.append(
            f"| {product_cell} | {version_cell} |"
        )

    readme_content = f'''# **AOFA**
**A**dobe **O**verview **F**eed for **A**pple

**AOFA** automatically aggregates Adobe Creative Cloud product information for macOS from multiple sources including Adobe's CDN API, Adobe Release Manager, official release notes, and Jamf's patch catalog. Data is refreshed hourly to provide the latest version numbers, release dates, and download information.

We welcome community contributions—fork the repository, ask questions, or share insights to help keep this resource accurate and useful for everyone.

<div align="center">

## All Adobe Products

<sup>**Raw Data**: [**JSON**](latest_adobe_files/adobe_latest_versions.json) | [**YAML**](latest_adobe_files/adobe_latest_versions.yaml) | [**XML**](latest_adobe_files/adobe_latest_versions.xml) | **Version History**: [**JSON**](latest_adobe_files/adobe_version_history.json) | [**YAML**](latest_adobe_files/adobe_version_history.yaml) | [**XML**](latest_adobe_files/adobe_version_history.xml)</sup>

<sup>_Last Updated: <code style="color : mediumseagreen">{last_updated}</code> (Automatically updated every hour)_</sup>

</div>

<div align="center">

| **Product** | **Version Information** | **Links** |
|-------------|------------------------|-----------|
{chr(10).join(product_rows)}

</div>

## Beta Applications

<div align="center">

| **Product** | **Version Information** |
|-------------|------------------------|
{chr(10).join(beta_rows)}

</div>

## Release Date Sources

| Source | Description |
|--------|-------------|
| `Official Adobe Source` | Release date provided directly from Adobe's API (most reliable) |
| `Jamf Patch` | Release date verified against Jamf's patch management catalog |
| `Manual Research` | Release date found through Adobe release notes, blogs, or community sources |
| `First Seen Date` | Date when the version was first detected by AOFA (used when no official date is available) |

## Data Sources

AOFA pulls data from the following APIs:

| Source | URL | Description |
|--------|-----|-------------|
| Adobe CDN API | `https://cdn-ffc.oobesaas.adobe.com/core/v5/products/all` | Primary source for all Creative Cloud product data |
| Adobe ARM | `https://armmf.adobe.com/arm-manifests/mac/AcrobatDC/reader/current_version.txt` | Adobe Release Manager endpoint for Acrobat Reader version |
| Adobe Release Notes | `https://www.adobe.com/devnet-docs/acrobatetk/tools/ReleaseNotesDC/index.html` | Official Acrobat/Reader release dates |
| Jamf Patch | `https://jamf-patch.jamfcloud.com/v1/software` | Cross-reference for release dates from Jamf's patch catalog |

<sup>A local copy of the raw Adobe API response is saved for easier viewing: [**adobe_raw_api_response.json**](latest_adobe_files/adobe_raw_api_response.json)</sup>

## API Information

AOFA uses Adobe's Creative Cloud CDN API to fetch product information:

```
Endpoint: https://cdn-ffc.oobesaas.adobe.com/core/v5/products/all
Parameters: channel=ccm&platform=osx10-64,osx10,macarm64,macuniversal
Header: x-adobe-app-id: accc-hdcore-desktop
```

### Available Data Fields

| Field | Description |
|-------|-------------|
| `sap_code` | Adobe's internal product code (e.g., PHSP for Photoshop) |
| `display_name` | Human-readable product name |
| `version` | Marketing version number |
| `full_version` | Complete build version (e.g., 27.2.0.15) |
| `release_date` | Release date (ISO format YYYY-MM-DD) - available for Lightroom and Acrobat products |
| `license_mode` | License type (PAID, FREE, FREEMIUM, RESIDUAL) |
| `min_macos_version` | Minimum macOS version required |
| `download_size` | Download size (MB/GB format) |
| `icon_url` | Product icon URL |
| `product_page` | Official product webpage |
| `whats_new_url` | Link to release notes/what's new page |
| `system_requirements_url` | Link to system requirements page |

*Note: Fields display "N/A" when data is not available from Adobe's API.*

### License Types

| License | Description |
|---------|-------------|
| `PAID` | Requires an active Creative Cloud subscription |
| `FREE` | Free to download and use, no subscription required (e.g., Bridge) |
| `FREEMIUM` | Free tier with limited features, paid tier unlocks full functionality (e.g., Premiere Rush) |
| `RESIDUAL` | Bundled with other subscriptions, not sold standalone (e.g., Lightroom with Photography plan) |
| `N/A` | Legacy apps or utilities that predate Adobe's NGL licensing system |

## Usage

### Direct API Access

```bash
curl -s "https://cdn-ffc.oobesaas.adobe.com/core/v5/products/all?channel=ccm&platform=osx10-64,macarm64" \\
  -H "x-adobe-app-id: accc-hdcore-desktop" | python3 -c "
import sys,json
d=json.load(sys.stdin)
seen={{}}
for c in d['channel']:
  for p in c['products']['product']:
    name=p['displayName']
    ver=p['version']
    sap=p['id']
    if name not in seen or ver>seen[name][1]:
      seen[name]=(sap,ver)
for name,(sap,ver) in sorted(seen.items()):
  print(f'{{sap}},{{name}},{{ver}}')"
```

### Using Raw JSON Feed

```bash
# Fetch latest versions
curl -s https://raw.githubusercontent.com/cocopuff2u/AOFA/main/latest_adobe_files/adobe_simple_versions.json
```

## Contributing

Contributions are welcome! Feel free to:
- Report issues or suggest improvements
- Submit pull requests
- Share feedback on the data structure

## License

MIT License - See [LICENSE](LICENSE) for details.

---

*This project is not affiliated with or endorsed by Adobe Inc.*
'''

    with open('README.md', 'w') as f:
        f.write(readme_content)
    print("README.md generated successfully!")


if __name__ == "__main__":
    generate_readme()
