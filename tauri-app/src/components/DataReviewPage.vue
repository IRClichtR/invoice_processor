<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import { updateInvoice, getJobImageUrl, cleanupJob, type FileProcessingResult, type InvoiceUpdate } from '../api';

interface LineItem {
  description: string;
  quantity: number;
  unitPrice: number;
  total: number;
}

interface InvoiceData {
  id: string;
  fileName: string;
  jobId?: string;  // Job ID for accessing preview image
  invoiceNumber: string;
  vendor: string;
  vendorAddress: string;
  vendorEmail: string;
  vendorPhone: string;
  clientName: string;
  clientAddress: string;
  date: string;
  dueDate: string;
  amount: number;
  taxAmount: number;
  totalAmount: number;
  currency: string;
  paymentTerms: string;
  notes: string;
  lineItems: LineItem[];
  status: 'valid' | 'warning' | 'error';
  selected: boolean;
  invoiceId?: number;  // ID from backend if saved
  isOtherDocument?: boolean;
}

const props = defineProps<{
  processingResults?: FileProcessingResult[];
}>();

const emit = defineEmits<{
  (e: 'back'): void;
  (e: 'confirm'): void;
}>();

// Convert API results to page format
function convertResults(results: FileProcessingResult[]): InvoiceData[] {
  return results.map((result, index) => {
    const extracted = result.processing?.extracted_data;
    const analysis = result.analysis;

    // Determine status
    let status: 'valid' | 'warning' | 'error' = 'valid';
    if (!result.success || result.error) {
      status = 'error';
    } else if (!extracted?.provider || !extracted?.total_ttc) {
      status = 'warning';
    }

    // Map line items
    const lineItems: LineItem[] = (extracted?.line_items || []).map(item => ({
      description: item.designation || '',
      quantity: item.quantity || 1,
      unitPrice: item.unit_price || 0,
      total: item.total_ht || 0,
    }));

    return {
      id: String(index + 1),
      fileName: result.filename,
      jobId: analysis?.job_id,
      invoiceNumber: extracted?.invoice_number || '',
      vendor: extracted?.provider || 'Unknown vendor',
      vendorAddress: '',
      vendorEmail: '',
      vendorPhone: '',
      clientName: '',
      clientAddress: '',
      date: extracted?.date || '',
      dueDate: '',
      amount: extracted?.total_ht || 0,
      taxAmount: extracted?.vat_amount || 0,
      totalAmount: extracted?.total_ttc || 0,
      currency: extracted?.currency || 'EUR',
      paymentTerms: '',
      notes: result.error || (analysis?.is_handwritten ? 'Handwritten document detected' : ''),
      lineItems,
      status,
      selected: result.success && extracted?.is_invoice !== false,
      invoiceId: result.processing?.invoice_id || undefined,
      isOtherDocument: extracted?.is_invoice === false,
    };
  });
}

const invoices = ref<InvoiceData[]>([]);
const isSaving = ref(false);
const saveError = ref<string | null>(null);

// Initialize from props
watch(() => props.processingResults, (newResults) => {
  if (newResults && newResults.length > 0) {
    invoices.value = convertResults(newResults);
  }
}, { immediate: true });

const selectedInvoiceId = ref<string | null>(null);

const selectedInvoice = computed(() => {
  if (!selectedInvoiceId.value) return null;
  return invoices.value.find(inv => inv.id === selectedInvoiceId.value) || null;
});

const selectedCount = computed(() => invoices.value.filter(inv => inv.selected).length);
const totalAmount = computed(() => {
  return invoices.value
    .filter(inv => inv.selected)
    .reduce((sum, inv) => sum + inv.totalAmount, 0);
});

const selectedCurrency = computed(() => {
  const selected = invoices.value.filter(inv => inv.selected);
  if (selected.length === 0) return 'EUR';
  const currencies = [...new Set(selected.map(inv => inv.currency))];
  return currencies.length === 1 ? currencies[0] : 'Mixed';
});

const selectedImageUrl = computed(() => {
  if (!selectedInvoice.value?.jobId) return null;
  return getJobImageUrl(selectedInvoice.value.jobId, 0);
});

function selectInvoice(id: string) {
  selectedInvoiceId.value = id;
}

