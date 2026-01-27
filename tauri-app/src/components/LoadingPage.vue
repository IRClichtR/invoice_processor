<!--
  Copyright 2026 Floriane TUERNAL SABOTINOV

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

      http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.
-->
<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import { analyzeDocument, processJob, type FileProcessingResult, type AnalyzeResponse, type ProcessResponse, type Pipeline, type UserPreference } from '../api';
import QualityConfirmModal from './QualityConfirmModal.vue';
import type { ApiKeyStatus } from '../api/types';
import { logger } from '../utils/logger';

const MODULE = 'LoadingPage';

interface ProcessingFile {
  name: string;
  file: File;
  status: 'pending' | 'analyzing' | 'processing' | 'awaiting_confirmation' | 'completed' | 'error';
  progress: number;
  error?: string;
  analysis?: AnalyzeResponse;
  result?: ProcessResponse;
}

const props = defineProps<{
  files?: File[];
  apiKeyStatus: ApiKeyStatus | null;
  processingMode: 'local' | 'cloud';
}>();

const emit = defineEmits<{
  (e: 'complete', results: FileProcessingResult[]): void;
  (e: 'error', message: string): void;
  (e: 'cancel'): void;
  (e: 'configure-api-key'): void;
}>();

const status = ref<'processing' | 'success' | 'error'>('processing');
const errorMessage = ref('');
const currentStep = ref(1);
const isCancelled = ref(false);

// Quality confirmation modal state
const showQualityModal = ref(false);
const pendingConfirmationFile = ref<ProcessingFile | null>(null);
const isProcessingPaused = ref(false);

const steps = [
  { id: 1, label: 'OCR Analysis', description: 'Analyzing document quality' },
  { id: 2, label: 'AI Extraction', description: 'Extracting data with AI model' },
  { id: 3, label: 'Finalization', description: 'Saving to database' }
];

const processingFiles = ref<ProcessingFile[]>([]);

const overallProgress = computed(() => {
  if (processingFiles.value.length === 0) return 0;
  const total = processingFiles.value.length * 100;
  const current = processingFiles.value.reduce((sum, file) => sum + file.progress, 0);
  return Math.round((current / total) * 100);
});

const completedCount = computed(() =>
  processingFiles.value.filter(f => f.status === 'completed').length
);

const errorCount = computed(() =>
  processingFiles.value.filter(f => f.status === 'error').length
);

const hasValidApiKey = computed(() => {
  return !!(props.apiKeyStatus?.configured && props.apiKeyStatus?.valid);
});

const userPreference = computed<UserPreference>(() => {
  return props.processingMode === 'local' ? 'local' : 'cloud';
});

// Initialize files when props change
watch(() => props.files, (newFiles) => {
  if (newFiles && newFiles.length > 0) {
    logger.info(MODULE, 'Files received for processing', {
      count: newFiles.length,
      files: newFiles.map(f => f.name)
    });
    processingFiles.value = newFiles.map(file => ({
      name: file.name,
      file,
      status: 'pending',
      progress: 0,
    }));
    startProcessing();
  }
}, { immediate: true });

