/* AIScore i18n — EN/DA language module */
(function () {
  var TRANSLATIONS = {
    en: {
      // Navbar
      'nav.sign_out': 'Sign out',

      // Sidebar – admin.html
      'sidebar.shortcuts': 'Shortcuts',
      'sidebar.paid_orders': 'Paid orders',
      'sidebar.pipeline': 'Pipeline',
      'sidebar.all_leads': 'All leads',
      'sidebar.applied': 'Applied',
      'sidebar.under_review': 'Under review',
      'sidebar.called': 'Called',
      'sidebar.payment': 'Payment',
      'sidebar.awaiting_payment': 'Awaiting payment',
      'sidebar.paid': 'Paid',
      'sidebar.production': 'Production',
      'sidebar.in_production': 'In production',
      'sidebar.qc_review': 'QC review',
      'sidebar.ready_for_review': 'Review Call',
      'sidebar.escalated': 'Escalated',
      'sidebar.completed': 'Completed',
      'sidebar.collapse': 'Collapse sidebar',
      'sidebar.navigation': 'Navigation',
      'sidebar.leads_pipeline': 'Leads & Pipeline',

      // Filter chips
      'filter.all': 'All',
      'filter.applied': 'Applied',
      'filter.under_review': 'Under Review',
      'filter.paid': 'Paid',
      'filter.production': 'Production',
      'filter.escalated': 'Escalated',
      'filter.qc_review': 'QC Review',
      'filter.review_call': 'Review Call',
      'filter.completed': 'Completed',

      // Table headers – leads
      'th.company': 'Company',
      'th.contact': 'Contact',
      'th.email': 'Email',
      'th.phone': 'Phone',
      'th.website': 'Website',
      'th.status': 'Status',
      'th.applied_date': 'Application date',

      // Search / sort
      'search.placeholder': 'Search company, contact or email…',
      'sort.newest': 'Newest first',
      'sort.oldest': 'Oldest first',
      'sort.company_az': 'Company A→Z',
      'sort.status': 'Status',

      // Status labels
      'status.APPLIED': 'Applied',
      'status.UNDER_REVIEW': 'Under review',
      'status.APPROVED': 'Approved',
      'status.REJECTED': 'Rejected',
      'status.CALLED': 'Called',
      'status.AWAITING_PAYMENT': 'Awaiting payment',
      'status.PAID': 'Paid',
      'status.IN_PRODUCTION': 'In production',
      'status.QC_REVIEW': 'QC review',
      'status.QC_PASSED': 'QC passed',
      'status.QC_FAILED': 'QC failed',
      'status.ESCALATED': 'Escalated',
      'status.RETRY': 'Retrying',
      'status.CANCELLED': 'Cancelled',
      'status.READY_FOR_REVIEW_CALL': 'Review Call',
      'status.COMPLETED': 'Completed',

      // Dynamic table text
      'table.loading': 'Loading applications…',
      'table.loading_short': 'Loading…',
      'table.showing': 'Showing <strong>{n}</strong> of <strong>{total}</strong> leads',
      'table.showing_filtered': 'Showing <strong>{n}</strong> of <strong>{total}</strong> leads with status <strong>{status}</strong>',
      'table.no_results': 'No applications match the filter.',
      'table.leads': 'Leads',

      // Modal – detail
      'modal.app_details': 'Application details',
      'modal.close': 'Close',
      'modal.change_status': 'Change status',
      'modal.confirm_status': 'Confirm status change',
      'modal.cancel': 'Cancel',
      'modal.saving': 'Saving…',
      'modal.no_transitions': 'No allowed transitions from <strong>{status}</strong>. This status is terminal.',
      'modal.select_status': 'Select the desired next status for this application:',
      'modal.note_label': 'Note (optional)',
      'modal.note_placeholder': 'Internal note for the status change…',

      // Detail modal field labels
      'detail.company': 'Company',
      'detail.status': 'Status',
      'detail.contact': 'Contact',
      'detail.email': 'Email',
      'detail.phone': 'Phone',
      'detail.website': 'Website',
      'detail.created': 'Created',
      'detail.updated': 'Updated',
      'detail.about': 'About the company',

      // Timeline
      'timeline.title': 'Status history',
      'timeline.no_history': 'No history available',
      'timeline.changed_by': 'by',

      // Interview dimensions
      'dim.heading': 'Call result — AI readiness dimensions',
      'dim.save_answers': 'Save answers',
      'dim.answer_placeholder': 'Answer from interview…',

      // Report questions
      'rq.title': 'Report questions',
      'rq.not_started': 'Awaiting response',
      'rq.generating': 'Generating…',
      'rq.done_n': '{n} questions ready',
      'rq.error': 'Error generating',
      'rq.loading': 'Report questions generating automatically…',
      'rq.pending': 'Generated automatically when all answers are saved.',
      'rq.none': 'No report questions yet.',
      'rq.retry': 'Generate again',

      // Toast messages
      'toast.answers_saved': 'Answers saved.',
      'toast.answers_saved_generating': 'Answers saved — report questions generating automatically…',
      'toast.status_updated': 'Status updated to ',
      'toast.questions_generating': 'Report questions generating…',
      'toast.questions_ready': ' report questions ready',
      'toast.questions_failed': 'Report questions: generation failed — try again',
      'toast.no_data': 'No data to export',
      'toast.csv_exported': 'CSV exported',

      // Pagination
      'page.info': 'Page {page} of {total}',

      // Orders page
      'orders.title': 'Paid reports',
      'orders.subtitle': 'Latest 20 paid AIScore analyses with status and booking',
      'orders.export_csv': 'Export CSV',
      'orders.refresh': 'Refresh',
      'orders.kpi_paid': 'Paid reports',
      'orders.kpi_paid_sub': 'Latest 20 shown',
      'orders.kpi_booked': 'Meeting booked',
      'orders.kpi_booked_sub': 'Calendly booking active',
      'orders.kpi_waiting': 'Awaiting booking',
      'orders.kpi_waiting_sub': 'Not yet booked',
      'orders.th_time': 'Time',
      'orders.th_company': 'Company',
      'orders.th_score': 'Score',
      'orders.th_report': 'Report',
      'orders.th_calendly': 'Calendly',
      'orders.th_email': 'Email',
      'orders.th_status': 'Status',
      'orders.showing': 'Showing <strong>{n}</strong> paid reports',
      'orders.no_reports': 'No paid reports found.',
      'orders.loading': 'Loading reports…',
      'orders.open_report': 'Open report ↗',
      'orders.booked': 'Booked',
      'orders.waiting': 'Awaiting',
      'orders.loading_error': 'Error loading: ',
      'orders.navigation': 'Navigation',
      'orders.leads_pipeline': 'Leads & Pipeline',
      'orders.paid_orders': 'Paid orders',
      'orders.footer': 'AIScore Admin',
    },

    da: {
      // Navbar
      'nav.sign_out': 'Log ud',

      // Sidebar – admin.html
      'sidebar.shortcuts': 'Genveje',
      'sidebar.paid_orders': 'Betalte ordrer',
      'sidebar.pipeline': 'Pipeline',
      'sidebar.all_leads': 'Alle leads',
      'sidebar.applied': 'Ansøgt',
      'sidebar.under_review': 'Under review',
      'sidebar.called': 'Kaldt',
      'sidebar.payment': 'Betaling',
      'sidebar.awaiting_payment': 'Afventer betaling',
      'sidebar.paid': 'Betalt',
      'sidebar.production': 'Produktion',
      'sidebar.in_production': 'I produktion',
      'sidebar.qc_review': 'QC review',
      'sidebar.ready_for_review': 'Review Call',
      'sidebar.escalated': 'Eskaleret',
      'sidebar.completed': 'Afsluttet',
      'sidebar.collapse': 'Kollaps sidebar',
      'sidebar.navigation': 'Navigation',
      'sidebar.leads_pipeline': 'Leads & Pipeline',

      // Filter chips
      'filter.all': 'Alle',
      'filter.applied': 'Ansøgt',
      'filter.under_review': 'Under Review',
      'filter.paid': 'Betalt',
      'filter.production': 'Produktion',
      'filter.escalated': 'Eskaleret',
      'filter.qc_review': 'QC Review',
      'filter.review_call': 'Review Call',
      'filter.completed': 'Afsluttet',

      // Table headers – leads
      'th.company': 'Virksomhed',
      'th.contact': 'Kontakt',
      'th.email': 'E-mail',
      'th.phone': 'Tlf.',
      'th.website': 'Website',
      'th.status': 'Status',
      'th.applied_date': 'Ansøgningsdato',

      // Search / sort
      'search.placeholder': 'Søg firma, kontakt eller e-mail…',
      'sort.newest': 'Nyeste først',
      'sort.oldest': 'Ældste først',
      'sort.company_az': 'Virksomhed A→Z',
      'sort.status': 'Status',

      // Status labels
      'status.APPLIED': 'Ansøgt',
      'status.UNDER_REVIEW': 'Under review',
      'status.APPROVED': 'Godkendt',
      'status.REJECTED': 'Afvist',
      'status.CALLED': 'Kaldt',
      'status.AWAITING_PAYMENT': 'Afventer betaling',
      'status.PAID': 'Betalt',
      'status.IN_PRODUCTION': 'I produktion',
      'status.QC_REVIEW': 'QC review',
      'status.QC_PASSED': 'QC godkendt',
      'status.QC_FAILED': 'QC fejlet',
      'status.ESCALATED': 'Eskaleret',
      'status.RETRY': 'Genprøver',
      'status.CANCELLED': 'Annulleret',
      'status.READY_FOR_REVIEW_CALL': 'Review Call',
      'status.COMPLETED': 'Afsluttet',

      // Dynamic table text
      'table.loading': 'Indlæser ansøgninger…',
      'table.loading_short': 'Indlæser…',
      'table.showing': 'Viser <strong>{n}</strong> af <strong>{total}</strong> leads',
      'table.showing_filtered': 'Viser <strong>{n}</strong> af <strong>{total}</strong> leads med status <strong>{status}</strong>',
      'table.no_results': 'Ingen ansøgninger matcher filteret.',
      'table.leads': 'Leads',

      // Modal – detail
      'modal.app_details': 'Ansøgningsdetaljer',
      'modal.close': 'Luk',
      'modal.change_status': 'Skift status',
      'modal.confirm_status': 'Bekræft statusskift',
      'modal.cancel': 'Annuller',
      'modal.saving': 'Gemmer…',
      'modal.no_transitions': 'Ingen tilladte overgange fra <strong>{status}</strong>. Denne status er terminal.',
      'modal.select_status': 'Vælg den ønskede næste status for denne ansøgning:',
      'modal.note_label': 'Note (valgfri)',
      'modal.note_placeholder': 'Intern note til statusskiftet…',

      // Detail modal field labels
      'detail.company': 'Virksomhed',
      'detail.status': 'Status',
      'detail.contact': 'Kontaktperson',
      'detail.email': 'E-mail',
      'detail.phone': 'Telefon',
      'detail.website': 'Website',
      'detail.created': 'Oprettet',
      'detail.updated': 'Opdateret',
      'detail.about': 'Om virksomheden',

      // Timeline
      'timeline.title': 'Statushistorik',
      'timeline.no_history': 'Ingen historik tilgængelig',
      'timeline.changed_by': 'af',

      // Interview dimensions
      'dim.heading': 'Opkaldsresultat — AI-parathed dimensioner',
      'dim.save_answers': 'Gem svar',
      'dim.answer_placeholder': 'Svar fra interview…',

      // Report questions
      'rq.title': 'Rapport-spørgsmål',
      'rq.not_started': 'Afventer svar',
      'rq.generating': 'Genererer…',
      'rq.done_n': '{n} spørgsmål klar',
      'rq.error': 'Fejl ved generering',
      'rq.loading': 'Rapport-spørgsmål genereres automatisk…',
      'rq.pending': 'Genereres automatisk når alle svar er gemt.',
      'rq.none': 'Ingen rapport-spørgsmål endnu.',
      'rq.retry': 'Generer igen',

      // Toast messages
      'toast.answers_saved': 'Svar gemt.',
      'toast.answers_saved_generating': 'Svar gemt — rapport-spørgsmål genereres automatisk…',
      'toast.status_updated': 'Status opdateret til ',
      'toast.questions_generating': 'Rapport-spørgsmål genereres…',
      'toast.questions_ready': ' rapport-spørgsmål klar',
      'toast.questions_failed': 'Rapport-spørgsmål: generering fejlede — prøv igen',
      'toast.no_data': 'Ingen data at eksportere',
      'toast.csv_exported': 'CSV eksporteret',

      // Pagination
      'page.info': 'Side {page} af {total}',

      // Orders page
      'orders.title': 'Betalte rapporter',
      'orders.subtitle': 'Seneste 20 betalte AIScore-analyser med status og booking',
      'orders.export_csv': 'Eksporter CSV',
      'orders.refresh': 'Opdater',
      'orders.kpi_paid': 'Betalte rapporter',
      'orders.kpi_paid_sub': 'Seneste 20 vises',
      'orders.kpi_booked': 'Møde booket',
      'orders.kpi_booked_sub': 'Calendly booking aktiv',
      'orders.kpi_waiting': 'Afventer booking',
      'orders.kpi_waiting_sub': 'Endnu ikke booket',
      'orders.th_time': 'Tidspunkt',
      'orders.th_company': 'Virksomhed',
      'orders.th_score': 'Score',
      'orders.th_report': 'Rapport',
      'orders.th_calendly': 'Calendly',
      'orders.th_email': 'Email',
      'orders.th_status': 'Status',
      'orders.showing': 'Viser <strong>{n}</strong> betalte rapporter',
      'orders.no_reports': 'Ingen betalte rapporter fundet.',
      'orders.loading': 'Indlæser rapporter…',
      'orders.open_report': 'Åbn rapport ↗',
      'orders.booked': 'Booket',
      'orders.waiting': 'Afventer',
      'orders.loading_error': 'Fejl ved indlæsning: ',
      'orders.navigation': 'Navigation',
      'orders.leads_pipeline': 'Leads & Pipeline',
      'orders.paid_orders': 'Betalte ordrer',
      'orders.footer': 'AIScore Admin',
    },
  };

  var DEFAULT_LANG = 'en';
  var STORAGE_KEY = 'aiscore_lang';

  var _lang = localStorage.getItem(STORAGE_KEY) || DEFAULT_LANG;

  function t(key, vars) {
    var map = TRANSLATIONS[_lang] || TRANSLATIONS[DEFAULT_LANG];
    var str = map[key] !== undefined ? map[key] : ((TRANSLATIONS[DEFAULT_LANG][key] !== undefined ? TRANSLATIONS[DEFAULT_LANG][key] : key));
    if (!vars) return str;
    return str.replace(/\{(\w+)\}/g, function (_, k) {
      return vars[k] !== undefined ? vars[k] : '{' + k + '}';
    });
  }

  function getLang() { return _lang; }

  function setLang(lang) {
    if (!TRANSLATIONS[lang]) return;
    _lang = lang;
    localStorage.setItem(STORAGE_KEY, lang);
    document.documentElement.lang = lang;
    applyTranslations();
    document.dispatchEvent(new CustomEvent('langchange', { detail: { lang: lang } }));
  }

  function applyTranslations() {
    // Sync toggle button state
    document.querySelectorAll('.lang-opt').forEach(function (btn) {
      btn.classList.toggle('lang-active', btn.dataset.lang === _lang);
    });

    // Static elements with data-i18n
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      el.textContent = t(el.dataset.i18n);
    });

    // Placeholder attributes
    document.querySelectorAll('[data-i18n-placeholder]').forEach(function (el) {
      el.placeholder = t(el.dataset.i18nPlaceholder);
    });

    // Title attributes
    document.querySelectorAll('[data-i18n-title]').forEach(function (el) {
      el.title = t(el.dataset.i18nTitle);
    });
  }

  // Apply language on load (before DOMContentLoaded so lang attr is set early)
  document.documentElement.lang = _lang;

  window.i18n = { t: t, getLang: getLang, setLang: setLang, applyTranslations: applyTranslations };
})();
