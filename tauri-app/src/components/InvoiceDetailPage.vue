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
import { ref, computed, onMounted, watch } from 'vue';
import {
  getInvoice,
  updateInvoice,
  getInvoiceDocumentUrl,
  type InvoiceResponse,
  type InvoiceUpdate,
  ApiException
} from '../api';

interface EditableLine {
  id: number | null;
  designation: string;
  quantity: number | null;
  unit_price: number | null;
  total_ht: number | null;
  _delete: boolean;
}

const props = defineProps<{
  invoiceId: number;
}>();

const emit = defineEmits<{
  (e: 'back'): void;
  (e: 'saved'): void;
  (e: 'home'): void;
}>();

// State
const invoice = ref<InvoiceResponse | null>(null);
const isLoading = ref(true);
const isSaving = ref(false);
const loadError = ref<string | null>(null);
const saveError = ref<string | null>(null);
const saveSuccess = ref(false);

// Editable fields
const editProvider = ref('');
const editDate = ref('');
const editInvoiceNumber = ref('');
const editCurrency = ref('EUR');
const editTotalWithoutVat = ref<number | null>(null);
const editTotalWithVat = ref<number | null>(null);
const editLines = ref<EditableLine[]>([]);

// Document
const documentUrl = ref<string | null>(null);
const documentError = ref(false);

// Track changes
const hasChanges = computed(() => {
  if (!invoice.value) return false;

  if (editProvider.value !== (invoice.value.provider || '')) return true;
  if (editDate.value !== (invoice.value.date || '')) return true;
  if (editInvoiceNumber.value !== (invoice.value.invoice_number || '')) return true;
  if (editCurrency.value !== (invoice.value.currency || 'EUR')) return true;
  if (editTotalWithoutVat.value !== invoice.value.total_without_vat) return true;
  if (editTotalWithVat.value !== invoice.value.total_with_vat) return true;

  // Check line items
  const originalLines = invoice.value.lines || [];
  const currentLines = editLines.value.filter(l => !l._delete);

  if (currentLines.length !== originalLines.length) return true;

  for (let i = 0; i < originalLines.length; i++) {
    const orig = originalLines[i];
    const curr = currentLines.find(l => l.id === orig.id);
    if (!curr) return true;
    if (curr.designation !== (orig.designation || '')) return true;
    if (curr.quantity !== orig.quantity) return true;
    if (curr.unit_price !== orig.unit_price) return true;
    if (curr.total_ht !== orig.total_ht) return true;
  }

  // Check for new lines
  if (editLines.value.some(l => l.id === null && !l._delete)) return true;

  return false;
});

async function loadInvoice() {
  isLoading.value = true;
  loadError.value = null;

  try {
    const response = await getInvoice(props.invoiceId);
    invoice.value = response;

    // Initialize editable fields
    editProvider.value = response.provider || '';
    editDate.value = response.date || '';
    editInvoiceNumber.value = response.invoice_number || '';
    editCurrency.value = response.currency || 'EUR';
    editTotalWithoutVat.value = response.total_without_vat;
    editTotalWithVat.value = response.total_with_vat;

    // Initialize line items
    editLines.value = (response.lines || []).map(line => ({
      id: line.id,
      designation: line.designation || '',
      quantity: line.quantity,
      unit_price: line.unit_price,
      total_ht: line.total_ht,
      _delete: false
    }));

    // Set document URL if available
    if (response.has_document) {
      documentUrl.value = getInvoiceDocumentUrl(response.id);
    }

  } catch (error) {
    if (error instanceof ApiException) {
      loadError.value = error.detail;
    } else {
      loadError.value = 'Failed to load invoice';
    }
    console.error('Failed to load invoice:', error);
  } finally {
    isLoading.value = false;
  }
}