async function startProcessing() {
  if (!props.files || props.files.length === 0) {
    logger.warn(MODULE, 'No files to process');
    status.value = 'error';
    errorMessage.value = 'No files to process';
    return;
  }

  logger.info(MODULE, 'Starting processing workflow', {
    fileCount: props.files.length,
    processingMode: props.processingMode,
    userPreference: userPreference.value
  });

  status.value = 'processing';
  isCancelled.value = false;
  isProcessingPaused.value = false;
  currentStep.value = 1;

  try {
    // Process files sequentially
    for (let i = 0; i < processingFiles.value.length; i++) {
      if (isCancelled.value) {
        logger.info(MODULE, 'Processing cancelled by user', { processedCount: i });
        break;
      }

      const pf = processingFiles.value[i];
      logger.info(MODULE, `Processing file ${i + 1}/${processingFiles.value.length}`, {
        filename: pf.name,
        fileSize: pf.file.size
      });

      // Step 1: Analyze
      pf.status = 'analyzing';
      pf.progress = 10;
      currentStep.value = 1;

      try {
        logger.debug(MODULE, 'Step 1: Analyzing document', { filename: pf.name });
        const analysis = await logger.trace(MODULE, `Analyze ${pf.name}`, () => analyzeDocument(pf.file));
        pf.analysis = analysis;
        pf.progress = 50;

        logger.info(MODULE, 'Document analysis complete', {
          filename: pf.name,
          jobId: analysis.job_id,
          suggestedPipeline: analysis.suggested_pipeline,
          confidenceScore: analysis.confidence_score,
          isHandwritten: analysis.is_handwritten
        });

        if (isCancelled.value) break;

        // Step 2: Process with suggested pipeline
        // Send the suggested pipeline along with user preference
        // Backend will return requires_confirmation if user wants local but doc needs cloud
        pf.status = 'processing';
        currentStep.value = 2;

        const pipeline: Pipeline = analysis.suggested_pipeline;

        logger.debug(MODULE, 'Step 2: Processing with pipeline', {
          filename: pf.name,
          pipeline,
          userMode: props.processingMode,
          userPreference: userPreference.value
        });

        const result = await logger.trace(
          MODULE,
          `Process ${pf.name}`,
          () => processJob(analysis.job_id, pipeline, true, userPreference.value)
        );

        // Check if confirmation is needed
        if (result.requires_confirmation) {
          logger.info(MODULE, 'Quality confirmation required', {
            filename: pf.name,
            warning: result.warning,
            suggestedPipeline: result.suggested_pipeline
          });
          pf.status = 'awaiting_confirmation';
          pf.result = result;
          pendingConfirmationFile.value = pf;
          showQualityModal.value = true;
          isProcessingPaused.value = true;

          // Wait for user decision
          logger.debug(MODULE, 'Waiting for user confirmation...', { filename: pf.name });
          await waitForConfirmation();

          // After confirmation, check if cancelled
          if (isCancelled.value) break;

          // If user continued, the file status should be updated (status can be changed by handlers)
          if ((pf.status as string) === 'error') {
            logger.warn(MODULE, 'File marked as error after confirmation', { filename: pf.name });
            continue;
          }
        } else {
          pf.result = result;
          pf.progress = 90;
          logger.debug(MODULE, 'Processing result received', {
            filename: pf.name,
            success: result.success,
            processingMethod: result.processing_method
          });
        }

        if (isCancelled.value) break;

        // Step 3: Finalize
        currentStep.value = 3;
        pf.progress = 100;

        if (pf.result?.success) {
          pf.status = 'completed';
          logger.info(MODULE, 'File processing completed successfully', {
            filename: pf.name,
            invoiceId: pf.result.invoice_id,
            processingMethod: pf.result.processing_method
          });
        } else if ((pf.status as string) !== 'error') {
          pf.status = 'error';
          pf.error = pf.result?.error || 'Processing error';
          logger.error(MODULE, 'File processing failed', null, {
            filename: pf.name,
            error: pf.error
          });
        }
      } catch (error) {
        pf.status = 'error';
        pf.error = error instanceof Error ? error.message : 'Unknown error';
        pf.progress = 100;
        logger.error(MODULE, 'Exception during file processing', error, { filename: pf.name });
      }
    }

    if (!isCancelled.value) {
      // Determine final status
      const allErrors = processingFiles.value.every(f => f.status === 'error');

      const summary = {
        total: processingFiles.value.length,
        completed: completedCount.value,
        errors: errorCount.value
      };

      if (allErrors) {
        status.value = 'error';
        const firstError = processingFiles.value.find(f => f.error)?.error;
        errorMessage.value = firstError ? getErrorMessage(firstError) : 'All files failed to process';
        logger.error(MODULE, 'All files failed to process', null, summary);
      } else {
        status.value = 'success';
        logger.info(MODULE, 'Processing workflow completed', summary);
      }
    }
  } catch (error) {
    status.value = 'error';
    errorMessage.value = error instanceof Error ? error.message : 'Processing error';
    logger.error(MODULE, 'Processing workflow failed with exception', error);
    emit('error', errorMessage.value);
  }
}

function waitForConfirmation(): Promise<void> {
  return new Promise((resolve) => {
    const checkInterval = setInterval(() => {
      if (!isProcessingPaused.value || isCancelled.value) {
        clearInterval(checkInterval);
        resolve();
      }
    }, 100);
  });
}

