<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue';
import type { ApiKeyStatus } from '../api/types';

const PREFERENCE_KEY = 'invoicator_processing_mode';

const props = defineProps<{
  apiKeyStatus: ApiKeyStatus | null;
}>();

const emit = defineEmits<{
  (e: 'configure-api-key'): void;
  (e: 'mode-changed', mode: 'local' | 'cloud'): void;
}>();

const currentMode = ref<'local' | 'cloud'>('local');

// Initialize from localStorage on mount
onMounted(() => {
  const savedMode = localStorage.getItem(PREFERENCE_KEY);
  if (savedMode === 'local' || savedMode === 'cloud') {
    currentMode.value = savedMode;
  } else if (props.apiKeyStatus?.valid) {
    // Default to cloud if API key is valid
    currentMode.value = 'cloud';
  }
});

// Watch for API key status changes
watch(() => props.apiKeyStatus, (newStatus) => {
  // If API key becomes invalid/missing while in cloud mode, switch to local
  if (currentMode.value === 'cloud' && (!newStatus?.configured || !newStatus?.valid)) {
    // Don't auto-switch, just leave as is - user will see the warning
  }
});

const isCloudEnabled = computed(() => {
  return props.apiKeyStatus?.configured && props.apiKeyStatus?.valid;
});

function toggleMode() {
  if (currentMode.value === 'local') {
    // Switching to cloud
    if (!isCloudEnabled.value) {
      // Need to configure API key first
      emit('configure-api-key');
      return;
    }
    currentMode.value = 'cloud';
  } else {
    // Switching to local
    currentMode.value = 'local';
  }

  localStorage.setItem(PREFERENCE_KEY, currentMode.value);
  emit('mode-changed', currentMode.value);
}

function setMode(mode: 'local' | 'cloud') {
  if (mode === 'cloud' && !isCloudEnabled.value) {
    emit('configure-api-key');
    return;
  }
  currentMode.value = mode;
  localStorage.setItem(PREFERENCE_KEY, currentMode.value);
  emit('mode-changed', currentMode.value);
}
</script>

<template>
  <div class="processing-mode-toggle">
    <button
      class="toggle-button"
      :class="{ 'mode-local': currentMode === 'local', 'mode-cloud': currentMode === 'cloud' }"
      @click="toggleMode"
      :title="currentMode === 'local' ? 'Local AI (100% Private)' : 'Cloud AI (Claude)'"
    >
      <!-- Local icon (lock) -->
      <svg v-if="currentMode === 'local'" class="toggle-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
        <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
      </svg>
      <!-- Cloud icon -->
      <svg v-else class="toggle-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"></path>
      </svg>
      <span class="toggle-label">{{ currentMode === 'local' ? 'Local' : 'Cloud' }}</span>
      <!-- Warning indicator if cloud mode but no API key -->
      <span v-if="currentMode === 'cloud' && !isCloudEnabled" class="warning-dot" title="API key not configured"></span>
    </button>
  </div>
</template>

<style scoped>
.processing-mode-toggle {
  display: flex;
  align-items: center;
}

.toggle-button {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  padding: var(--spacing-xs) var(--spacing-md);
  border: 1px solid var(--color-gray-300);
  border-radius: 100px;
  background-color: var(--color-white);
  cursor: pointer;
  transition: var(--transition);
  font-family: var(--font-family);
  font-size: 0.8125rem;
  font-weight: var(--font-weight-medium);
  position: relative;
}

.toggle-button:hover {
  border-color: var(--color-gray-500);
  background-color: var(--color-gray-100);
}

.toggle-button.mode-local {
  color: var(--color-gray-700);
}

.toggle-button.mode-cloud {
  color: #1e40af;
  border-color: #93c5fd;
  background-color: #eff6ff;
}

.toggle-button.mode-cloud:hover {
  border-color: #60a5fa;
  background-color: #dbeafe;
}

.toggle-icon {
  flex-shrink: 0;
}

.toggle-label {
  white-space: nowrap;
}

.warning-dot {
  position: absolute;
  top: -2px;
  right: -2px;
  width: 8px;
  height: 8px;
  background-color: #ef4444;
  border-radius: 50%;
  border: 2px solid var(--color-white);
}
</style>