function closeDetail() {
  selectedInvoiceId.value = null;
}

function toggleSelectAll() {
  const allSelected = invoices.value.every(inv => inv.selected);
  invoices.value.forEach(inv => inv.selected = !allSelected);
}

function updateInvoiceStatus(invoice: InvoiceData) {
  if (invoice.invoiceNumber && invoice.vendor && invoice.totalAmount > 0) {
    invoice.status = 'valid';
  } else if (invoice.invoiceNumber || invoice.vendor) {
    invoice.status = 'warning';
  } else {
    invoice.status = 'error';
  }
}

function addLineItem() {
  if (selectedInvoice.value) {
    selectedInvoice.value.lineItems.push({
      description: '',
      quantity: 1,
      unitPrice: 0,
      total: 0
    });
  }
}

function removeLineItem(index: number) {
  if (selectedInvoice.value) {
    selectedInvoice.value.lineItems.splice(index, 1);
    recalculateTotals();
  }
}

function updateLineItemTotal(item: LineItem) {
  item.total = item.quantity * item.unitPrice;
  recalculateTotals();
}

function recalculateTotals() {
  if (selectedInvoice.value) {
    const subtotal = selectedInvoice.value.lineItems.reduce((sum, item) => sum + item.total, 0);
    selectedInvoice.value.amount = subtotal;
    selectedInvoice.value.totalAmount = subtotal + selectedInvoice.value.taxAmount;
    updateInvoiceStatus(selectedInvoice.value);
  }
}

function removeInvoice(id: string) {
  invoices.value = invoices.value.filter(inv => inv.id !== id);
  if (selectedInvoiceId.value === id) {
    selectedInvoiceId.value = null;
  }
}

async function confirmAndSave() {
  const selectedInvoices = invoices.value.filter(inv => inv.selected);
  const invoicesToUpdate = selectedInvoices.filter(inv => inv.invoiceId && !inv.isOtherDocument);

  // Collect all job IDs for cleanup
  const jobIds = [...new Set(invoices.value.map(inv => inv.jobId).filter(Boolean))] as string[];

  if (invoicesToUpdate.length === 0) {
    // Clean up temp files even if nothing to update
    for (const jobId of jobIds) {
      try {
        await cleanupJob(jobId);
      } catch (e) {
        console.warn('Failed to cleanup job:', jobId, e);
      }
    }
    emit('confirm');
    return;
  }

  isSaving.value = true;
  saveError.value = null;

  try {
    // Update each invoice with the modified data
    for (const invoice of invoicesToUpdate) {
      const updateData: InvoiceUpdate = {
        provider: invoice.vendor || null,
        date: invoice.date || null,
        invoice_number: invoice.invoiceNumber || null,
        currency: invoice.currency || 'EUR',
        total_without_vat: invoice.amount,
        total_with_vat: invoice.totalAmount,
        lines: invoice.lineItems.map(line => ({
          id: null, // New lines from review don't have IDs
          designation: line.description || null,
          quantity: line.quantity,
          unit_price: line.unitPrice,
          total_ht: line.total,
        }))
      };

      await updateInvoice(invoice.invoiceId!, updateData);
    }

    // Clean up temp files after successful save
    for (const jobId of jobIds) {
      try {
        await cleanupJob(jobId);
      } catch (e) {
        console.warn('Failed to cleanup job:', jobId, e);
      }
    }

    emit('confirm');
  } catch (error) {
    console.error('Failed to save invoice updates:', error);
    saveError.value = error instanceof Error ? error.message : 'Failed to save changes';
  } finally {
    isSaving.value = false;
  }
}

function getStatusLabel(status: string): string {
  switch (status) {
    case 'valid': return 'Ready';
    case 'warning': return 'Review needed';
    case 'error': return 'Incomplete';
    default: return status;
  }
}
</script>