async function handleSave() {
  if (!invoice.value) return;

  isSaving.value = true;
  saveError.value = null;
  saveSuccess.value = false;

  try {
    // Build update data
    const updateData: InvoiceUpdate = {
      provider: editProvider.value || null,
      date: editDate.value || null,
      invoice_number: editInvoiceNumber.value || null,
      currency: editCurrency.value || 'EUR',
      total_without_vat: editTotalWithoutVat.value,
      total_with_vat: editTotalWithVat.value,
      lines: editLines.value.map(line => ({
        id: line.id,
        designation: line.designation || null,
        quantity: line.quantity,
        unit_price: line.unit_price,
        total_ht: line.total_ht,
        _delete: line._delete
      }))
    };

    const response = await updateInvoice(props.invoiceId, updateData);
    invoice.value = response;

    // Reinitialize editable fields from response
    editProvider.value = response.provider || '';
    editDate.value = response.date || '';
    editInvoiceNumber.value = response.invoice_number || '';
    editCurrency.value = response.currency || 'EUR';
    editTotalWithoutVat.value = response.total_without_vat;
    editTotalWithVat.value = response.total_with_vat;

    // Reinitialize line items (removing deleted ones)
    editLines.value = (response.lines || []).map(line => ({
      id: line.id,
      designation: line.designation || '',
      quantity: line.quantity,
      unit_price: line.unit_price,
      total_ht: line.total_ht,
      _delete: false
    }));

    saveSuccess.value = true;
    setTimeout(() => { saveSuccess.value = false; }, 3000);

  } catch (error) {
    if (error instanceof ApiException) {
      saveError.value = error.detail;
    } else {
      saveError.value = 'Failed to save invoice';
    }
    console.error('Failed to save invoice:', error);
  } finally {
    isSaving.value = false;
  }
}

function handleBack() {
  if (hasChanges.value) {
    if (!confirm('You have unsaved changes. Are you sure you want to leave?')) {
      return;
    }
  }
  emit('back');
}

function addLineItem() {
  editLines.value.push({
    id: null,
    designation: '',
    quantity: 1,
    unit_price: 0,
    total_ht: 0,
    _delete: false
  });
}

function removeLineItem(index: number) {
  const line = editLines.value[index];
  if (line.id) {
    // Mark existing line for deletion
    line._delete = true;
  } else {
    // Remove new line entirely
    editLines.value.splice(index, 1);
  }
}

function updateLineTotal(line: EditableLine) {
  if (line.quantity != null && line.unit_price != null) {
    line.total_ht = Math.round(line.quantity * line.unit_price * 100) / 100;
  }
}

function handleDocumentError() {
  documentError.value = true;
}

function isPdf(url: string | null): boolean {
  if (!url) return false;
  // The backend returns the original filename, check if it's a PDF
  return invoice.value?.original_filename?.toLowerCase().endsWith('.pdf') || false;
}

onMounted(() => {
  loadInvoice();
});

// Reload if invoice ID changes
watch(() => props.invoiceId, () => {
  loadInvoice();
});
</script>

