// Copyright 2026 Floriane TUERNAL SABOTINOV
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

/**
 * API Response Types for ParseFacture Backend
 * Two-step workflow: Analyze -> Process
 */

// ============================================================================
// Invoice Types
// ============================================================================

export interface InvoiceLineResponse {
  id: number;
  invoice_id: number;
  designation: string | null;
  quantity: number | null;
  unit_price: number | null;
  total_ht: number | null;
}

export interface InvoiceResponse {
  id: number;
  provider: string;
  date: string | null;
  invoice_number: string | null;
  total_without_vat: number | null;
  total_with_vat: number | null;
  currency: string;
  original_filename: string | null;
  document_path: string | null;
  has_document: boolean;
  created_at: string | null;
  updated_at: string | null;
  lines: InvoiceLineResponse[];
}

// ============================================================================
// Invoice Update Types
// ============================================================================

export interface InvoiceLineUpdate {
  id?: number | null;
  designation: string | null;
  quantity: number | null;
  unit_price: number | null;
  total_ht: number | null;
  _delete?: boolean;
}

export interface InvoiceUpdate {
  provider?: string | null;
  date?: string | null;
  invoice_number?: string | null;
  total_without_vat?: number | null;
  total_with_vat?: number | null;
  currency?: string | null;
  lines?: InvoiceLineUpdate[] | null;
}

export interface OtherDocumentResponse {
  id: number;
  provider: string | null;
  original_filename: string | null;
  raw_text: string | null;
  created_at: string | null;
}

// ============================================================================
// Analysis Types (Step 1)
// ============================================================================

export interface QualityDetails {
  blur_score: number;
  contrast_score: number;
  word_count: number;
  low_conf_ratio: number;
}

export interface AnalyzeResponse {
  job_id: string;
  confidence_score: number;
  is_handwritten: boolean;
  is_low_quality: boolean;
  suggested_pipeline: 'florence' | 'claude';
  preview_text: string;
  word_count: number;
  page_count: number;
  expires_at: string | null;
  quality_classification: string;
  quality_details: QualityDetails;
  claude_available: boolean;
  claude_configured: boolean;
  original_filename: string | null;
}

// ============================================================================
// Processing Types (Step 2)
// ============================================================================

export type Pipeline = 'florence' | 'claude';

export type UserPreference = 'local' | 'cloud' | 'auto';

export interface ProcessRequest {
  job_id: string;
  pipeline: Pipeline;
  save_to_db?: boolean;
  user_preference?: UserPreference;
}

export interface ExtractedLineItem {
  designation: string;
  quantity: number | null;
  unit_price: number | null;
  total_ht: number | null;
}

export interface ExtractedData {
  is_invoice: boolean;
  provider: string | null;
  invoice_number: string | null;
  date: string | null;
  currency: string;
  total_ht: number | null;
  total_ttc: number | null;
  vat_amount: number | null;
  line_items: ExtractedLineItem[];
}

export interface ProcessResponse {
  success: boolean;
  invoice_id: number | null;
  document_id: number | null;
  extracted_data: ExtractedData | null;
  processing_method: string | null;
  error: string | null;
  requires_api_key: boolean;
  console_url: string | null;
  requires_confirmation: boolean;
  warning: string | null;
  suggested_pipeline: string | null;
}

// ============================================================================
// Job Status Types
// ============================================================================

export type JobStatus = 'analyzed' | 'processing' | 'completed' | 'expired' | 'failed';

export interface JobStatusResponse {
  found: boolean;
  job_id: string | null;
  status: JobStatus | null;
  is_expired: boolean;
  can_be_processed: boolean;
  result_invoice_id: number | null;
  result_document_id: number | null;
  processing_method: string | null;
  processing_error: string | null;
  created_at: string | null;
  expires_at: string | null;
  completed_at: string | null;
  error: string | null;
}

// ============================================================================
// Cleanup Types
// ============================================================================

export interface CleanupResponse {
  expired_jobs_cleaned: number;
  files_deleted: number;
  errors: string[];
}

export interface TempDirStatsResponse {
  exists: boolean;
  file_count: number;
  total_size_mb: number;
  path: string;
}

// ============================================================================
// API Key Types
// ============================================================================

export interface ApiKeyStoreRequest {
  provider: string;
  key: string;
  validate?: boolean;
}

export interface ApiKeyStoreResponse {
  success: boolean;
  valid: boolean;
  provider: string;
  error: string | null;
}

export type ApiKeyStatusType = 'valid' | 'invalid' | 'expired' | 'not_configured';

export interface ApiKeyStatus {
  provider: string;
  status: ApiKeyStatusType;
  configured: boolean;
  valid: boolean;
  expired: boolean;
  key_prefix: string | null;
  error: string | null;
  source: string | null;
  last_validated_at: string | null;
}

export interface ApiKeysStatusResponse {
  anthropic: ApiKeyStatus | null;
  console_url: string;
}

// ============================================================================
// Error Types
// ============================================================================

export interface ApiError {
  detail: string;
  status?: number;
}

export class ApiException extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = 'ApiException';
    this.status = status;
    this.detail = detail;
  }
}
