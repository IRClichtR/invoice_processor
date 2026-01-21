<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { listInvoices, deleteInvoice as apiDeleteInvoice, type InvoiceResponse, ApiException } from '../api';

interface InvoiceRecord {
  id: number;
  invoiceNumber: string;
  vendor: string;
  clientName: string;
  date: string;
  dueDate: string;
  amount: number;
  taxAmount: number;
  totalAmount: number;
  currency: string;
  status: 'imported';
  importedAt: string;
  selected: boolean;
}

const emit = defineEmits<{
  (e: 'back'): void;
  (e: 'view-invoice', id: number): void;
}>();

const invoices = ref<InvoiceRecord[]>([]);
const isLoading = ref(true);
const loadError = ref<string | null>(null);
const isDeleting = ref(false);

// Convert API response to page format
function convertInvoice(inv: InvoiceResponse): InvoiceRecord {
  // Calculate tax amount from totals
  const totalHT = inv.total_without_vat || 0;
  const totalTTC = inv.total_with_vat || 0;
  const taxAmount = totalTTC - totalHT;

  return {
    id: inv.id,
    invoiceNumber: inv.invoice_number || `#${inv.id}`,
    vendor: inv.provider || 'Unknown vendor',
    clientName: '',
    date: inv.date || '',
    dueDate: '',
    amount: totalHT,
    taxAmount: taxAmount > 0 ? taxAmount : 0,
    totalAmount: totalTTC,
    currency: inv.currency || 'EUR',
    status: 'imported',
    importedAt: inv.created_at || '',
    selected: false,
  };
}

async function fetchInvoices() {
  isLoading.value = true;
  loadError.value = null;

  try {
    const response = await listInvoices(0, 100);
    invoices.value = response.map(convertInvoice);
  } catch (error) {
    if (error instanceof ApiException) {
      loadError.value = error.detail;
    } else {
      loadError.value = 'Failed to load invoices';
    }
    console.error('Failed to fetch invoices:', error);
  } finally {
    isLoading.value = false;
  }
}

onMounted(() => {
  fetchInvoices();
});

const searchQuery = ref('');
const sortBy = ref<'date' | 'vendor' | 'amount'>('date');
const sortOrder = ref<'asc' | 'desc'>('desc');

const filteredInvoices = computed(() => {
  let result = [...invoices.value];

  // Search filter
  if (searchQuery.value) {
    const query = searchQuery.value.toLowerCase();
    result = result.filter(inv =>
      inv.invoiceNumber.toLowerCase().includes(query) ||
      inv.vendor.toLowerCase().includes(query)
    );
  }

  // Sort
  result.sort((a, b) => {
    let comparison = 0;
    switch (sortBy.value) {
      case 'date':
        comparison = new Date(a.date || '1970-01-01').getTime() - new Date(b.date || '1970-01-01').getTime();
        break;
      case 'vendor':
        comparison = a.vendor.localeCompare(b.vendor);
        break;
      case 'amount':
        comparison = a.totalAmount - b.totalAmount;
        break;
    }
    return sortOrder.value === 'asc' ? comparison : -comparison;
  });

  return result;
});

const selectedCount = computed(() => invoices.value.filter(inv => inv.selected).length);

const selectedTotal = computed(() => {
  return invoices.value
    .filter(inv => inv.selected)
    .reduce((sum, inv) => sum + inv.totalAmount, 0);
});

const allFilteredSelected = computed(() => {
  return filteredInvoices.value.length > 0 && filteredInvoices.value.every(inv => inv.selected);
});

const stats = computed(() => {
  const total = invoices.value.length;
  const totalAmount = invoices.value.reduce((sum, inv) => sum + inv.totalAmount, 0);
  const totalHT = invoices.value.reduce((sum, inv) => sum + inv.amount, 0);

  return { total, totalAmount, totalHT };
});

function toggleSelectAll() {
  const newValue = !allFilteredSelected.value;
  filteredInvoices.value.forEach(inv => {
    inv.selected = newValue;
  });
}

function clearSelection() {
  invoices.value.forEach(inv => inv.selected = false);
}

function toggleSort(field: 'date' | 'vendor' | 'amount') {
  if (sortBy.value === field) {
    sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc';
  } else {
    sortBy.value = field;
    sortOrder.value = 'desc';
  }
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric'
  });
}

function formatDateTime(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  });
}

