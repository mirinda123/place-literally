import {test} from 'node:test';
import assert from 'node:assert/strict';
import {loadAtlas,searchAtlas,resolveMapPlace,similarPlaces,vectorSimilarPlaces} from '../lib/atlas-api';
import {createAtlas,hasLiteralMeaning,type AtlasRecord,coordinates} from '../lib/feature-model';
import features from '../data/features.json';

test('map uses feature documents and never reconstructs missing seed places',()=>{
 const feature=structuredClone(features.find(r=>r.feature_id==='naples-it')!);
 feature.location={lon:10,lat:20};feature.literal_meanings[0].translations.zh='更新后的翻译';
 assert.deepEqual(coordinates(feature),[10,20]);
 assert.equal(createAtlas([feature]).collectionRecords('new-settlement','exact').length,1);
 assert.equal(createAtlas([]).collectionRecords('all','exact').length,0);
 const blank:AtlasRecord={feature_id:'river',kind:'river',names:{fr:'Rivière'},location:{lon:0,lat:0},literal_name:null,literal_meanings:[],meaning_id:null};
 assert.equal(createAtlas([blank,features.find(r=>r.feature_id==='new-york-us')!]).relatedTo(blank,'exact').length,1);
});

test('map resolution sends the complete OSM identity and distinguishes absence from outages',async t=>{
 let called='';
 t.mock.method(globalThis,'fetch',async(input:RequestInfo|URL)=>{
  called=String(input);return Response.json({osm:'node/244081381',status:'not_found',feature:null});
 });
 assert.equal((await resolveMapPlace('node/244081381')).status,'not_found');
 assert.equal(called,'/atlas-api/features/resolve?osm=node%2F244081381');
 t.mock.method(globalThis,'fetch',async()=>new Response('Unavailable',{status:503}));
 await assert.rejects(resolveMapPlace('node/244081381'),/数据服务/);
});
test('groups retain the New York and directional boundaries',()=>{
 const atlas=createAtlas(features);
 assert.equal(atlas.collectionRecords('new-settlement','exact').length,2);
 const seoul=features.find(r=>r.feature_id==='seoul-kr')!;
 assert.equal(atlas.relatedTo(seoul,'exact').length,2);
 assert.equal(atlas.relatedTo(seoul,'near').length,5);
 assert.equal(atlas.collectionRecords('centrality','theme').length,6);
});
test('loader reads multiple API pages',async t=>{
 const paths:string[]=[];
 t.mock.method(globalThis,'fetch',async(input:RequestInfo|URL)=>{
  paths.push(String(input));
  return Response.json({total:101,results:paths.length===1?Array.from({length:100},(_,i)=>({...features[0],feature_id:'id-'+i})):[features[0]],next_after:paths.length===1?'id-99':null});
 });
 assert.equal((await loadAtlas()).length,101);
 assert.deepEqual(paths,['/atlas-api/map-features?limit=1000','/atlas-api/map-features?limit=1000&after=id-99']);
});
test('API errors reject rather than falling back to academic seed data',async t=>{
 t.mock.method(globalThis,'fetch',async()=>new Response('Unavailable',{status:503}));
 await assert.rejects(loadAtlas(),/数据服务/);
 await assert.rejects(searchAtlas('新城','near'),/数据服务/);
});

test('any place with a meaning can be selected; empty places do not need a similar request',()=>{
 const source=features.find(r=>r.feature_id==='china-cn')!;
 assert.equal(hasLiteralMeaning(source),true);
 assert.equal(hasLiteralMeaning({...source,kind:'river'}),true);
 assert.equal(hasLiteralMeaning({...source,literal_meanings:[]}),false);
 assert.equal(hasLiteralMeaning({...source,literal_meanings:[{translations:{fr:'  '}}]}),false);
});

test('similar places request uses selected locale, returns mixed kinds and aborts a superseded selection',async t=>{
 const calls:{url:string;signal:AbortSignal}[]=[];
 t.mock.method(globalThis,'fetch',async(input:RequestInfo|URL,options?:RequestInit)=>{
  calls.push({url:String(input),signal:options!.signal!});
  if(String(input).includes('nanjing-cn'))return new Promise<Response>((_,reject)=>{
   options!.signal!.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true});
  });
  return Response.json({feature_id:'china-cn',lang:'ja',threshold:2,total:2,results:[
   {feature:{...features[0],kind:'city'},score:5,source_meaning_index:0,matched_meaning_index:0},
   {feature:{...features[1],kind:'river'},score:4,source_meaning_index:0,matched_meaning_index:0}
  ]});
 });
 const previous=new AbortController();
 const oldRequest=similarPlaces('nanjing-cn','zh',previous.signal);
 previous.abort();
 await assert.rejects(oldRequest,{name:'AbortError'});
 const result=await similarPlaces('china-cn','ja');
 assert.equal(calls[0].url,'/atlas-api/features/nanjing-cn/similar?lang=zh');
 assert.equal(calls[1].url,'/atlas-api/features/china-cn/similar?lang=ja');
 assert.equal(calls[0].signal.aborted,true);
 assert.equal(result.lang,'ja');
 assert.deepEqual(result.results.map(item=>item.feature.kind),['city','river']);
});

test('vector request sends current language and threshold and preserves availability and scores',async t=>{
 let url='';
 t.mock.method(globalThis,'fetch',async(input:RequestInfo|URL)=>{
  url=String(input);
  return Response.json({feature_id:'china-cn',lang:'zh',engine:'vector',min_similarity:0.63,
   available:true,total:1,results:[{feature:{...features[0],kind:'country'},score:0.6312,
    source_meaning_index:0,matched_meaning_index:1}]});
 });
 const result=await vectorSimilarPlaces('china-cn','zh',0.63);
 assert.equal(url,'/atlas-api/features/china-cn/vector-similar?lang=zh&min_similarity=0.63');
 assert.equal(result.available,true);
 assert.equal(result.results[0].score,0.6312);
 assert.equal(result.results[0].matched_meaning_index,1);
});

test('changing the vector request aborts its predecessor instead of accepting stale results',async t=>{
 const calls:{url:string;signal:AbortSignal}[]=[];
 t.mock.method(globalThis,'fetch',async(input:RequestInfo|URL,options?:RequestInit)=>{
  const signal=options!.signal!;
  calls.push({url:String(input),signal});
  if(String(input).includes('min_similarity=0.60'))return new Promise<Response>((_,reject)=>{
   signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true});
  });
  return Response.json({feature_id:'china-cn',lang:'ja',engine:'vector',min_similarity:0.75,
   available:false,total:0,results:[]});
 });
 const prior=new AbortController();
 const stale=vectorSimilarPlaces('china-cn','zh',0.60,prior.signal);
 prior.abort();
 await assert.rejects(stale,{name:'AbortError'});
 const fresh=await vectorSimilarPlaces('china-cn','ja',0.75);
 assert.equal(calls[0].signal.aborted,true);
 assert.equal(calls[1].url,'/atlas-api/features/china-cn/vector-similar?lang=ja&min_similarity=0.75');
 assert.equal(fresh.available,false);
 assert.equal(fresh.total,0);
});
