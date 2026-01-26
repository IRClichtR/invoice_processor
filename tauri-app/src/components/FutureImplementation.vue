<script setup lang="ts">
defineProps<{
  feature: string;
}>();

const emit = defineEmits<{
  (e: 'back'): void;
}>();
</script>

<template>
  <div class="future-page">
    <header class="header">
      <div class="container header-content">
        <div class="logo clickable" @click="emit('back')">
          <img src="../assets/invoicator_logo.png" alt="Invoicator" />
          <span class="logo-text">Invoicator</span>
        </div>
        <button class="btn btn-secondary" @click="emit('back')">Back</button>
        <a href="https://liberapay.com/IRClichtR/donate" target="_blank" class="donate-btn">
          <img alt="Donate using Liberapay" src="https://liberapay.com/assets/widgets/donate.svg" />
        </a>
      </div>
    </header>

    <main class="future-content">
      <div class="container">
        <div class="future-card">
          <div class="icon">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"></circle>
              <polyline points="12 6 12 12 16 14"></polyline>
            </svg>
          </div>
          <h1>Coming Soon</h1>
          <h2>{{ feature }}</h2>
          <p>
            This feature is currently under development.
            We're working hard to bring you the best experience possible.
          </p>
          <button class="btn btn-primary" @click="emit('back')">
            Return to Home
          </button>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
.future-page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.future-content {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--spacing-2xl) 0;
}

.future-card {
  text-align: center;
  max-width: 500px;
  padding: var(--spacing-3xl);
  background-color: var(--color-gray-100);
  border: 1px solid var(--color-gray-200);
  border-radius: var(--border-radius-lg);
}

.future-card .icon {
  width: 80px;
  height: 80px;
  margin: 0 auto var(--spacing-xl);
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: var(--color-black);
  color: var(--color-white);
  border-radius: 50%;
}

.future-card h1 {
  font-size: 2rem;
  margin-bottom: var(--spacing-sm);
}

.future-card h2 {
  font-size: 1.25rem;
  color: var(--color-gray-500);
  font-weight: var(--font-weight-medium);
  margin-bottom: var(--spacing-lg);
}

.future-card p {
  margin-bottom: var(--spacing-xl);
  line-height: 1.7;
}
</style>
