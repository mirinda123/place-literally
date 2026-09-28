"""Apply sourced editorial decisions to the third European city batch."""

import argparse
from datetime import datetime, timezone
import json

from backend.config import ROOT, Settings, connect
from backend.indexing import Feature


RUN_ROOT = ROOT / "work/literal-translations/europe-third-cities-50-20260928"


def meaning(zh, en, ja, fr, es):
    return {"translations": {"zh": zh, "en": en, "ja": ja, "fr": fr, "es": es}}


# The model's cached response is left unchanged. Each decision is guarded by
# the expected Chinese gloss, and every changed ES document is backed up first.
DECISIONS = {
    "osm-node-1559853166": ("Augsburg", ["奥古斯都（尊贵者）之城"], ("replace", [meaning(
        "奥古斯都之城", "Augustus's city", "アウグストゥスの町", "Ville d'Auguste", "Ciudad de Augusto")]),
        "The Roman Augusta honors Emperor Augustus; the deeper meaning of his title is not the city's description."),
    "osm-node-1697770807": ("Livorno", ["利布尔尼亚战船", "利布尔尼亚人的"], ("uncertain", []),
        "The Livorno Port Authority lists ship, Liburnian people, and personal-name origins without resolving them."),
    "osm-node-240028377": ("Wiesbaden", ["草地上的浴场", "疗愈浴场"], ("keep", [0]),
        "Wiesbaden's city lexicon favors the meadow-and-baths interpretation; healing baths is an older reading."),
    "osm-node-240055326": ("Duisburg", ["洪泛平原上方的设防地点", "湿地中的设防地点"], ("uncertain", []),
        "The city occupied flood-free ground, but this does not establish the first element's lexical origin; the wetland root also conflicts."),
    "osm-node-240090728": ("Wuppertal", ["跃动之河的河谷"], ("replace", [meaning(
        "伍珀河谷", "Wupper River valley", "ヴッパー川の谷", "Vallée de la Wupper", "Valle del río Wupper")]),
        "The city combines the Wupper river name and Tal, valley; a deeper river-name root is not certain."),
    "osm-node-240120582": ("Karlsruhe", ["军队的安歇之地", "男子的安歇之地"], ("replace", [meaning(
        "卡尔的安歇之地", "Karl's resting place", "カールの安息の地", "Lieu de repos de Karl", "Lugar de descanso de Karl")]),
        "The name refers to founder Karl Wilhelm's repose; army and man are disputed roots of his personal name."),
    "osm-node-26373169": ("Bonn", ["根基"], ("uncertain", []),
        "The City of Bonn and the German place-name dictionary leave Bonna's meaning unresolved."),
    "osm-node-26553042": ("Szczecin", ["山顶上的聚落", "鬃毛者的城寨"], ("uncertain", []),
        "The National Museum in Szczecin describes conflicting historical forms; hilltop and bristly-name roots remain hypotheses."),
    "osm-node-26686504": ("Dijon", ["神圣的泉", "神圣者迪维乌斯的领地"], ("keep", [0]),
        "Dijon municipal and local-history material supports a sacred-water interpretation; the Divius suffix analysis is weaker."),
    "osm-node-26686539": ("Saint-Étienne", ["戴冠的圣人"], ("replace", [meaning(
        "圣斯德望", "Saint Stephen", "聖ステファノ", "Saint Étienne", "San Esteban")]),
        "Municipal archives trace the place name to a church of Saint Stephen; crown is a deeper root of the saint's name."),
    "osm-node-26686572": ("Angers", ["大洼地之民的城市", "伟大英雄们的城市"], ("replace", [meaning(
        "安德卡维人的城市", "City of the Andecavi", "アンデカウィ族の町", "Cité des Andécaves", "Ciudad de los andécavos")]),
        "The Andecavi people are the documented namesake; analyses of their ethnonym disagree."),
    "osm-node-26686587": ("Rouen", ["好运市场", "战车赛场", "渡河处的聚落"], ("keep", [0, 2]),
        "Peer-reviewed studies offer distinct ratu- fortune and water-crossing analyses; the later roto- wheel account conflicts with earliest Ratumacos forms."),
    "osm-node-26686589": ("Grenoble", ["格拉提安之城（名字源于“恩典”）"], ("replace", [meaning(
        "格拉提安之城", "Gratian's city", "グラティアヌスの町", "Ville de Gratien", "Ciudad de Graciano")]),
        "The city was named for Emperor Gratian; grace is a deeper root of his personal name."),
    "osm-node-27193090": ("Kaunas", ["喜好打斗的人", "低洼之地"], ("replace", [meaning(
        "考纳斯之地", "Place of Kaunas", "カウナスの地", "Lieu de Kaunas", "Lugar de Kaunas")]),
        "The leading scholarly account treats Kaunas as a personal name; the deeper fighter root and lowland alternative are weaker."),
    "osm-node-27350363": ("Essen", ["东面的地区", "长有白蜡树的地区", "有干燥炉的地方"], ("uncertain", []),
        "The city chronicle, diocese, and place-name study give incompatible analyses of Astnide without a settled origin."),
    "osm-node-29272534": ("Valladolid", ["新生者的聚落", "多水的山谷"], ("replace", [meaning(
        "瓦利德的聚落", "Walid's settlement", "ワリードの集落", "Village de Walid", "Poblado de Walid")]),
        "A medieval-name study supports Baldat Ulit, Walid's settlement; newborn is the deeper root of the personal name, and the valley theory is disputed."),
    "osm-node-30014556": ("Lublin", ["亲爱之人的聚落"], ("replace", [meaning(
        "卢布拉的聚落", "Lubla's settlement", "ルブラの集落", "Village de Lubla", "Poblado de Lubla")]),
        "The possessive place-name points to personal name Lubla; dear is only a deeper root of that name."),
    "osm-node-31337673": ("Bydgoszcz", ["比德戈斯特的聚落（唤醒与待客）"], ("replace", [meaning(
        "比德戈斯特的聚落", "Bydgost's settlement", "ビドゴストの集落", "Village de Bydgost", "Poblado de Bydgost")]),
        "The settlement is associated with Bydgost; awakening and guests analyze his personal name rather than the city."),
    "osm-node-406747508": ("Padova", ["开阔的平原", "松树林"], ("uncertain", []),
        "Treccani calls Patavium's history complex; open-land, pine, and river derivations remain speculative."),
    "osm-node-57116400": ("Timișoara", ["沼泽河畔的堡垒"], ("replace", [meaning(
        "蒂米什河畔的堡垒", "Fortress on the Timiș River", "ティミシュ川の城塞", "Forteresse sur la rivière Timiș", "Fortaleza junto al río Timiș")]),
        "Hungarian Temesvár combines the Timiș river name and fortress; swamp is an uncertain deeper river-name reconstruction."),
    "osm-node-62221032": ("Πάτρα", ["故乡"], ("uncertain", []),
        "The modern form resembles a Greek word for homeland, but that does not establish the city's etymology; Pausanias records a different founder tradition."),
    "osm-node-68528603": ("Taranto", ["湍急的河流", "橡树"], ("uncertain", []),
        "The museum records a Taras river or namesake figure, while the swift-river and oak lexical roots are disputed."),
    "osm-node-69300003": ("Modena", ["土丘", "多雾的城市"], ("uncertain", []),
        "Etruscan mound and Celtic fog derivations of ancient Mutina remain competing reconstructions."),
    "osm-node-69300007": ("Parma", ["圆盾"], ("uncertain", []),
        "Treccani considers the round-shield derivation less probable and the older city and river name unresolved."),
    "osm-node-823582966": ("Brest", ["高地", "极远之民的山丘"], ("keep", [0]),
        "The Breton Language Office gives the height reading from Breton bri/bre; the farthest-people suffix analysis is more speculative."),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_env()
    source_notes = {}
    for cache_file in (RUN_ROOT / "cache").glob("*.json"):
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        source_notes[cached["input"]["feature_id"]] = cached["result"].get("note", "")
    changes, already, decisions = [], [], {}
    with connect(settings) as client:
        for feature_id, (label, expected_zh, action, reason) in DECISIONS.items():
            hit = client.get(index=settings.index, id=feature_id)
            doc = hit["_source"]
            if (doc.get("feature_id") != feature_id or doc.get("kind") != "city"
                    or label not in doc.get("names", {}).values()):
                raise ValueError(f"Unexpected identity: {feature_id}")
            current = doc.get("literal_meanings") or []
            mode, value = action
            replacement = ([current[i] for i in value] if mode == "keep" else
                           value if mode == "replace" else [])
            if current != replacement and [m["translations"].get("zh") for m in current] != expected_zh:
                raise ValueError(f"Meanings changed for {feature_id}")
            patch = {"literal_meanings": replacement, "meaning_id": None}
            Feature.model_validate({**doc, **patch})
            if current != replacement:
                changes.append((hit, patch))
            else:
                already.append(feature_id)
            decisions[feature_id] = {
                "label": label, "status": "uncertain" if not replacement else "corrected",
                "reason": reason, "before_zh": expected_zh,
                "after_zh": [m["translations"]["zh"] for m in replacement],
                "source_note": source_notes.get(feature_id, ""),
            }
        report = {"index": settings.index, "apply": args.apply, "changes": len(changes),
                  "already_corrected": already, "decisions": decisions}
        if args.apply:
            run_dir = RUN_ROOT / "editorial-review" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            run_dir.mkdir(parents=True, exist_ok=False)
            (run_dir / "before.json").write_text(json.dumps(
                [{"hit": dict(hit), "patch": patch} for hit, patch in changes],
                ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            for hit, patch in changes:
                client.update(index=settings.index, id=hit["_id"], doc=patch,
                              if_seq_no=hit["_seq_no"], if_primary_term=hit["_primary_term"],
                              refresh="wait_for")
            (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (RUN_ROOT / "editorial-decisions.json").write_text(json.dumps(
                {"reviewed_at": datetime.now(timezone.utc).isoformat(), "decisions": decisions},
                ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            report["backup_dir"] = str(run_dir.resolve())
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
