"""Apply conservative editorial decisions to the selected South America cities."""

import argparse
from datetime import datetime, timezone
import json

from backend.config import ROOT, Settings, connect
from backend.indexing import Feature


RUN_ROOT = ROOT / "work/literal-translations/south-america-cities-40-20260927"


def meaning(zh, en, ja, fr, es):
    return {"translations": {"zh": zh, "en": en, "ja": ja, "fr": fr, "es": es}}


# The model results remain an immutable record. An empty replacement records an
# unresolved etymology, rather than presenting a conjecture as a fact in the UI.
DECISIONS = {
    "osm-node-198403560": ("Mendoza", ["寒冷的山", "Ventuitius的庄园"], [],
        "The Argentine city is named for governor García Hurtado de Mendoza; the surname's deeper Basque/Latin derivations compete.",
        ["https://www.argentina.gob.ar/node/151248", "https://www.euskaltzaindia.eus/dok/iker_jagon_tegiak/80204.pdf"]),
    "osm-node-214220794": ("Antofagasta", ["大盐滩的村庄", "隐藏的铜"], [],
        "The coastal city borrowed Antofagasta de la Sierra's name; both proposed Indigenous analyses remain unproved.",
        ["https://www.memoriachilena.gob.cl/602/w3-article-3296.html"]),
    "osm-node-2466067279": ("Córdoba", ["瓜达尔基维尔河畔的城市"], [],
        "The Argentine city copied Córdoba, Spain; the deeper Corduba analysis is hypothetical.",
        ["https://turismo.cordoba.gob.ar/turismo-cordoba-capital/breve-historia-de-cordoba-capital/"]),
    "osm-node-296140043": ("Montevideo", ["我看见一座山", "自东向西第六座山"], [],
        "The 1520 hill name is recorded, but the derivation of its Vidi element is unresolved.",
        ["https://municipiog.montevideo.gub.uy/sites/municipiog/files/guia_turistica_oficial_descubri_montevideo-_espanol_0.pdf"]),
    "osm-node-281537750": ("Paramaribo", ["登陆处", "彩虹溪旁的地方"], [],
        "The Lokono and creek-name analyses compete without a settled Indigenous segmentation.",
        ["https://purp.sr/area-7/", "https://unstats.un.org/unsd/geoinfo/ungegn/docs/29th-gegn-docs/WP/WP15_18_UNGEGN%20Conference%20of%20Bangkok%202016.pdf"]),
    "osm-node-274021463": ("Cali", ["不用针织成的织物", "房屋"], [],
        "The municipality calls the city's etymology unresolved; both proposed language links remain hypotheses.",
        ["https://www.cali.gov.co/cultura/publicaciones/225/resea-histrica-de-santiago-de-cali/"]),
    "osm-node-344799743": ("Medellín", ["雇佣兵之地"], [],
        "The Colombian city was named for a Spanish count's title; the proposed Metellus/mercenary root is doubtful.",
        ["https://www.medellin.gov.co/es/historia-y-simbolos-de-medellin/"]),
    "osm-node-671806634": ("Bogotá", ["耕地之外的围地", "草地的庭院", "草地的耕田"], [],
        "Early Bogotá/Bacatá forms and the competing Muisca segmentations remain disputed.",
        ["https://bogota.gov.co/mi-ciudad/cultura-recreacion-y-deporte/historia-del-nombre-de-bogota-por-que-la-ciudad-se-llama-asi", "https://biblioteca.icanh.gov.co/DOCS/MARC/texto/REV-0915V17a-5.PDF"]),
    "osm-node-195594311": ("Manaus", ["众神之母"], [],
        "The city was named for the Manáos people; 'mother of gods' is a traditional gloss, while the ethnonym's linguistic origin is unknown.",
        ["https://www.manaus.am.gov.br/turismo/historia/", "https://www.gov.br/iphan/pt-br/patrimonio-cultural/patrimonio-material/bens-tombados/conjuntos-urbanos-tombados-cidades-historicas/norte/manaus-am"]),
    "osm-node-293789508": ("Georgetown", ["农夫的城镇"], [meaning(
        "乔治之城", "George's town", "ジョージの町", "Ville de George", "Ciudad de Jorge")],
        "Guyana's National Trust documents naming for King George III, not a farmer.",
        ["https://ntg.gov.gy/historic-georgetown/"]),
    "osm-node-30674098": ("São Paulo", ["圣保罗（小者）"], [meaning(
        "圣保罗", "Saint Paul", "聖パウロ", "Saint Paul", "San Pablo")],
        "The city's patron is Saint Paul; 'small one' is a distant root of his personal name.",
        ["https://prefeitura.sp.gov.br/web/seguranca_urbana/w/noticias/324253"]),
    "osm-node-50016356": ("Santiago", ["圣者——愿上帝护佑他", "抓住脚跟的圣者"], [meaning(
        "圣雅各伯", "Saint James", "聖ヤコブ", "Saint Jacques", "San Jacobo")],
        "Chile's National Archive identifies the apostle as namesake; the drafts expand debated Hebrew roots of his personal name.",
        ["https://www.archivonacional.gob.cl/474-anos-de-historia-de-la-ciudad-de-santiago"]),
    "osm-node-34567423": ("Brasília", ["炭火般红的染料木之地"], [meaning(
        "以巴西命名之城", "City named for Brazil", "ブラジルにちなむ都市", "Ville nommée d'après le Brésil", "Ciudad llamada así por Brasil")],
        "Brasília was coined from Brasil for the new capital; the deeper dye-wood root is disputed and the wood was not at the city's site.",
        ["https://atlas.ipe.df.gov.br/en/?p=1124"]),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_env()
    changes = []
    already = []
    decisions = {}
    with connect(settings) as client:
        for feature_id, (label, expected_zh, replacement, reason, sources) in DECISIONS.items():
            hit = client.get(index=settings.index, id=feature_id)
            doc = hit["_source"]
            if (doc.get("feature_id") != feature_id or doc.get("kind") != "city"
                    or label not in doc.get("names", {}).values()):
                raise ValueError(f"Unexpected feature identity: {feature_id}")
            current = doc.get("literal_meanings") or []
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
                "reason": reason, "sources": sources,
                "before_zh": expected_zh,
                "after_zh": [m["translations"]["zh"] for m in replacement],
            }
        report = {"index": settings.index, "apply": args.apply,
                  "changes": len(changes), "already_corrected": already,
                  "decisions": decisions}
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
