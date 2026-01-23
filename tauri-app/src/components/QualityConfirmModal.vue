<script setup lang="ts">
import { computed, watch } from 'vue';
import { logger } from '../utils/logger';

const MODULE = 'QualityConfirmModal';

const props = defineProps<{
  visible: boolean;
  documentName: string;
  qualityScore?: number;
  hasValidApiKey: boolean;
}>();

const emit = defineEmits<{
  (e: 'continue-local'): void;
  (e: 'use-cloud'): void;
  (e: 'configure-api-key'): void;
  (e: 'cancel'): void;
}>();

// Log when modal becomes visible
watch(() => props.visible, (newVisible) => {
  if (newVisible) {
    logger.info(MODULE, 'Modal opened', {
      documentName: props.documentName,
      qualityScore: props.qualityScore,
      hasValidApiKey: props.hasValidApiKey
    });
  }
});

const qualityLabel = computed(() => {
  if (!props.qualityScore) return 'Low';
  if (props.qualityScore >= 0.8) return 'Good';
  if (props.qualityScore >= 0.5) return 'Medium';
  return 'Low';
});

const qualityPercentage = computed(() => {
  if (!props.qualityScore) return 0;
  return Math.round(props.qualityScore * 100);
});

function handleContinueLocal() {
  logger.action(MODULE, 'User selected: Continue with Local AI', {
    documentName: props.documentName,
    qualityScore: props.qualityScore
  });
  emit('continue-local');
}

function handleUseCloud() {
  if (props.hasValidApiKey) {
    logger.action(MODULE, 'User selected: Use Cloud AI', { documentName: props.documentName });
    emit('use-cloud');
  } else {
    logger.action(MODULE, 'User selected: Configure API Key (cloud unavailable)', { documentName: props.documentName });
    emit('configure-api-key');
  }
}

function handleCancel() {
  logger.action(MODULE, 'User cancelled quality confirmation', { documentName: props.documentName });
  emit('cancel');
}
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="modal-overlay" @click.self="handleCancel">
      <div class="modal-container">
        <!-- Modal Header -->
        <div class="modal-header">
          <div class="modal-icon warning">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
              <line x1="12" y1="9" x2="12" y2="13"></line>
              <line x1="12" y1="17" x2="12.01" y2="17"></line>
            </svg>
          </div>
          <h2>Low Quality Document Detected</h2>
        </div>

        <!-- Modal Body -->
        <div class="modal-body">
          <p class="document-name">
            <strong>File:</strong> {{ documentName }}
          </p>

          <div v-if="qualityScore !== undefined" class="quality-indicator">
            <div class="quality-bar-container">
              <div class="quality-bar" :style="{ width: `${qualityPercentage}%` }"></div>
            </div>
            <span class="quality-label">Quality: {{ qualityLabel }} ({{ qualityPercentage }}%)</span>
          </div>

          <p class="modal-message">
            This document may not process well with local AI due to low image quality,
            poor contrast, or handwriting. How would you like to proceed?
          </p>

          <div class="options-container">
            <div class="option-card">
              <div class="option-icon local">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                  <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
                </svg>
              </div>
              <div class="option-content">
                <h3>Continue with Local AI</h3>
                <p>Process locally with possibly reduced accuracy. Your data stays 100% private.</p>
              </div>
            </div>

            <div class="option-card">
              <div class="option-icon cloud">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"></path>
                </svg>
              </div>
              <div class="option-content">
                <h3>Use Cloud AI (Claude)</h3>
                <p>
                  Send to Claude for better extraction accuracy.
                  <span v-if="!hasValidApiKey" class="api-key-note">Requires API key configuration.</span>
                </p>
              </div>
            </div>
          </div>
        </div>

        <!-- Modal Footer -->
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="handleCancel">
            Cancel
          </button>
          <button class="btn btn-secondary" @click="handleContinueLocal">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
              <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
            </svg>
            Continue Local
          </button>
          <button class="btn btn-primary" @click="handleUseCloud">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"></path>
            </svg>
            {{ hasValidApiKey ? 'Use Cloud AI' : 'Configure API Key' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: var(--spacing-lg);
}

.modal-container {
  background-color: var(--color-white);
  border-radius: var(--border-radius-lg);
  max-width: 520px;
  width: 100%;
  max-height: 90vh;
  overflow-y: auto;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
}

.modal-header {
  padding: var(--spacing-xl);
  text-align: center;
  border-bottom: 1px solid var(--color-gray-200);
}

.modal-icon {
  width: 56px;
  height: 56px;
  margin: 0 auto var(--spacing-md);
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
}

.modal-icon.warning {
  background-color: #fef3c7;
  color: #d97706;
}

.modal-header h2 {
  font-size: 1.25rem;
  margin: 0;
}

.modal-body {
  padding: var(--spacing-xl);
}

.document-name {
  font-size: 0.875rem;
  color: var(--color-gray-600);
  margin-bottom: var(--spacing-md);
  padding: var(--spacing-sm) var(--spacing-md);
  background-color: var(--color-gray-100);
  border-radius: var(--border-radius);
  word-break: break-all;
}

.document-name strong {
  color: var(--color-gray-700);
}

.quality-indicator {
  margin-bottom: var(--spacing-lg);
}

.quality-bar-container {
  height: 8px;
  background-color: var(--color-gray-200);
  border-radius: 100px;
  overflow: hidden;
  margin-bottom: var(--spacing-xs);
}

.quality-bar {
  height: 100%;
  background-color: #f59e0b;
  border-radius: 100px;
  transition: width 0.3s ease;
}

.quality-label {
  font-size: 0.75rem;
  color: var(--color-gray-500);
}

.modal-message {
  font-size: 0.875rem;
  color: var(--color-gray-600);
  margin-bottom: var(--spacing-lg);
  line-height: 1.6;
}

.options-container {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
}

.option-card {
  display: flex;
  gap: var(--spacing-md);
  padding: var(--spacing-md);
  border: 1px solid var(--color-gray-200);
  border-radius: var(--border-radius);
  background-color: var(--color-gray-100);
}

.option-icon {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--border-radius);
  flex-shrink: 0;
}

.option-icon.local {
  background-color: var(--color-gray-200);
  color: var(--color-gray-700);
}

.option-icon.cloud {
  background-color: #dbeafe;
  color: #1e40af;
}

.option-content h3 {
  font-size: 0.875rem;
  font-weight: var(--font-weight-semibold);
  margin-bottom: var(--spacing-xs);
}

.option-content p {
  font-size: 0.8125rem;
  color: var(--color-gray-500);
  margin: 0;
}

.api-key-note {
  color: #d97706;
  font-weight: var(--font-weight-medium);
}

.modal-footer {
  padding: var(--spacing-lg) var(--spacing-xl);
  border-top: 1px solid var(--color-gray-200);
  display: flex;
  justify-content: flex-end;
  gap: var(--spacing-sm);
  flex-wrap: wrap;
}

.modal-footer .btn {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-xs);
}

@media (max-width: 500px) {
  .modal-footer {
    flex-direction: column;
  }

  .modal-footer .btn {
    width: 100%;
  }
}
</style>
