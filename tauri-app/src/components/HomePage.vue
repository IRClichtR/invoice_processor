<script setup lang="ts">
import { ref } from 'vue';
import ProcessingModeToggle from './ProcessingModeToggle.vue';
import type { ApiKeyStatus } from '../api/types';

defineProps<{
  apiKeyStatus: ApiKeyStatus | null;
  processingMode: 'local' | 'cloud';
}>();

const emit = defineEmits<{
  (e: 'navigate', page: string): void;
  (e: 'files-dropped', files: File[]): void;
  (e: 'configure-api-key'): void;
  (e: 'mode-changed', mode: 'local' | 'cloud'): void;
}>();

const isDragging = ref(false);
const fileInputRef = ref<HTMLInputElement | null>(null);

const acceptedTypes = [
  'application/pdf',
  'image/jpeg',
  'image/png',
  'image/bmp',
  'image/tiff',
  'image/webp',
];

const acceptedExtensions = ['.pdf', '.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'];

function isValidFile(file: File): boolean {
  const extension = '.' + file.name.split('.').pop()?.toLowerCase();
  return acceptedTypes.includes(file.type) || acceptedExtensions.includes(extension);
}

function handleDragOver(e: DragEvent) {
  e.preventDefault();
  isDragging.value = true;
}

function handleDragLeave(e: DragEvent) {
  e.preventDefault();
  isDragging.value = false;
}

function handleDrop(e: DragEvent) {
  e.preventDefault();
  isDragging.value = false;

  const files = Array.from(e.dataTransfer?.files || []);
  const validFiles = files.filter(isValidFile);

  if (validFiles.length > 0) {
    emit('files-dropped', validFiles);
  }
}

function openFileDialog() {
  fileInputRef.value?.click();
}

function handleFileInput(e: Event) {
  const input = e.target as HTMLInputElement;
  const files = Array.from(input.files || []);
  const validFiles = files.filter(isValidFile);

  if (validFiles.length > 0) {
    emit('files-dropped', validFiles);
  }

  // Reset input
  input.value = '';
}
</script>

<template>
  <div class="home">
    <!-- Header -->
    <header class="header">
      <div class="container header-content">
        <div class="logo">
          <img src="../assets/invoicator_logo.png" alt="Invoicator" />
          <span class="logo-text">Invoicator</span>
        </div>
        <div class="header-actions">
          <ProcessingModeToggle
            :api-key-status="apiKeyStatus"
            @configure-api-key="emit('configure-api-key')"
            @mode-changed="(mode) => emit('mode-changed', mode)"
          />
          <button class="btn btn-secondary" @click="emit('navigate', 'invoices')">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
              <line x1="16" y1="13" x2="8" y2="13"></line>
              <line x1="16" y1="17" x2="8" y2="17"></line>
            </svg>
            View Invoices
          </button>
        </div>
      </div>
    </header>

    <!-- Hero Section -->
    <section class="hero">
      <div class="container">
        <span class="tagline">
          {{ processingMode === 'local' ? 'Local Processing' : 'Cloud-Enhanced Processing' }}
        </span>
        <h1>Invoicator</h1>
        <p class="subtitle">
            AI-powered invoice extraction, local by default. 
            Optional cloud processing for complex documents, always encrypted.
        </p>

        <!-- Dropzone -->
        <div
          class="dropzone"
          :class="{ 'dropzone-active': isDragging }"
          @dragover="handleDragOver"
          @dragleave="handleDragLeave"
          @drop="handleDrop"
          @click="openFileDialog"
        >
          <input
            ref="fileInputRef"
            type="file"
            accept=".pdf,.jpg,.jpeg,.png,.bmp,.tiff,.tif,.webp"
            multiple
            hidden
            @change="handleFileInput"
          />
          <div class="dropzone-icon">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="17 8 12 3 7 8"></polyline>
              <line x1="12" y1="3" x2="12" y2="15"></line>
            </svg>
          </div>
          <p class="dropzone-text">
            <span class="dropzone-highlight">Drop your files here</span>
            or click to browse
          </p>
          <p class="dropzone-hint">PDF and images accepted (JPG, PNG, TIFF, WEBP)</p>
        </div>
      </div>
    </section>

    <!-- Features Section -->
    <section class="features">
      <div class="container">
        <div class="features-header">
          <h2>Summon your personal Invoicator</h2>
        </div>
        <div class="grid grid-3">
          <!-- Feature 1: Extract (click to preview review page) -->
          <div class="feature-card clickable" @click="emit('navigate', 'review')">
            <div class="icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                <polyline points="14 2 14 8 20 8"></polyline>
                <line x1="16" y1="13" x2="8" y2="13"></line>
                <line x1="16" y1="17" x2="8" y2="17"></line>
                <polyline points="10 9 9 9 8 9"></polyline>
              </svg>
            </div>
            <h3>Extract Documents</h3>
            <p>
              Drop your PDFs and let AI do the magic. Automatically extract
              invoice data including amounts, dates, line items, and vendor
              information with high accuracy.
            </p>
          </div>

          <!-- Feature 2: CSV Export -->
          <div class="feature-card clickable" @click="emit('navigate', 'invoices')">
            <div class="icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="7 10 12 15 17 10"></polyline>
                <line x1="12" y1="15" x2="12" y2="3"></line>
              </svg>
            </div>
            <h3>Export to CSV</h3>
            <p>
              Export your data in clean, ready-to-use CSV files. Perfect for
              importing into accounting software, spreadsheets, or any other
              business tools you use.
            </p>
          </div>

          <!-- Feature 3: Interrogate -->
          <div class="feature-card clickable" @click="emit('navigate', 'interrogate')">
            <div class="icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="11" cy="11" r="8"></circle>
                <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
              </svg>
            </div>
            <h3>Payment matching</h3>
            <p>
                Reconcile your invoices with bank statements to track 
                paid vs unpaid invoices and detect discrepancies.
            </p>
          </div>
        </div>
      </div>
    </section>

    <!-- Footer -->
    <footer class="footer">
      <div class="container">
        <p>Invoicator - Your invoices, your data, your machine.</p>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.home {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.dropzone {
  max-width: 500px;
  margin: 0 auto;
  padding: var(--spacing-2xl);
  border: 2px dashed var(--color-gray-300);
  border-radius: var(--border-radius-lg);
  background-color: var(--color-gray-100);
  cursor: pointer;
  transition: var(--transition);
}

.dropzone:hover {
  border-color: var(--color-gray-500);
  background-color: var(--color-white);
}

.dropzone-active {
  border-color: var(--color-black);
  background-color: var(--color-white);
  border-style: solid;
}

.dropzone-icon {
  margin-bottom: var(--spacing-md);
  color: var(--color-gray-500);
}

.dropzone-active .dropzone-icon {
  color: var(--color-black);
}

.dropzone-text {
  font-size: 1rem;
  color: var(--color-gray-600);
  margin-bottom: var(--spacing-xs);
}

.dropzone-highlight {
  font-weight: var(--font-weight-semibold);
  color: var(--color-black);
}

.dropzone-hint {
  font-size: 0.875rem;
  color: var(--color-gray-400);
}

.feature-card.clickable {
  cursor: pointer;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
}

.header-actions .btn {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
}
</style>
