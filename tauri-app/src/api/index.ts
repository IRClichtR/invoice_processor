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
