import type {AtlasRecord,Scope} from './feature-model';
import type {ActiveLocale} from './i18n';

export type SearchResponse={query:string;scope:Scope;engine:string;total:number;notice?:string;results:(AtlasRecord & {match_kind:string;reason:string;score:number})[]};
// Relative proxy in development; use a reachable API URL when hosting.
const base=(import.meta.env?.VITE_ATLAS_API_BASE_URL || '/atlas-api').replace(/\/$/,'');
async function request<T>(path:string,options:RequestInit={},timeoutMs=15000):Promise<T>{
 const signal=AbortSignal.any([...(options.signal?[options.signal]:[]),AbortSignal.timeout(timeoutMs)]);
 const response=await fetch(`${base}${path}`,{...options,signal,cache:'no-store'});
 if(!response.ok)throw new Error('数据服务暂时无法连接，请稍后重试。');
 return response.json();
}
export async function loadAtlas(signal?:AbortSignal):Promise<AtlasRecord[]>{
 const records:AtlasRecord[]=[];
 let after:string|null=null;
 let total=0;
 do{
  const params=new URLSearchParams({limit:'1000'});
  if(after)params.set('after',after);
  const page=await request<{total:number;results:AtlasRecord[];next_after:string|null}>(`/map-features?${params}`,{signal});
  total=page.total;
  if(page.next_after && (!page.results.length||page.next_after===after))throw new Error('地点数据正在更新，请重新加载。');
  records.push(...page.results);
  after=page.next_after;
 }while(after);
 if(records.length!==total)throw new Error('地点数据正在更新，请重新加载。');
 return records;
}
export function searchAtlas(query:string,scope:Scope,signal?:AbortSignal){
 return request<SearchResponse>('/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query,scope,limit:100}),signal});
}
export async function loadRecord(id:string,signal?:AbortSignal){
 return await request<AtlasRecord>(`/features/${encodeURIComponent(id)}`,{signal});
}
export type ResolveResult={osm:string;status:'matched'|'not_found'|'ambiguous';feature:AtlasRecord|null};
export function resolveMapPlace(osm:string,signal?:AbortSignal){
 return request<ResolveResult>(`/features/resolve?${new URLSearchParams({osm})}`,{signal});
}
export type SimilarResponse={feature_id:string;lang:ActiveLocale;threshold:number|null;total:number;results:{feature:AtlasRecord;score:number;source_meaning_index:number;matched_meaning_index:number}[]};
export function similarPlaces(featureId:string,lang:ActiveLocale,signal?:AbortSignal){
 return request<SimilarResponse>(`/features/${encodeURIComponent(featureId)}/similar?${new URLSearchParams({lang})}`,{signal},120000);
}
export type VectorSimilarResponse={feature_id:string;lang:ActiveLocale;engine:'vector';min_similarity:number;available:boolean;total:number;results:SimilarResponse['results']};
export function vectorSimilarPlaces(featureId:string,lang:ActiveLocale,minSimilarity:number,signal?:AbortSignal){
 const params=new URLSearchParams({lang,min_similarity:minSimilarity.toFixed(2)});
 return request<VectorSimilarResponse>(`/features/${encodeURIComponent(featureId)}/vector-similar?${params}`,{signal},120000);
}

export type MeaningFeedbackInput={feature_id:string;meaning_index:number|null;language:ActiveLocale;description:string;suggested_meaning:string|null;source_url:string|null};
export type MeaningFeedbackResponse={id:string;status:'pending'};
export function submitMeaningFeedback(feedback:MeaningFeedbackInput){
 return request<MeaningFeedbackResponse>('/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(feedback)});
}
