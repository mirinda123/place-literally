'use client';
import {createContext,useContext,useEffect,useState} from 'react';
import {isLocale,translate,type ActiveLocale,type MessageKey} from '../lib/i18n';
const Context=createContext<{locale:ActiveLocale;setLocale:(locale:ActiveLocale)=>void}>({locale:'zh',setLocale:()=>{}});
export function LocaleProvider({children}:{children:React.ReactNode}){
 const [locale,setLocale]=useState<ActiveLocale>('zh');
 useEffect(()=>{try{const saved=localStorage.getItem('atlas-language');if(isLocale(saved))setLocale(saved);else if(saved==='ko')localStorage.setItem('atlas-language','zh');}catch{}},[]);
 useEffect(()=>{document.documentElement.lang=locale==='zh'?'zh-CN':locale;},[locale]);
 function change(value:ActiveLocale){setLocale(value);try{localStorage.setItem('atlas-language',value);}catch{}}
 return <Context.Provider value={{locale,setLocale:change}}>{children}</Context.Provider>;
}
export function useLocale(){const state=useContext(Context);return {...state,t:(key:MessageKey,params?:Record<string,string|number>)=>translate(state.locale,key,params)};}
