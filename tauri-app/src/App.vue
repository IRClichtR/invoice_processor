<script setup lang="ts">
import { ref } from "vue";
import { invoke } from "@tauri-apps/api/core";
import HomePage from "./components/HomePage.vue";
import FutureImplementation from "./components/FutureImplementation.vue";

const currentPage = ref<'home' | 'csv' | 'interrogate'>('home');
const featureNames: Record<string, string> = {
  csv: 'Export to CSV',
  interrogate: 'Interrogate Your Data'
};

function navigate(page: string) {
  currentPage.value = page as 'home' | 'csv' | 'interrogate';
}

function goHome() {
  currentPage.value = 'home';
}
</script>

<template>
  <HomePage v-if="currentPage === 'home'" @navigate="navigate" />
  <FutureImplementation
    v-else
    :feature="featureNames[currentPage]"
    @back="goHome"
  />
</template>

<style scoped>
</style>