<script setup lang="ts">
import { ref, onMounted, provide } from "vue";
import HomePage from "./components/HomePage.vue";
import FutureImplementation from "./components/FutureImplementation.vue";
import DataReviewPage from "./components/DataReviewPage.vue";
import InvoicesListPage from "./components/InvoicesListPage.vue";
import InvoiceDetailPage from "./components/InvoiceDetailPage.vue";
import LoadingPage from "./components/LoadingPage.vue";
import SettingsPage from "./components/SettingsPage.vue";
import ProcessingModeToggle from "./components/ProcessingModeToggle.vue";
import { getApiKeysStatus } from "./api";
import type { FileProcessingResult, ApiKeyStatus } from "./api";

const currentPage = ref<'home' | 'csv' | 'interrogate' | 'review' | 'invoices' | 'invoice-detail' | 'loading' | 'settings'>('home');
const droppedFiles = ref<File[]>([]);
const processingResults = ref<FileProcessingResult[]>([]);
const selectedInvoiceId = ref<number | null>(null);
const featureNames: Record<string, string> = {
  csv: 'Export to CSV',
  interrogate: 'Interrogate Your Data'
};

// Global API key status
const apiKeyStatus = ref<ApiKeyStatus | null>(null);
const processingMode = ref<'local' | 'cloud'>('local');

// Provide API key status to child components
provide('apiKeyStatus', apiKeyStatus);
provide('processingMode', processingMode);

// Load API key status on mount
onMounted(async () => {
  try {
    const status = await getApiKeysStatus();
    apiKeyStatus.value = status.anthropic;

    // Initialize processing mode from localStorage
    const savedMode = localStorage.getItem('invoicator_processing_mode');
    if (savedMode === 'local' || savedMode === 'cloud') {
      processingMode.value = savedMode;
    } else if (status.anthropic?.valid) {
      processingMode.value = 'cloud';
    }
  } catch (error) {
    console.error('Failed to load API key status:', error);
  }
});

async function refreshApiKeyStatus() {
  try {
    const status = await getApiKeysStatus();
    apiKeyStatus.value = status.anthropic;
  } catch (error) {
    console.error('Failed to refresh API key status:', error);
  }
}

function navigate(page: string) {
  currentPage.value = page as 'home' | 'csv' | 'interrogate' | 'review' | 'invoices' | 'invoice-detail' | 'loading';
}

function goHome() {
  droppedFiles.value = [];
  processingResults.value = [];
  currentPage.value = 'home';
}

function handleFilesDropped(files: File[]) {
  // Store files and navigate to loading page
  droppedFiles.value = files;
  processingResults.value = [];
  console.log('Files dropped:', files.map(f => f.name));
  currentPage.value = 'loading';
}

function handleProcessingComplete(results: FileProcessingResult[]) {
  // Store results and navigate to review page
  console.log('Processing complete:', results);
  processingResults.value = results;
  currentPage.value = 'review';
}

function handleProcessingError(message: string) {
  console.error('Processing error:', message);
  // Stay on loading page to show error state
}

function handleDataConfirmed() {
  // Data is already saved during processing, just navigate to list
  console.log('Data confirmed, navigating to invoices list');
  droppedFiles.value = [];
  processingResults.value = [];
  currentPage.value = 'invoices';
}

function handleViewInvoice(id: number) {
  selectedInvoiceId.value = id;
  currentPage.value = 'invoice-detail';
}

function handleInvoiceDetailBack() {
  selectedInvoiceId.value = null;
  currentPage.value = 'invoices';
}

function handleConfigureApiKey() {
  currentPage.value = 'settings';
}

function handleSettingsBack() {
  refreshApiKeyStatus();
  goHome();
}

function handleModeChanged(mode: 'local' | 'cloud') {
  processingMode.value = mode;
}
</script>

<template>
  <HomePage
    v-if="currentPage === 'home'"
    :api-key-status="apiKeyStatus"
    :processing-mode="processingMode"
    @navigate="navigate"
    @files-dropped="handleFilesDropped"
    @configure-api-key="handleConfigureApiKey"
  />
  <LoadingPage
    v-else-if="currentPage === 'loading'"
    :files="droppedFiles"
    :api-key-status="apiKeyStatus"
    :processing-mode="processingMode"
    @complete="handleProcessingComplete"
    @error="handleProcessingError"
    @cancel="goHome"
    @configure-api-key="handleConfigureApiKey"
  />
  <DataReviewPage
    v-else-if="currentPage === 'review'"
    :processing-results="processingResults"
    @back="goHome"
    @confirm="handleDataConfirmed"
  />
  <InvoicesListPage
    v-else-if="currentPage === 'invoices'"
    @back="goHome"
    @view-invoice="handleViewInvoice"
  />
  <InvoiceDetailPage
    v-else-if="currentPage === 'invoice-detail' && selectedInvoiceId"
    :invoice-id="selectedInvoiceId"
    @back="handleInvoiceDetailBack"
    @saved="handleInvoiceDetailBack"
    @home="goHome"
  />
  <SettingsPage
    v-else-if="currentPage === 'settings'"
    :api-key-status="apiKeyStatus"
    :processing-mode="processingMode"
    @back="handleSettingsBack"
    @mode-changed="handleModeChanged"
  />
  <FutureImplementation
    v-else
    :feature="featureNames[currentPage]"
    @back="goHome"
  />
</template>

<style scoped>
</style>