async function handleContinueLocal() {
  if (!pendingConfirmationFile.value) return;

  const pf = pendingConfirmationFile.value;
  logger.action(MODULE, 'User chose to continue with local processing', {
    filename: pf.name,
    jobId: pf.analysis?.job_id
  });
  showQualityModal.value = false;

  // Continue processing with florence pipeline (local)
  pf.status = 'processing';
  try {
    const result = await logger.trace(
      MODULE,
      `Process locally: ${pf.name}`,
      () => processJob(pf.analysis!.job_id, 'florence', true, 'auto')
    );
    pf.result = result;
    pf.progress = 90;

    if (result.success) {
      pf.status = 'completed';
      pf.progress = 100;
      logger.info(MODULE, 'Local processing completed successfully', { filename: pf.name });
    } else {
      pf.status = 'error';
      pf.error = result.error || 'Processing error';
      pf.progress = 100;
      logger.warn(MODULE, 'Local processing failed', { filename: pf.name, error: pf.error });
    }
  } catch (error) {
    pf.status = 'error';
    pf.error = error instanceof Error ? error.message : 'Unknown error';
    pf.progress = 100;
    logger.error(MODULE, 'Exception during local processing', error, { filename: pf.name });
  }

  pendingConfirmationFile.value = null;
  isProcessingPaused.value = false;
}

async function handleUseCloud() {
  if (!pendingConfirmationFile.value) return;

  const pf = pendingConfirmationFile.value;
  logger.action(MODULE, 'User chose to use cloud processing', {
    filename: pf.name,
    jobId: pf.analysis?.job_id
  });
  showQualityModal.value = false;

  // Process with claude pipeline
  pf.status = 'processing';
  try {
    const result = await logger.trace(
      MODULE,
      `Process with Claude: ${pf.name}`,
      () => processJob(pf.analysis!.job_id, 'claude', true, 'cloud')
    );
    pf.result = result;
    pf.progress = 90;

    if (result.success) {
      pf.status = 'completed';
      pf.progress = 100;
      logger.info(MODULE, 'Cloud processing completed successfully', { filename: pf.name });
    } else if (result.requires_api_key) {
      // Need to configure API key
      pf.status = 'error';
      pf.error = 'API key required';
      pf.progress = 100;
      logger.warn(MODULE, 'Cloud processing requires API key', { filename: pf.name });
    } else {
      pf.status = 'error';
      pf.error = result.error || 'Processing error';
      pf.progress = 100;
      logger.warn(MODULE, 'Cloud processing failed', { filename: pf.name, error: pf.error });
    }
  } catch (error) {
    pf.status = 'error';
    pf.error = error instanceof Error ? error.message : 'Unknown error';
    pf.progress = 100;
    logger.error(MODULE, 'Exception during cloud processing', error, { filename: pf.name });
  }

  pendingConfirmationFile.value = null;
  isProcessingPaused.value = false;
}

function handleConfigureApiKey() {
  logger.action(MODULE, 'User chose to configure API key from modal');
  if (pendingConfirmationFile.value) {
    pendingConfirmationFile.value.status = 'error';
    pendingConfirmationFile.value.error = 'Waiting for API key configuration';
    pendingConfirmationFile.value.progress = 100;
  }
  showQualityModal.value = false;
  pendingConfirmationFile.value = null;
  isProcessingPaused.value = false;
  emit('configure-api-key');
}

function handleModalCancel() {
  logger.action(MODULE, 'User cancelled quality confirmation modal', {
    filename: pendingConfirmationFile.value?.name
  });
  if (pendingConfirmationFile.value) {
    pendingConfirmationFile.value.status = 'error';
    pendingConfirmationFile.value.error = 'Processing cancelled by user';
    pendingConfirmationFile.value.progress = 100;
  }
  showQualityModal.value = false;
  pendingConfirmationFile.value = null;
  isProcessingPaused.value = false;
}

function handleComplete() {
  const results: FileProcessingResult[] = processingFiles.value.map(pf => ({
    filename: pf.name,
    success: pf.status === 'completed' && pf.result?.success === true,
    analysis: pf.analysis || null,
    processing: pf.result || null,
    error: pf.error || null,
  }));
  logger.action(MODULE, 'User confirmed results, completing workflow', {
    totalResults: results.length,
    successCount: results.filter(r => r.success).length
  });
  emit('complete', results);
}

function handleCancel() {
  logger.action(MODULE, 'User cancelled processing');
  isCancelled.value = true;
  showQualityModal.value = false;
  isProcessingPaused.value = false;
  emit('cancel');
}

function handleRetry() {
  logger.action(MODULE, 'User requested retry', {
    fileCount: processingFiles.value.length
  });
  processingFiles.value.forEach(f => {
    f.status = 'pending';
    f.progress = 0;
    f.error = undefined;
    f.analysis = undefined;
    f.result = undefined;
  });
  startProcessing();
}

