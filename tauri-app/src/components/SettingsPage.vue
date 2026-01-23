<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { getApiKeysStatus, storeApiKey, deleteApiKey } from '../api';
import type { ApiKeyStatus } from '../api/types';
import { logger } from '../utils/logger';

const MODULE = 'SettingsPage';
const PREFERENCE_KEY = 'invoicator_processing_mode';

const props = defineProps<{
  apiKeyStatus: ApiKeyStatus | null;
  processingMode: 'local' | 'cloud';
}>();

const emit = defineEmits<{
  (e: 'back'): void;
  (e: 'mode-changed', mode: 'local' | 'cloud'): void;
}>();

const apiKeyInput = ref('');
const isLoading = ref(true);
const isSaving = ref(false);
const isDeleting = ref(false);
const anthropicStatus = ref<ApiKeyStatus | null>(null);
const consoleUrl = ref('https://console.anthropic.com');
const errorMessage = ref<string | null>(null);
const successMessage = ref<string | null>(null);

const currentMode = ref<'local' | 'cloud'>(props.processingMode);

const isCloudEnabled = computed(() => {
  return anthropicStatus.value?.configured && anthropicStatus.value?.valid;
});

onMounted(async () => {
  logger.debug(MODULE, 'Component mounted, loading API key status');
  await loadApiKeyStatus();
});

async function loadApiKeyStatus() {
  isLoading.value = true;
  errorMessage.value = null;
  logger.debug(MODULE, 'Loading API key status...');

  try {
    const status = await logger.trace(MODULE, 'Fetch API key status', () => getApiKeysStatus());
    anthropicStatus.value = status.anthropic;
    consoleUrl.value = status.console_url || 'https://console.anthropic.com';
    logger.state(MODULE, 'API key status loaded', {
      configured: status.anthropic?.configured,
      valid: status.anthropic?.valid,
      source: status.anthropic?.source
    });
  } catch (error) {
    logger.error(MODULE, 'Failed to load API key status', error);
    errorMessage.value = 'Failed to load API key status';
  } finally {
    isLoading.value = false;
  }
}

async function handleSaveApiKey() {
  if (!apiKeyInput.value.trim()) {
    logger.warn(MODULE, 'Save API key blocked - empty input');
    errorMessage.value = 'Please enter an API key';
    return;
  }

  logger.action(MODULE, 'Save API key initiated', { keyPrefix: apiKeyInput.value.trim().substring(0, 10) + '...' });
  isSaving.value = true;
  errorMessage.value = null;
  successMessage.value = null;

  try {
    const result = await logger.trace(MODULE, 'Store and validate API key', () =>
      storeApiKey('anthropic', apiKeyInput.value.trim(), true)
    );

    if (result.valid) {
      logger.info(MODULE, 'API key saved successfully', { valid: true });
      successMessage.value = 'API key saved and validated successfully!';
      apiKeyInput.value = '';
      await loadApiKeyStatus();
    } else {
      logger.warn(MODULE, 'API key validation failed', { error: result.error });
      errorMessage.value = result.error || 'API key validation failed';
    }
  } catch (error: any) {
    logger.error(MODULE, 'Failed to save API key', error);
    errorMessage.value = error.detail || 'Failed to save API key';
  } finally {
    isSaving.value = false;
  }
}

async function handleDeleteApiKey() {
  logger.action(MODULE, 'Delete API key requested');
  if (!confirm('Are you sure you want to remove the API key?')) {
    logger.debug(MODULE, 'Delete API key cancelled by user');
    return;
  }

  logger.action(MODULE, 'Delete API key confirmed');
  isDeleting.value = true;
  errorMessage.value = null;
  successMessage.value = null;

  try {
    await logger.trace(MODULE, 'Delete API key', () => deleteApiKey('anthropic'));
    logger.info(MODULE, 'API key deleted successfully');
    successMessage.value = 'API key removed successfully';
    await loadApiKeyStatus();

    // If removing API key while in cloud mode, switch to local
    if (currentMode.value === 'cloud') {
      logger.state(MODULE, 'Switching to local mode after API key deletion');
      setMode('local');
    }
  } catch (error: any) {
    logger.error(MODULE, 'Failed to delete API key', error);
    errorMessage.value = error.detail || 'Failed to remove API key';
  } finally {
    isDeleting.value = false;
  }
}

