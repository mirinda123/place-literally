'use client';
import {Languages} from 'lucide-react';
import {Select,SelectTrigger,SelectValue,SelectContent,SelectItem} from './ui/select';
import {useLocale} from './locale-provider';
import {isLocale,languages} from '../lib/i18n';
export function LanguageSwitcher(){
 const {locale,setLocale,t}=useLocale();
 return <div className="language-switcher"><Select value={locale} onValueChange={value=>{if(isLocale(value))setLocale(value);}}>
  <SelectTrigger aria-label={t('language')} title={t('language')}><Languages size={18}/><SelectValue>{languages.find(l=>l.code===locale)?.short}</SelectValue></SelectTrigger>
  <SelectContent position="popper" align="end" className="language-menu">{languages.map(l=><SelectItem key={l.code} value={l.code}><span lang={l.code}>{l.name}</span></SelectItem>)}</SelectContent>
 </Select></div>;
}