function getErrorMessage(error: string): string {
  // Parse common error messages into user-friendly text
  const lowerError = error.toLowerCase();

  if (lowerError.includes('same name already exists') || lowerError.includes('file with the same name')) {
    return 'File already exists in database';
  }
  if (lowerError.includes('invalid file type') || lowerError.includes('allowed:')) {
    return 'Invalid file type';
  }
  if (lowerError.includes('file size exceeds') || lowerError.includes('too large')) {
    return 'File too large';
  }
  if (lowerError.includes('api key') || lowerError.includes('anthropic')) {
    return 'Claude API key not configured';
  }
  if (lowerError.includes('network') || lowerError.includes('fetch')) {
    return 'Network error';
  }

  // Return original error if no match (truncated if too long)
  return error.length > 40 ? error.substring(0, 37) + '...' : error;
}
</script>

<template>
  <div class="loading-page">
    <!-- Header -->
    <header class="header">
      <div class="container header-content">
        <div class="logo clickable" @click="emit('cancel')">
          <img src="../assets/invoicator_logo.png" alt="Invoicator" />
          <span class="logo-text">Invoicator</span>
        </div>
        <button
          v-if="status === 'processing'"
          class="btn btn-secondary"
          @click="handleCancel"
        >
          Cancel
        </button>
        <a href="https://ko-fi.com/W7W41T13JM" target="_blank" class="donate-btn">
          <img alt="Support me on Ko-fi" src="https://storage.ko-fi.com/cdn/kofi2.png?v=3" height="36" />
        </a>
      </div>
    </header>

    <!-- Main Content -->
    <main class="loading-content">
      <div class="container">
        <!-- Processing State -->
        <div v-if="status === 'processing'" class="state-card">
          <div class="state-icon processing">
            <div class="spinner-ring"></div>
          </div>
          <h1>Processing Documents</h1>
          <p class="state-description">
            Analyzing your invoices with {{ processingMode === 'local' ? 'local' : 'cloud' }} AI. This may take a moment.
          </p>

          <!-- Progress Bar -->
          <div class="progress-section">
            <div class="progress-header">
              <span>Overall Progress</span>
              <span class="progress-percent">{{ overallProgress }}%</span>
            </div>
            <div class="progress-bar">
              <div class="progress-fill" :style="{ width: `${overallProgress}%` }"></div>
            </div>
          </div>

          <!-- Steps -->
          <div class="steps-section">
            <div
              v-for="step in steps"
              :key="step.id"
              class="step-item"
              :class="{
                'step-completed': currentStep > step.id,
                'step-active': currentStep === step.id,
                'step-pending': currentStep < step.id
              }"
            >
              <div class="step-indicator">
                <svg v-if="currentStep > step.id" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                  <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
                <span v-else>{{ step.id }}</span>
              </div>
              <div class="step-content">
                <span class="step-label">{{ step.label }}</span>
                <span class="step-description">{{ step.description }}</span>
              </div>
            </div>
          </div>

          <!-- Files List -->
          <div class="files-section">
            <h3>Files ({{ completedCount }}/{{ processingFiles.length }} completed)</h3>
            <div class="files-list">
              <div
                v-for="file in processingFiles"
                :key="file.name"
                class="file-item"
                :class="`file-${file.status}`"
              >
                <div class="file-icon">
                  <svg v-if="file.status === 'completed'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                    <polyline points="22 4 12 14.01 9 11.01"></polyline>
                  </svg>
                  <div v-else-if="file.status === 'analyzing' || file.status === 'processing'" class="mini-spinner"></div>
                  <svg v-else-if="file.status === 'awaiting_confirmation'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="12" y1="8" x2="12" y2="12"></line>
                    <line x1="12" y1="16" x2="12.01" y2="16"></line>
                  </svg>
                  <svg v-else-if="file.status === 'error'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="15" y1="9" x2="9" y2="15"></line>
                    <line x1="9" y1="9" x2="15" y2="15"></line>
                  </svg>
                  <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                  </svg>
                </div>
                <span class="file-name">{{ file.name }}</span>
                <span v-if="file.status === 'awaiting_confirmation'" class="file-status-text">Awaiting decision...</span>
                <span v-else-if="file.error" class="file-error-text" :title="file.error">{{ getErrorMessage(file.error) }}</span>
                <div v-else class="file-progress">
                  <div class="file-progress-bar">
                    <div class="file-progress-fill" :style="{ width: `${file.progress}%` }"></div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Success State -->
        <div v-else-if="status === 'success'" class="state-card">
          <div class="state-icon success">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
              <polyline points="22 4 12 14.01 9 11.01"></polyline>
            </svg>
          </div>
          <h1>Processing Complete</h1>
          <p class="state-description">
            Successfully processed {{ completedCount }} document(s).
            Ready to review extracted data.
          </p>

          <div class="success-stats">
            <div class="success-stat">
              <span class="stat-value">{{ processingFiles.length }}</span>
              <span class="stat-label">Documents</span>
            </div>
            <div class="success-stat">
              <span class="stat-value">{{ completedCount }}</span>
              <span class="stat-label">Successful</span>
            </div>
            <div class="success-stat">
              <span class="stat-value">{{ errorCount }}</span>
              <span class="stat-label">Errors</span>
            </div>
          </div>

          <div class="action-buttons">
            <button class="btn btn-secondary" @click="handleCancel">
              Back to Home
            </button>
            <button class="btn btn-primary" @click="handleComplete">
              Review Extracted Data
            </button>
          </div>
        </div>

        <!-- Error State -->
        <div v-else-if="status === 'error'" class="state-card">
          <div class="state-icon error">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="8" x2="12" y2="12"></line>
              <line x1="12" y1="16" x2="12.01" y2="16"></line>
            </svg>
          </div>
          <h1>Processing Failed</h1>
          <p class="state-description">
            {{ errorMessage || 'An error occurred while processing your documents. Please try again.' }}
          </p>

          <!-- Files with errors -->
          <div v-if="processingFiles.length > 0" class="files-section error-files">
            <h3>Failed Files</h3>
            <div class="files-list">
              <div
                v-for="file in processingFiles"
                :key="file.name"
                class="file-item file-error"
              >
                <div class="file-icon">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="15" y1="9" x2="9" y2="15"></line>
                    <line x1="9" y1="9" x2="15" y2="15"></line>
                  </svg>
                </div>
                <span class="file-name">{{ file.name }}</span>
                <span v-if="file.error" class="file-error-text" :title="file.error">{{ getErrorMessage(file.error) }}</span>
              </div>
            </div>
          </div>

          <div class="action-buttons">
            <button class="btn btn-secondary" @click="handleCancel">
              Back to Home
            </button>
            <button class="btn btn-primary" @click="handleRetry">
              Try Again
            </button>
          </div>
        </div>
      </div>
    </main>

    <!-- Quality Confirmation Modal -->
    <QualityConfirmModal
      :visible="showQualityModal"
      :document-name="pendingConfirmationFile?.name || ''"
      :quality-score="pendingConfirmationFile?.analysis?.confidence_score"
      :has-valid-api-key="hasValidApiKey"
      @continue-local="handleContinueLocal"
      @use-cloud="handleUseCloud"
      @configure-api-key="handleConfigureApiKey"
      @cancel="handleModalCancel"
    />
  </div>