function getStatusLabel(status: string): string {
  switch (status) {
    case 'imported': return 'Imported';
    case 'paid': return 'Paid';
    case 'pending': return 'Pending';
    case 'overdue': return 'Overdue';
    default: return status;
  }
}

async function handleDeleteInvoice(id: number) {
  if (!confirm('Are you sure you want to delete this invoice?')) {
    return;
  }

  isDeleting.value = true;
  try {
    await apiDeleteInvoice(id);
    invoices.value = invoices.value.filter(inv => inv.id !== id);
  } catch (error) {
    const message = error instanceof ApiException ? error.detail : 'Error deleting invoice';
    alert(message);
    console.error('Failed to delete invoice:', error);
  } finally {
    isDeleting.value = false;
  }
}

function exportToCsv() {
  const invoicesToExport = invoices.value.filter(inv => inv.selected);

  if (invoicesToExport.length === 0) {
    alert('Please select at least one invoice to export.');
    return;
  }

  const headers = ['Invoice #', 'Vendor', 'Date', 'Amount (excl. VAT)', 'VAT', 'Total Amount', 'Currency'];
  const rows = invoicesToExport.map(inv => [
    inv.invoiceNumber,
    `"${inv.vendor}"`,
    inv.date,
    inv.amount.toFixed(2),
    inv.taxAmount.toFixed(2),
    inv.totalAmount.toFixed(2),
    inv.currency,
  ]);

  const csv = [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `invoices_export_${new Date().toISOString().split('T')[0]}.csv`;
  a.click();
  URL.revokeObjectURL(url);

  // Clear selection after export
  clearSelection();
}
</script>

<template>
  <div class="invoices-page">
    <!-- Header -->
    <header class="header">
      <div class="container header-content">
        <div class="logo">
          <img src="../assets/invoicator_logo.png" alt="Invoicator" />
          <span class="logo-text">Invoicator</span>
        </div>
        <button class="btn btn-secondary" @click="emit('back')">Back to Home</button>
      </div>
    </header>

    <!-- Main Content -->
    <main class="page-content">
      <div class="container">
        <!-- Page Header -->
        <div class="page-header">
          <div class="page-title">
            <h1>Invoices Database</h1>
            <p>View and manage all imported invoices</p>
          </div>
        </div>

        <!-- Stats Cards -->
        <div class="stats-grid stats-grid-3">
          <div class="stat-card">
            <div class="stat-icon">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                <polyline points="14 2 14 8 20 8"></polyline>
              </svg>
            </div>
            <div class="stat-info">
              <span class="stat-value">{{ stats.total }}</span>
              <span class="stat-label">Total Invoices</span>
            </div>
          </div>
          <div class="stat-card stat-amount">
            <div class="stat-icon">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="12" y1="1" x2="12" y2="23"></line>
                <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path>
              </svg>
            </div>
            <div class="stat-info">
              <span class="stat-value">{{ stats.totalHT.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 }) }}</span>
              <span class="stat-label">Total (excl. VAT)</span>
            </div>
          </div>
          <div class="stat-card stat-paid">
            <div class="stat-icon">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                <polyline points="22 4 12 14.01 9 11.01"></polyline>
              </svg>
            </div>
            <div class="stat-info">
              <span class="stat-value">{{ stats.totalAmount.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 }) }}</span>
              <span class="stat-label">Total (incl. VAT)</span>
            </div>
          </div>
        </div>

        <!-- Filters -->
        <div class="filters-bar">
          <div class="search-box">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="11" cy="11" r="8"></circle>
              <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
            </svg>
            <input
              type="text"
              v-model="searchQuery"
              placeholder="Search by invoice # or vendor..."
            />
          </div>
          <button class="btn btn-secondary btn-sm" @click="fetchInvoices" :disabled="isLoading">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="23 4 23 10 17 10"></polyline>
              <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
            </svg>
            Refresh
          </button>
          <div class="results-count">
            {{ filteredInvoices.length }} invoice(s)
          </div>
        </div>

        <!-- Selection Bar -->
        <transition name="slide">
          <div v-if="selectedCount > 0" class="selection-bar">
            <div class="selection-info">
              <span class="selection-count">{{ selectedCount }} invoice(s) selected</span>
              <span class="selection-total">
                Total: {{ selectedTotal.toLocaleString('en-US', { minimumFractionDigits: 2 }) }} EUR
              </span>
            </div>
            <div class="selection-actions">
              <button class="btn btn-secondary btn-sm" @click="clearSelection">
                Clear Selection
              </button>
              <button class="btn btn-primary btn-sm" @click="exportToCsv">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                  <polyline points="7 10 12 15 17 10"></polyline>
                  <line x1="12" y1="15" x2="12" y2="3"></line>
                </svg>
                Export {{ selectedCount }} to CSV
              </button>
            </div>
          </div>
        </transition>

        <!-- Loading State -->
        <div v-if="isLoading" class="loading-state">
          <div class="spinner"></div>
          <p>Loading invoices...</p>
        </div>

        <!-- Error State -->
        <div v-else-if="loadError" class="error-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="8" x2="12" y2="12"></line>
            <line x1="12" y1="16" x2="12.01" y2="16"></line>
          </svg>
          <p>{{ loadError }}</p>
          <button class="btn btn-primary" @click="fetchInvoices">Retry</button>
        </div>

        <!-- Invoices Table -->
        <div v-else class="table-container">
          <table class="data-table">
            <thead>
              <tr>
                <th class="col-checkbox">
                  <input
                    type="checkbox"
                    :checked="allFilteredSelected"
                    @change="toggleSelectAll"
                    title="Select all"
                  />
                </th>
                <th class="col-invoice">Invoice #</th>
                <th class="col-vendor sortable" @click="toggleSort('vendor')">
                  Vendor
                  <span v-if="sortBy === 'vendor'" class="sort-icon">{{ sortOrder === 'asc' ? '↑' : '↓' }}</span>
                </th>
                <th class="col-date sortable" @click="toggleSort('date')">
                  Date
                  <span v-if="sortBy === 'date'" class="sort-icon">{{ sortOrder === 'asc' ? '↑' : '↓' }}</span>
                </th>
                <th class="col-amount sortable" @click="toggleSort('amount')">
                  Total Amount
                  <span v-if="sortBy === 'amount'" class="sort-icon">{{ sortOrder === 'asc' ? '↑' : '↓' }}</span>
                </th>
                <th class="col-imported">Imported</th>
                <th class="col-actions"></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="invoice in filteredInvoices"
                :key="invoice.id"
                :class="{ 'row-selected': invoice.selected }"
              >
                <td class="col-checkbox" @click.stop>
                  <input type="checkbox" v-model="invoice.selected" />
                </td>
                <td class="col-invoice">
                  <span class="invoice-number">{{ invoice.invoiceNumber }}</span>
                </td>
                <td class="col-vendor">{{ invoice.vendor }}</td>
                <td class="col-date">{{ formatDate(invoice.date) }}</td>
                <td class="col-amount">
                  {{ invoice.totalAmount.toLocaleString('en-US', { minimumFractionDigits: 2 }) }}
                  <span class="currency">{{ invoice.currency }}</span>
                </td>
                <td class="col-imported">
                  <span class="imported-date">{{ formatDateTime(invoice.importedAt) }}</span>
                </td>
                <td class="col-actions">
                  <div class="action-buttons">
                    <button class="btn-icon" @click="emit('view-invoice', invoice.id)" title="View details">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                        <circle cx="12" cy="12" r="3"></circle>
                      </svg>
                    </button>
                    <button
                      class="btn-icon btn-icon-danger"
                      @click="handleDeleteInvoice(invoice.id)"
                      title="Delete"
                      :disabled="isDeleting"
                    >
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6"></polyline>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                      </svg>
                    </button>
                  </div>
                </td>
              </tr>
              <tr v-if="filteredInvoices.length === 0">
                <td colspan="7" class="empty-state">
                  <div class="empty-content">
                    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                      <polyline points="14 2 14 8 20 8"></polyline>
                    </svg>
                    <p>No invoices found</p>
                    <span>{{ searchQuery ? 'Try a different search' : 'Import invoices from the home page' }}</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Help Text -->
        <p class="help-text">
          Select invoices using the checkboxes, then click "Export to CSV" to download.
        </p>
      </div>
    </main>
  </div>
