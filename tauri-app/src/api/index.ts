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
 * API Module Barrel Export
 */

// Types
export * from './types';

// API Functions
export {
  // Two-step workflow
  analyzeDocument,
  processJob,
  getJobStatus,
  processFile,
  getJobImageUrl,
  cleanupJob,
  // Invoice CRUD
  listInvoices,
  getInvoice,
  deleteInvoice,
  updateInvoice,
  getInvoiceDocumentUrl,
  // Other documents
  listOtherDocuments,
  getOtherDocument,
  deleteOtherDocument,
  // Cleanup
  triggerCleanup,
  forceCleanup,
  getTempDirStats,
  // API Keys
  storeApiKey,
  getApiKeysStatus,
  validateApiKey,
  deleteApiKey,
} from './invoices';

export type { FileProcessingResult } from './invoices';
