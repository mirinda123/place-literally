import groups from '../data/meaning-groups.json';
export type Scope='exact'|'near'|'theme';
export type AtlasRecord={
 feature_id:string;kind:string;names:Partial<Record<string,string>>;
 location:{lon:number;lat:number};
 literal_name:{text:string;lang:string}|null;
 literal_meanings:{translations:Record<string,string>}[];meaning_id:string|null;
 external_ids?:{osm:string[]};
};
type Group={concept_ids:string[];cluster_ids:string[]};
export function coordinates(r:AtlasRecord):[number,number]{return [r.location.lon,r.location.lat];}
export function displayName(r:AtlasRecord,lang='en'){return r.names[lang]||r.names.en||r.names.zh||Object.values(r.names)[0]||r.feature_id;}
export function hasLiteralMeaning(r:AtlasRecord){return r.literal_meanings.some(meaning=>Object.values(meaning.translations||{}).some(text=>typeof text==='string'&&!!text.trim()));}
export const kindLabels:Record<string,string>={country:'国家',state:'省级行政区',province:'省级行政区',city:'城市',metropolis:'城市',ancient_city:'古城',town:'城镇',village:'村庄',river:'河流',lake:'湖泊',sea:'海域',ocean:'海洋',mountain:'山',island:'岛屿'};
export const collections=[{id:'new-settlement',label:'New City',zh:'新城',symbol:'✦',color:'#315bc9'},{id:'white-settlement',label:'White City',zh:'白城',symbol:'◒',color:'#718292'},{id:'capital-family',label:'Capital',zh:'都城',symbol:'♜',color:'#8869a6'},{id:'centrality',label:'Center',zh:'中心与都城',symbol:'◎',color:'#be7945'},{id:'newness',label:'New beginnings',zh:'名字里的新',symbol:'↗',color:'#497e72'}];
function memberships(r:AtlasRecord){return ((r.meaning_id?(groups.meanings as Record<string,Group>)[r.meaning_id]:undefined)||(groups.overrides as Record<string,Group>)[r.feature_id])?.cluster_ids||[];}
export function createAtlas(records:AtlasRecord[]){
 function inCollection(id:string){return records.filter(r=>memberships(r).includes(id));}
 function relatedTo(origin:AtlasRecord,scope:Scope){
  if(scope==='exact')return records.filter(r=>r.feature_id===origin.feature_id||(!!origin.meaning_id&&r.meaning_id===origin.meaning_id));
  const ids=memberships(origin).filter(id=>scope==='theme'||['new-settlement','white-settlement','capital-family'].includes(id));
  return records.filter(r=>r.feature_id===origin.feature_id||memberships(r).some(id=>ids.includes(id)));
 }
 function collectionRecords(id:string,scope:Scope):AtlasRecord[]{
  if(id==='all')return records;
  if(id==='centrality'||id==='newness')return inCollection(id);
  const meaning=({'new-settlement':'new-city','white-settlement':'white-city','capital-family':'capital'} as Record<string,string>)[id];
  const anchor=records.find(r=>r.meaning_id===meaning);
  return anchor?relatedTo(anchor,scope):inCollection(id);
 }
 return {inCollection,relatedTo,collectionRecords};
}
export function primaryCollection(r:AtlasRecord){return memberships(r).find(id=>collections.some(c=>c.id===id))||'all';}
export function relationLabel(a:AtlasRecord,b:AtlasRecord){
 if(a.feature_id===b.feature_id)return '当前地点';
 if(a.meaning_id&&a.meaning_id===b.meaning_id)return '同义归一';
 if(memberships(a).includes('capital-family')&&memberships(b).includes('capital-family'))return '相近含义 · 方位不同';
 return '共同主题';
}
