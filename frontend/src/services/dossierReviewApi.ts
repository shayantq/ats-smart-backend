import {apiRequest} from './apiClient';

export interface ReviewEvent {id:string;action:string;visibility:string;own:boolean;created_at:string;payload:Record<string,unknown>}
export interface ReviewState {application_id:string;revision:number;source_hash:string|null;effective_parsed:Record<string,unknown>;targets:{target:string;anchor:string;original:Record<string,unknown>}[];events:ReviewEvent[];notes:ReviewEvent[];corrections:Record<string,unknown>[];shortlisted:boolean;sections:Record<string,unknown>}
export interface VersionItem {id:string;created_at:string;source_hash:string|null;analysis_version:string|null;job_sha256:string|null}
export const getDossierReview=(id:string)=>apiRequest<ReviewState>(`/dossiers/${id}/review`,{cache:'no-store'});
export const addReviewEvent=(id:string,body:Record<string,unknown>)=>apiRequest<ReviewState>(`/dossiers/${id}/events`,{method:'POST',body:JSON.stringify(body)});
export const getVersions=(id:string)=>apiRequest<{items:VersionItem[]}>(`/dossiers/${id}/versions`);
export const compareVersions=(id:string,left:string,right:string)=>apiRequest<Record<string,unknown>>(`/dossiers/${id}/versions/compare?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`);
export const compareDossiers=(ids:string[])=>apiRequest<{items:Record<string,unknown>[];comparable:boolean;ranked:boolean}>(`/dossiers/compare`,{method:'POST',body:JSON.stringify({application_ids:ids})});
export const createReanalysisBatch=(ids:string[])=>apiRequest<{batch_id:string;items:Record<string,unknown>}>(`/dossiers/batches`,{method:'POST',body:JSON.stringify({application_ids:ids})});
export const getBatch=(id:string)=>apiRequest<{items:Record<string,unknown>[];can_recover?:boolean}>(`/dossiers/batches/${id}`);
export const recoverBatch=(id:string)=>apiRequest<{batch_id:string}>(`/dossiers/batches/${id}/recover`,{method:'POST'});
