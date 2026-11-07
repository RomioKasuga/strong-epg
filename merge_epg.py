
import gzip
import shutil
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

SOURCES = {
    "FR": "https://iptv-epg.org/files/epg-fr.xml",
    "PT": "https://iptv-epg.org/files/epg-pt.xml",
    "GB": "https://iptv-epg.org/files/epg-gb.xml",
    "US": "https://iptv-epg.org/files/epg-us.xml",
}

OUTPUT = Path("epg.xml.gz")
MAX_GITHUB_SIZE = 95 * 1024 * 1024


def download_xml(country, url):
    print(f"\n[{country}] Téléchargement : {url}", flush=True)

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 StrongEPG/1.0"},
    )

    with urllib.request.urlopen(request, timeout=180) as response:
        content = response.read()

    if content.startswith(b"\x1f\x8b"):
        content = gzip.decompress(content)

    root = ET.fromstring(content)

    if root.tag != "tv":
        raise ValueError(
            f"[{country}] Racine XMLTV invalide : {root.tag}"
        )

    channels = root.findall("channel")
    programmes = root.findall("programme")

    if not channels or not programmes:
        raise ValueError(f"[{country}] Guide vide")

    print(
        f"[{country}] {len(channels)} chaînes, "
        f"{len(programmes)} programmes",
        flush=True,
    )

    return channels, programmes


def main():
    channels = {}
    programmes = []
    seen = set()
    stats = Counter()
    failures = []

    for country, url in SOURCES.items():
        try:
            source_channels, source_programmes = download_xml(
                country, url
            )

            for channel in source_channels:
                channel_id = channel.get("id")

                if channel_id and channel_id not in channels:
                    channels[channel_id] = channel

            for programme in source_programmes:
                channel_id = programme.get("channel")
                key = (
                    channel_id,
                    programme.get("start"),
                    programme.get("stop"),
                )

                if channel_id and key not in seen:
                    seen.add(key)
                    programmes.append(programme)

            stats[country] = len(source_programmes)

        except Exception as error:
            failures.append(f"{country}: {error}")
            print(f"[{country}] ERREUR : {error}", flush=True)

    if failures:
        raise RuntimeError(
            "Fusion annulée :\n" + "\n".join(failures)
        )

    programmes.sort(
        key=lambda p: (
            p.get("channel", ""),
            p.get("start", ""),
        )
    )

    root = ET.Element(
        "tv",
        {"generator-info-name": "Strong EPG Merger"},
    )

    for channel in channels.values():
        root.append(channel)

    for programme in programmes:
        if programme.get("channel") in channels:
            root.append(programme)

    print("\nCompression GZIP en cours...", flush=True)

    with OUTPUT.open("wb") as raw_file:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw_file,
            compresslevel=9,
            mtime=0,
        ) as compressed_file:
            ET.ElementTree(root).write(
                compressed_file,
                encoding="utf-8",
                xml_declaration=True,
            )

    size = OUTPUT.stat().st_size

    print("\n=== FUSION TERMINÉE ===")
    print(f"Chaînes : {len(channels)}")
    print(f"Programmes : {len(programmes)}")
    print(f"Fichier : {OUTPUT}")
    print(f"Taille compressée : {size / 1024 / 1024:.2f} Mo")

    for country, count in stats.items():
        print(f"{country} : {count} programmes")

    if size > MAX_GITHUB_SIZE:
        raise RuntimeError(
            "Fichier compressé encore trop volumineux "
            "pour GitHub. Il faudra adapter la publication."
        )

    print("Compression validée !")


if __name__ == "__main__":
    main()
