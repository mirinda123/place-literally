'use client';
import {useEffect,useMemo,useRef,useState} from 'react';
import {ArrowUpRight,ChevronLeft,Link2,Maximize,PanelLeft,Search,X} from 'lucide-react';
import {flushSync} from 'react-dom';
import dynamic from 'next/dynamic';
import {loadAtlas,searchAtlas,loadRecord,resolveMapPlace,similarPlaces,vectorSimilarPlaces,type SearchResponse,type SimilarResponse,type VectorSimilarResponse} from '../lib/atlas-api';
import type {MapPlaceTarget} from '../lib/map-identity';
import {Button} from '../components/ui/button';
import {Input} from '../components/ui/input';
import {Slider} from '../components/ui/slider';
import {Sidebar,SidebarProvider,SidebarTrigger,useSidebar} from '../components/ui/sidebar';
import {hasLiteralMeaning,type AtlasRecord} from '../lib/feature-model';
import {LocaleProvider,useLocale} from '../components/locale-provider';
import {LanguageSwitcher} from '../components/language-switcher';
import {PlaceDetail} from '../components/place-detail';
import {kindName,languageName,localizedText,relatedListLabels,vectorLabels} from '../lib/i18n';
import {relatedMeanings} from '../lib/related-places';
const MapView=dynamic(()=>import('./map-view'),{ssr:false});
export default function Home(){return <LocaleProvider><SidebarProvider className="atlas-provider" defaultOpen={false}><Atlas /></SidebarProvider></LocaleProvider>;}
function SimilarityThreshold({label,value,onCommit}:{label:string;value:number;onCommit:(value:number)=>void}){
 const [draft,setDraft]=useState(value);
 useEffect(()=>setDraft(value),[value]);
 return <div className="vector-threshold"><span id="vector-threshold-label">{label}</span><output>{draft.toFixed(2)}</output>
  <Slider className="material-threshold-slider" min={50} max={90} step={1} value={[Math.round(draft*100)]} aria-labelledby="vector-threshold-label" aria-valuetext={draft.toFixed(2)} onValueChange={values=>setDraft(values[0]/100)} onValueCommit={values=>onCommit(values[0]/100)}/>
 </div>;
}
function Atlas(){
 const {locale,t}=useLocale();
 const vectorText=vectorLabels[locale];
 const relatedText=relatedListLabels[locale];
 const nameOf=(r:AtlasRecord)=>localizedText(r.names,locale)?.text||r.feature_id;
 const [records,setRecords]=useState<AtlasRecord[]>([]),[loading,setLoading]=useState(true),[loadError,setLoadError]=useState(''),[reload,setReload]=useState(0);
 useEffect(()=>{
  const controller=new AbortController();setLoading(true);setLoadError('');
  loadAtlas(controller.signal).then(items=>{if(!controller.signal.aborted)setRecords(items);})
   .catch(()=>{if(!controller.signal.aborted)setLoadError('地点数据暂时无法加载，请确认数据服务已启动后重试。');})
   .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
  return()=>controller.abort();
 },[reload]);
 const {open,isMobile,openMobile,setOpen,setOpenMobile}=useSidebar();
 const panelOpen=isMobile?openMobile:open;
 const [selected,setSelected]=useState<string|null>(null),[query,setQuery]=useState(''),[fit,setFit]=useState(0),[lines,setLines]=useState(true);
 const [focusRequest,setFocusRequest]=useState<{id:string;sequence:number}|null>(null);
 const [connectionMode,setConnectionMode]=useState<'text'|'vector'>('text');
 const [minSimilarity,setMinSimilarity]=useState(0.60);
 const [hoveredConnection,setHoveredConnection]=useState<{key:string;featureId:string}|null>(null);
 const [relatedHeaderStuck,setRelatedHeaderStuck]=useState(false);
 const [listLimit,setListLimit]=useState(100);
 const sidebarRef=useRef<HTMLElement|null>(null);
 const searchWrapRef=useRef<HTMLDivElement|null>(null);
 const relatedHeaderRef=useRef<HTMLDivElement|null>(null);
 const relatedListRef=useRef<HTMLDivElement|null>(null);
 const searchInputRef=useRef<HTMLInputElement|null>(null);
 const resetRelatedScroll=useRef(false);
 useEffect(()=>setListLimit(100),[query,selected]);
 function changeConnectionMode(value:'text'|'vector'){
  if(value===connectionMode)return;
  resetRelatedScroll.current=true;
  setConnectionMode(value);
 }

 const [searchResult,setSearchResult]=useState<SearchResponse|null>(null),[searching,setSearching]=useState(false);
 const [searchError,setSearchError]=useState(''),[searchRetry,setSearchRetry]=useState(0);
 const [similarState,setSimilarState]=useState<{key:string;status:'loading'|'ready'|'error';result?:SimilarResponse|VectorSimilarResponse}|null>(null);
 const [similarRetry,setSimilarRetry]=useState(0);
 const mapRequest=useRef<AbortController|null>(null);
 const [mapLookup,setMapLookup]=useState<{target:MapPlaceTarget;state:'loading'|'not_found'|'ambiguous'|'unsupported'|'error'}|null>(null);
 useEffect(()=>()=>mapRequest.current?.abort(),[]);
 function clearMapLookup(){mapRequest.current?.abort();setMapLookup(null);}
 async function selectMapPlace(target:MapPlaceTarget){
  mapRequest.current?.abort();const controller=new AbortController();mapRequest.current=controller;
  setSelected(null);setQuery('');if(isMobile)setOpenMobile(false);
  if(!target.osm&&!target.featureId){setMapLookup({target,state:'unsupported'});return;}
  setMapLookup(null);
  const loadingTimer=setTimeout(()=>{if(!controller.signal.aborted)setMapLookup({target,state:'loading'});},200);
  try{
   const result=target.osm?await resolveMapPlace(target.osm,controller.signal):{status:'matched',feature:await loadRecord(target.featureId!,controller.signal)};
   if(controller.signal.aborted)return;
   if(result.status!=='matched'||!result.feature){setMapLookup({target,state:result.status==='ambiguous'?'ambiguous':'not_found'});return;}
   const record=result.feature;
   setRecords(previous=>[...previous.filter(r=>r.feature_id!==record.feature_id),record]);
   setSelected(record.feature_id);setMapLookup(null);
   revealRelated();
  }catch{if(!controller.signal.aborted)setMapLookup({target,state:'error'});}
  finally{clearTimeout(loadingTimer);}
 }
 async function fetchSearch(text:string,signal?:AbortSignal){
  const result=await searchAtlas(text.trim(),'near',signal);
  // ES may contain a record imported after the map's initial load.
  const missing=result.results.filter(hit=>!records.some(r=>r.feature_id===hit.feature_id));
  if(missing.length){const extra=await Promise.all(missing.map(hit=>loadRecord(hit.feature_id,signal)));if(!signal?.aborted)setRecords(previous=>[...previous,...extra.filter(r=>!previous.some(p=>p.feature_id===r.feature_id))]);}
  return result;
 }
 useEffect(()=>{
  setSearchError('');setSearchResult(null);
  if(!query.trim()||loading||loadError){setSearching(false);return;}
  const controller=new AbortController();setSearching(true);
  const timer=setTimeout(()=>{fetchSearch(query.trim(),controller.signal).then(result=>{if(!controller.signal.aborted)setSearchResult(result);}).catch(()=>{if(!controller.signal.aborted)setSearchError('搜索服务暂时无法连接，请稍后重试。');}).finally(()=>{if(!controller.signal.aborted)setSearching(false);});},250);
  return()=>{clearTimeout(timer);controller.abort();};
 },[query,loading,loadError,searchRetry]);
 const current=records.find(r=>r.feature_id===selected);
 useEffect(()=>{
  const sidebar=sidebarRef.current,header=relatedHeaderRef.current;
  if(!current||!sidebar||!header){setRelatedHeaderStuck(false);return;}
  const update=()=>{
   const stickyTop=parseFloat(getComputedStyle(header).top)||0;
   setRelatedHeaderStuck(sidebar.scrollTop>0&&header.getBoundingClientRect().top-sidebar.getBoundingClientRect().top<=stickyTop+1);
  };
  update();
  sidebar.addEventListener('scroll',update,{passive:true});
  window.addEventListener('resize',update);
  return()=>{sidebar.removeEventListener('scroll',update);window.removeEventListener('resize',update);};
 },[current?.feature_id]);
 const similarSelected=!!current&&hasLiteralMeaning(current);
 const similarKey=selected&&similarSelected?`${selected}|${locale}|${connectionMode}|${connectionMode==='vector'?minSimilarity.toFixed(2):''}|${similarRetry}`:null;
 const similarContext=selected&&similarSelected?`${selected}|${locale}|${connectionMode}|`:null;
 useEffect(()=>{
  if(!selected||!similarSelected||loading||loadError||!similarKey)return;
  const controller=new AbortController();
  queueMicrotask(()=>{if(!controller.signal.aborted)setSimilarState(previous=>({key:similarKey,status:'loading',result:previous?.key.startsWith(`${selected}|${locale}|${connectionMode}|`)?previous.result:undefined}));});
  const timer=setTimeout(()=>{
   const request=connectionMode==='vector'?vectorSimilarPlaces(selected,locale,minSimilarity,controller.signal):similarPlaces(selected,locale,controller.signal);
   request.then(result=>{
    if(controller.signal.aborted)return;
    setSimilarState({key:similarKey,status:'ready',result});
    setRecords(previous=>{
     const missing=result.results.map(hit=>hit.feature).filter(r=>!previous.some(p=>p.feature_id===r.feature_id));
     return missing.length?[...previous,...missing]:previous;
    });
   }).catch(()=>{if(!controller.signal.aborted)setSimilarState(previous=>({key:similarKey,status:'error',result:previous?.key===similarKey?previous.result:undefined}));});
  },connectionMode==='vector'?200:0);
  return()=>{clearTimeout(timer);controller.abort();};
 },[selected,similarSelected,locale,loading,loadError,similarKey,connectionMode,minSimilarity]);
 const activeSimilar=similarState?.result&&similarContext&&similarState.key.startsWith(similarContext)?similarState.result:null;
 const relatedHits=activeSimilar?.results||[];
 const highlightedConnection=hoveredConnection?.key===similarKey&&relatedHits.some(hit=>hit.feature.feature_id===hoveredConnection.featureId)?hoveredConnection.featureId:null;
 const vectorUnavailable=connectionMode==='vector'&&activeSimilar&&'available' in activeSimilar&&!activeSimilar.available;
 const similarError=!!similarKey&&similarState?.key===similarKey&&similarState.status==='error';
 const similarLoading=!!similarKey&&!loading&&!loadError&&(similarState?.key!==similarKey||similarState.status==='loading');
 useEffect(()=>{
  if(!resetRelatedScroll.current)return;
  resetRelatedScroll.current=false;
  const frame=requestAnimationFrame(()=>{
   const sidebar=sidebarRef.current,search=searchWrapRef.current,header=relatedHeaderRef.current,list=relatedListRef.current;
   if(!sidebar||!search||!header||!list)return;
   sidebar.scrollTop=Math.max(0,sidebar.scrollTop+list.getBoundingClientRect().top-sidebar.getBoundingClientRect().top-search.offsetHeight-header.offsetHeight);
  });
  return()=>cancelAnimationFrame(frame);
 },[connectionMode]);
 const visible=useMemo(()=>{
  if(query.trim())return searchResult?.query===query.trim()&&searchResult.scope==='near'?searchResult.results.map(hit=>records.find(r=>r.feature_id===hit.feature_id)).filter((r):r is typeof records[number]=>!!r):[];
  if(current)return [current,...(activeSimilar?.results.map(hit=>hit.feature)||[])];
  return [];
 },[query,searchResult,current,activeSimilar,records]);
 function revealRelated(){if(isMobile)setOpenMobile(true);else setOpen(true);}
 function collapsePanel(){if(isMobile)setOpenMobile(false);else setOpen(false);}
 function openSearch(){if(isMobile)setOpenMobile(true);else setOpen(true);requestAnimationFrame(()=>searchInputRef.current?.focus());}
 function closeSearch(){flushSync(()=>setQuery(''));collapsePanel();}
 function select(id:string){clearMapLookup();const record=records.find(r=>r.feature_id===id);if(!record)return;setSelected(id);setFocusRequest(previous=>({id,sequence:(previous?.sequence??0)+1}));setQuery('');revealRelated();}
 function backToExplore(){clearMapLookup();setSelected(null);closeSearch();}
 function closeSelected(){clearMapLookup();setSelected(null);setQuery('');collapsePanel();}
 useEffect(()=>{
  const context=(document as any).modelContext;if(!context?.registerTool)return;
  const lifecycle=new AbortController();
  const tools=[{
   name:'select_place',title:'查看地名字面含义',description:'在地图中选中一个已收录地点，显示字面含义与关联图钉。',
   inputSchema:{type:'object',properties:{feature_id:{type:'string'}},required:['feature_id'],additionalProperties:false},annotations:{readOnlyHint:false},
   execute(input:any){const record=records.find(r=>r.feature_id===input?.feature_id);if(!record)throw Error('Unknown feature_id');clearMapLookup();flushSync(()=>{setSelected(record.feature_id);setQuery('');});revealRelated();return {feature_id:record.feature_id};}
  },{
   name:'search_meanings',title:'搜索地名与含义',description:'通过同一搜索接口查找地点名称或语义概念，并更新地图与可见结果。',
   inputSchema:{type:'object',properties:{query:{type:'string',minLength:1,maxLength:200}},required:['query'],additionalProperties:false},annotations:{readOnlyHint:false},
   async execute(input:any){if(typeof input?.query!=='string'||!input.query.trim()||input.query.length>200)throw Error('Invalid query');const result=await fetchSearch(input.query.trim());clearMapLookup();flushSync(()=>{setQuery(input.query.trim());setSelected(null);setSearchResult(result);setSearching(false);});return {engine:result.engine,results:result.results};}
  }];
  for(const tool of tools){try{Promise.resolve(context.registerTool(tool,{signal:lifecycle.signal})).catch(()=>{});}catch{}}
  return()=>lifecycle.abort();
 },[records]);
 return <main className="atlas-app" data-panel-open={panelOpen} lang={locale}>
  {!panelOpen&&<Button variant="ghost" className="map-search-launch" type="button" onClick={openSearch} aria-label={t('search')} aria-expanded={false} aria-controls="meaning-sidebar"><span className="map-search-launch-icon"><PanelLeft size={19} aria-hidden="true"/></span><span className="map-search-launch-label">{query||(current?nameOf(current):t('search'))}</span><span className="map-search-launch-icon"><Search size={20} aria-hidden="true"/></span></Button>}
  <LanguageSwitcher/>
  <div className="workspace">
   <Sidebar collapsible="offcanvas" className="atlas-sidebar-shell"><aside ref={sidebarRef} id="meaning-sidebar" className="sidebar" aria-label={t('explore')} inert={!isMobile&&!open}>
    <div ref={searchWrapRef} className="sidebar-search-wrap"><form className="sidebar-search" onSubmit={e=>{e.preventDefault();setQuery(query.trim());}} role="search">
     {current?<Button variant="ghost" type="button" aria-label={relatedText.back} title={relatedText.back} onClick={backToExplore}><ChevronLeft size={20}/></Button>
      :<SidebarTrigger type="button" aria-label={t('close')} title={t('close')} aria-expanded={panelOpen} aria-controls="meaning-sidebar"/>}
     <Input ref={searchInputRef} aria-label={t('search')} value={query} maxLength={200} onChange={e=>{clearMapLookup();const value=e.target.value;setQuery(value);setSelected(null);if(!value.trim())closeSearch();}} placeholder={current?nameOf(current):t('search')}/>
     <Button variant="ghost" type="submit" aria-label={t('submit')}><Search size={20}/></Button>
     {(query||current)&&<Button variant="ghost" type="button" aria-label={current?t('closeDetail'):t('clear')} onClick={current?closeSelected:closeSearch}><X size={19}/></Button>}
    </form></div>
    {current?<>
     <div className="place-hero" aria-hidden="true"/>
     <PlaceDetail record={current}/>
     <div ref={relatedHeaderRef} className={`related-results-header${relatedHeaderStuck?' is-stuck':''}`}>
      <div className="related-browser-tools">
       <h3 className="related-browser-kicker">{t('related',{count:relatedHits.length})}</h3>
       <div className="related-mode-control">
        <span className="related-mode-label" aria-hidden="true">{vectorText.matchMode}</span>
        <fieldset className="related-mode-switch">
         <legend className="sr-only">{vectorText.matchMode}</legend>
         <label><input type="radio" name="connection-mode" value="text" checked={connectionMode==='text'} onChange={()=>changeConnectionMode('text')} aria-label={vectorText.textMatch}/><span>{vectorText.textShort}</span></label>
         <label><input type="radio" name="connection-mode" value="vector" checked={connectionMode==='vector'} onChange={()=>changeConnectionMode('vector')} aria-label={vectorText.vectorMatch}/><span>{vectorText.vectorShort}</span></label>
        </fieldset>
       </div>
      </div>
      {connectionMode==='vector'&&<SimilarityThreshold label={vectorText.threshold} value={minSimilarity} onCommit={setMinSimilarity}/>}
     </div>
    </>:query.trim()?<div className="result-heading"><span>{t('results')}</span></div>:null}
    {query&&<div className="search-status" role="status">{t(searching?'searching':searchError?'searchError':searchResult?.notice?'negative':'searchLabel')}
     {searchError&&<Button variant="ghost" onClick={()=>setSearchRetry(n=>n+1)}>{t('retry')}</Button>}
     {!!searchResult&&searchResult.total>searchResult.results.length&&<p>{t('searchTotal',{total:searchResult.total,shown:searchResult.results.length})}</p>}
    </div>}
    {similarSelected&&relatedHits.length>0&&(similarLoading||similarError||vectorUnavailable)&&<div className="search-status" role={similarError?'alert':'status'}>
     {similarLoading?t('searching'):similarError?t('searchError'):vectorUnavailable?vectorText.noVector:t('empty')}
     {similarError&&<Button variant="ghost" onClick={()=>setSimilarRetry(n=>n+1)}>{t('retry')}</Button>}
    </div>}
    {(current||query.trim()||loading||loadError)&&<div ref={relatedListRef} className={`place-list ${current?'related-place-list':''}`} aria-live="polite">{loading||loadError?<div className="empty-results" role={loadError?'alert':'status'}><strong>{t(loading?'loading':'loadError')}</strong>{loadError&&<Button variant="outline" onClick={()=>setReload(n=>n+1)}>{t('retry')}</Button>}</div>
     :current?relatedHits.length?relatedHits.map(hit=>{
      const r=hit.feature;
      const meanings=relatedMeanings(hit,locale);
      return <div key={r.feature_id} className="related-place-card" onMouseEnter={()=>setHoveredConnection({key:similarKey||'',featureId:r.feature_id})} onMouseLeave={()=>setHoveredConnection(null)} onFocusCapture={()=>setHoveredConnection({key:similarKey||'',featureId:r.feature_id})} onBlurCapture={event=>{if(!event.currentTarget.contains(event.relatedTarget as Node))setHoveredConnection(null);}}>
       <Button variant="ghost" className="related-place-main" data-kind={r.kind} onClick={()=>select(r.feature_id)}>
        <span className="related-place-copy"><span className="related-place-name"><strong dir="auto">{nameOf(r)}</strong><small>{kindName(r.kind,locale)}</small></span>
         <span className="related-meaning-list">{meanings.length?meanings.map((meaning,index)=><span className="related-meaning-row" key={index}>
          <span className="related-meaning-text" dir="auto" lang={meaning.lang}>{meaning.text}</span>
          {meaning.lang!==locale&&<small className="related-translation-language">{languageName(meaning.lang,locale)}</small>}
         </span>):<span className="related-meaning-row">{t('noMeaning')}</span>}</span>
         {connectionMode==='vector'&&<small className="related-score">{vectorText.score} {hit.score.toFixed(2)}</small>}
        </span><ArrowUpRight size={15}/>
       </Button>
      </div>;
     })
      :<div className="empty-results" role={similarError?'alert':'status'}><strong>{similarLoading?t('searching'):similarError?t('searchError'):vectorUnavailable?vectorText.noVector:similarSelected?t('empty'):t('noMeaning')}</strong>{similarError&&<Button variant="outline" onClick={()=>setSimilarRetry(n=>n+1)}>{t('retry')}</Button>}</div>
     :visible.length?visible.slice(0,listLimit).map((r,i)=><Button variant="ghost" key={r.feature_id} className={`place-row ${selected===r.feature_id?'chosen':''}`} onClick={()=>select(r.feature_id)}>
      <span className="place-index">{String(i+1).padStart(2,'0')}</span><span><strong dir="auto">{nameOf(r)}</strong><small>{kindName(r.kind,locale)}</small>
       {query&&<span className="match-reason">{t(searchResult?.results.find(h=>h.feature_id===r.feature_id)?.match_kind==='name'?'nameMatch':'meaningMatch')}</span>}
      </span><ArrowUpRight size={15}/>
     </Button>)
     :<div className="empty-results"><Search size={24}/><strong>{t(searching?'searching':searchError?'searchError':'empty')}</strong><p>{t('hint')}</p></div>}
    </div>}
    {!loading&&!loadError&&!current&&!!query.trim()&&visible.length>listLimit&&<Button variant="ghost" onClick={()=>setListLimit(n=>n+100)}>{t('more',{shown:listLimit,total:visible.length})}</Button>}
   </aside></Sidebar>
   <section className="map-stage" aria-label={t('map')}>
    <MapView all={records} visible={visible} selected={selected} focusRequest={focusRequest} onSelect={select} onMapPlace={selectMapPlace} onMapBackgroundClick={collapsePanel} fit={fit} lines={lines} highlightedConnection={lines?highlightedConnection:null}/>
    <div className="map-tools"><Button variant="ghost" onClick={()=>setFit(n=>n+1)} title={t('fit')} aria-label={t('fit')}><Maximize size={18}/></Button><Button variant="ghost" onClick={()=>setLines(v=>!v)} aria-pressed={lines} title={t('lines')} aria-label={t('lines')} className={lines?'pressed':''}><Link2 size={18}/></Button></div>
    {mapLookup&&<article className="detail-card" aria-label={t('lookup')} aria-busy={mapLookup.state==='loading'}>
     <div className="detail-topline"><span>{t('lookup')}</span><Button variant="ghost" aria-label={t('closeDetail')} onClick={clearMapLookup}><X size={17}/></Button></div>
     <h2 dir="auto">{mapLookup.target.name}</h2>
     <p className="local-name" role={mapLookup.state==='error'?'alert':'status'}>{t(({loading:'lookupLoading',not_found:'notFound',ambiguous:'ambiguous',unsupported:'unsupported',error:'lookupError'} as const)[mapLookup.state])}</p>
     {mapLookup.state==='error'&&<Button variant="outline" onClick={()=>selectMapPlace(mapLookup.target)}>{t('retry')}</Button>}
    </article>}
   </section>
  </div>
 </main>;
}