<template>
  <div class="detail-page">
    <!-- Header -->
    <header class="header">
      <div class="container header-content">
        <div class="logo clickable" @click="emit('home')">
          <img src="../assets/invoicator_logo.png" alt="Invoicator" />
          <span class="logo-text">Invoicator</span>
        </div>
        <div class="header-actions">
          <button class="btn btn-secondary" @click="handleBack">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="19" y1="12" x2="5" y2="12"></line>
              <polyline points="12 19 5 12 12 5"></polyline>
            </svg>
            Back to List
          </button>
          <a href="https://ko-fi.com/W7W41T13JM" target="_blank" class="donate-btn">
            <img alt="Support me on Ko-fi" src="https://storage.ko-fi.com/cdn/kofi2.png?v=3" height="36" />
          </a>
        </div>
      </div>
    </header>

    <!-- Main Content -->
    <main class="detail-content">
      <div class="container">
        <!-- Loading State -->
        <div v-if="isLoading" class="loading-state">
          <div class="spinner"></div>
          <p>Loading invoice...</p>
        </div>

        <!-- Error State -->
        <div v-else-if="loadError" class="error-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="8" x2="12" y2="12"></line>
            <line x1="12" y1="16" x2="12.01" y2="16"></line>
          </svg>
          <p>{{ loadError }}</p>
          <button class="btn btn-primary" @click="loadInvoice">Retry</button>
        </div>

        <!-- Invoice Detail -->
        <div v-else-if="invoice" class="split-view">
          <!-- Document Viewer -->
          <div class="document-panel">
            <div class="panel-header">
              <h2>Original Document</h2>
              <span v-if="invoice.original_filename" class="filename">{{ invoice.original_filename }}</span>
            </div>
            <div class="document-viewer">
              <template v-if="documentUrl && !documentError">
                <iframe
                  v-if="isPdf(documentUrl)"
                  :src="documentUrl"
                  class="pdf-viewer"
                  frameborder="0"
                  @error="handleDocumentError"
                ></iframe>
                <img
                  v-else
                  :src="documentUrl"
                  alt="Invoice document"
                  class="image-viewer"
                  @error="handleDocumentError"
                />
              </template>
              <div v-else class="no-document">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                  <polyline points="14 2 14 8 20 8"></polyline>
                </svg>
                <p>No document available</p>
                <span v-if="documentError">Document could not be loaded</span>
              </div>
            </div>
          </div>

          <!-- Edit Panel -->
          <div class="edit-panel">
            <div class="panel-header">
              <h2>Invoice Details</h2>
              <div class="header-badges">
                <span v-if="hasChanges" class="badge badge-warning">Unsaved changes</span>
                <span v-if="saveSuccess" class="badge badge-success">Saved!</span>
              </div>
            </div>

            <div class="edit-content">
              <!-- Save Error -->
              <div v-if="saveError" class="save-error">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="12" cy="12" r="10"></circle>
                  <line x1="15" y1="9" x2="9" y2="15"></line>
                  <line x1="9" y1="9" x2="15" y2="15"></line>
                </svg>
                {{ saveError }}
              </div>

              <!-- Invoice Info Section -->
              <div class="edit-section">
                <div class="section-header">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                    <polyline points="14 2 14 8 20 8"></polyline>
                  </svg>
                  <span>Invoice Information</span>
                </div>
                <div class="form-grid">
                  <div class="form-group">
                    <label>Invoice Number</label>
                    <input type="text" v-model="editInvoiceNumber" placeholder="e.g., INV-001" />
                  </div>
                  <div class="form-group">
                    <label>Currency</label>
                    <select v-model="editCurrency">
                      <optgroup label="Major Currencies">
                        <option value="EUR">EUR - Euro</option>
                        <option value="USD">USD - US Dollar</option>
                        <option value="GBP">GBP - British Pound</option>
                        <option value="CHF">CHF - Swiss Franc</option>
                        <option value="JPY">JPY - Japanese Yen</option>
                        <option value="CNY">CNY - Chinese Yuan</option>
                        <option value="CAD">CAD - Canadian Dollar</option>
                        <option value="AUD">AUD - Australian Dollar</option>
                      </optgroup>
                      <optgroup label="Africa">
                        <option value="DZD">DZD - Algerian Dinar</option>
                        <option value="AOA">AOA - Angolan Kwanza</option>
                        <option value="BWP">BWP - Botswanan Pula</option>
                        <option value="BIF">BIF - Burundian Franc</option>
                        <option value="CVE">CVE - Cape Verdean Escudo</option>
                        <option value="XAF">XAF - Central African CFA Franc</option>
                        <option value="KMF">KMF - Comorian Franc</option>
                        <option value="CDF">CDF - Congolese Franc</option>
                        <option value="DJF">DJF - Djiboutian Franc</option>
                        <option value="EGP">EGP - Egyptian Pound</option>
                        <option value="ERN">ERN - Eritrean Nakfa</option>
                        <option value="SZL">SZL - Eswatini Lilangeni</option>
                        <option value="ETB">ETB - Ethiopian Birr</option>
                        <option value="GMD">GMD - Gambian Dalasi</option>
                        <option value="GHS">GHS - Ghanaian Cedi</option>
                        <option value="GNF">GNF - Guinean Franc</option>
                        <option value="KES">KES - Kenyan Shilling</option>
                        <option value="LSL">LSL - Lesotho Loti</option>
                        <option value="LRD">LRD - Liberian Dollar</option>
                        <option value="LYD">LYD - Libyan Dinar</option>
                        <option value="MGA">MGA - Malagasy Ariary</option>
                        <option value="MWK">MWK - Malawian Kwacha</option>
                        <option value="MRU">MRU - Mauritanian Ouguiya</option>
                        <option value="MUR">MUR - Mauritian Rupee</option>
                        <option value="MAD">MAD - Moroccan Dirham</option>
                        <option value="MZN">MZN - Mozambican Metical</option>
                        <option value="NAD">NAD - Namibian Dollar</option>
                        <option value="NGN">NGN - Nigerian Naira</option>
                        <option value="RWF">RWF - Rwandan Franc</option>
                        <option value="STN">STN - São Tomé Dobra</option>
                        <option value="SCR">SCR - Seychellois Rupee</option>
                        <option value="SLE">SLE - Sierra Leonean Leone</option>
                        <option value="SOS">SOS - Somali Shilling</option>
                        <option value="ZAR">ZAR - South African Rand</option>
                        <option value="SSP">SSP - South Sudanese Pound</option>
                        <option value="SDG">SDG - Sudanese Pound</option>
                        <option value="TZS">TZS - Tanzanian Shilling</option>
                        <option value="TND">TND - Tunisian Dinar</option>
                        <option value="UGX">UGX - Ugandan Shilling</option>
                        <option value="XOF">XOF - West African CFA Franc</option>
                        <option value="ZMW">ZMW - Zambian Kwacha</option>
                        <option value="ZWL">ZWL - Zimbabwean Dollar</option>
                      </optgroup>
                      <optgroup label="Asia">
                        <option value="AFN">AFN - Afghan Afghani</option>
                        <option value="AMD">AMD - Armenian Dram</option>
                        <option value="AZN">AZN - Azerbaijani Manat</option>
                        <option value="BHD">BHD - Bahraini Dinar</option>
                        <option value="BDT">BDT - Bangladeshi Taka</option>
                        <option value="BTN">BTN - Bhutanese Ngultrum</option>
                        <option value="BND">BND - Brunei Dollar</option>
                        <option value="KHR">KHR - Cambodian Riel</option>
                        <option value="GEL">GEL - Georgian Lari</option>
                        <option value="HKD">HKD - Hong Kong Dollar</option>
                        <option value="INR">INR - Indian Rupee</option>
                        <option value="IDR">IDR - Indonesian Rupiah</option>
                        <option value="IRR">IRR - Iranian Rial</option>
                        <option value="IQD">IQD - Iraqi Dinar</option>
                        <option value="ILS">ILS - Israeli Shekel</option>
                        <option value="JOD">JOD - Jordanian Dinar</option>
                        <option value="KZT">KZT - Kazakhstani Tenge</option>
                        <option value="KWD">KWD - Kuwaiti Dinar</option>
                        <option value="KGS">KGS - Kyrgyzstani Som</option>
                        <option value="LAK">LAK - Lao Kip</option>
                        <option value="LBP">LBP - Lebanese Pound</option>
                        <option value="MOP">MOP - Macanese Pataca</option>
                        <option value="MYR">MYR - Malaysian Ringgit</option>
                        <option value="MVR">MVR - Maldivian Rufiyaa</option>
                        <option value="MNT">MNT - Mongolian Tugrik</option>
                        <option value="MMK">MMK - Myanmar Kyat</option>
                        <option value="NPR">NPR - Nepalese Rupee</option>
                        <option value="KPW">KPW - North Korean Won</option>
                        <option value="OMR">OMR - Omani Rial</option>
                        <option value="PKR">PKR - Pakistani Rupee</option>
                        <option value="PHP">PHP - Philippine Peso</option>
                        <option value="QAR">QAR - Qatari Riyal</option>
                        <option value="SAR">SAR - Saudi Riyal</option>
                        <option value="SGD">SGD - Singapore Dollar</option>
                        <option value="KRW">KRW - South Korean Won</option>
                        <option value="LKR">LKR - Sri Lankan Rupee</option>
                        <option value="SYP">SYP - Syrian Pound</option>
                        <option value="TWD">TWD - Taiwan Dollar</option>
                        <option value="TJS">TJS - Tajikistani Somoni</option>
                        <option value="THB">THB - Thai Baht</option>
                        <option value="TRY">TRY - Turkish Lira</option>
                        <option value="TMT">TMT - Turkmenistani Manat</option>
                        <option value="AED">AED - UAE Dirham</option>
                        <option value="UZS">UZS - Uzbekistani Som</option>
                        <option value="VND">VND - Vietnamese Dong</option>
                        <option value="YER">YER - Yemeni Rial</option>
                      </optgroup>
                      <optgroup label="Americas">
                        <option value="ARS">ARS - Argentine Peso</option>
                        <option value="AWG">AWG - Aruban Florin</option>
                        <option value="BSD">BSD - Bahamian Dollar</option>
                        <option value="BBD">BBD - Barbadian Dollar</option>
                        <option value="BZD">BZD - Belize Dollar</option>
                        <option value="BMD">BMD - Bermudian Dollar</option>
                        <option value="BOB">BOB - Bolivian Boliviano</option>
                        <option value="BRL">BRL - Brazilian Real</option>
                        <option value="KYD">KYD - Cayman Islands Dollar</option>
                        <option value="CLP">CLP - Chilean Peso</option>
                        <option value="COP">COP - Colombian Peso</option>
                        <option value="CRC">CRC - Costa Rican Colón</option>
                        <option value="CUP">CUP - Cuban Peso</option>
                        <option value="DOP">DOP - Dominican Peso</option>
                        <option value="XCD">XCD - East Caribbean Dollar</option>
                        <option value="SVC">SVC - Salvadoran Colón</option>
                        <option value="FKP">FKP - Falkland Islands Pound</option>
                        <option value="GTQ">GTQ - Guatemalan Quetzal</option>
                        <option value="GYD">GYD - Guyanese Dollar</option>
                        <option value="HTG">HTG - Haitian Gourde</option>
                        <option value="HNL">HNL - Honduran Lempira</option>
                        <option value="JMD">JMD - Jamaican Dollar</option>
                        <option value="MXN">MXN - Mexican Peso</option>
                        <option value="ANG">ANG - Netherlands Antillean Guilder</option>
                        <option value="NIO">NIO - Nicaraguan Córdoba</option>
                        <option value="PAB">PAB - Panamanian Balboa</option>
                        <option value="PYG">PYG - Paraguayan Guaraní</option>
                        <option value="PEN">PEN - Peruvian Sol</option>
                        <option value="SRD">SRD - Surinamese Dollar</option>
                        <option value="TTD">TTD - Trinidad Dollar</option>
                        <option value="UYU">UYU - Uruguayan Peso</option>
                        <option value="VES">VES - Venezuelan Bolívar</option>
                      </optgroup>
                      <optgroup label="Europe">
                        <option value="ALL">ALL - Albanian Lek</option>
                        <option value="BYN">BYN - Belarusian Ruble</option>
                        <option value="BAM">BAM - Bosnia-Herzegovina Mark</option>
                        <option value="BGN">BGN - Bulgarian Lev</option>
                        <option value="HRK">HRK - Croatian Kuna</option>
                        <option value="CZK">CZK - Czech Koruna</option>
                        <option value="DKK">DKK - Danish Krone</option>
                        <option value="HUF">HUF - Hungarian Forint</option>
                        <option value="ISK">ISK - Icelandic Króna</option>
                        <option value="MDL">MDL - Moldovan Leu</option>
                        <option value="MKD">MKD - Macedonian Denar</option>
                        <option value="NOK">NOK - Norwegian Krone</option>
                        <option value="PLN">PLN - Polish Zloty</option>
                        <option value="RON">RON - Romanian Leu</option>
                        <option value="RUB">RUB - Russian Ruble</option>
                        <option value="RSD">RSD - Serbian Dinar</option>
                        <option value="SEK">SEK - Swedish Krona</option>
                        <option value="UAH">UAH - Ukrainian Hryvnia</option>
                      </optgroup>
                      <optgroup label="Oceania">
                        <option value="FJD">FJD - Fijian Dollar</option>
                        <option value="NZD">NZD - New Zealand Dollar</option>
                        <option value="PGK">PGK - Papua New Guinean Kina</option>
                        <option value="WST">WST - Samoan Tala</option>
                        <option value="SBD">SBD - Solomon Islands Dollar</option>
                        <option value="TOP">TOP - Tongan Pa'anga</option>
                        <option value="VUV">VUV - Vanuatu Vatu</option>
                        <option value="XPF">XPF - CFP Franc</option>
                      </optgroup>
                    </select>
                  </div>
                  <div class="form-group">
                    <label>Invoice Date</label>
                    <input type="date" v-model="editDate" />
                  </div>
                </div>
              </div>

              <!-- Vendor Section -->
              <div class="edit-section">
                <div class="section-header">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
                    <polyline points="9 22 9 12 15 12 15 22"></polyline>
                  </svg>
                  <span>Vendor</span>
                </div>
                <div class="form-grid">
                  <div class="form-group full-width">
                    <label>Vendor Name</label>
                    <input type="text" v-model="editProvider" placeholder="Enter vendor name" />
                  </div>
                </div>
              </div>

              <!-- Line Items Section -->
              <div class="edit-section">
                <div class="section-header">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="8" y1="6" x2="21" y2="6"></line>
                    <line x1="8" y1="12" x2="21" y2="12"></line>
                    <line x1="8" y1="18" x2="21" y2="18"></line>
                    <line x1="3" y1="6" x2="3.01" y2="6"></line>
                    <line x1="3" y1="12" x2="3.01" y2="12"></line>
                    <line x1="3" y1="18" x2="3.01" y2="18"></line>
                  </svg>
                  <span>Line Items</span>
                  <button class="btn-add" @click="addLineItem">+ Add Item</button>
                </div>
                <div class="line-items-table">
                  <table>
                    <thead>
                      <tr>
                        <th>Description</th>
                        <th>Qty</th>
                        <th>Unit Price</th>
                        <th>Total</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      <template v-for="(line, index) in editLines" :key="line.id || `new-${index}`">
                        <tr v-if="!line._delete" :class="{ 'new-line': line.id === null }">
                          <td>
                            <input
                              type="text"
                              v-model="line.designation"
                              class="input-description"
                              placeholder="Item description"
                            />
                          </td>
                          <td>
                            <input
                              type="number"
                              v-model.number="line.quantity"
                              min="0"
                              step="0.01"
                              class="input-number"
                              @change="updateLineTotal(line)"
                            />
                          </td>
                          <td>
                            <input
                              type="number"
                              v-model.number="line.unit_price"
                              min="0"
                              step="0.01"
                              class="input-number"
                              @change="updateLineTotal(line)"
                            />
                          </td>
                          <td>
                            <input
                              type="number"
                              v-model.number="line.total_ht"
                              min="0"
                              step="0.01"
                              class="input-number"
                            />
                          </td>
                          <td>
                            <button
                              class="btn-icon btn-icon-small"
                              @click="removeLineItem(index)"
                              title="Remove"
                            >
                              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <line x1="18" y1="6" x2="6" y2="18"></line>
                                <line x1="6" y1="6" x2="18" y2="18"></line>
                              </svg>
                            </button>
                          </td>
                        </tr>
                      </template>
                      <tr v-if="editLines.filter(l => !l._delete).length === 0">
                        <td colspan="5" class="empty-items">
                          No line items. Click "+ Add Item" to add.
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>

              <!-- Totals Section -->
              <div class="edit-section totals-section">
                <div class="section-header">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="12" y1="1" x2="12" y2="23"></line>
                    <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path>
                  </svg>
                  <span>Totals</span>
                </div>
                <div class="form-grid totals-grid">
                  <div class="form-group">
                    <label>Total (excl. VAT)</label>
                    <div class="input-with-currency">
                      <input type="number" v-model.number="editTotalWithoutVat" step="0.01" />
                      <span class="currency-suffix">{{ editCurrency }}</span>
                    </div>
                  </div>
                  <div class="form-group">
                    <label>Total (incl. VAT)</label>
                    <div class="input-with-currency">
                      <input type="number" v-model.number="editTotalWithVat" step="0.01" class="total-input" />
                      <span class="currency-suffix">{{ editCurrency }}</span>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Action Buttons -->
              <div class="action-bar">
                <button class="btn btn-secondary" @click="handleBack">
                  Cancel
                </button>
                <button
                  class="btn btn-primary"
                  @click="handleSave"
                  :disabled="isSaving || !hasChanges"
                >
                  <span v-if="isSaving">Saving...</span>
                  <span v-else>Save Changes</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
