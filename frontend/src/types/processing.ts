export interface ProcessingState {
  status: "queued" | "processing" | "retrying" | "succeeded" | "failed";
  stage: string;
  attempt: number;
  error_code?: string | null;
}
