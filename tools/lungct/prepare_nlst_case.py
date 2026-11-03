"""Explicit online download of ONE licensed, reference-annotated public CT.

Run in the separate download environment with idc-index; never from the app.
Original files are byte-preserved. SEG is an external validation reference only.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / 'data/lungct-assets/nlst100206'
CT = '1.2.840.113654.2.55.311588773585696213046701923278910973620'
SEG = '1.2.276.0.7230010.3.1.3.296485632.7.1764581241.581065'
BASE = 'https://storage.googleapis.com/idc-open-data'


def download_series(row, directory):
    directory.mkdir(parents=True, exist_ok=True)
    prefix = row['crdc_series_uuid'] + '/'
    listing = ET.fromstring(urllib.request.urlopen(BASE + '?prefix=' + prefix, timeout=60).read())
    ns = {'s': 'http://doc.s3.amazonaws.com/2006-03-01'}
    if listing.findtext('s:IsTruncated', namespaces=ns) != 'false':
        raise ValueError('Refuse incomplete object listing')
    objects = listing.findall('s:Contents', ns)
    if len(objects) != row['instanceCount']:
        raise ValueError('IDC instance count mismatch')

    def fetch(item):
        key = item.findtext('s:Key', namespaces=ns)
        etag = item.findtext('s:ETag', namespaces=ns).strip('"')
        size = int(item.findtext('s:Size', namespaces=ns))
        target = directory / Path(key).name
        content = target.read_bytes() if target.exists() else urllib.request.urlopen(BASE+'/'+key, timeout=120).read()
        if len(content) != size or hashlib.md5(content).hexdigest() != etag:
            raise ValueError('Publisher object integrity mismatch')
        if not target.exists(): target.write_bytes(content)
        return dict(file=target.relative_to(DEST).as_posix(), url=BASE+'/'+key,
                    sha256=hashlib.sha256(content).hexdigest(), bytes=size, publisher_etag=etag)
    with ThreadPoolExecutor(max_workers=6) as pool:
        return list(pool.map(fetch, objects))


def main():
    from idc_index import IDCClient
    client = IDCClient()
    rows = client.index[client.index.SeriesInstanceUID.isin([CT, SEG])].to_dict('records')
    if len(rows) != 2: raise ValueError('Expected exactly two pinned series')
    manifest = []
    for row in rows:
        if row['license_short_name'] != 'CC BY 4.0': raise ValueError('License changed')
        files = download_series(row, DEST / ('original' if row['Modality'] == 'CT' else 'reference'))
        manifest.append(dict(series_uid=row['SeriesInstanceUID'], modality=row['Modality'],
            source_doi=row['source_DOI'], license=row['license_short_name'], files=files))
        print(row['Modality'], len(files), 'files verified', flush=True)
    (DEST/'provisioning.json').write_text(json.dumps(dict(public_case='NLST-100206',
        source='https://www.cancerimagingarchive.net/collection/nlst/',
        reference='https://portal.imaging.datacommons.cancer.gov/analysis_results/lidc_annot_nlst501/',
        series=manifest), indent=2), encoding='utf-8')


if __name__ == '__main__': main()
