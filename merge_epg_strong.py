"""Fusion XMLTV FR/PT/GB/US avec alias Strong sûrs.

Seuls les identifiants Strong explicites et validés sont utilisés.
Les lignes ambiguës ou à vérifier sont ignorées volontairement.
"""
import copy
import csv
import gzip
import os
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

SOURCES = {
    "FR": "https://iptv-epg.org/files/epg-fr.xml",
    "PT": "https://iptv-epg.org/files/epg-pt.xml",
    "GB": "https://iptv-epg.org/files/epg-gb.xml",
    "US": "https://iptv-epg.org/files/epg-us.xml",
}
EXTRA_FR_SOURCE = "https://epgshare01.online/epgshare01/epg_ripper_FR1.xml.gz"
EXTRA_PT_SOURCE = "https://epgshare01.online/epgshare01/epg_ripper_PT1.xml.gz"
EXTRA_UK_SOURCE = "https://epgshare01.online/epgshare01/epg_ripper_UK1.xml.gz"
OUTPUT = Path("epg.xml.gz")
CSV_PATH = Path("correspondances_strong_epg.csv")
MAX_SIZE = 95 * 1024 * 1024

# Correspondance vérifiée manuellement lors des tests précédents.
VERIFIED = {"canalplussport360.fr": "CANAL+SPORT360.fr"}


def download(country, url):
    print(f"[{country}] Téléchargement", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 StrongEPG/1.0"})
    with urllib.request.urlopen(req, timeout=180) as response:
        content = response.read()
    if content.startswith(b"\x1f\x8b"):
        content = gzip.decompress(content)
    root = ET.fromstring(content)
    if root.tag != "tv":
        raise ValueError(f"XMLTV invalide pour {country}")
    channels = root.findall("channel")
    programmes = root.findall("programme")
    if not channels or not programmes:
        raise ValueError(f"Guide vide pour {country}")
    print(f"[{country}] {len(channels)} chaînes, {len(programmes)} programmes")
    return channels, programmes


def read_verified_aliases():
    """N'accepte que les ID Strong explicites déjà identifiés dans le CSV.

    Les statuts 'À vérifier' ne sont pas validés automatiquement.
    """
    if not CSV_PATH.exists():
        raise FileNotFoundError(CSV_PATH)
    by_strong = defaultdict(set)
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"EPG_Strong", "EPG_Candidat", "Statut"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Colonnes CSV manquantes")
        for row in reader:
            if (row["Statut"] or "").strip() != "Déjà identifié":
                continue
            strong = (row["EPG_Strong"] or "").strip()
            candidate = (row["EPG_Candidat"] or "").strip()
            if strong and candidate:
                by_strong[strong].add(candidate)
    return {strong: next(iter(ids)) for strong, ids in by_strong.items() if len(ids) == 1}


def main():
    channels = {}
    programmes = []
    seen = set()
    stats = Counter()

    # Échec explicite si une source échoue : on ne publie pas de guide incomplet.
    for country, url in SOURCES.items():
        source_channels, source_programmes = download(country, url)
        for channel in source_channels:
            cid = channel.get("id")
            if cid and cid not in channels:
                channels[cid] = channel
        for programme in source_programmes:
            cid = programme.get("channel")
            key = (cid, programme.get("start"), programme.get("stop"))
            if cid and key not in seen:
                seen.add(key)
                programmes.append(programme)
        stats[country] = len(source_programmes)

    # Sources complémentaires optionnelles : FR et PT.
    for extra_name, extra_url in (("FR-EPGShare", EXTRA_FR_SOURCE), ("PT-EPGShare", EXTRA_PT_SOURCE), ("UK-EPGShare", EXTRA_UK_SOURCE)):
        try:
            extra_channels, extra_programmes = download(extra_name, extra_url)
            for channel in extra_channels:
                cid = channel.get("id")
                if cid and cid not in channels:
                    channels[cid] = channel
            for programme in extra_programmes:
                cid = programme.get("channel")
                key = (cid, programme.get("start"), programme.get("stop"))
                if cid in channels and key not in seen:
                    seen.add(key)
                    programmes.append(programme)
            stats[extra_name] = len(extra_programmes)
        except Exception as exc:
            print(f"[{extra_name}] Source optionnelle indisponible : {exc}", flush=True)

    aliases = read_verified_aliases()
    aliases.update(VERIFIED)
    by_source = defaultdict(list)
    rejected = Counter()
    for strong_id, source_id in sorted(aliases.items()):
        if source_id not in channels:
            rejected["source absente"] += 1
            continue
        if strong_id in channels:
            # Ne jamais remplacer un identifiant XMLTV déjà existant.
            if strong_id != source_id:
                rejected["ID déjà utilisé"] += 1
            continue
        clone = copy.deepcopy(channels[source_id])
        clone.set("id", strong_id)
        channels[strong_id] = clone
        by_source[source_id].append(strong_id)

    added = 0
    for programme in list(programmes):
        for alias in by_source.get(programme.get("channel"), ()):
            clone = copy.deepcopy(programme)
            clone.set("channel", alias)
            programmes.append(clone)
            added += 1

    programmes.sort(key=lambda p: (p.get("channel", ""), p.get("start", "")))
    root = ET.Element("tv", {"generator-info-name": "Strong EPG FR/PT/GB/US"})
    for channel in channels.values():
        root.append(channel)
    for programme in programmes:
        if programme.get("channel") in channels:
            root.append(programme)

    temporary = OUTPUT.with_name(OUTPUT.name + ".tmp")
    try:
        with temporary.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as compressed:
                ET.ElementTree(root).write(compressed, encoding="utf-8", xml_declaration=True)
        size = temporary.stat().st_size
        if size > MAX_SIZE:
            raise RuntimeError(f"EPG trop volumineux : {size} octets")
        # Validation avant remplacement du fichier publié.
        with gzip.open(temporary, "rb") as f:
            if ET.parse(f).getroot().tag != "tv":
                raise ValueError("Fichier final invalide")
        os.replace(temporary, OUTPUT)
    finally:
        if temporary.exists():
            temporary.unlink()

    print(f"Alias Strong ajoutés : {sum(map(len, by_source.values()))}")
    print(f"Programmes dupliqués : {added}")
    print(f"Alias ignorés : {dict(rejected)}")
    print(f"Total : {len(channels)} chaînes, {len(programmes)} programmes")
    print(f"EPG généré : {size / 1024 / 1024:.2f} Mio")
    print(f"Sources : {dict(stats)}")


if __name__ == "__main__":
    main()
