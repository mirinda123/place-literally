import Fuse from 'fuse.js';
import {data,records,type AtlasRecord,type Scope} from './atlas';

export type SearchHit={analysis_id:string;place_id:string;reason:string;matched_concepts:string[];kind:'name'|'meaning'|'related'};
export type SearchResponse={query:string;scope:Scope;data_version:string;engine:'concept'|'hybrid-vector';results:SearchHit[];notice?:string};
export function normalize(text:string){return text.normalize('NFKD').replace(/\p{M}/gu,'').toLowerCase().replace(/[^\p{L}\p{N}\s]/gu,' ').replace(/\s+/g,' ').trim();}
const vocabulary:Record<string,string[]>={
 new:['新','新建','新的','新兴','new','newly','fresh'],settlement:['城','城市','城镇','定居点','city','cities','town','towns','settlement','settlements'],
 capital:['首都','都城','京城','capital','capitals','seat of government'],central:['中央','中心','center','centre','central','middle'],
 north:['北','北方','north','northern'],south:['南','南方','south','southern'],east:['东','東','东方','east','eastern'],west:['西','西方','west','western'],
 white:['白','白色','white'],black:['黑','黑色','black'],country:['国家','国度','country','state','kingdom'],
 water:['水','河','海','water','river','rivers','sea','ocean'],mountain:['山','mountain','mountains','hill'],old:['旧','老城','old','ancient']};
const conceptLabels:Record<string,string>={new:'新',settlement:'城镇',capital:'都城',central:'中心',north:'北方',south:'南方',east:'东方',west:'西方',white:'白色',black:'黑色',country:'国',water:'水',mountain:'山',old:'旧'};
function includesTerm(query:string,term:string){return /[\u3400-\u9fff]/.test(term)?query.includes(term):(` ${query} `).includes(` ${term} `);}
export function queryConcepts(query:string){const q=normalize(query);return Object.entries(vocabulary).filter(([,terms])=>terms.some(t=>includesTerm(q,t))).map(([id])=>id);}
function recordConcepts(record:AtlasRecord){const concepts=[...(data.semantic_profiles.find(p=>p.analysis_id===record.id)?.concept_ids||[])];if(concepts.includes('capital'))concepts.push('settlement');return new Set(concepts);}
const nameIndex=records.map(r=>({id:r.id,names:[r.place.display_name.en,r.place.display_name.zh,...data.names.filter(n=>n.place_id===r.place.id).flatMap(n=>[n.form,n.romanization||''])].map(normalize)}));
const fuse=new Fuse(nameIndex,{keys:['names'],includeScore:true,threshold:.3,ignoreLocation:true,minMatchCharLength:2});
function hit(record:AtlasRecord,kind:SearchHit['kind'],concepts:string[],reason:string):SearchHit{return {analysis_id:record.id,place_id:record.place.id,kind,matched_concepts:concepts,reason};}
export function conceptSearch(query:string,scope:Scope='near',limit=12):SearchResponse{
 const q=normalize(query),concepts=queryConcepts(q),results:SearchHit[]=[];
 if(!q)return {query,scope,data_version:data.generated_on,engine:'concept',results:[]};
 // An explicitly negated concept is not silently treated as a positive query.
 if(/(?:不要|不含|没有|不是|without|not\s)/iu.test(query))return {query,scope,data_version:data.generated_on,engine:'concept',results:[],notice:'当前检索暂不解析否定条件，请使用正向含义描述。'};
 const exactNames=nameIndex.filter(r=>r.names.includes(q));
 for(const match of exactNames)results.push(hit(records.find(r=>r.id===match.id)!,'name',[],'名称匹配；卡片会注明正在分析的具体名称。'));
 if(concepts.length){
  for(const record of records){
   if(results.some(r=>r.analysis_id===record.id))continue;
   const rc=recordConcepts(record),matched=concepts.filter(c=>rc.has(c));
   const allMatch=matched.length===concepts.length;
   const centralTheme=scope==='theme'&&concepts.length===1&&concepts[0]==='central'&&record.memberships.some(m=>m.cluster_id==='centrality');
   if(!allMatch&&!centralTheme)continue;
   // A capital keyword in exact scope means the unqualified literal meaning.
   if(scope==='exact'&&concepts.length===1&&concepts[0]==='capital'&&record.analysis.meaning_id!=='capital')continue;
   const broad=centralTheme&&!allMatch;
   results.push(hit(record,broad?'related':'meaning',matched,broad?'共同主题：中心与都城；完整词义并不相同。':`名称含义包含${matched.map(c=>`「${conceptLabels[c]||c}」`).join('、')}。`));
  }
 }else if(!exactNames.length){
  for(const match of fuse.search(q,{limit})){if((match.score??1)>.3)continue;results.push(hit(records.find(r=>r.id===match.item.id)!,'name',[],'名称或转写的近似拼写匹配。'));}
 }
 return {query,scope,data_version:data.generated_on,engine:'concept',results:results.slice(0,limit)};
}
export function cosine(a:number[],b:number[]){if(!a.length||a.length!==b.length||[...a,...b].some(v=>!Number.isFinite(v)))throw Error('Invalid embedding dimensions or values');let dot=0,aa=0,bb=0;for(let i=0;i<a.length;i++){dot+=a[i]*b[i];aa+=a[i]*a[i];bb+=b[i]*b[i];}if(!aa||!bb)throw Error('Zero embedding');return dot/Math.sqrt(aa*bb);}
// Reciprocal rank fusion combines rankings rather than incompatible raw scores.
export function fuseRanks(lexical:SearchHit[],semantic:SearchHit[],limit:number){const map=new Map<string,{hit:SearchHit;score:number}>();for(const list of [lexical,semantic])list.forEach((h,i)=>{const prev=map.get(h.analysis_id);map.set(h.analysis_id,{hit:prev?.hit||h,score:(prev?.score||0)+1/(60+i+1)});});const exact=lexical.filter(h=>h.kind==='name');const ordered=[...map.values()].sort((a,b)=>b.score-a.score).map(v=>v.hit);return [...exact,...ordered.filter(h=>!exact.some(e=>e.analysis_id===h.analysis_id))].slice(0,limit);}
