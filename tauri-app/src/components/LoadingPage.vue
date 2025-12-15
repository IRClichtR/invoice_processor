<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';

interface ProcessingFile {
  name: string;
  status: 'pending' | 'processing' | 'completed' | 'error';
  progress: number;
  error?: string;
}

const props = defineProps<{
  files?: File[];
}>();

const emit = defineEmits<{
  (e: 'complete', results: any[]): void;
  (e: 'error', message: string): void;
  (e: 'cancel'): void;
}>();

const status = ref<'processing' | 'success' | 'error'>('processing');
const errorMessage = ref('');
const currentStep = ref(1);
const totalSteps = 4;

const steps = [
  { id: 1, label: 'Reading files', description: 'Extracting content from documents' },
  { id: 2, label: 'AI Analysis', description: 'Running local AI model on documents' },
  { id: 3, label: 'Data Extraction', description: 'Extracting invoice fields' },
  { id: 4, label: 'Validation', description: 'Verifying extracted data' }
];

// Mock files being processed
const processingFiles = ref<ProcessingFile[]>([
  { name: 'invoice_2024_001.pdf', status: 'completed', progress: 100 },
  { name: 'invoice_2024_002.pdf', status: 'completed', progress: 100 },
  { name: 'facture_janvier.pdf', status: 'processing', progress: 65 },
  { name: 'scan_receipt.pdf', status: 'pending', progress: 0 },
  { name: 'invoice_cloud_services.pdf', status: 'pending', progress: 0 }
]);

const overallProgress = computed(() => {
  const total = processingFiles.value.length * 100;
  const current = processingFiles.value.reduce((sum, file) => sum + file.progress, 0);
  return Math.round((current / total) * 100);
});

const completedCount = computed(() =>
  processingFiles.value.filter(f => f.status === 'completed').length
);

const processingCount = computed(() =>
  processingFiles.value.filter(f => f.status === 'processing').length
);

// Mock processing simulation
onMounted(() => {
  simulateProcessing();
});

async function simulateProcessing() {
  // Simulate step progression
  for (let step = 1; step <= totalSteps; step++) {
    currentStep.value = step;
    await delay(1500);
  }

  // Simulate file processing
  for (const file of processingFiles.value) {
    if (file.status === 'pending') {
      file.status = 'processing';
    }

    while (file.progress < 100 && file.status === 'processing') {
      await delay(100);
      file.progress = Math.min(100, file.progress + Math.random() * 15);
    }

    file.progress = 100;
    file.status = 'completed';
  }

  await delay(500);
  status.value = 'success';
}

function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function handleComplete() {
  emit('complete', []);
}

function handleCancel() {
  emit('cancel');
}

function handleRetry() {
  status.value = 'processing';
  currentStep.value = 1;
  processingFiles.value.forEach(f => {
    f.status = 'pending';
    f.progress = 0;
  });
  simulateProcessing();
}

function getFileIcon(status: string) {
  switch (status) {
    case 'completed': return 'check';
    case 'processing': return 'spinner';
    case 'error': return 'error';
    default: return 'pending';
  }
}
</script>

<template>
  <div class="loading-page">
    <!-- Header -->
    <header class="header">
      <div class="container header-content">
        <div class="logo">
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
            Analyzing your invoices with local AI. This may take a moment.
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
                  <div v-else-if="file.status === 'processing'" class="mini-spinner"></div>
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
                <div class="file-progress">
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
            Successfully processed {{ processingFiles.length }} document(s).
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
              <span class="stat-value">0</span>
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