</template>

<style scoped>
.loading-page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background-color: var(--color-white);
}

.loading-content {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--spacing-2xl) 0;
}

/* State Card */
.state-card {
  width: 100%;
  max-width: 600px;
  text-align: center;
  padding: var(--spacing-3xl);
  background-color: var(--color-gray-100);
  border: 1px solid var(--color-gray-200);
  border-radius: var(--border-radius-lg);
}

.state-icon {
  width: 80px;
  height: 80px;
  margin: 0 auto var(--spacing-xl);
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
}

.state-icon.processing {
  background-color: var(--color-gray-200);
}

.state-icon.success {
  background-color: #dcfce7;
  color: #166534;
}

.state-icon.error {
  background-color: #fee2e2;
  color: #991b1b;
}

.state-card h1 {
  font-size: 1.5rem;
  margin-bottom: var(--spacing-sm);
}

.state-description {
  color: var(--color-gray-500);
  margin-bottom: var(--spacing-xl);
}

/* Spinner */
.spinner-ring {
  width: 48px;
  height: 48px;
  border: 4px solid var(--color-gray-300);
  border-top-color: var(--color-black);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Progress Section */
.progress-section {
  margin-bottom: var(--spacing-xl);
}

.progress-header {
  display: flex;
  justify-content: space-between;
  font-size: 0.875rem;
  color: var(--color-gray-600);
  margin-bottom: var(--spacing-sm);
}

.progress-percent {
  font-weight: var(--font-weight-semibold);
  color: var(--color-black);
}

.progress-bar {
  height: 8px;
  background-color: var(--color-gray-200);
  border-radius: 100px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background-color: var(--color-black);
  border-radius: 100px;
  transition: width 0.3s ease;
}

/* Steps */
.steps-section {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
  margin-bottom: var(--spacing-xl);
  text-align: left;
}

.step-item {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
  padding: var(--spacing-sm);
  border-radius: var(--border-radius);
}

.step-indicator {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  font-size: 0.75rem;
  font-weight: var(--font-weight-semibold);
  flex-shrink: 0;
}

.step-pending .step-indicator {
  background-color: var(--color-gray-200);
  color: var(--color-gray-500);
}

.step-active .step-indicator {
  background-color: var(--color-black);
  color: var(--color-white);
}

.step-completed .step-indicator {
  background-color: #166534;
  color: var(--color-white);
}

.step-content {
  display: flex;
  flex-direction: column;
}

.step-label {
  font-size: 0.875rem;
  font-weight: var(--font-weight-medium);
  color: var(--color-black);
}

.step-pending .step-label {
  color: var(--color-gray-500);
}

.step-description {
  font-size: 0.75rem;
  color: var(--color-gray-500);
}

/* Files Section */
.files-section {
  text-align: left;
  padding-top: var(--spacing-lg);
  border-top: 1px solid var(--color-gray-200);
}

.files-section h3 {
  font-size: 0.875rem;
  font-weight: var(--font-weight-semibold);
  margin-bottom: var(--spacing-md);
}

.files-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
}