<template>
  <div class="review-page">
    <!-- Header -->
    <header class="header">
      <div class="container header-content">
        <div class="logo clickable" @click="emit('back')">
          <img src="../assets/invoicator_logo.png" alt="Invoicator" />
          <span class="logo-text">Invoicator</span>
        </div>
        <button class="btn btn-secondary" @click="emit('back')">Cancel</button>
          <a href="https://liberapay.com/IRClichtR/donate" target="_blank" class="donate-btn">
            <img alt="Donate using Liberapay" src="https://liberapay.com/assets/widgets/donate.svg" />
          </a>
      </div>
    </header>

    <!-- Main Content -->
    <main class="review-content">
      <div class="container">
        <!-- Page Header -->
        <div class="page-header">
          <div class="page-title">
            <h1>Review Extracted Data</h1>
            <p>Click on a row to view and edit all invoice details</p>
          </div>
          <div class="page-stats">
            <div class="stat">
              <span class="stat-value">{{ invoices.length }}</span>
              <span class="stat-label">Documents</span>
            </div>
            <div class="stat">
              <span class="stat-value">{{ selectedCount }}</span>
              <span class="stat-label">Selected</span>
            </div>
            <div class="stat">
              <span class="stat-value">{{ totalAmount.toLocaleString('en-US', { minimumFractionDigits: 2 }) }} <span class="stat-currency">{{ selectedCurrency }}</span></span>
              <span class="stat-label">Total Amount</span>
            </div>
          </div>
        </div>

        <!-- Split View Container -->
        <div class="split-view" :class="{ 'detail-open': selectedInvoiceId }">
          <!-- Invoice List -->
          <div class="invoice-list">
            <div class="table-container">
              <table class="data-table">
                <thead>
                  <tr>
                    <th class="col-checkbox">
                      <input
                        type="checkbox"
                        :checked="invoices.every(inv => inv.selected)"
                        @change="toggleSelectAll"
                        @click.stop
                      />
                    </th>
                    <th class="col-status">Status</th>
                    <th class="col-file">File</th>
                    <th class="col-vendor">Vendor</th>
                    <th class="col-amount">Amount</th>
                    <th class="col-actions"></th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="invoice in invoices"
                    :key="invoice.id"
                    :class="{
                      'row-disabled': !invoice.selected,
                      'row-selected': selectedInvoiceId === invoice.id
                    }"
                    @click="selectInvoice(invoice.id)"
                  >
                    <td class="col-checkbox" @click.stop>
                      <input type="checkbox" v-model="invoice.selected" />
                    </td>
                    <td class="col-status">
                      <span :class="['status-badge', `status-${invoice.status}`]">
                        {{ getStatusLabel(invoice.status) }}
                      </span>
                    </td>
                    <td class="col-file">
                      <span class="file-name">{{ invoice.fileName }}</span>
                    </td>
                    <td class="col-vendor">{{ invoice.vendor }}</td>
                    <td class="col-amount">
                      {{ invoice.totalAmount.toLocaleString('en-US', { minimumFractionDigits: 2 }) }} {{ invoice.currency }}
                    </td>
                    <td class="col-actions" @click.stop>
                      <button class="btn-icon btn-icon-danger" @click="removeInvoice(invoice.id)" title="Remove">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                          <polyline points="3 6 5 6 21 6"></polyline>
                          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                        </svg>
                      </button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Detail Panel -->
          <div v-if="selectedInvoice" class="detail-panel">
            <div class="detail-header">
              <h2>Invoice Details</h2>
              <button class="btn-icon" @click="closeDetail" title="Close">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18"></line>
                  <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
              </button>
            </div>

            <!-- Document Preview -->
            <div v-if="selectedImageUrl" class="document-preview">
              <img :src="selectedImageUrl" alt="Invoice preview" @error="(e) => (e.target as HTMLImageElement).style.display = 'none'" />
            </div>

            <div class="detail-content">
              <!-- File Info -->
              <div class="detail-section">
                <div class="section-header">
                  <span class="section-icon">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                      <polyline points="14 2 14 8 20 8"></polyline>
                    </svg>
                  </span>
                  <span>Source File</span>
                </div>
                <p class="file-info">{{ selectedInvoice.fileName }}</p>
              </div>

              <!-- Invoice Info -->
              <div class="detail-section">
                <div class="section-header">
                  <span class="section-icon">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
                      <line x1="16" y1="2" x2="16" y2="6"></line>
                      <line x1="8" y1="2" x2="8" y2="6"></line>
                      <line x1="3" y1="10" x2="21" y2="10"></line>
                    </svg>
                  </span>
                  <span>Invoice Information</span>
                </div>
                <div class="form-grid">
                  <div class="form-group">
                    <label>Invoice Number</label>
                    <input type="text" v-model="selectedInvoice.invoiceNumber" @change="updateInvoiceStatus(selectedInvoice)" />
                  </div>
                  <div class="form-group">
                    <label>Currency</label>
                    <select v-model="selectedInvoice.currency">
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
                    <input type="date" v-model="selectedInvoice.date" />
                  </div>
                  <div class="form-group">
                    <label>Due Date</label>
                    <input type="date" v-model="selectedInvoice.dueDate" />
                  </div>
                  <div class="form-group">
                    <label>Payment Terms</label>
                    <input type="text" v-model="selectedInvoice.paymentTerms" />
                  </div>
                </div>
              </div>

              <!-- Vendor Info -->
              <div class="detail-section">
                <div class="section-header">
                  <span class="section-icon">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
                      <polyline points="9 22 9 12 15 12 15 22"></polyline>
                    </svg>
                  </span>
                  <span>Vendor</span>
                </div>
                <div class="form-grid">
                  <div class="form-group full-width">
                    <label>Vendor Name</label>
                    <input type="text" v-model="selectedInvoice.vendor" @change="updateInvoiceStatus(selectedInvoice)" />
                  </div>
                  <div class="form-group full-width">
                    <label>Address</label>
                    <input type="text" v-model="selectedInvoice.vendorAddress" />
                  </div>
                  <div class="form-group">
                    <label>Email</label>
                    <input type="email" v-model="selectedInvoice.vendorEmail" />
                  </div>
                  <div class="form-group">
                    <label>Phone</label>
                    <input type="tel" v-model="selectedInvoice.vendorPhone" />
                  </div>
                </div>
              </div>

              <!-- Client Info -->
              <div class="detail-section">
                <div class="section-header">
                  <span class="section-icon">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                      <circle cx="12" cy="7" r="4"></circle>
                    </svg>
                  </span>
                  <span>Client</span>
                </div>
                <div class="form-grid">
                  <div class="form-group full-width">
                    <label>Client Name</label>
                    <input type="text" v-model="selectedInvoice.clientName" />
                  </div>
                  <div class="form-group full-width">
                    <label>Client Address</label>
                    <input type="text" v-model="selectedInvoice.clientAddress" />
                  </div>
                </div>
              </div>

              <!-- Line Items -->
              <div class="detail-section">
                <div class="section-header">
                  <span class="section-icon">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <line x1="8" y1="6" x2="21" y2="6"></line>
                      <line x1="8" y1="12" x2="21" y2="12"></line>
                      <line x1="8" y1="18" x2="21" y2="18"></line>
                      <line x1="3" y1="6" x2="3.01" y2="6"></line>
                      <line x1="3" y1="12" x2="3.01" y2="12"></line>
                      <line x1="3" y1="18" x2="3.01" y2="18"></line>
                    </svg>
                  </span>
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
                      <tr v-for="(item, index) in selectedInvoice.lineItems" :key="index">
                        <td>
                          <input type="text" v-model="item.description" class="input-description" />
                        </td>
                        <td>
                          <input
                            type="number"
                            v-model.number="item.quantity"
                            min="0"
                            class="input-number"
                            @change="updateLineItemTotal(item)"
                          />
                        </td>
                        <td>
                          <input
                            type="number"
                            v-model.number="item.unitPrice"
                            min="0"
                            step="0.01"
                            class="input-number"
                            @change="updateLineItemTotal(item)"
                          />
                        </td>
                        <td class="cell-total">
                          {{ item.total.toLocaleString('en-US', { minimumFractionDigits: 2 }) }}
                        </td>
                        <td>
                          <button class="btn-icon btn-icon-small" @click="removeLineItem(index)" title="Remove">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                              <line x1="18" y1="6" x2="6" y2="18"></line>
                              <line x1="6" y1="6" x2="18" y2="18"></line>
                            </svg>
                          </button>
                        </td>
                      </tr>
                      <tr v-if="selectedInvoice.lineItems.length === 0">
                        <td colspan="5" class="empty-items">No line items. Click "+ Add Item" to add.</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>

              <!-- Totals -->
              <div class="detail-section totals-section">
                <div class="form-grid">
                  <div class="form-group">
                    <label>Subtotal</label>
                    <input
                      type="number"
                      v-model.number="selectedInvoice.amount"
                      step="0.01"
                      @change="updateInvoiceStatus(selectedInvoice)"
                    />
                  </div>
                  <div class="form-group">
                    <label>Tax Amount</label>
                    <input
                      type="number"
                      v-model.number="selectedInvoice.taxAmount"
                      step="0.01"
                      @change="recalculateTotals"
                    />
                  </div>
                  <div class="form-group total-field">
                    <label>Total Amount</label>
                    <input
                      type="number"
                      v-model.number="selectedInvoice.totalAmount"
                      step="0.01"
                      @change="updateInvoiceStatus(selectedInvoice)"
                    />
                  </div>
                </div>
              </div>

              <!-- Notes -->
              <div class="detail-section">
                <div class="section-header">
                  <span class="section-icon">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                    </svg>
                  </span>
                  <span>Notes</span>
                </div>
                <textarea v-model="selectedInvoice.notes" rows="3" placeholder="Add notes..."></textarea>
              </div>
            </div>
          </div>
        </div>

        <!-- Save Error -->
        <div v-if="saveError" class="save-error">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="15" y1="9" x2="9" y2="15"></line>
            <line x1="9" y1="9" x2="15" y2="15"></line>
          </svg>
          {{ saveError }}
        </div>

        <!-- Action Buttons -->
        <div class="action-bar">
          <button class="btn btn-secondary" @click="emit('back')" :disabled="isSaving">
            Cancel
          </button>
          <button
            class="btn btn-primary"
            @click="confirmAndSave"
            :disabled="selectedCount === 0 || isSaving"
          >
            <span v-if="isSaving">Saving...</span>
            <span v-else>Save {{ selectedCount }} Invoice(s) to Database</span>
          </button>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