.detail-page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background-color: var(--color-gray-100);
}

.detail-content {
  flex: 1;
  padding: var(--spacing-xl) 0;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
}

.header-actions .btn {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
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

/* Split View */
.split-view {
  display: flex;
  gap: var(--spacing-lg);
  height: calc(100vh - 180px);
}

/* Document Panel */
.document-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  background-color: var(--color-white);
  border: 1px solid var(--color-gray-200);
  border-radius: var(--border-radius-lg);
  overflow: hidden;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--spacing-md) var(--spacing-lg);
  border-bottom: 1px solid var(--color-gray-200);
  background-color: var(--color-gray-50);
}

.panel-header h2 {
  font-size: 1rem;
  margin: 0;
}

.filename {
  font-size: 0.75rem;
  color: var(--color-gray-500);
  font-family: monospace;
}

.header-badges {
  display: flex;
  gap: var(--spacing-sm);
}

.badge {
  padding: 2px 8px;
  border-radius: 100px;
  font-size: 0.6875rem;
  font-weight: var(--font-weight-medium);
}

.badge-warning {
  background-color: #fef9c3;
  color: #854d0e;
}

.badge-success {
  background-color: #dcfce7;
  color: #166534;
}

.document-viewer {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: var(--color-gray-100);
  overflow: auto;
}

