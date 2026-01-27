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
import { ref, onMounted, provide } from "vue";
import HomePage from "./components/HomePage.vue";
import FutureImplementation from "./components/FutureImplementation.vue";
import DataReviewPage from "./components/DataReviewPage.vue";
import InvoicesListPage from "./components/InvoicesListPage.vue";
import InvoiceDetailPage from "./components/InvoiceDetailPage.vue";
import LoadingPage from "./components/LoadingPage.vue";
import SettingsPage from "./components/SettingsPage.vue";
import { getApiKeysStatus } from "./api";
import type { FileProcessingResult, ApiKeyStatus } from "./api";
import { logger } from "./utils/logger";

const MODULE = 'App';

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
  logger.info(MODULE, 'Application mounted, initializing...');
  try {
    const status = await logger.trace(MODULE, 'Load API key status', () => getApiKeysStatus());
    apiKeyStatus.value = status.anthropic;
    logger.state(MODULE, 'API key status loaded', {
      configured: status.anthropic?.configured,
      valid: status.anthropic?.valid,
      status: status.anthropic?.status
    });

    // Initialize processing mode from localStorage
    const savedMode = localStorage.getItem('invoicator_processing_mode');
    if (savedMode === 'local' || savedMode === 'cloud') {
      processingMode.value = savedMode;
      logger.state(MODULE, 'Processing mode restored from localStorage', { mode: savedMode });
    } else if (status.anthropic?.valid) {
      processingMode.value = 'cloud';
      logger.state(MODULE, 'Processing mode defaulted to cloud (valid API key)', { mode: 'cloud' });
    } else {
      logger.state(MODULE, 'Processing mode defaulted to local', { mode: 'local' });
    }
  } catch (error) {
    logger.error(MODULE, 'Failed to load API key status', error);
  }
});

async function refreshApiKeyStatus() {
  logger.debug(MODULE, 'Refreshing API key status...');
  try {
    const status = await getApiKeysStatus();
    apiKeyStatus.value = status.anthropic;
    logger.state(MODULE, 'API key status refreshed', {
      configured: status.anthropic?.configured,
      valid: status.anthropic?.valid
    });
  } catch (error) {
    logger.error(MODULE, 'Failed to refresh API key status', error);
  }
}

function navigate(page: string) {
  logger.action(MODULE, 'Navigate', { from: currentPage.value, to: page });
  currentPage.value = page as 'home' | 'csv' | 'interrogate' | 'review' | 'invoices' | 'invoice-detail' | 'loading';
}

function goHome() {
  logger.action(MODULE, 'Go home', { previousPage: currentPage.value });
  droppedFiles.value = [];
  processingResults.value = [];
  currentPage.value = 'home';
}

function handleFilesDropped(files: File[]) {
  const fileInfo = files.map(f => ({ name: f.name, size: f.size, type: f.type }));
  logger.action(MODULE, 'Files dropped', { count: files.length, files: fileInfo });
  droppedFiles.value = files;
  processingResults.value = [];
  currentPage.value = 'loading';
}

function handleProcessingComplete(results: FileProcessingResult[]) {
  const summary = {
    total: results.length,
    successful: results.filter(r => r.success).length,
    failed: results.filter(r => !r.success).length
  };
  logger.info(MODULE, 'Processing complete', summary);
  processingResults.value = results;
  currentPage.value = 'review';
}

function handleProcessingError(message: string) {
  logger.error(MODULE, 'Processing error', null, { message });
  // Stay on loading page to show error state
}

function handleDataConfirmed() {
  logger.action(MODULE, 'Data confirmed', { resultsCount: processingResults.value.length });
  droppedFiles.value = [];
  processingResults.value = [];
  currentPage.value = 'invoices';
}

function handleViewInvoice(id: number) {
  logger.action(MODULE, 'View invoice', { invoiceId: id });
  selectedInvoiceId.value = id;
  currentPage.value = 'invoice-detail';
}

function handleInvoiceDetailBack() {
  logger.action(MODULE, 'Invoice detail back');
  selectedInvoiceId.value = null;
  currentPage.value = 'invoices';
}

function handleConfigureApiKey() {
  logger.action(MODULE, 'Configure API key requested');
  currentPage.value = 'settings';
}

function handleSettingsBack() {
  logger.action(MODULE, 'Settings back');
  refreshApiKeyStatus();
  goHome();
}

function handleModeChanged(mode: 'local' | 'cloud') {
  logger.state(MODULE, 'Processing mode changed', { previousMode: processingMode.value, newMode: mode });
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
    @mode-changed="handleModeChanged"
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