function setMode(mode: 'local' | 'cloud') {
  const previousMode = currentMode.value;
  if (mode === 'cloud' && !isCloudEnabled.value) {
    logger.warn(MODULE, 'Set cloud mode blocked - no valid API key', { requestedMode: mode });
    errorMessage.value = 'Please configure and validate an API key to enable Cloud mode';
    return;
  }
  currentMode.value = mode;
  localStorage.setItem(PREFERENCE_KEY, mode);
  logger.action(MODULE, 'Processing mode changed', { from: previousMode, to: mode });
  emit('mode-changed', mode);
}
</script>

<template>
  <div class="settings-page">
    <!-- Header -->
    <header class="header">
      <div class="container header-content">
        <div class="logo clickable" @click="emit('back')">
          <img src="../assets/invoicator_logo.png" alt="Invoicator" />
          <span class="logo-text">Invoicator</span>
        </div>
        <button class="btn btn-secondary" @click="emit('back')">Back to Home</button>
      </div>
    </header>

    <!-- Main Content -->
    <main class="settings-content">
      <div class="container">
        <div class="settings-header">
          <h1>Settings</h1>
          <p>Configure your API keys and processing preferences</p>
        </div>

        <!-- Processing Mode Section -->
        <div class="settings-section">
          <div class="section-header">
            <div class="section-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="3"></circle>
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
              </svg>
            </div>
            <div>
              <h2>Processing Mode</h2>
              <p>Choose how documents are processed</p>
            </div>
          </div>

          <div class="mode-options">
            <div
              class="mode-option"
              :class="{ 'mode-option-selected': currentMode === 'local' }"
              @click="setMode('local')"
            >
              <div class="mode-radio">
                <div v-if="currentMode === 'local'" class="mode-radio-inner"></div>
              </div>
              <div class="mode-icon local">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                  <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
                </svg>
              </div>
              <div class="mode-content">
                <h3>Local AI</h3>
                <p>
                  Process documents 100% locally using Florence-2.
                  Your data never leaves your machine.
                </p>
                <ul class="mode-features">
                  <li>Maximum privacy</li>
                  <li>Works offline</li>
                  <li>Best for clear, printed documents</li>
                </ul>
              </div>
            </div>

            <div
              class="mode-option"
              :class="{
                'mode-option-selected': currentMode === 'cloud',
                'mode-option-disabled': !isCloudEnabled
              }"
              @click="setMode('cloud')"
            >
              <div class="mode-radio">
                <div v-if="currentMode === 'cloud'" class="mode-radio-inner"></div>
              </div>
              <div class="mode-icon cloud">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"></path>
                </svg>
              </div>
              <div class="mode-content">
                <h3>
                  Cloud AI (Claude)
                  <span v-if="!isCloudEnabled" class="mode-badge">Requires API Key</span>
                </h3>
                <p>
                  Use Claude Vision for difficult documents.
                  Documents are sent to Anthropic's servers for processing.
                </p>
                <ul class="mode-features">
                  <li>Better for handwritten text</li>
                  <li>Higher accuracy on low-quality scans</li>
                  <li>Requires internet connection</li>
                </ul>
              </div>
            </div>
          </div>
        </div>

        <!-- API Key Section -->
        <div class="settings-section">
          <div class="section-header">
            <div class="section-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"></path>
              </svg>
            </div>
            <div>
              <h2>Claude API Key</h2>
              <p>Required for Cloud AI processing mode</p>
            </div>
          </div>

          <!-- Loading State -->
          <div v-if="isLoading" class="loading-state">
            <div class="spinner"></div>
            <span>Loading...</span>
          </div>

          <!-- API Key Status -->
          <div v-else class="api-key-content">
            <!-- Messages -->
            <div v-if="errorMessage" class="message message-error">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="15" y1="9" x2="9" y2="15"></line>
                <line x1="9" y1="9" x2="15" y2="15"></line>
              </svg>
              {{ errorMessage }}
            </div>
            <div v-if="successMessage" class="message message-success">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                <polyline points="22 4 12 14.01 9 11.01"></polyline>
              </svg>
              {{ successMessage }}
            </div>

            <!-- Current Status -->
            <div v-if="anthropicStatus?.configured" class="current-key">
              <div class="key-info">
                <span class="key-label">Current key:</span>
                <code class="key-prefix">{{ anthropicStatus.key_prefix }}...</code>
                <span
                  class="key-status"
                  :class="anthropicStatus.valid ? 'status-valid' : 'status-invalid'"
                >
                  {{ anthropicStatus.valid ? 'Valid' : 'Invalid' }}
                </span>
                <span v-if="anthropicStatus.source === 'env_migrated'" class="key-source">
                  (from environment)
                </span>
              </div>
              <button
                class="btn btn-danger btn-sm"
                @click="handleDeleteApiKey"
                :disabled="isDeleting"
              >
                {{ isDeleting ? 'Removing...' : 'Remove' }}
              </button>
            </div>

            <!-- Input Form -->
            <div class="api-key-form">
              <label for="apiKey">{{ anthropicStatus?.configured ? 'Replace API Key' : 'Enter API Key' }}</label>
              <div class="input-group">
                <input
                  id="apiKey"
                  type="password"
                  v-model="apiKeyInput"
                  placeholder="sk-ant-..."
                  :disabled="isSaving"
                />
                <button
                  class="btn btn-primary"
                  @click="handleSaveApiKey"
                  :disabled="isSaving || !apiKeyInput.trim()"
                >
                  {{ isSaving ? 'Saving...' : 'Save' }}
                </button>
              </div>
              <p class="input-hint">
                Get your API key from
                <a :href="consoleUrl" target="_blank" rel="noopener noreferrer">
                  Anthropic Console
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                    <polyline points="15 3 21 3 21 9"></polyline>
                    <line x1="10" y1="14" x2="21" y2="3"></line>
                  </svg>
                </a>
              </p>
            </div>
          </div>
        </div>

        <!-- Info Box -->
        <div class="info-box">
          <div class="info-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="16" x2="12" y2="12"></line>
              <line x1="12" y1="8" x2="12.01" y2="8"></line>
            </svg>
          </div>
          <div class="info-content">
            <h3>When is Cloud AI used?</h3>
            <p>
              In <strong>Cloud mode</strong>, documents are automatically processed with Claude when local AI detects:
              handwritten text, very low quality scans, or poor OCR confidence.
              In <strong>Local mode</strong>, you'll be prompted to confirm before any data leaves your machine.
            </p>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
