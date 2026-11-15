import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type DragEvent, type ComponentProps } from "react";
import { defaultRangeExtractor, useVirtualizer } from "@tanstack/react-virtual";
import ApplicationCard from "./ApplicationCard";
import type { ApplicationListItem, ApplicationStatus } from "../types/application";
interface KanbanColumnProps {
  status:ApplicationStatus;label:string;applications:ApplicationListItem[];draggedApplicationId:string|null;
  onDragStart:(event:DragEvent<HTMLDivElement>,application:ApplicationListItem)=>void;
  onDragEnd:(event:DragEvent<HTMLDivElement>)=>void;onDropOnColumn:(status:ApplicationStatus)=>void;
  cardControls?:(application:ApplicationListItem)=>Partial<ComponentProps<typeof ApplicationCard>>;
  total?:number;hasMore?:boolean;fetching?:boolean;loadError?:boolean;onLoadMore?:()=>void;
  registerFocus?:(handler:(id:string)=>void)=>void;pinnedIds?:string[];
}
export default function KanbanColumn({status,label,applications,draggedApplicationId,onDragStart,onDragEnd,onDropOnColumn,cardControls,total,hasMore,fetching,loadError,onLoadMore,registerFocus,pinnedIds=[]}:KanbanColumnProps){
  const column=useRef<HTMLDivElement>(null),viewport=useRef<HTMLDivElement>(null);
  const controls=useMemo(()=>new Map(applications.map(item=>[item.application_id,cardControls?.(item)])),[applications,cardControls]);
  const [visible,setVisible]=useState(typeof IntersectionObserver==='undefined');
  const [focused,setFocused]=useState<string|null>(null),[requested,setRequested]=useState<string|null>(null),[isOver,setIsOver]=useState(false);
  useEffect(()=>{
    if(typeof IntersectionObserver==='undefined')return;
    const observer=new IntersectionObserver(entries=>setVisible(entries[0].isIntersecting),{root:column.current?.parentElement,threshold:0});
    if(column.current)observer.observe(column.current);return()=>observer.disconnect();
  },[]);
  const pinned=[...pinnedIds,focused,requested].map(id=>applications.findIndex(item=>item.application_id===id)).filter(index=>index>=0);
  const virtual=useVirtualizer({count:applications.length,getScrollElement:()=>viewport.current,estimateSize:()=>250,overscan:2,
    getItemKey:index=>applications[index].application_id,enabled:visible||pinned.length>0,initialRect:{width:280,height:560},
    rangeExtractor:range=>[...new Set([...((visible||requested)?defaultRangeExtractor(range):[]),...pinned])].sort((a,b)=>a-b)});
  const focus=useCallback((id:string)=>{column.current?.scrollIntoView?.({block:'nearest',inline:'nearest'});setVisible(true);setRequested(id);},[]);
  useEffect(()=>{registerFocus?.(focus)},[registerFocus,focus]);
  useLayoutEffect(()=>{
    if(!requested)return;const index=applications.findIndex(item=>item.application_id===requested);if(index<0)return;
    virtual.scrollToIndex(index,{align:'auto'});
    const element=Array.from(viewport.current?.querySelectorAll<HTMLButtonElement>('[data-move-id]')??[]).find(element=>element.dataset.moveId===requested);
    if(element){element.focus();setRequested(null);}
  });
  const rows=virtual.getVirtualItems();
  const last=rows[rows.length-1]?.index??-1;
  useEffect(()=>{if(visible && hasMore && !fetching && !loadError && last>=applications.length-3)onLoadMore?.();},[visible,hasMore,fetching,loadError,last,applications.length,onLoadMore]);
  return <div ref={column} role="region" aria-label={label} data-testid={`kanban-column-${status}`}
    onFocusCapture={event=>{const control=(event.target as HTMLElement).closest<HTMLElement>('[data-move-id]');if(control)setFocused(control.dataset.moveId??null)}}
    onBlurCapture={event=>{if(!event.currentTarget.contains(event.relatedTarget as Node|null))setFocused(null)}}
    onDragOver={event=>{event.preventDefault();setIsOver(true)}} onDragLeave={()=>setIsOver(false)}
    onDrop={event=>{event.preventDefault();setIsOver(false);onDropOnColumn(status)}}
    className={`flex w-[17rem] shrink-0 flex-col rounded border p-3 sm:w-[19rem] ${isOver?'border-slate-500 bg-wash':'border-rule bg-wash'}`}>
    <div className="mb-4 flex items-center justify-between gap-2 border-b border-rule pb-3"><h2 className="text-sm font-semibold leading-7 text-ink">{label}</h2><span data-testid="column-count" className="text-caption text-muted">{typeof total==='number'?total:`${applications.length} بارگذاری‌شده`}</span></div>
    <div ref={viewport} data-virtual-viewport={status} tabIndex={0} aria-label={`فهرست ${label}`} className="h-[min(60dvh,560px)] min-h-[180px] overflow-y-auto overscroll-contain">
      {applications.length===0 && <p className="py-8 text-caption text-muted">کارتی در این مرحله نیست</p>}
      <div role="list" aria-label={`کارت‌های ${label}`} style={{height:virtual.getTotalSize(),position:'relative',width:'100%'}}>
        {rows.map(row=>{const application=applications[row.index];return <div key={row.key} role="listitem" aria-posinset={row.index+1} aria-setsize={typeof total==='number'?total:-1} data-index={row.index} ref={virtual.measureElement} style={{position:'absolute',top:0,left:0,width:'100%',transform:`translateY(${row.start}px)`,paddingBottom:8}}>
          <ApplicationCard application={application} isDragging={draggedApplicationId===application.application_id} onDragStart={onDragStart} onDragEnd={onDragEnd} {...controls.get(application.application_id)} />
        </div>})}
      </div>
    </div>
    {loadError && <p role="alert" className="text-caption text-red-700 dark:text-red-300">دریافت صفحهٔ بعد ناموفق بود.</p>}
    {hasMore ? <button onClick={onLoadMore} disabled={fetching} className="mt-2 border border-slate-500 px-2 py-2 text-caption">{fetching?'در حال دریافت…':loadError?'تلاش مجدد':'بارگذاری بیشتر'}</button> : <p className="mt-2 text-caption text-muted">پایان فهرست</p>}
  </div>;
}
