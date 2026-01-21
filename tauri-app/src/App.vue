<script setup lang="ts">
import { ref } from "vue";
import HomePage from "./components/HomePage.vue";
import FutureImplementation from "./components/FutureImplementation.vue";
import DataReviewPage from "./components/DataReviewPage.vue";
import InvoicesListPage from "./components/InvoicesListPage.vue";
import InvoiceDetailPage from "./components/InvoiceDetailPage.vue";
import LoadingPage from "./components/LoadingPage.vue";
import type { FileProcessingResult, ProcessResponse, AnalyzeResponse } from "./api";

const currentPage = ref<'home' | 'csv' | 'interrogate' | 'review' | 'invoices' | 'invoice-detail' | 'loading'>('home');
const droppedFiles = ref<File[]>([]);
const processingResults = ref<FileProcessingResult[]>([]);
const selectedInvoiceId = ref<number | null>(null);
const featureNames: Record<string, string> = {
  csv: 'Export to CSV',
  interrogate: 'Interrogate Your Data'
};

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
</script>

<template>
  <HomePage
    v-if="currentPage === 'home'"
    @navigate="navigate"
    @files-dropped="handleFilesDropped"
  />
  <LoadingPage
    v-else-if="currentPage === 'loading'"
    :files="droppedFiles"
    @complete="handleProcessingComplete"
    @error="handleProcessingError"
    @cancel="goHome"
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
  />
  <FutureImplementation
    v-else
    :feature="featureNames[currentPage]"
    @back="goHome"
  />
</template>

<style scoped>
</style>