.settings-page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background-color: var(--color-gray-100);
}

.settings-content {
  flex: 1;
  padding: var(--spacing-xl) 0;
}

.settings-header {
  margin-bottom: var(--spacing-xl);
}

.settings-header h1 {
  font-size: 1.5rem;
  margin-bottom: var(--spacing-xs);
}

.settings-header p {
  color: var(--color-gray-500);
  font-size: 0.875rem;
}

/* Section */
.settings-section {
  background-color: var(--color-white);
  border: 1px solid var(--color-gray-200);
  border-radius: var(--border-radius-lg);
  padding: var(--spacing-xl);
  margin-bottom: var(--spacing-lg);
}

.section-header {
  display: flex;
  align-items: flex-start;
  gap: var(--spacing-md);
  margin-bottom: var(--spacing-lg);
  padding-bottom: var(--spacing-lg);
  border-bottom: 1px solid var(--color-gray-200);
}

.section-icon {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: var(--color-gray-100);
  border-radius: var(--border-radius);
  color: var(--color-gray-600);
}

.section-header h2 {
  font-size: 1.125rem;
  margin-bottom: var(--spacing-xs);
}

.section-header p {
  color: var(--color-gray-500);
  font-size: 0.875rem;
}

/* Mode Options */
.mode-options {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
}

.mode-option {
  display: flex;
  align-items: flex-start;
  gap: var(--spacing-md);
  padding: var(--spacing-lg);
  border: 2px solid var(--color-gray-200);
  border-radius: var(--border-radius-lg);
  cursor: pointer;
  transition: var(--transition);
}

.mode-option:hover {
  border-color: var(--color-gray-400);
}

.mode-option-selected {
  border-color: var(--color-black);
  background-color: var(--color-gray-100);
}

.mode-option-disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.mode-option-disabled:hover {
  border-color: var(--color-gray-200);
}

.mode-radio {
  width: 20px;
  height: 20px;
  border: 2px solid var(--color-gray-300);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 2px;
}

.mode-option-selected .mode-radio {
  border-color: var(--color-black);
}

.mode-radio-inner {
  width: 10px;
  height: 10px;
  background-color: var(--color-black);
  border-radius: 50%;
}

.mode-icon {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--border-radius);
  flex-shrink: 0;
}

