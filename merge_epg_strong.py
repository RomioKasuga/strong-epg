import copy
import csv
import gzip
import hashlib
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

SOURCES = {
    'FR': 'https://iptv-epg.org/files/epg-fr.xml',
    'PT': 'https://iptv-epg.org/files/epg-pt.xml',
    'GB': 'https://iptv-epg.org/files/epg-gb.xml',
    'US': 'https://iptv-epg.org/files/epg-us.xml',
}
OUTPUT = Path('epg.xml.gz')
CSV_PATH = Path('correspondances_strong_epg.csv')
MAX_GITHUB_SIZE = 95 * 1024 * 1024
# Conservative first test: avoids duplicating 1000+ channels' schedules.
MAX_ALIASES = 350


def download_xml(country, url):
    print(f'[{country}] Téléchargement : {url}', flush=True)
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 StrongEPG/1.0'})
    with urllib.request.urlopen(request, timeout=180) as response:
        content = response.read()
    if content.startswith(b'\x1f\x8b'):
        content = gzip.decompress(content)
    root = ET.fromstring(content)
    if root.tag != 'tv':
        raise ValueError(f'[{country}] Racine XMLTV invalide : {root.tag}')
    channels = root.findall('channel')
    programmes = root.findall('programme')
    if not channels or not programmes:
        raise ValueError(f'[{country}] Guide vide')
    print(f'[{country}] {len(channels)} chaînes, {len(programmes)} programmes', flush=True)
    return channels, programmes


def read_aliases():
    if not CSV_PATH.exists():
        raise FileNotFoundError(f'CSV absent : {CSV_PATH}')
    mapping = defaultdict(set)
    with CSV_PATH.open('r', encoding='utf-8-sig', newline='') as file:
        reader = csv.DictReader(file)
        expected = {'Chaine_Strong', 'EPG_Strong', 'EPG_Candidat', 'Statut'}
        if not expected.issubset(reader.fieldnames or []):
            raise ValueError('Colonnes CSV manquantes')
        for row in reader:
            if (row['Statut'] or '').strip() != 'Correspondance unique':
                continue
            name = (row['Chaine_Strong'] or '').strip()
            source_id = (row['EPG_Candidat'] or '').strip()
            if name and source_id and not (row['EPG_Strong'] or '').strip():
                mapping[name].add(source_id)
    return {name: next(iter(ids)) for name, ids in mapping.items() if len(ids) == 1}


def priority(item):
    name, source_id = item
    upper = name.upper()
    # Prefer recognisable FR/PT channel groups, then HD and normal variants.
    group = 0 if upper.startswith(('FR:', 'PT:', 'VIP:', 'MEO:')) else 1
    quality = 0 if ' HD' in upper else 1 if not any(x in upper for x in ('4K', 'UHD', 'RAW', 'HEVC')) else 2
    return (group, quality, source_id.casefold(), name.casefold())


def main():
    channels = {}
    programmes = []
    seen = set()
    stats = Counter()
    failures = []
    eligible_sources = set()

    for country, url in SOURCES.items():
        try:
            source_channels, source_programmes = download_xml(country, url)
            if country in ('FR', 'PT'):
                eligible_sources.update(ch.get('id') for ch in source_channels if ch.get('id'))
            for channel in source_channels:
                channel_id = channel.get('id')
                if channel_id and channel_id not in channels:
                    channels[channel_id] = channel
            for programme in source_programmes:
                channel_id = programme.get('channel')
                key = (channel_id, programme.get('start'), programme.get('stop'))
                if channel_id and key not in seen:
                    seen.add(key)
                    programmes.append(programme)
            stats[country] = len(source_programmes)
        except Exception as error:
            failures.append(f'{country}: {error}')
            print(f'[{country}] ERREUR : {error}', flush=True)
    if failures:
        raise RuntimeError('Fusion annulée :\n' + '\n'.join(failures))

    aliases = read_aliases()
    candidates = sorted(
        ((name, source_id) for name, source_id in aliases.items()
         if source_id in eligible_sources and source_id in channels),
        key=priority,
    )
    print(f'Correspondances uniques CSV : {len(aliases)}')
    print(f'Candidats ayant une source FR/PT : {len(candidates)}')
    print(f'Limite volontaire pour ce test : {MAX_ALIASES} alias')
    by_source = defaultdict(list)
    added_channels = 0
    for strong_name, source_id in candidates[:MAX_ALIASES]:
        alias_id = 'strong.alias.' + hashlib.sha256(strong_name.encode('utf-8')).hexdigest()[:20]
        if alias_id in channels:
            continue
        alias_channel = ET.Element('channel', {'id': alias_id})
        ET.SubElement(alias_channel, 'display-name').text = strong_name
        for icon in channels[source_id].findall('icon'):
            alias_channel.append(copy.deepcopy(icon))
        channels[alias_id] = alias_channel
        by_source[source_id].append(alias_id)
        added_channels += 1

    added_programmes = 0
    for programme in list(programmes):
        for alias_id in by_source.get(programme.get('channel'), ()):
            alias_programme = copy.deepcopy(programme)
            alias_programme.set('channel', alias_id)
            programmes.append(alias_programme)
            added_programmes += 1

    programmes.sort(key=lambda p: (p.get('channel', ''), p.get('start', '')))
    root = ET.Element('tv', {'generator-info-name': 'Strong EPG Merger FR/PT test'})
    for channel in channels.values():
        root.append(channel)
    for programme in programmes:
        if programme.get('channel') in channels:
            root.append(programme)

    print('Compression GZIP en cours...', flush=True)
    temp_output = OUTPUT.with_suffix('.gz.tmp')
    try:
        with temp_output.open('wb') as raw_file:
            with gzip.GzipFile(filename='', mode='wb', fileobj=raw_file, compresslevel=9, mtime=0) as compressed_file:
                ET.ElementTree(root).write(compressed_file, encoding='utf-8', xml_declaration=True)
        size = temp_output.stat().st_size
        print(f'Chaînes : {len(channels)} ; programmes : {len(programmes)}')
        print(f'Alias ajoutés : {added_channels} ; programmes dupliqués : {added_programmes}')
        print(f'Alias écartés (hors FR/PT ou source absente) : {len(aliases) - len(candidates)}')
        print(f'Alias FR/PT reportés (limite de test) : {max(0, len(candidates) - MAX_ALIASES)}')
        print(f'Taille compressée : {size / 1024 / 1024:.2f} Mio')
        for country, count in stats.items():
            print(f'{country} : {count} programmes sources')
        if size > MAX_GITHUB_SIZE:
            raise RuntimeError('Taille > 95 Mio : test annulé, ancien fichier préservé')
        temp_output.replace(OUTPUT)
        print('Compression validée !')
    finally:
        if temp_output.exists():
            temp_output.unlink()


if __name__ == '__main__':
    main()