.file-item {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  padding: var(--spacing-sm) var(--spacing-md);
  background-color: var(--color-white);
  border: 1px solid var(--color-gray-200);
  border-radius: var(--border-radius);
}

.file-icon {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.file-completed .file-icon {
  color: #166534;
}

.file-processing .file-icon {
  color: var(--color-black);
}

.file-error .file-icon {
  color: #991b1b;
}

.file-pending .file-icon {
  color: var(--color-gray-400);
}

.file-awaiting_confirmation .file-icon {
  color: #d97706;
}

.mini-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--color-gray-300);
  border-top-color: var(--color-black);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.file-name {
  flex: 1;
  font-size: 0.8125rem;
  font-family: monospace;
  color: var(--color-gray-700);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-progress {
  width: 80px;
  flex-shrink: 0;
}

.file-progress-bar {
  height: 4px;
  background-color: var(--color-gray-200);
  border-radius: 100px;
  overflow: hidden;
}

.file-progress-fill {
  height: 100%;
  background-color: var(--color-black);
  border-radius: 100px;
  transition: width 0.2s ease;
}

.file-completed .file-progress-fill {
  background-color: #166534;
}

.file-error .file-progress-fill {
  background-color: #991b1b;
}

.file-error-text {
  flex: 1;
  font-size: 0.75rem;
  color: #991b1b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-left: var(--spacing-sm);
}

.file-status-text {
  flex: 1;
  font-size: 0.75rem;
  color: #d97706;
  font-style: italic;
  margin-left: var(--spacing-sm);
}

.file-analyzing .file-icon {
  color: #1e40af;
}

/* Error Files Section */
.error-files {
  margin-bottom: var(--spacing-xl);
}

.error-files h3 {
  color: #991b1b;
}

/* Success Stats */
.success-stats {
  display: flex;
  justify-content: center;
  gap: var(--spacing-xl);
  margin-bottom: var(--spacing-xl);
}

.success-stat {
  text-align: center;
  padding: var(--spacing-md) var(--spacing-lg);
  background-color: var(--color-white);
  border-radius: var(--border-radius);
}

.success-stat .stat-value {
  display: block;
  font-size: 1.5rem;
  font-weight: var(--font-weight-bold);
  color: var(--color-black);
}

.success-stat .stat-label {
  font-size: 0.75rem;
  color: var(--color-gray-500);
}

/* Action Buttons */
.action-buttons {
  display: flex;
  justify-content: center;
  gap: var(--spacing-md);
}

/* Responsive */
@media (max-width: 600px) {
  .state-card {
    padding: var(--spacing-xl);
  }

  .success-stats {
    flex-direction: column;
    gap: var(--spacing-sm);
  }

  .action-buttons {
    flex-direction: column;
  }

  .action-buttons .btn {
    width: 100%;
  }
}
</style>