.mode-icon.local {
  background-color: var(--color-gray-200);
  color: var(--color-gray-700);
}

.mode-icon.cloud {
  background-color: #dbeafe;
  color: #1e40af;
}

.mode-content {
  flex: 1;
}

.mode-content h3 {
  font-size: 1rem;
  margin-bottom: var(--spacing-xs);
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
}

.mode-badge {
  font-size: 0.6875rem;
  font-weight: var(--font-weight-medium);
  padding: 2px 8px;
  background-color: #fef3c7;
  color: #d97706;
  border-radius: 100px;
}

.mode-content p {
  font-size: 0.875rem;
  color: var(--color-gray-600);
  margin-bottom: var(--spacing-sm);
}

.mode-features {
  list-style: none;
  padding: 0;
  margin: 0;
  font-size: 0.8125rem;
  color: var(--color-gray-500);
}

.mode-features li {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
}

.mode-features li::before {
  content: "•";
  color: var(--color-gray-400);
}

/* Loading */
.loading-state {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
  color: var(--color-gray-500);
}

.spinner {
  width: 20px;
  height: 20px;
  border: 2px solid var(--color-gray-200);
  border-top-color: var(--color-black);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Messages */
.message {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  padding: var(--spacing-sm) var(--spacing-md);
  border-radius: var(--border-radius);
  margin-bottom: var(--spacing-md);
  font-size: 0.875rem;
}

.message-error {
  background-color: #fee2e2;
  color: #991b1b;
}

.message-success {
  background-color: #dcfce7;
  color: #166534;
}

/* Current Key */
.current-key {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--spacing-md);
  background-color: var(--color-gray-100);
  border-radius: var(--border-radius);
  margin-bottom: var(--spacing-lg);
}

.key-info {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  flex-wrap: wrap;
}

.key-label {
  font-size: 0.875rem;
  color: var(--color-gray-600);
}

.key-prefix {
  font-family: monospace;
  font-size: 0.875rem;
  background-color: var(--color-white);
  padding: 2px 8px;
  border-radius: var(--border-radius);
}

.key-status {
  font-size: 0.75rem;
  font-weight: var(--font-weight-medium);
  padding: 2px 8px;
  border-radius: 100px;
}

.status-valid {
  background-color: #dcfce7;
  color: #166534;
}

.status-invalid {
  background-color: #fee2e2;
  color: #991b1b;
}

.key-source {
  font-size: 0.75rem;
  color: var(--color-gray-500);
  font-style: italic;
}

/* Form */
.api-key-form label {
  display: block;
  font-size: 0.875rem;
  font-weight: var(--font-weight-medium);
  margin-bottom: var(--spacing-sm);
}

.input-group {
  display: flex;
  gap: var(--spacing-sm);
}

.input-group input {
  flex: 1;
  padding: var(--spacing-sm) var(--spacing-md);
  border: 1px solid var(--color-gray-300);
  border-radius: var(--border-radius);
  font-family: var(--font-family);
  font-size: 0.875rem;
}

.input-group input:focus {
  outline: none;
  border-color: var(--color-black);
}

.input-hint {
  margin-top: var(--spacing-sm);
  font-size: 0.8125rem;
  color: var(--color-gray-500);
}

.input-hint a {
  color: var(--color-black);
  text-decoration: underline;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.input-hint a:hover {
  color: var(--color-gray-700);
}

/* Info Box */
.info-box {
  display: flex;
  gap: var(--spacing-md);
  padding: var(--spacing-lg);
  background-color: #f0f9ff;
  border: 1px solid #bfdbfe;
  border-radius: var(--border-radius-lg);
}

.info-icon {
  color: #1e40af;
  flex-shrink: 0;
}

.info-content h3 {
  font-size: 0.875rem;
  font-weight: var(--font-weight-semibold);
  margin-bottom: var(--spacing-xs);
  color: #1e40af;
}

.info-content p {
  font-size: 0.8125rem;
  color: #1e40af;
  line-height: 1.5;
}

.info-content strong {
  font-weight: var(--font-weight-semibold);
}

/* Button variants */
.btn-danger {
  background-color: #ef4444;
  color: white;
  border-color: #ef4444;
}

.btn-danger:hover {
  background-color: #dc2626;
  border-color: #dc2626;
}

.btn-sm {
  padding: var(--spacing-xs) var(--spacing-md);
  font-size: 0.8125rem;
}
</style>
