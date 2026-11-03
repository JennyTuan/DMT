"""Explicit online provisioning only. The application runtime never downloads."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[2]
DEST=ROOT/'data'/'lungct-assets'
REV='7226a40a4c3713f7d5469559b7f2fc296fd54825'
SERIES='1.3.6.1.4.1.14519.5.2.1.6279.6001.179049373636438705059720603192'
EXPECTED='b5e79231466adae93a6fe8e8594029e9add142914e223b879aa0343bb2402d01'


def fetch(url,path,expected=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        temporary=path.with_suffix(path.suffix+'.partial')
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'DMT-LungCT-Research/0.1'}),timeout=120) as source,temporary.open('wb') as target:
            shutil.copyfileobj(source,target,1024*1024)
        temporary.replace(path)
    checksum=hashlib.sha256(path.read_bytes()).hexdigest()
    if expected and checksum!=expected:raise ValueError('Downloaded checksum differs from publisher metadata')
    print(json.dumps({'file':path.relative_to(DEST).as_posix(),'bytes':path.stat().st_size,'sha256':checksum}),flush=True)
    return dict(url=url,file=path.relative_to(DEST).as_posix(),sha256=checksum,bytes=path.stat().st_size)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--include-rejected-lidc-case',action='store_true',
        help='Reproduce initial intake investigation only: LIDC-IDRI-0001 has IV contrast and is NOT eligible for P0.')
    args=parser.parse_args()
    bundle=DEST/'monai-0.6.9'
    entries=[(f'https://huggingface.co/MONAI/lung_nodule_ct_detection/resolve/{REV}/{file}',bundle/file,EXPECTED if file=='models/model.pt' else None)
             for file in ['models/model.pt','configs/metadata.json','configs/inference.json','LICENSE','docs/README.md']]
    if args.include_rejected_lidc_case: entries += [
        (f'https://services.cancerimagingarchive.net/nbia-api/services/v1/getImage?SeriesInstanceUID={SERIES}&NewFileNames=Yes',DEST/'lidc0001'/'source.zip',None),
        ('https://www.cancerimagingarchive.net/wp-content/uploads/LIDC-XML-only.zip',DEST/'annotations.zip',None)]
    with ThreadPoolExecutor(max_workers=3) as pool:manifest=list(pool.map(lambda args:fetch(*args),entries))
    (DEST/'model-provisioning.json').write_text(json.dumps(dict(model_revision=REV,downloads=manifest),indent=2),encoding='utf-8')
    if not args.include_rejected_lidc_case:return
    target=DEST/'lidc0001'/'original';target.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(DEST/'lidc0001'/'source.zip') as archive:
        for member in archive.infolist():
            if member.is_dir():continue
            path=(target/member.filename).resolve()
            if not path.is_relative_to(target.resolve()):raise ValueError('Unsafe archive member')
            path.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(member) as source,path.open('wb') as output:shutil.copyfileobj(source,output)
    matches=[]
    with zipfile.ZipFile(DEST/'annotations.zip') as archive:
        for name in archive.namelist():
            if not name.lower().endswith('.xml'):continue
            payload=archive.read(name)
            if SERIES.encode() in payload:
                path=DEST/'lidc0001'/('annotation-'+str(len(matches))+'.xml');path.write_bytes(payload);matches.append(name)
    provenance=dict(collection='LIDC-IDRI',public_case='LIDC-IDRI-0001',series_uid=SERIES,license='CC BY 3.0',
                    source='https://www.cancerimagingarchive.net/collection/lidc-idri/',doi='10.7937/K9/TCIA.2015.LO9QL9SX',
                    model_revision=REV,downloads=manifest,matched_annotation_files=matches,
                    restriction='Technical reproduction only; no independent performance claim; no clinical diagnosis')
    (DEST/'provisioning.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Matching annotation XML files:',matches)


if __name__=='__main__':main()