.pdf-viewer {
  width: 100%;
  height: 100%;
  border: none;
}

.image-viewer {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

.no-document {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-md);
  color: var(--color-gray-400);
  text-align: center;
}

.no-document p {
  font-size: 1rem;
  font-weight: var(--font-weight-medium);
  color: var(--color-gray-600);
  margin: 0;
}

.no-document span {
  font-size: 0.875rem;
}

/* Edit Panel */
.edit-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  background-color: var(--color-white);
  border: 1px solid var(--color-gray-200);
  border-radius: var(--border-radius-lg);
  overflow: hidden;
}

.edit-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--spacing-lg);
}

.save-error {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  padding: var(--spacing-sm) var(--spacing-md);
  background-color: #fee2e2;
  color: #991b1b;
  border-radius: var(--border-radius);
  margin-bottom: var(--spacing-md);
  font-size: 0.875rem;
}

/* Edit Sections */
.edit-section {
  background-color: var(--color-gray-50);
  border: 1px solid var(--color-gray-200);
  border-radius: var(--border-radius);
  padding: var(--spacing-md);
  margin-bottom: var(--spacing-md);
}

.section-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  font-size: 0.75rem;
  font-weight: var(--font-weight-semibold);
  color: var(--color-gray-700);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: var(--spacing-md);
}

