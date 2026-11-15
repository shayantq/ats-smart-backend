import { useInfiniteQuery } from "@tanstack/react-query";
import { useRef } from "react";
import { fetchApplicationPage } from "../services/applicationsApi";
import type { ApplicationStatus } from "../types/application";
export const columnKey = (jobId:string,status:ApplicationStatus) => ["applications",jobId,status];
function useStatusPages(job:string,status:ApplicationStatus) {
  const lock=useRef(false);
  const query=useInfiniteQuery({queryKey:columnKey(job,status),initialPageParam:null as string|null,
    queryFn:({pageParam,signal})=>fetchApplicationPage(job,status,pageParam,signal),enabled:!!job,
    getNextPageParam:(last,_pages,_param,params)=>last.has_next && last.next_cursor && !params.includes(last.next_cursor) ? last.next_cursor : undefined});
  return {...query,loadMore:async()=>{
    if(lock.current||!query.hasNextPage)return;
    lock.current=true;
    try{await query.fetchNextPage({cancelRefetch:false});}finally{lock.current=false;}
  }};
}
/** تعداد hookها ثابت است؛ هر ستون cursor و cache مستقل دارد. */
export function useKanbanPages(job:string) {
  const draft=useStatusPages(job,"Draft");const applied=useStatusPages(job,"Applied");
  const screening=useStatusPages(job,"Screening");const technical=useStatusPages(job,"Technical Interview");
  const hr=useStatusPages(job,"HR Interview");const offer=useStatusPages(job,"Offer");
  const accepted=useStatusPages(job,"Accepted");const hired=useStatusPages(job,"Hired");const rejected=useStatusPages(job,"Rejected");
  return [draft,applied,screening,technical,hr,offer,accepted,hired,rejected];
}
