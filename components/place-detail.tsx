'use client';
import {useLocale} from './locale-provider';
import {kindName,languageName,localizedText} from '../lib/i18n';
import type {AtlasRecord} from '../lib/feature-model';
import {MeaningFeedback} from './meaning-feedback';
export function PlaceDetail({record}:{record:AtlasRecord}){
 const {locale,t}=useLocale();
 const name=localizedText(record.names,locale);
 const meanings=record.literal_meanings.map(item=>localizedText(item.translations,locale));
 const original=record.literal_name;
 return <article className="localized-detail sidebar-place-detail" aria-label={`${name?.text||record.feature_id} · ${t('literal')}`}>
  <header className="detail-header">
   <div className="detail-heading">
    <h2 dir="auto" lang={name?.lang}>{name?.text||record.feature_id}</h2>
    <span className="detail-kind">{kindName(record.kind,locale)}</span>
    {original&&<p className="detail-original"><span>{t('original')}</span><strong dir="auto" lang={original.lang}>{original.text}</strong><span>({languageName(original.lang,locale)})</span></p>}
   </div>
  </header>
  {name&&name.lang!==locale&&<p className="translation-fallback">{t('fallback',{language:languageName(name.lang,locale)})}</p>}
  <section className="meaning-block"><span>{t('literal')}</span>
   {meanings.length>1?<ol className="meaning-list">{meanings.map((meaning,index)=><li key={index} dir="auto" lang={meaning?.lang}>{meaning?.text||t('noMeaning')}</li>)}</ol>
    :<h3 dir="auto" lang={meanings[0]?.lang} className={!meanings[0]?'meaning-empty':undefined}>{meanings[0]?.text||t('noMeaning')}</h3>}
   {meanings.find(meaning=>meaning&&meaning.lang!==locale)&&<p className="translation-fallback">{t('fallback',{language:languageName(meanings.find(meaning=>meaning&&meaning.lang!==locale)!.lang,locale)})}</p>}
   <MeaningFeedback key={record.feature_id} record={record}/>
  </section>
 </article>;
}
