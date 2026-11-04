"""Plan missing regions and merge only published, verified release assets."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
from publish_packages import REGIONS, MAX_PACKAGE, digest

def gh(*args):
    return subprocess.check_output(['gh', *args], text=True)

def read_release_catalog(tag):
    with tempfile.TemporaryDirectory() as folder:
        gh('release', 'download', tag, '--pattern', 'catalog-v1.json', '--dir', folder)
        result = json.loads((Path(folder) / 'catalog-v1.json').read_text())
        if result.get('schema') != 'rutasgen-poi-catalog-v1':
            raise ValueError('Unsupported catalogue')
        return result

def latest():
    # Failure is fatal: never replace a catalogue we could not read.
    tag = json.loads(gh('release', 'view', '--json', 'tagName'))['tagName']
    return read_release_catalog(tag)

def missing_regions(catalog):
    existing = {p['id'] for p in catalog['packages']}
    return [key for key in REGIONS if key + '-geofabrik' not in existing]

def merge(base, additions):
    entries = {p['id']: p for p in base['packages']}
    if len(entries) != len(base['packages']):
        raise ValueError('Duplicate base identities')
    for item in additions:
        if not 0 < item['bytes'] <= MAX_PACKAGE or len(item['sha256']) != 64:
            raise ValueError('Invalid package metadata')
        old = entries.get(item['id'])
        if old is None or item['snapshot'] >= old['snapshot']:
            entries[item['id']] = item
    return {'schema': 'rutasgen-poi-catalog-v1',
            'generatedAt': datetime.now(timezone.utc).isoformat(),
            'packages': sorted(entries.values(), key=lambda p: (p['country'], p['name']))}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['plan', 'merge'])
    parser.add_argument('--prefix')
    args = parser.parse_args()
    base = latest()
    if args.command == 'plan':
        missing = missing_regions(base)
        matrix = {'region': missing or ['none']}
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write('matrix=' + json.dumps(matrix) + '\n')
        print(f'{len(missing)} regiones pendientes; {len(base["packages"])} paquetes conservados')
        return
    if not args.prefix:
        raise ValueError('Release prefix required')
    pages = json.loads(gh('api', '--paginate', '--slurp', f'repos/{os.environ["GH_REPO"]}/releases?per_page=100'))
    additions = []
    for release in (item for page in pages for item in page):
        if release['draft'] or release['prerelease'] or not release['tag_name'].startswith(args.prefix):
            continue
        catalog = read_release_catalog(release['tag_name'])
        assets = {a['browser_download_url']: a for a in release['assets']}
        for item in catalog['packages']:
            asset = assets.get(item['url'])
            if not asset or asset['state'] != 'uploaded' or asset['size'] != item['bytes'] or asset.get('digest') != 'sha256:' + item['sha256']:
                raise ValueError('Published asset mismatch: ' + item['id'])
            additions.append(item)
    if not additions:
        raise ValueError('No new verified packages; previous catalogue unchanged')
    result = merge(base, additions)
    output = Path('combined'); output.mkdir(exist_ok=True)
    path = output / 'catalog-v1.json'
    text = json.dumps(result, ensure_ascii=False)
    if len(text.encode()) > 4 * 1024 * 1024:
        raise ValueError('Catalogue exceeds Android client limit')
    path.write_text(text, encoding='utf-8')
    (output / 'SHA256SUMS').write_text(f'{digest(path)}  catalog-v1.json\n')
    remaining = missing_regions(result)
    summary = f'Publicados en este lote: {len(additions)}. Total catálogo: {len(result["packages"])}.\nPendientes: {", ".join(remaining) or "ninguno"}\n'
    print(summary)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as report: report.write(summary)

if __name__ == '__main__':
    main()