.section-header svg {
  color: var(--color-gray-500);
}

.btn-add {
  margin-left: auto;
  padding: 4px 12px;
  background-color: var(--color-black);
  color: var(--color-white);
  border: none;
  border-radius: var(--border-radius);
  font-size: 0.75rem;
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: var(--transition);
}

.btn-add:hover {
  background-color: var(--color-gray-800);
}

/* Form Grid */
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--spacing-md);
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.form-group.full-width {
  grid-column: 1 / -1;
}

.form-group label {
  font-size: 0.6875rem;
  font-weight: var(--font-weight-medium);
  color: var(--color-gray-500);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.form-group input,
.form-group select {
  padding: var(--spacing-sm);
  border: 1px solid var(--color-gray-300);
  border-radius: var(--border-radius);
  font-family: var(--font-family);
  font-size: 0.875rem;
  transition: var(--transition);
  background-color: var(--color-white);
}

.form-group input:focus,
.form-group select:focus {
  outline: none;
  border-color: var(--color-black);
}

/* Line Items Table */
.line-items-table {
  overflow-x: auto;
}

.line-items-table table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8125rem;
}

.line-items-table th,
.line-items-table td {
  padding: var(--spacing-sm);
  text-align: left;
  border-bottom: 1px solid var(--color-gray-200);
}

