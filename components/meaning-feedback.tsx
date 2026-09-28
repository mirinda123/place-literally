'use client';

import {useId,useState,type FormEvent} from 'react';
import {Button} from './ui/button';
import {Dialog,DialogContent,DialogDescription,DialogHeader,DialogTitle,DialogTrigger} from './ui/dialog';
import {Sheet,SheetContent,SheetDescription,SheetHeader,SheetTitle,SheetTrigger} from './ui/sheet';
import {Input} from './ui/input';
import {Textarea} from './ui/textarea';
import {useIsMobile} from '../hooks/use-mobile';
import {submitMeaningFeedback} from '../lib/atlas-api';
import {hasLiteralMeaning,type AtlasRecord} from '../lib/feature-model';
import {feedbackLabels,localizedText} from '../lib/i18n';
import {useLocale} from './locale-provider';

function isValidReferenceUrl(value:string){
 if(!value.trim())return true;
 try{
  const url=new URL(value.trim());
  return url.protocol==='http:'||url.protocol==='https:';
 }catch{return false;}
}

export function MeaningFeedback({record}:{record:AtlasRecord}){
 const {locale,t}=useLocale();
 const labels=feedbackLabels[locale];
 const isMobile=useIsMobile();
 const id=useId();
 const hasMeaning=hasLiteralMeaning(record);
 const meanings=record.literal_meanings.map(item=>localizedText(item.translations,locale));
 const name=localizedText(record.names,locale)?.text||record.feature_id;
 const [open,setOpen]=useState(false);
 const [meaningIndex,setMeaningIndex]=useState(0);
 const [description,setDescription]=useState('');
 const [suggestion,setSuggestion]=useState('');
 const [sourceUrl,setSourceUrl]=useState('');
 const [status,setStatus]=useState<'idle'|'sending'|'success'|'error'>('idle');
 const [validation,setValidation]=useState<'reason'|'source'|null>(null);

 function changeOpen(next:boolean){
  if(!next&&status==='sending')return;
  if(next){setMeaningIndex(0);setDescription('');setSuggestion('');setSourceUrl('');setStatus('idle');setValidation(null);}
  setOpen(next);
 }
 async function submit(event:FormEvent<HTMLFormElement>){
  event.preventDefault();
  if(status==='sending')return;
  if(!description.trim()){setValidation('reason');return;}
  if(!isValidReferenceUrl(sourceUrl)){setValidation('source');return;}
  setValidation(null);
  setStatus('sending');
  try{
   await submitMeaningFeedback({feature_id:record.feature_id,meaning_index:hasMeaning?meaningIndex:null,
    language:locale,description:description.trim(),suggested_meaning:suggestion.trim()||null,source_url:sourceUrl.trim()||null});
   setStatus('success');
  }catch{setStatus('error');}
 }

 const trigger=<Button type="button" variant="ghost" size="xs" className="feedback-entry">
  {hasMeaning?labels.report:labels.supplement}
 </Button>;
 const title=hasMeaning?labels.title:labels.supplementTitle;
 const content=<>
  {isMobile?<SheetHeader className="feedback-heading"><SheetTitle>{title}</SheetTitle><SheetDescription>{name}</SheetDescription></SheetHeader>
   :<DialogHeader className="feedback-heading"><DialogTitle>{title}</DialogTitle><DialogDescription>{name}</DialogDescription></DialogHeader>}
  <div className="feedback-context">
   <div><span>{labels.context}</span><strong dir="auto">{name}</strong></div>
   {record.literal_name&&<div><span>{labels.original}</span><strong dir="auto" lang={record.literal_name.lang}>{record.literal_name.text}</strong></div>}
   {hasMeaning&&<div><span>{labels.meaning}</span><strong dir="auto" lang={meanings[meaningIndex]?.lang}>{meanings[meaningIndex]?.text||t('noMeaning')}</strong></div>}
  </div>
  {status==='success'?<div className="feedback-success" role="status">
    <p>{labels.success}</p><Button type="button" onClick={()=>changeOpen(false)}>{labels.done}</Button>
   </div>
   :<form className="feedback-form" onSubmit={submit} noValidate>
    {hasMeaning&&meanings.length>1&&<label htmlFor={`${id}-meaning`}>{labels.chooseMeaning}
     <select id={`${id}-meaning`} value={meaningIndex} onChange={event=>setMeaningIndex(Number(event.target.value))} disabled={status==='sending'}>
      {meanings.map((meaning,index)=><option key={index} value={index}>{index+1}. {meaning?.text||t('noMeaning')}</option>)}
     </select>
    </label>}
    <label htmlFor={`${id}-reason`}>{labels.reason}
     <Textarea id={`${id}-reason`} value={description} onChange={event=>{setDescription(event.target.value);if(validation==='reason')setValidation(null);if(status==='error')setStatus('idle');}}
      maxLength={2000} required disabled={status==='sending'} placeholder={labels.reasonHint}
      aria-invalid={validation==='reason'} aria-describedby={validation==='reason'?`${id}-reason-error`:undefined}/>
     {validation==='reason'&&<span id={`${id}-reason-error`} className="feedback-field-error" role="alert">{labels.reasonRequired}</span>}
    </label>
    <label htmlFor={`${id}-suggestion`}>{labels.suggestion}
     <Input id={`${id}-suggestion`} value={suggestion} onChange={event=>setSuggestion(event.target.value)}
      maxLength={500} disabled={status==='sending'} placeholder={labels.suggestionHint}/>
    </label>
    <label htmlFor={`${id}-source`}>{labels.source}
     <Input id={`${id}-source`} type="text" inputMode="url" value={sourceUrl} onChange={event=>{setSourceUrl(event.target.value);if(validation==='source')setValidation(null);if(status==='error')setStatus('idle');}}
      disabled={status==='sending'} placeholder={labels.sourceHint}
      aria-invalid={validation==='source'} aria-describedby={validation==='source'?`${id}-source-error`:undefined}/>
     {validation==='source'&&<span id={`${id}-source-error`} className="feedback-field-error" role="alert">{labels.invalidSource}</span>}
    </label>
    {status==='error'&&<p className="feedback-error" role="alert">{labels.error}</p>}
    <div className="feedback-actions">
     <Button type="button" variant="ghost" disabled={status==='sending'} onClick={()=>changeOpen(false)}>{labels.cancel}</Button>
     <Button type="submit" disabled={status==='sending'}>{status==='sending'?labels.sending:labels.send}</Button>
    </div>
   </form>}
 </>;

 return <div className="feedback-entry-row">
  {isMobile?<Sheet open={open} onOpenChange={changeOpen}>
    <SheetTrigger asChild>{trigger}</SheetTrigger>
    <SheetContent side="bottom" className="feedback-panel feedback-sheet" showCloseButton={status!=='sending'}>{content}</SheetContent>
   </Sheet>
   :<Dialog open={open} onOpenChange={changeOpen}>
    <DialogTrigger asChild>{trigger}</DialogTrigger>
    <DialogContent className="feedback-panel feedback-dialog" showCloseButton={status!=='sending'}>{content}</DialogContent>
   </Dialog>}
 </div>;
}
