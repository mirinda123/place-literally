"""Apply sourced, conservative editorial decisions to the Africa city batch."""

import argparse
from datetime import datetime, timezone
import json
import re

from backend.config import ROOT, Settings, connect
from backend.indexing import Feature


RUN_ROOT = ROOT / "work/literal-translations/africa-cities-50-20260927"


def meaning(zh, en, ja, fr, es):
    return {"translations": {"zh": zh, "en": en, "ja": ja, "fr": fr, "es": es}}


# Modes: keep only selected parallel senses; replace all five-language glosses;
# or clear an unresolvable etymology. The cached model response remains intact.
DECISIONS = {
    "osm-node-1046100133": ("Abidjan", ["比让人的土地", "制定规则者居住的地方"], ("keep", [0]),
        "The Bidjan association is documented; the deeper rule-maker split is a single disputed proposal."),
    "osm-node-25470100": ("Gqeberha", ["芦苇", "在山谷中"], ("keep", [0]),
        "Local toponymic scholarship favors the reeds reading; the valley segmentation is disputed."),
    "osm-node-255590322": ("Mwanza", ["湖", "往湖边"], ("keep", [0]),
        "Both proposed Sukuma source phrases share the lake root; their difference is unproved."),
    "osm-node-261833893": ("Johannesburg", ["约翰内斯之城（耶和华是仁慈的）"], ("replace", [meaning(
        "约翰内斯之城", "Johannes's city", "ヨハネスの町", "Ville de Johannes", "Ciudad de Johannes")]),
        "The city is named for a Johann/Johannes; the deeper Hebrew sense of his personal name is not the city's literal description."),
    "osm-node-27564946": ("Constantine", ["坚定不移"], ("replace", [meaning(
        "君士坦丁之城", "Constantine's city", "コンスタンティヌスの町", "Ville de Constantin", "Ciudad de Constantino")]),
        "The Algerian city was named for Emperor Constantine, not for the abstract Latin root of his name."),
    "osm-node-27564968": ("Tunis", ["过夜的营地"], ("uncertain", []),
        "The ancient T-N-S overnight-camp reading is a proposal without an established derivation."),
    "osm-node-27043346": ("Kinshasa", ["交易之地", "盐袋之地"], ("uncertain", []),
        "The trade-place and salt-sack analyses of older Nshasa conflict and neither lexical derivation is established."),
    "osm-node-27564941": ("Luanda", ["低平地", "贡税", "渔网"], ("uncertain", []),
        "The island name has several competing historical and Kimbundu explanations without a secure root."),
    "osm-node-27565027": ("Dar es Salaam", ["和平之家", "和平之港"], ("keep", [0]),
        "The written dār as-salām means house of peace; the Bandar/harbour chain is disputed."),
    "osm-node-27565020": ("Alexandria", ["护卫众人者之城"], ("replace", [meaning(
        "亚历山大之城", "Alexander's city", "アレクサンドロスの町", "Ville d'Alexandre", "Ciudad de Alejandro")]),
        "The city was named for Alexander the Great; the deeper Greek root of his personal name should not replace the namesake."),
    "osm-node-27564994": ("Lusaka", ["卢萨卡的村庄", "荆棘灌木丛"], ("keep", [0]),
        "The headman Lusaaka and village chain is documented; the thorn-bush etymology of his name is contested."),
    "osm-node-27565008": ("Bouaké", ["格贝凯的村庄", "干羊"], ("keep", [0]),
        "Gbéké's village is documented; the dry-sheep reading is a folk segmentation."),
    "osm-node-27564996": ("Durban", ["城里人的后裔", "托尔之熊"], ("uncertain", []),
        "The city honors Governor D'Urban, but competing surname roots cannot be assigned to his family."),
    "osm-node-27565045": ("Dakar", ["罗望子树", "避难之地"], ("uncertain", []),
        "The tamarind and refuge explanations compete without a demonstrated historical derivation."),
    "osm-node-27565065": ("Port Harcourt", ["赫鲁尔夫（军狼）庄园的港口"], ("replace", [meaning(
        "哈考特港", "Port of Harcourt", "ハーコート港", "Port de Harcourt", "Puerto de Harcourt")]),
        "The port was named for Lewis Harcourt; remote, uncertain surname roots are not part of the place-name gloss."),
    "osm-node-27565116": ("Antananarivo", ["千人之城", "在人民的土地上"], ("keep", [0]),
        "Madagascar's UNESCO submission supports the thousand-town reading; the second requires a proposed earlier spelling."),
    "osm-node-27565117": ("Khartoum", ["象鼻", "红花"], ("keep", [0]),
        "Arabic خرطوم directly means trunk or snout; the safflower proposal requires an unproved spelling change."),
    "osm-node-289035432": ("Fez", ["斧头"], ("uncertain", []),
        "The axe is a founding tale, while another history derives the name from an older settlement; origin remains unsettled."),
    "osm-node-298296168": ("Dire Dawa", ["药物之原野"], ("uncertain", []),
        "The medicine-plain analysis competes with other Oromo and Somali explanations without a settled origin."),
    "osm-node-32675806": ("Cape Town", ["好望角之城"], ("replace", [meaning(
        "海角之城", "Town of the Cape", "ケープの町", "Ville du Cap", "Ciudad del Cabo")]),
        "The given name literally says Cape Town; Good Hope belongs in its naming history, not the short gloss."),
    "osm-node-31203257": ("Abuja", ["肤色偏红的幼骆驼之父"], ("replace", [meaning(
        "阿布·贾之城", "City of Abu Ja", "アブ・ジャの町", "Ville d'Abu Ja", "Ciudad de Abu Ja")]),
        "The capital inherited the older town's name, itself linked to ruler Abu Ja; camel imagery expands a remote personal-name root."),
    "osm-node-71556493": ("Gonder", ["两河之间", "沟渠边缘"], ("uncertain", []),
        "The older name has competing Qemant, Agaw, and Amharic analyses without a demonstrated derivation."),
    "osm-node-60715164": ("Goma", ["鼓"], ("uncertain", []),
        "The drum interpretation comes from a local volcanic-sound legend; no linguistic origin is established."),
    "osm-node-732125487": ("Douala", ["旅行者的河口", "旅行者"], ("uncertain", []),
        "The Ewale association is established, but the locative and travel-word derivations conflict."),
    "osm-node-34684808": ("Mogadishu", ["令人目眩者", "沙阿的驻地"], ("uncertain", []),
        "Somali and Persian-Arabic etymologies conflict; neither historical derivation is established."),
    "osm-node-331136682": ("Yaoundé", ["埃翁多人的地方", "花生"], ("keep", [0]),
        "The city name is traced to the Ewondo people; the groundnut root is an uncertain deeper ethnonym analysis."),
    "osm-node-671824694": ("Thiès", ["Boscia angustifolia 树"], ("replace", [meaning(
        "树", "Tree", "木", "Arbre", "Árbol")]),
        "Two local Noon traditions identify ndiess as a tree; the exact botanical species is supported by only one account."),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_env()
    changes, already, decisions = [], [], {}
    source_notes = {}
    for cache_file in (RUN_ROOT / "cache").glob("*.json"):
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        source_notes[cached["input"]["feature_id"]] = cached["result"].get("note", "")
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
