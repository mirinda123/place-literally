import seed from '../data/seed.json';
export const data=seed;
export type Scope='exact'|'near'|'theme';
export const countryNames:Record<string,string>={IT:'意大利',TN:'突尼斯',RU:'俄罗斯',RS:'塞尔维亚',KR:'韩国',JP:'日本',CN:'中国',US:'美国'};
export const records=seed.analyses.map(analysis=>{const name=seed.names.find(n=>n.id===analysis.name_id)!;const place=seed.places.find(p=>p.id===name.place_id)!;return {id:analysis.id,analysis,name,place,meaning:seed.meanings.find(m=>m.id===analysis.meaning_id),memberships:seed.cluster_memberships.filter(m=>m.analysis_id===analysis.id)};});
export type AtlasRecord=typeof records[number];
export const collections=[{id:'new-settlement',label:'New City',zh:'新城',symbol:'✦',color:'#315bc9'},{id:'white-settlement',label:'White City',zh:'白城',symbol:'◒',color:'#718292'},{id:'capital-family',label:'Capital',zh:'都城',symbol:'♜',color:'#8869a6'},{id:'centrality',label:'Center',zh:'中心与都城',symbol:'◎',color:'#be7945'},{id:'newness',label:'New beginnings',zh:'名字里的新',symbol:'↗',color:'#497e72'}];
export function inCollection(id:string){return records.filter(r=>r.memberships.some(m=>m.cluster_id===id));}
export function collectionRecords(id:string,scope:Scope):AtlasRecord[]{
 if(id==='all')return records;
 if(id==='centrality'||id==='newness')return inCollection(id);
 const anchor=records.find(r=>r.analysis.meaning_id===({'new-settlement':'new-city','white-settlement':'white-city','capital-family':'capital'} as Record<string,string>)[id]);
 return anchor?relatedTo(anchor,scope):inCollection(id);
}
export function primaryCollection(record:AtlasRecord){return record.memberships.find(m=>['new-settlement','white-settlement','capital-family'].includes(m.cluster_id))?.cluster_id||(record.place.id==='china-cn'?'centrality':'newness');}
export function relatedTo(record:AtlasRecord,scope:Scope):AtlasRecord[]{if(scope==='exact')return records.filter(r=>r.id===record.id||(record.analysis.meaning_id!==null&&r.analysis.meaning_id===record.analysis.meaning_id));const relevant=scope==='near'?record.memberships.filter(m=>['new-settlement','white-settlement','capital-family'].includes(m.cluster_id)):record.memberships;return records.filter(r=>r.id===record.id||r.memberships.some(m=>relevant.some(x=>x.cluster_id===m.cluster_id)));}
export function relationLabel(origin:AtlasRecord,target:AtlasRecord){if(origin.id===target.id)return '当前地点';if(origin.analysis.meaning_id!==null&&origin.analysis.meaning_id===target.analysis.meaning_id)return '同义归一';if(origin.memberships.some(m=>m.cluster_id==='capital-family')&&target.memberships.some(m=>m.cluster_id==='capital-family'))return '相近含义 · 方位不同';return '共同主题';}
