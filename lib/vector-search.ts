import index from '../data/embeddings.json';
import {data,records,type Scope} from './atlas';
import {conceptSearch,cosine,fuseRanks,type SearchHit,type SearchResponse} from './search';

export async function search(query:string,scope:Scope,limit:number,signal?:AbortSignal):Promise<SearchResponse>{
 const lexical=conceptSearch(query,scope,limit);
 const endpoint=process.env.EMBEDDING_URL,token=process.env.EMBEDDING_API_KEY,model=process.env.EMBEDDING_MODEL;
 const vectors=index.vectors as {analysis_id:string;values:number[]}[];
 // Seed mode works without accounts or model downloads. Never invent vectors.
 if(!endpoint||!model||!vectors.length||scope==='exact')return lexical;
 if(index.model!==model||index.data_version!==data.generated_on)return {...lexical,notice:'语义索引正在更新，当前使用名称与概念匹配。'};
 try{
  const url=new URL(endpoint);if(url.protocol!=='https:')throw Error('HTTPS required');
  const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json',...(token?{Authorization:`Bearer ${token}`}:{})},body:JSON.stringify({model,input:[query],encoding_format:'float'}),signal:signal?AbortSignal.any([signal,AbortSignal.timeout(8000)]):AbortSignal.timeout(8000)});
  if(!response.ok)throw Error('Embedding provider unavailable');
  const body=await response.json() as {data?:{embedding:number[]}[]};const vector=body.data?.[0]?.embedding;
  if(!vector||vector.length!==index.dimensions)throw Error('Embedding model mismatch');
  const configured=Number(process.env.SEMANTIC_MIN_SCORE??'.65');const min=Number.isFinite(configured)?Math.max(-1,Math.min(1,configured)):.65;
  const semantic:SearchHit[]=vectors.map(v=>({...v,similarity:cosine(vector,v.values)})).filter(v=>v.similarity>=min&&records.some(r=>r.id===v.analysis_id)).sort((a,b)=>b.similarity-a.similarity).slice(0,limit).map(v=>{const record=records.find(r=>r.id===v.analysis_id)!;return {analysis_id:v.analysis_id,place_id:record.place.id,reason:'语义相近的候选；请对照卡片中的原始释义与来源。',matched_concepts:[],kind:'related'};});
  return {...lexical,engine:'hybrid-vector',results:fuseRanks(lexical.results,semantic,limit)};
 }catch{return {...lexical,notice:'语义检索暂时不可用，已显示名称与概念匹配。'};}
}
