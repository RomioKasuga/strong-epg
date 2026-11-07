
import gzip
import io
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

OUTPUT = Path("epg.xml")


def download_xml(country, url):
    print(f"\n[{country}] Téléchargement : {url}", flush=True)

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 StrongEPG/1.0"},
    )

    with urllib.request.urlopen(request, timeout=120) as response:
        content = response.read()

    if content.startswith(b"\x1f\x8b"):
        content = gzip.decompress(content)

    root = ET.fromstring(content)

    if root.tag != "tv":
        raise ValueError(
            f"[{country}] Format XMLTV invalide : racine {root.tag}"
        )

    channels = root.findall("channel")
    programmes = root.findall("programme")

    if not channels or not programmes:
        raise ValueError(
            f"[{country}] Guide vide ou sans programmes"
        )

    print(
        f"[{country}] OK : {len(channels)} chaînes, "
        f"{len(programmes)} programmes",
        flush=True,
    )

    return channels, programmes


def main():
    all_channels = {}
    all_programmes = []
    failures = []
    stats = Counter()

    for country, url in SOURCES.items():
        try:
            channels, programmes = download_xml(country, url)

            for channel in channels:
                channel_id = channel.get("id")

                if channel_id and channel_id not in all_channels:
                    all_channels[channel_id] = channel

            for programme in programmes:
                channel_id = programme.get("channel")

                if channel_id:
                    all_programmes.append(programme)

            stats[country] = len(programmes)

        except Exception as error:
            failures.append(f"{country}: {error}")
            print(f"[{country}] ERREUR : {error}", flush=True)

    # Ne jamais publier un guide partiel.
    if failures:
        raise RuntimeError(
            "Fusion annulée :\n" + "\n".join(failures)
        )

    root = ET.Element(
        "tv",
        {"generator-info-name": "Strong EPG Merger"},
    )

    for channel in all_channels.values():
        root.append(channel)

    # Supprime les programmes identiques.
    seen = set()
    unique_programmes = []

    for programme in all_programmes:
        key = (
            programme.get("channel"),
            programme.get("start"),
            programme.get("stop"),
        )

        if key not in seen:
            seen.add(key)
            unique_programmes.append(programme)

    unique_programmes.sort(
        key=lambda p: (
            p.get("channel", ""),
            p.get("start", ""),
        )
    )

    for programme in unique_programmes:
        if programme.get("channel") in all_channels:
            root.append(programme)

    tree = ET.ElementTree(root)

    with OUTPUT.open("wb") as file:
        tree.write(
            file,
            encoding="utf-8",
            xml_declaration=True,
        )

    print("\n=== FUSION TERMINÉE ===")
    print(f"Chaînes : {len(all_channels)}")
    print(f"Programmes : {len(unique_programmes)}")
    print(f"Fichier : {OUTPUT.resolve()}")

    for country, count in stats.items():
        print(f"{country} : {count} programmes")


if __name__ == "__main__":
    main()