</template>

<style scoped>
.invoices-page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background-color: var(--color-gray-100);
}

.page-content {
  flex: 1;
  padding: var(--spacing-xl) 0;
}

/* Page Header */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--spacing-xl);
  flex-wrap: wrap;
  gap: var(--spacing-md);
}

.page-title h1 {
  font-size: 1.5rem;
  margin-bottom: var(--spacing-xs);
}

.page-title p {
  color: var(--color-gray-500);
  font-size: 0.875rem;
}

.page-header .btn {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
}

/* Stats Grid */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: var(--spacing-md);
  margin-bottom: var(--spacing-xl);
}

.stat-card {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
  padding: var(--spacing-lg);
  background-color: var(--color-white);
  border: 1px solid var(--color-gray-200);
  border-radius: var(--border-radius-lg);
}

.stat-icon {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: var(--color-gray-100);
  border-radius: var(--border-radius);
  color: var(--color-gray-600);
}

.stat-paid .stat-icon {
  background-color: #dcfce7;
  color: #166534;
}

.stat-pending .stat-icon {
  background-color: #fef9c3;
  color: #854d0e;
}

.stat-overdue .stat-icon {
  background-color: #fee2e2;
  color: #991b1b;
}

.stat-amount .stat-icon {
  background-color: #dbeafe;
  color: #1e40af;
}

