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
 * Invoice API Functions
 * Two-step workflow: Analyze -> Process
 */

import { apiGet, apiPost, apiPostForm, apiDelete, apiPut, buildUrl } from './client';
import type {
  AnalyzeResponse,
  ProcessRequest,
  ProcessResponse,
  JobStatusResponse,
  InvoiceResponse,
  InvoiceUpdate,
  OtherDocumentResponse,
  CleanupResponse,
  TempDirStatsResponse,
  ApiKeyStoreRequest,
  ApiKeyStoreResponse,
  ApiKeysStatusResponse,
  Pipeline,
  UserPreference,
} from './types';

// ============================================================================
// Two-Step Workflow
// ============================================================================

/**
 * Step 1: Analyze a document
 * Uploads the file, runs OCR, and returns quality analysis with job ID
 */
export async function analyzeDocument(file: File): Promise<AnalyzeResponse> {
  const formData = new FormData();
  formData.append('file', file);
  return apiPostForm<AnalyzeResponse>('/analyze', formData);
}

/**
 * Step 2: Process a job with the chosen pipeline
 * Uses the job_id from analyzeDocument to extract invoice data
 */
export async function processJob(
  jobId: string,
  pipeline: Pipeline,
  saveToDb: boolean = true,
  userPreference: UserPreference = 'auto'
): Promise<ProcessResponse> {
  const request: ProcessRequest = {
    job_id: jobId,
    pipeline,
    save_to_db: saveToDb,
    user_preference: userPreference,
  };
  return apiPost<ProcessResponse>('/process', request);
}

/**
 * Check the status of an analysis job
 */
export async function getJobStatus(jobId: string): Promise<JobStatusResponse> {
  return apiGet<JobStatusResponse>(`/jobs/${jobId}/status`);
}

// ============================================================================
// Invoice CRUD
// ============================================================================

/**
 * List all invoices
 */
export async function listInvoices(
  skip: number = 0,
  limit: number = 100
): Promise<InvoiceResponse[]> {
  return apiGet<InvoiceResponse[]>(`/invoices?skip=${skip}&limit=${limit}`);
}

/**
 * Get a specific invoice by ID
 */
export async function getInvoice(id: number): Promise<InvoiceResponse> {
  return apiGet<InvoiceResponse>(`/invoices/${id}`);
}

/**
 * Delete an invoice
 */
export async function deleteInvoice(id: number): Promise<void> {
  await apiDelete(`/invoices/${id}`);
}

/**
 * Update an invoice
 */
export async function updateInvoice(
  id: number,
  data: InvoiceUpdate
): Promise<InvoiceResponse> {
  return apiPut<InvoiceResponse>(`/invoices/${id}`, data);
}

/**
 * Get the URL for an invoice's original document
 */
export function getInvoiceDocumentUrl(id: number): string {
  return buildUrl(`/invoices/${id}/document`);
}

/**
 * Get the URL for a job's page image (used during review)
 */
export function getJobImageUrl(jobId: string, page: number = 0): string {
  return buildUrl(`/jobs/${jobId}/image?page=${page}`);
}

/**
 * Clean up temp files for a job after review is complete
 */
export async function cleanupJob(jobId: string): Promise<void> {
  await apiDelete(`/jobs/${jobId}`);
}

// ============================================================================
// Other Documents
// ============================================================================

/**
 * List all non-invoice documents
 */
export async function listOtherDocuments(
  skip: number = 0,
  limit: number = 100
): Promise<OtherDocumentResponse[]> {
  return apiGet<OtherDocumentResponse[]>(`/other-documents?skip=${skip}&limit=${limit}`);
}

/**
 * Get a specific other document by ID
 */
export async function getOtherDocument(id: number): Promise<OtherDocumentResponse> {
  return apiGet<OtherDocumentResponse>(`/other-documents/${id}`);
}

/**
 * Delete an other document
 */
export async function deleteOtherDocument(id: number): Promise<void> {
  await apiDelete(`/other-documents/${id}`);
}

// ============================================================================
// Cleanup
// ============================================================================

/**
 * Trigger cleanup of expired jobs and temp files
 */
export async function triggerCleanup(): Promise<CleanupResponse> {
  return apiPost<CleanupResponse>('/cleanup');
}

/**
 * Force cleanup of all jobs
 */
export async function forceCleanup(): Promise<CleanupResponse> {
  return apiPost<CleanupResponse>('/cleanup-force');
}

/**
 * Get temp directory statistics
 */
export async function getTempDirStats(): Promise<TempDirStatsResponse> {
  return apiGet<TempDirStatsResponse>('/cleanup/stats');
}

// ============================================================================
// API Key Management
// ============================================================================

/**
 * Store an API key for a provider
 */
export async function storeApiKey(
  provider: string,
  key: string,
  validate: boolean = true
): Promise<ApiKeyStoreResponse> {
  const request: ApiKeyStoreRequest = { provider, key, validate };
  return apiPost<ApiKeyStoreResponse>('/api-keys', request);
}

/**
 * Get status of all configured API keys
 */
export async function getApiKeysStatus(): Promise<ApiKeysStatusResponse> {
  return apiGet<ApiKeysStatusResponse>('/api-keys/status');
}

/**
 * Validate a stored API key
 */
export async function validateApiKey(provider: string): Promise<ApiKeyStoreResponse> {
  return apiPost<ApiKeyStoreResponse>(`/api-keys/${provider}/validate`);
}

/**
 * Delete a stored API key
 */
export async function deleteApiKey(provider: string): Promise<void> {
  await apiDelete(`/api-keys/${provider}`);
}

// ============================================================================
// Helper Types for Frontend
// ============================================================================

/**
 * Result of processing a single file (analysis + processing)
 */
export interface FileProcessingResult {
  filename: string;
  success: boolean;
  analysis: AnalyzeResponse | null;
  processing: ProcessResponse | null;
  error: string | null;
}

/**
 * Process a single file through the full workflow
 * Returns analysis data and processing result
 */
export async function processFile(
  file: File,
  pipeline?: Pipeline,
  saveToDb: boolean = true
): Promise<FileProcessingResult> {
  const result: FileProcessingResult = {
    filename: file.name,
    success: false,
    analysis: null,
    processing: null,
    error: null,
  };

  try {
    // Step 1: Analyze
    const analysis = await analyzeDocument(file);
    result.analysis = analysis;

    // Step 2: Process with chosen or suggested pipeline
    const chosenPipeline = pipeline || analysis.suggested_pipeline;
    const processResult = await processJob(analysis.job_id, chosenPipeline, saveToDb);
    result.processing = processResult;
    result.success = processResult.success;

    if (!processResult.success) {
      result.error = processResult.error || 'Processing error';
    }
  } catch (error) {
    result.error = error instanceof Error ? error.message : 'Unknown error';
  }

  return result;
}