.review-page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background-color: var(--color-white);
}

.review-content {
  flex: 1;
  padding: var(--spacing-xl) 0;
}

/* Page Header */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--spacing-xl);
  flex-wrap: wrap;
  gap: var(--spacing-lg);
}

.page-title h1 {
  font-size: 1.5rem;
  margin-bottom: var(--spacing-xs);
}

.page-title p {
  color: var(--color-gray-500);
  font-size: 0.875rem;
}

.page-stats {
  display: flex;
  gap: var(--spacing-md);
}

.stat {
  text-align: center;
  padding: var(--spacing-sm) var(--spacing-md);
  background-color: var(--color-gray-100);
  border-radius: var(--border-radius);
}

.stat-value {
  display: block;
  font-size: 1.25rem;
  font-weight: var(--font-weight-bold);
  color: var(--color-black);
}

.stat-label {
  font-size: 0.6875rem;
  color: var(--color-gray-500);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.stat-currency {
  font-size: 0.75rem;
  font-weight: var(--font-weight-medium);
  color: var(--color-gray-500);
}

/* Split View */
.split-view {
  display: flex;
  gap: var(--spacing-lg);
  margin-bottom: var(--spacing-lg);
}

.invoice-list {
  flex: 1;
  min-width: 0;
  transition: all 0.3s ease;
}

.detail-open .invoice-list {
  flex: 0 0 45%;
}

/* Table */
.table-container {
  overflow-x: auto;
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
  padding: var(--spacing-sm) var(--spacing-md);
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

.data-table tbody tr {
  cursor: pointer;
  transition: var(--transition);
}

.data-table tbody tr:hover {
  background-color: var(--color-gray-100);
}

.data-table tbody tr:last-child td {
  border-bottom: none;
}

.row-disabled {
  opacity: 0.5;
}

.row-selected {
  background-color: var(--color-gray-100);
  border-left: 3px solid var(--color-black);
}

.row-selected:hover {
  background-color: var(--color-gray-200);
}

/* Column widths */
.col-checkbox { width: 36px; text-align: center; }
.col-status { width: 80px; }
.col-file { min-width: 140px; }
.col-vendor { min-width: 120px; }
.col-amount { width: 100px; text-align: right; }
.col-actions { width: 40px; text-align: center; }

/* Status badges */
.status-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 100px;
  font-size: 0.6875rem;
  font-weight: var(--font-weight-medium);
}

.status-valid {
  background-color: #dcfce7;
  color: #166534;
}

.status-warning {
  background-color: #fef9c3;
  color: #854d0e;
}

.status-error {
  background-color: #fee2e2;
  color: #991b1b;
}

/* File name */
.file-name {
  font-family: monospace;
  font-size: 0.75rem;
  color: var(--color-gray-600);
}

/* Detail Panel */
.detail-panel {
  flex: 0 0 55%;
  background-color: var(--color-gray-100);
  border: 1px solid var(--color-gray-200);
  border-radius: var(--border-radius-lg);
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 280px);
  overflow: hidden;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--spacing-md) var(--spacing-lg);
  border-bottom: 1px solid var(--color-gray-200);
  background-color: var(--color-white);
}