.stat-info {
  display: flex;
  flex-direction: column;
}

.stat-value {
  font-size: 1.25rem;
  font-weight: var(--font-weight-bold);
  color: var(--color-black);
}

.stat-label {
  font-size: 0.75rem;
  color: var(--color-gray-500);
}

/* Filters Bar */
.filters-bar {
  display: flex;
  align-items: center;
  gap: var(--spacing-lg);
  margin-bottom: var(--spacing-md);
  padding: var(--spacing-md) var(--spacing-lg);
  background-color: var(--color-white);
  border: 1px solid var(--color-gray-200);
  border-radius: var(--border-radius-lg);
}

.search-box {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  flex: 1;
  max-width: 400px;
  padding: var(--spacing-sm) var(--spacing-md);
  background-color: var(--color-gray-100);
  border-radius: var(--border-radius);
  color: var(--color-gray-500);
}

.search-box input {
  flex: 1;
  border: none;
  background: transparent;
  font-family: var(--font-family);
  font-size: 0.875rem;
  outline: none;
}

.filter-group {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
}

.filter-group label {
  font-size: 0.8125rem;
  color: var(--color-gray-600);
}

.filter-group select {
  padding: var(--spacing-sm) var(--spacing-md);
  border: 1px solid var(--color-gray-300);
  border-radius: var(--border-radius);
  font-family: var(--font-family);
  font-size: 0.8125rem;
  background-color: var(--color-white);
  cursor: pointer;
}

.results-count {
  margin-left: auto;
  font-size: 0.8125rem;
  color: var(--color-gray-500);
}

/* Selection Bar */
.selection-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-lg);
  margin-bottom: var(--spacing-md);
  padding: var(--spacing-md) var(--spacing-lg);
  background-color: var(--color-black);
  color: var(--color-white);
  border-radius: var(--border-radius-lg);
}

.selection-info {
  display: flex;
  align-items: center;
  gap: var(--spacing-lg);
}

.selection-count {
  font-weight: var(--font-weight-semibold);
}

.selection-total {
  font-size: 0.875rem;
  opacity: 0.8;
}

.selection-actions {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
}

.btn-sm {
  padding: var(--spacing-sm) var(--spacing-md);
  font-size: 0.8125rem;
}

.selection-bar .btn-secondary {
  background-color: transparent;
  border-color: var(--color-white);
  color: var(--color-white);
}

.selection-bar .btn-secondary:hover {
  background-color: rgba(255, 255, 255, 0.1);
}

.selection-bar .btn-primary {
  background-color: var(--color-white);
  color: var(--color-black);
  border-color: var(--color-white);
}

.selection-bar .btn-primary:hover {
  background-color: var(--color-gray-200);
}

/* Slide Transition */
.slide-enter-active,
.slide-leave-active {
  transition: all 0.3s ease;
}

.slide-enter-from,
.slide-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

/* Table */
.table-container {
  overflow-x: auto;
  background-color: var(--color-white);
  border: 1px solid var(--color-gray-200);
  border-radius: var(--border-radius-lg);
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8125rem;
}

.data-table th,
.data-table td {
  padding: var(--spacing-md);
  text-align: left;
  border-bottom: 1px solid var(--color-gray-200);
}