.line-items-table th {
  font-size: 0.6875rem;
  font-weight: var(--font-weight-medium);
  color: var(--color-gray-500);
  text-transform: uppercase;
}

.line-items-table tbody tr:last-child td {
  border-bottom: none;
}

.new-line {
  background-color: #f0f9ff;
}

.input-description {
  width: 100%;
  min-width: 150px;
  padding: 4px 8px;
  border: 1px solid var(--color-gray-300);
  border-radius: var(--border-radius);
  font-size: 0.8125rem;
}

.input-number {
  width: 80px;
  padding: 4px 8px;
  border: 1px solid var(--color-gray-300);
  border-radius: var(--border-radius);
  font-size: 0.8125rem;
  text-align: right;
}

.empty-items {
  text-align: center;
  color: var(--color-gray-400);
  font-style: italic;
  padding: var(--spacing-lg) !important;
}

/* Totals Section */
.totals-section {
  background-color: var(--color-white);
}

.totals-grid {
  grid-template-columns: 1fr 1fr;
}

.total-input {
  font-weight: var(--font-weight-bold);
}

.input-with-currency {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
}

.input-with-currency input {
  flex: 1;
}

.currency-suffix {
  font-size: 0.75rem;
  font-weight: var(--font-weight-medium);
  color: var(--color-gray-500);
  min-width: 32px;
}

/* Buttons */
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
  background-color: #fee2e2;
  border-color: #ef4444;
  color: #dc2626;
}

.btn-icon-small {
  width: 24px;
  height: 24px;
}

/* Action Bar */
.action-bar {
  display: flex;
  justify-content: flex-end;
  gap: var(--spacing-md);
  padding-top: var(--spacing-lg);
  border-top: 1px solid var(--color-gray-200);
  margin-top: var(--spacing-md);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Responsive */
@media (max-width: 1024px) {
  .split-view {
    flex-direction: column;
    height: auto;
  }

  .document-panel,
  .edit-panel {
    flex: none;
  }

  .document-panel {
    height: 400px;
  }
}

@media (max-width: 768px) {
  .form-grid {
    grid-template-columns: 1fr;
  }

  .totals-grid {
    grid-template-columns: 1fr;
  }
}
</style>
