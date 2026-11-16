import {createContext,useContext,useState,type ReactNode} from 'react';

export interface EvidenceReference {text:string;page?:number;bbox?:number[];block_id?:string}
interface EvidenceSelection {reference:EvidenceReference;sequence:number}
const Context=createContext<{selection:EvidenceSelection|null;select:(reference:EvidenceReference)=>void}|null>(null);

export function EvidenceProvider({children}:{children:ReactNode}) {
  const [selection,setSelection]=useState<EvidenceSelection|null>(null);
  return <Context.Provider value={{selection,select:reference=>setSelection(old=>({reference,sequence:(old?.sequence||0)+1}))}}>{children}</Context.Provider>;
}
export const useEvidence=()=>useContext(Context);
