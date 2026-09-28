"""Apply conservative, source-checked editorial decisions to the India batch."""

import argparse
from datetime import datetime, timezone
import json

from backend.config import ROOT, Settings, connect
from backend.indexing import Feature


OUTPUT_ROOT = ROOT / "work/literal-translations/india-places-80-20260927"


def meaning(zh, en, ja, fr, es):
    return {"translations": {"zh": zh, "en": en, "ja": ja, "fr": fr, "es": es}}


# An empty replacement means the historical derivation cannot responsibly be
# presented as a literal translation. The model report remains untouched.
DECISIONS = {
    "osm-node-14069907105": ("Delhi", ["门槛"], [], "Threshold is a conditional, disputed derivation of Dhillika.", ["https://delhi.gov.in/hi"]),
    "osm-node-316416994": ("Delhi", ["门槛"], [], "The regional name has the same unresolved origin as the city.", ["https://delhi.gov.in/hi"]),
    "osm-node-10029899747": ("Surat", ["太阳之城"], [], "The older Suryapur name is attested, but the link to the modern form Surat is unproved.", ["https://nri.gujarat.gov.in/Home/surathistory"]),
    "osm-node-245707150": ("Kolkata", ["迦梨女神的土地", "开凿的运河", "被水道切开的河岸"], [], "The three proposed derivations of older Kalikata compete; none is established.", ["https://www.kmcgov.in/KMCPortal/jsp/KMCAboutKolkataHome.jsp", "https://www.nabard.org/auth/writereaddata/tender/2401221556Kolkata.pdf"]),
    "osm-node-287687798": ("Varanasi", ["瓦鲁纳河与阿西河之间", "瓦拉纳树之地"], [], "The two-river reading may be a reinterpretation, and the tree reading is tentative.", ["https://ignca.gov.in/coilnet/kv_0002.htm"]),
    "osm-node-2510123017": ("Ranchi", ["赶牛用的短棍", "竹林", "当地的一种鸟"], [], "The proposed local-language roots conflict and no historical naming link is settled.", ["https://ranchi.nic.in/history/"]),
    "osm-node-2516759396": ("Dhanbad", ["出产拜德稻的地方", "不宜种稻的土地"], [], "The district gazetteer says no authentic record establishes the name's origin.", ["https://dhanbad.nic.in/about-district/history/"]),
    "osm-node-245730439": ("Kota", ["堡垒"], [], "The fort reading conflicts with the Rajasthan heritage authority's Kotya eponym account.", ["https://www.tourism.rajasthan.gov.in/kota.html"]),
    "osm-node-2845526137": ("Telangana", ["三座湿婆林伽之地", "三个迦陵伽地区之地"], [], "Both Trilinga and Tri-Kalinga derivations remain disputed.", ["https://content.ucpress.edu/title/9780520344525/9780520344525_intro.pdf"]),
    "osm-node-567267943": ("Agra", ["盐田", "森林边缘"], [], "Neither proposed root is established for the attested name Agra.", ["https://agra.nic.in/history/"]),
    "osm-node-559844882": ("Jalandhar", ["持水者", "两河之间的土地"], [], "The personal-name and geographic analyses are competing traditional accounts.", ["https://jalandhar.nic.in/history/"]),
    "osm-node-316417278": ("Andaman and Nicobar Islands", ["大颌者与裸体人之地的群岛"], [], "Both component-name derivations are conjectural and do not justify this confident combined gloss.", ["https://www.andaman.gov.in/about"]),
    "osm-node-2240851596": ("Tripura", ["临水之地", "三座城"], [], "Tuipra's component analysis is disputed and the Sanskrit reading may be a later reinterpretation.", ["https://cdnbbsr.s3waas.gov.in/s32d2ca7eedf739ef4c3800713ec482e1a/uploads/2023/09/2023092156.pdf"]),
    "osm-node-1600720976": ("Vasai-Virar", ["聚居地—无双女英雄"], [], "The proposed Ekavira chain lacks a secure historical naming link.", ["https://vvcmc.in/"]),
    "osm-node-2237699941": ("Goa", ["牛群繁盛之地"], [], "The connection between the modern name and Gomanta is only proposed.", ["https://www.goa.gov.in/about-goa/history/"]),
    "osm-node-571773704": ("Meerut", ["造物者摩耶之地"], [], "The Maya account is traditional, while historical sources do not settle the derivation.", ["https://meerut.nic.in/history/"]),
    "osm-node-339279350": ("Howrah", ["雨季积水的沼泽洼地"], [], "The proposed marshland root does not resolve the older Harirah name.", ["https://howrah.gov.in/history/"]),
    "osm-node-520986776": ("Rewari", ["富裕女子的村落"], [], "The translation drills into an unverified personal-name legend.", ["https://rewari.gov.in/history/"]),
    "osm-node-16173235": ("Mumbai", ["蒙巴母神", "伟大的安巴母神"], [0], "The district attests the Mumbadevi naming link; the deeper Maha-Amba derivation is disputed.", ["https://mumbaicity.gov.in/en/history/"]),
    "osm-node-2237699954": ("Kerala", ["哲罗人的土地", "海水退去后增添的土地", "椰子树之地"], [0], "The Chera/Cheram connection has historical support; the sea and coconut readings are disputed.", ["https://www.kerala.gov.in/"]),
    "osm-node-316417213": ("Haryana", ["葱郁森林之地", "毗湿奴的居所"], [0], "Retain the supported green-land reading; the Vishnu derivation is conjectural.", ["https://haryana.gov.in/about-haryana/"]),
    "osm-node-245709027": ("Indore", ["因陀罗之城", "因陀罗之主"], [0], "The second gloss translates the shrine deity's name rather than the place-name chain.", ["https://indore.nic.in/en/about-district/"]),
    "osm-node-619091882": ("Navi Mumbai", ["蒙巴母神的新城"], [meaning("新孟买", "New Mumbai", "新しいムンバイ", "Nouveau Mumbai", "Nueva Bombay")], "Navi modifies the current city name Mumbai; translating a deeper disputed root obscures this straightforward name.", ["https://www.cidco.maharashtra.gov.in/navi_mumbai"]),
    "osm-node-245711197": ("Ahmedabad", ["最值得赞颂者之城"], [meaning("艾哈迈德之城", "Ahmed's city", "アフマドの町", "Ville d'Ahmed", "Ciudad de Ahmed")], "The city is named for Sultan Ahmed Shah; retain his personal name.", ["https://ahmedabad.nic.in/history/"]),
    "osm-node-3233393892": ("Chennai", ["俊美之人的城镇"], [meaning("钦纳帕的城镇", "Chennappa's town", "チェンナッパの町", "Ville de Chennappa", "Ciudad de Chennappa")], "The district attributes the name to Chennappa Nayak, not the lexical sense of his personal name.", ["https://chennai.nic.in/history/"]),
    "osm-node-315734346": ("Jaipur", ["胜利之城"], [meaning("斋·辛格之城", "Jai Singh's city", "ジャイ・シングの町", "Ville de Jai Singh", "Ciudad de Jai Singh")], "The municipal history says the city is named for founder Jai Singh II.", ["https://www.jaipurmc.org/presentation/AboutJaipur/HistoryOfJaipur.aspx"]),
    "osm-node-245746448": ("Jodhpur", ["勇士之城"], [meaning("焦达之城", "Jodha's city", "ジョーダーの町", "Ville de Jodha", "Ciudad de Jodha")], "The city is named for its founder Rao Jodha, not a dictionary sense of his name.", ["https://jodhpur.nic.in/history/"]),
    "osm-node-2521085873": ("Ghaziabad", ["信仰战士的聚落"], [meaning("加齐乌丁的聚落", "Ghazi-ud-din's settlement", "ガーズィー・ウッディーンの町", "Ville de Ghazi-ud-din", "Asentamiento de Ghazi-ud-din")], "The district traces Ghaziuddinnagar to founder Ghazi-ud-din.", ["https://ghaziabad.nic.in/en/about-district/"]),
    "osm-node-1180652177": ("Kanpur", ["黝黑者克里希纳之城"], [meaning("坎海亚之城", "Kanhaiya's town", "カンハイヤーの町", "Ville de Kanhaiya", "Ciudad de Kanhaiya")], "The older Kanhpur name supports the eponym; the deeper Krishna gloss is unnecessary.", ["https://kanpurnagar.nic.in/hi/%E0%A4%87%E0%A4%A4%E0%A4%BF%E0%A4%B9%E0%A4%BE%E0%A4%B8/"]),
    "osm-node-245641840": ("Visakhapatnam", ["维沙卡（分叉者）之城"], [meaning("维沙克什瓦拉之城", "Town of Visakeswara", "ヴィサケーシュヴァラの町", "Ville de Visakeswara", "Ciudad de Visakeswara")], "The district records a traditional shrine-naming chain, but not the 'forked one' gloss.", ["https://visakhapatnam.ap.gov.in/history/"]),
    "osm-node-245753718": ("Lucknow", ["身带吉祥印记者之城"], [meaning("拉克什马纳之城", "Lakshmana's city", "ラクシュマナの町", "Ville de Lakshmana", "Ciudad de Lakshmana")], "The district records the traditional Lakshmana eponym; avoid expanding the personal name.", ["https://lucknow.nic.in/history/"]),
    "osm-node-245640543": ("Hyderabad", ["狮子之城"], [meaning("海达尔之城", "Haydar's city", "ハイダルの町", "Ville de Haydar", "Ciudad de Haydar")], "The Haydar personal name should remain intact rather than be presented as a lion reference to Ali.", ["https://hyderabad.telangana.gov.in/"]),
    "osm-node-6960120087": ("Jammu and Kashmir", ["蒲桃树之城与克什米尔"], [meaning("占布之城与克什米尔", "Jambu's city and Kashmir", "ジャンブの町とカシミール", "Ville de Jambu et Cachemire", "Ciudad de Jambu y Cachemira")], "Jammu is traditionally named for Jambu Lochan; Kashmir remains an opaque proper name.", ["https://jammu.nic.in/about-district/"]),
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
            if doc["feature_id"] != feature_id or label not in doc.get("names", {}).values():
                raise ValueError(f"Unexpected feature identity: {feature_id}")
            current = doc.get("literal_meanings") or []
            current_zh = [m["translations"].get("zh") for m in current]
            if replacement and isinstance(replacement[0], int):
                retained_zh = [expected_zh[i] for i in replacement]
                if current_zh == retained_zh:
                    new_meanings = current
                elif current_zh == expected_zh:
                    new_meanings = [current[i] for i in replacement]
                else:
                    raise ValueError(f"Meanings changed for {feature_id}: {current_zh}")
            else:
                new_meanings = replacement
            if current == new_meanings:
                already.append(feature_id)
            elif current_zh != expected_zh:
                raise ValueError(f"Meanings changed for {feature_id}: {current_zh}")
            patch = {"literal_meanings": new_meanings, "meaning_id": None}
            Feature.model_validate({**doc, **patch})
            if current != new_meanings:
                changes.append((hit, patch))
            decisions[feature_id] = {
                "label": label, "status": "uncertain" if not new_meanings else "corrected",
                "reason": reason, "sources": sources,
                "before_zh": current_zh,
                "after_zh": [m["translations"]["zh"] for m in new_meanings],
            }
        report = {"index": settings.index, "apply": args.apply,
                  "changes": len(changes), "already_corrected": already,
                  "decisions": decisions}
        if args.apply:
            run_dir = OUTPUT_ROOT / "editorial-review" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            run_dir.mkdir(parents=True, exist_ok=False)
            (run_dir / "before.json").write_text(json.dumps(
                [{"hit": dict(hit), "patch": patch} for hit, patch in changes],
                ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            for hit, patch in changes:
                client.update(index=settings.index, id=hit["_id"], doc=patch,
                              if_seq_no=hit["_seq_no"], if_primary_term=hit["_primary_term"],
                              refresh="wait_for")
            (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (OUTPUT_ROOT / "editorial-decisions.json").write_text(json.dumps(
                {"reviewed_at": datetime.now(timezone.utc).isoformat(), "decisions": decisions},
                ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            report["backup_dir"] = str(run_dir.resolve())
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
