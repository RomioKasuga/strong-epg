"""Guide FR/PT de test, indépendant de l'EPG principal.
Aucun identifiant ni URL de flux IPTV n'est publié.
"""
import gzip
import os
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

SOURCES = [
    "https://epgshare01.online/epgshare01/epg_ripper_FR1.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_PT1.xml.gz",
]
OUTPUT = Path("epg-fr-pt-test.xml.gz")

def main():
    channels = {}
    programmes = {}
    for url in SOURCES:
        print("Téléchargement:", url, flush=True)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=180) as response:
            payload = response.read()
        if payload[:2] == b"\x1f\x8b":
            payload = gzip.decompress(payload)
        root = ET.fromstring(payload)
        if root.tag != "tv":
            raise ValueError("XMLTV invalide")
        count = 0
        for child in root:
            if child.tag == "channel":
                cid = child.get("id")
                if cid:
                    channels.setdefault(cid, child)
            elif child.tag == "programme":
                key = (child.get("channel"), child.get("start"), child.get("stop"))
                if all(key):
                    programmes.setdefault(key, child)
                    count += 1
        print("Programmes lus:", count, flush=True)
    tv = ET.Element("tv", {"generator-info-name": "Strong FR/PT test EPGShare"})
    for ch in channels.values():
        tv.append(ch)
    for pr in programmes.values():
        if pr.get("channel") in channels:
            tv.append(pr)
    tmp = OUTPUT.with_suffix(".tmp")
    try:
        with tmp.open("wb") as out:
            with gzip.GzipFile(filename="", mode="wb", fileobj=out, compresslevel=6, mtime=0) as zipped:
                ET.ElementTree(tv).write(zipped, encoding="utf-8", xml_declaration=True)
        with gzip.open(tmp, "rb") as f:
            check = ET.parse(f).getroot()
            assert check.tag == "tv" and check.findall("programme")
        os.replace(tmp, OUTPUT)
    finally:
        if tmp.exists():
            tmp.unlink()
    print("Publié:", OUTPUT, len(channels), len(programmes), flush=True)

if __name__ == "__main__":
    main()
