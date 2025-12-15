<script setup lang="ts">
import { ref } from "vue";
import { invoke } from "@tauri-apps/api/core";
import HomePage from "./components/HomePage.vue";
import FutureImplementation from "./components/FutureImplementation.vue";
import DataReviewPage from "./components/DataReviewPage.vue";
import InvoicesListPage from "./components/InvoicesListPage.vue";
import LoadingPage from "./components/LoadingPage.vue";

const currentPage = ref<'home' | 'csv' | 'interrogate' | 'review' | 'invoices' | 'loading'>('home');
const droppedFiles = ref<File[]>([]);
const featureNames: Record<string, string> = {
  csv: 'Export to CSV',
  interrogate: 'Interrogate Your Data'
};

function navigate(page: string) {
  currentPage.value = page as 'home' | 'csv' | 'interrogate' | 'review' | 'invoices' | 'loading';
}

function goHome() {
  currentPage.value = 'home';
}

function handleFilesDropped(files: File[]) {
  // Store files and navigate to loading page
  droppedFiles.value = files;
  console.log('Files dropped:', files);
  currentPage.value = 'loading';
}

function handleProcessingComplete(results: any[]) {
  // Navigate to review page after processing
  console.log('Processing complete:', results);
  currentPage.value = 'review';
}

function handleProcessingError(message: string) {
  console.error('Processing error:', message);
  // Stay on loading page to show error state
}

function handleDataConfirmed(data: any[]) {
  // In real implementation, this would save to database
  console.log('Data confirmed:', data);
  currentPage.value = 'invoices'; // Navigate to invoices list after saving
}

function handleViewInvoice(id: string) {
  // In real implementation, this would open invoice detail view
  console.log('View invoice:', id);
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
    @back="goHome"
    @confirm="handleDataConfirmed"
  />
  <InvoicesListPage
    v-else-if="currentPage === 'invoices'"
    @back="goHome"
    @view-invoice="handleViewInvoice"
  />
  <FutureImplementation
    v-else
    :feature="featureNames[currentPage]"
    @back="goHome"
  />
</template>

<style scoped>
</style>