.data-table th {
  background-color: var(--color-gray-100);
  font-weight: var(--font-weight-semibold);
  color: var(--color-gray-700);
  font-size: 0.6875rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.data-table th.sortable {
  cursor: pointer;
  user-select: none;
}

.data-table th.sortable:hover {
  background-color: var(--color-gray-200);
}

.sort-icon {
  margin-left: 4px;
  font-size: 0.75rem;
}

.data-table tbody tr:hover {
  background-color: var(--color-gray-50, #fafafa);
}

.data-table tbody tr.row-selected {
  background-color: #f0f9ff;
}

.data-table tbody tr.row-selected:hover {
  background-color: #e0f2fe;
}

.data-table tbody tr:last-child td {
  border-bottom: none;
}

/* Column widths */
.col-checkbox { width: 40px; text-align: center; }
.col-invoice { min-width: 130px; }
.col-vendor { min-width: 150px; }
.col-date { width: 100px; }
.col-due { width: 100px; }
.col-amount { width: 120px; text-align: right; }
.col-status { width: 90px; }
.col-imported { width: 130px; }
.col-actions { width: 80px; text-align: center; }

.col-amount {
  text-align: right;
}

.invoice-number {
  font-family: monospace;
  font-weight: var(--font-weight-medium);
}

.currency {
  font-size: 0.6875rem;
  color: var(--color-gray-500);
  margin-left: 4px;
}

.imported-date {
  font-size: 0.75rem;
  color: var(--color-gray-500);
}

/* Checkbox styling */
input[type="checkbox"] {
  width: 16px;
  height: 16px;
  cursor: pointer;
  accent-color: var(--color-black);
}

/* Status badges */
.status-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 100px;
  font-size: 0.6875rem;
  font-weight: var(--font-weight-medium);
}

.status-paid {
  background-color: #dcfce7;
  color: #166534;
}

.status-pending {
  background-color: #fef9c3;
  color: #854d0e;
}

.status-overdue {
  background-color: #fee2e2;
  color: #991b1b;
}

/* Action Buttons */
.action-buttons {
  display: flex;
  justify-content: center;
  gap: var(--spacing-xs);
}

.btn-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  background: transparent;
  border: 1px solid var(--color-gray-300);
  border-radius: var(--border-radius);
  color: var(--color-gray-500);
  cursor: pointer;
  transition: var(--transition);
}

.btn-icon:hover {
  background-color: var(--color-gray-100);
  border-color: var(--color-gray-400);
  color: var(--color-black);
}

.btn-icon-danger:hover {
  background-color: #fee2e2;
  border-color: #ef4444;
  color: #dc2626;
}

/* Empty State */
.empty-state {
  padding: var(--spacing-3xl) !important;
}

.empty-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-md);
  color: var(--color-gray-400);
}

.empty-content p {
  font-size: 1rem;
  font-weight: var(--font-weight-medium);
  color: var(--color-gray-600);
  margin: 0;
}

.empty-content span {
  font-size: 0.875rem;
}

/* Help Text */
.help-text {
  font-size: 0.8125rem;
  color: var(--color-gray-400);
  margin-top: var(--spacing-md);
  text-align: center;
}

/* Responsive */
@media (max-width: 1200px) {
  .stats-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 900px) {
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .filters-bar {
    flex-wrap: wrap;
  }

  .search-box {
    width: 100%;
    max-width: none;
  }

  .selection-bar {
    flex-direction: column;
    gap: var(--spacing-md);
  }

  .selection-info,
  .selection-actions {
    width: 100%;
    justify-content: center;
  }
}

@media (max-width: 600px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }

  .page-header {
    flex-direction: column;
    align-items: flex-start;
  }
}

/* Loading and Error States */
.loading-state,
.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--spacing-3xl);
  background-color: var(--color-white);
  border: 1px solid var(--color-gray-200);
  border-radius: var(--border-radius-lg);
  gap: var(--spacing-md);
}

.loading-state p,
.error-state p {
  color: var(--color-gray-600);
  margin: 0;
}

.error-state svg {
  color: var(--color-gray-400);
}

.spinner {
  width: 40px;
  height: 40px;
  border: 4px solid var(--color-gray-200);
  border-top-color: var(--color-black);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.stats-grid-3 {
  grid-template-columns: repeat(3, 1fr);
}

@media (max-width: 900px) {
  .stats-grid-3 {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 600px) {
  .stats-grid-3 {
    grid-template-columns: 1fr;
  }
}

.btn-sm {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
}
</style>