.detail-header h2 {
  font-size: 1rem;
  margin: 0;
}

/* Document Preview */
.document-preview {
  flex-shrink: 0;
  max-height: 250px;
  overflow: hidden;
  background-color: var(--color-gray-200);
  border-bottom: 1px solid var(--color-gray-200);
  display: flex;
  align-items: center;
  justify-content: center;
}

.document-preview img {
  max-width: 100%;
  max-height: 250px;
  object-fit: contain;
}

.detail-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--spacing-lg);
}

/* Detail Sections */
.detail-section {
  background-color: var(--color-white);
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

.section-icon {
  display: flex;
  color: var(--color-gray-500);
}

.file-info {
  font-family: monospace;
  font-size: 0.8125rem;
  color: var(--color-gray-600);
  margin: 0;
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
.form-group select,
.detail-section textarea {
  padding: var(--spacing-sm);
  border: 1px solid var(--color-gray-300);
  border-radius: var(--border-radius);
  font-family: var(--font-family);
  font-size: 0.8125rem;
  transition: var(--transition);
}

.form-group input:focus,
.form-group select:focus,
.detail-section textarea:focus {
  outline: none;
  border-color: var(--color-black);
}

.detail-section textarea {
  width: 100%;
  resize: vertical;
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

.input-description {
  width: 100%;
  min-width: 150px;
  padding: 4px 8px;
  border: 1px solid var(--color-gray-300);
  border-radius: var(--border-radius);
  font-size: 0.8125rem;
}

.input-number {
  width: 70px;
  padding: 4px 8px;
  border: 1px solid var(--color-gray-300);
  border-radius: var(--border-radius);
  font-size: 0.8125rem;
  text-align: right;
}

.cell-total {
  text-align: right;
  font-weight: var(--font-weight-medium);
}

.empty-items {
  text-align: center;
  color: var(--color-gray-400);
  font-style: italic;
  padding: var(--spacing-lg) !important;
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

/* Totals Section */
.totals-section {
  background-color: var(--color-gray-100);
}

.totals-section .form-grid {
  grid-template-columns: repeat(3, 1fr);
}

.total-field input {
  font-weight: var(--font-weight-bold);
  font-size: 1rem;
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
  background-color: var(--color-gray-100);
  border-color: var(--color-gray-400);
  color: var(--color-black);
}

.btn-icon-danger:hover {
  background-color: #fee2e2;
  border-color: #ef4444;
  color: #dc2626;
}

.btn-icon-small {
  width: 24px;
  height: 24px;
}

/* Save error */
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

/* Action bar */
.action-bar {
  display: flex;
  justify-content: flex-end;
  gap: var(--spacing-md);
  padding-top: var(--spacing-lg);
  border-top: 1px solid var(--color-gray-200);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Checkbox styling */
input[type="checkbox"] {
  width: 16px;
  height: 16px;
  cursor: pointer;
  accent-color: var(--color-black);
}

/* Responsive */
@media (max-width: 1024px) {
  .split-view {
    flex-direction: column;
  }

  .detail-open .invoice-list {
    flex: 1;
  }

  .detail-panel {
    flex: 1;
    max-height: 500px;
  }
}

@media (max-width: 768px) {
  .page-header {
    flex-direction: column;
  }

  .page-stats {
    width: 100%;
    justify-content: space-between;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }

  .totals-section .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
