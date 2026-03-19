/**
 * Stravish Internationalization (i18n)
 * 
 * Supported languages: it (Italian), en (English)
 * Default: Italian
 */

const I18N = {
  // Current language
  _lang: 'it',

  // Available languages
  languages: {
    it: 'Italiano',
    en: 'English'
  },

  // Translations dictionary
  translations: {
    // ─── APP / TOPBAR ───────────────────────────────────────────
    'app.title': {
      it: 'stravish',
      en: 'stravish'
    },
    'app.connecting': {
      it: 'Connessione…',
      en: 'Connecting…'
    },
    'app.serverUnreachable': {
      it: '⚠ Server non raggiungibile',
      en: '⚠ Server unreachable'
    },
    'app.status': {
      it: '{activities} attività · {segments} segmenti · {efforts} effort',
      en: '{activities} activities · {segments} segments · {efforts} efforts'
    },

    // ─── BUTTONS ────────────────────────────────────────────────
    'btn.syncStrava': {
      it: '⚡ Sync Strava',
      en: '⚡ Sync Strava'
    },
    'btn.import': {
      it: '+ Importa GPX',
      en: '+ Import GPX'
    },
    'btn.settings': {
      it: 'Impostazioni',
      en: 'Settings'
    },
    'btn.save': {
      it: 'Salva',
      en: 'Save'
    },
    'btn.close': {
      it: 'Chiudi',
      en: 'Close'
    },
    'btn.skip': {
      it: 'Salta',
      en: 'Skip'
    },
    'btn.confirm': {
      it: 'Conferma',
      en: 'Confirm'
    },
    'btn.selectNew': {
      it: 'Seleziona nuove',
      en: 'Select new'
    },
    'btn.openStrava': {
      it: '↗ Apri Strava',
      en: '↗ Open Strava'
    },
    'btn.importFromStrava': {
      it: '⬇ Importa da Strava',
      en: '⬇ Import from Strava'
    },
    'btn.importing': {
      it: '⟳ Importazione…',
      en: '⟳ Importing…'
    },

    // ─── LEFT PANEL ─────────────────────────────────────────────
    'left.activities': {
      it: 'Attività',
      en: 'Activities'
    },
    'left.loading': {
      it: 'Caricamento…',
      en: 'Loading…'
    },
    'left.noActivities': {
      it: 'Nessuna attività.<br>Importa un file GPX.',
      en: 'No activities.<br>Import a GPX file.'
    },
    'left.unknownDate': {
      it: 'data ignota',
      en: 'unknown date'
    },
    'left.noSegment': {
      it: 'nessun segmento',
      en: 'no segment'
    },
    'left.refreshTitle': {
      it: 'Ricalcola aggregati e segmentizzazione',
      en: 'Recalculate aggregates and segmentation'
    },
    'left.deleteTitle': {
      it: 'Elimina attività',
      en: 'Delete activity'
    },
    'left.editTitle': {
      it: 'Rinomina attività',
      en: 'Rename activity'
    },
    'left.stravaIdPlaceholder': {
      it: 'Strava Activity ID',
      en: 'Strava Activity ID'
    },
    'left.stravaIdTitle': {
      it: 'ID numerico dell\'attività Strava',
      en: 'Numeric ID of Strava activity'
    },
    'left.fromStrava': {
      it: 'da Strava',
      en: 'from Strava'
    },
    'left.noSegmentRun': {
      it: 'Nessun segmento percorso',
      en: 'No segment traversed'
    },
    'left.deleteEffortTitle': {
      it: 'Elimina effort',
      en: 'Delete effort'
    },

    // ─── MAP CONTROLS ───────────────────────────────────────────
    'map.pan': {
      it: '🔒 Pan',
      en: '🔒 Pan'
    },
    'map.fit': {
      it: '⊞ Fit',
      en: '⊞ Fit'
    },
    'map.unsegmentedSection': {
      it: 'Tratta non segmentata',
      en: 'Unsegmented section'
    },

    // ─── IMPORT OVERLAY ─────────────────────────────────────────
    'import.dropTitle': {
      it: 'Trascina qui i tuoi file <strong>GPX</strong>',
      en: 'Drop your <strong>GPX</strong> files here'
    },
    'import.dropSubtitle': {
      it: 'oppure clicca per selezionarli',
      en: 'or click to select them'
    },
    'import.inProgress': {
      it: 'Importazione in corso…',
      en: 'Import in progress…'
    },
    'import.importing': {
      it: 'Importazione di {count} file…',
      en: 'Importing {count} file(s)…'
    },
    'import.pleaseWait': {
      it: 'Attendere prego, l\'operazione potrebbe richiedere alcuni secondi…',
      en: 'Please wait, this may take a few seconds…'
    },

    // ─── REFRESH ──────────────────────────────────────────────────
    'refresh.inProgress': {
      it: 'Aggiornamento in corso…',
      en: 'Refresh in progress…'
    },

    // ─── SETTINGS MODAL ─────────────────────────────────────────
    'settings.title': {
      it: '⚙ Impostazioni',
      en: '⚙ Settings'
    },
    'settings.cyclistProfile': {
      it: 'Profilo ciclista',
      en: 'Cyclist profile'
    },
    'settings.riderWeight': {
      it: 'Peso ciclista (kg)',
      en: 'Rider weight (kg)'
    },
    'settings.bikeWeight': {
      it: 'Peso bici + attrezzatura (kg)',
      en: 'Bike + equipment weight (kg)'
    },
    'settings.resistance': {
      it: 'Resistenza',
      en: 'Resistance'
    },
    'settings.crr': {
      it: 'Coefficiente attrito (Crr)',
      en: 'Rolling resistance (Crr)'
    },
    'settings.crrSmooth': {
      it: 'Asfalto liscio / pista (0.003)',
      en: 'Smooth asphalt / track (0.003)'
    },
    'settings.crrNormal': {
      it: 'Asfalto normale (0.005)',
      en: 'Normal asphalt (0.005)'
    },
    'settings.crrRough': {
      it: 'Asfalto ruvido / graniglia (0.007)',
      en: 'Rough asphalt / gravel (0.007)'
    },
    'settings.crrCompact': {
      it: 'Sterrato compatto (0.012)',
      en: 'Compact dirt (0.012)'
    },
    'settings.crrGravel': {
      it: 'Sterrato / ghiaia (0.020)',
      en: 'Dirt / gravel (0.020)'
    },
    'settings.aeroPosition': {
      it: 'Posizione aerodinamica (CdA)',
      en: 'Aerodynamic position (CdA)'
    },
    'settings.position': {
      it: 'Posizione',
      en: 'Position'
    },
    'settings.posUpright': {
      it: 'Eretta / MTB (0.45)',
      en: 'Upright / MTB (0.45)'
    },
    'settings.posHoods': {
      it: 'Sportiva con mani sul manubrio (0.36)',
      en: 'On the hoods (0.36)'
    },
    'settings.posDrops': {
      it: 'Sportiva con mani sui manici (0.32)',
      en: 'On the drops (0.32)'
    },
    'settings.posAero': {
      it: 'Bassa / gomiti sul tubo (0.26)',
      en: 'Aero / elbows on bar (0.26)'
    },
    'settings.posTT': {
      it: 'TT / triathlon (0.22)',
      en: 'TT / triathlon (0.22)'
    },
    'settings.saved': {
      it: '✓ Salvato',
      en: '✓ Saved'
    },
    'settings.language': {
      it: 'Lingua',
      en: 'Language'
    },

    // ─── SYNC MODAL ─────────────────────────────────────────────
    'sync.title': {
      it: 'Attività Strava',
      en: 'Strava Activities'
    },
    'sync.loading': {
      it: 'Caricamento attività da Strava…',
      en: 'Loading activities from Strava…'
    },
    'sync.noActivities': {
      it: 'Nessuna attività.',
      en: 'No activities.'
    },
    'sync.authError': {
      it: '⚠ {error}<br><small>Esegui: python run.py auth login</small>',
      en: '⚠ {error}<br><small>Run: python run.py auth login</small>'
    },
    'sync.toDownload': {
      it: '<b style="color:var(--orange)">{count}</b> da scaricare · {imported}/{total} già importate',
      en: '<b style="color:var(--orange)">{count}</b> to download · {imported}/{total} already imported'
    },
    'sync.alreadyImported': {
      it: '{imported}/{total} già importate',
      en: '{imported}/{total} already imported'
    },
    'sync.noGpx': {
      it: 'senza GPX',
      en: 'no GPX'
    },

    // ─── ACTIVITY SUMMARY ───────────────────────────────────────
    'summary.distance': {
      it: 'Distanza',
      en: 'Distance'
    },
    'summary.elevation': {
      it: 'Dislivello',
      en: 'Elevation'
    },
    'summary.time': {
      it: 'Tempo',
      en: 'Time'
    },
    'summary.avgPower': {
      it: 'Potenza media',
      en: 'Avg Power'
    },
    'summary.avgSpeed': {
      it: 'Vel. media',
      en: 'Avg Speed'
    },
    'summary.calories': {
      it: 'Calorie',
      en: 'Calories'
    },
    'summary.heartRate': {
      it: 'Freq. cardiaca',
      en: 'Heart rate'
    },
    'summary.cadence': {
      it: 'Cadenza',
      en: 'Cadence'
    },
    'summary.avg': {
      it: 'media',
      en: 'avg'
    },
    'summary.max': {
      it: 'max',
      en: 'max'
    },
    'summary.segments': {
      it: '✓ {count} segmenti',
      en: '✓ {count} segments'
    },
    'summary.noSegments': {
      it: 'nessun segmento — usa ⚡ Strava',
      en: 'no segments — use ⚡ Strava'
    },
    'summary.medals': {
      it: 'Premi di questa uscita',
      en: 'Awards from this ride'
    },
    'summary.powerRecords': {
      it: '⚡ Record di potenza (stimata)',
      en: '⚡ Power records (estimated)'
    },
    'summary.notes': {
      it: 'Note',
      en: 'Notes'
    },
    'summary.notesPlaceholder': {
      it: 'Note sull\'uscita…',
      en: 'Notes about this ride…'
    },
    'summary.estimatedTitle': {
      it: 'Stima modello fisico',
      en: 'Physics model estimate'
    },
    'summary.atTime': {
      it: 'alle',
      en: 'at'
    },

    // ─── SEGMENT HISTORY ────────────────────────────────────────
    'segment.distance': {
      it: 'Distanza',
      en: 'Distance'
    },
    'segment.grade': {
      it: 'Pendenza',
      en: 'Grade'
    },
    'segment.bestTime': {
      it: 'Best time',
      en: 'Best time'
    },
    'segment.vamBest': {
      it: 'VAM best',
      en: 'VAM best'
    },
    'segment.estimatedWatts': {
      it: 'Watt stimati',
      en: 'Estimated watts'
    },
    'segment.trendTitle': {
      it: 'Andamento nel tempo',
      en: 'Trend over time'
    },
    'segment.history': {
      it: 'Storico ({count} effort)',
      en: 'History ({count} efforts)'
    },
    'segment.noHistory': {
      it: 'Nessun effort storico.',
      en: 'No historical efforts.'
    },
    'segment.rideNotes': {
      it: 'Note uscita',
      en: 'Ride notes'
    },

    // ─── TABLE HEADERS ──────────────────────────────────────────
    'table.rank': {
      it: '#',
      en: '#'
    },
    'table.date': {
      it: 'Data',
      en: 'Date'
    },
    'table.time': {
      it: 'Tempo',
      en: 'Time'
    },
    'table.speed': {
      it: 'km/h',
      en: 'km/h'
    },
    'table.hr': {
      it: 'bpm',
      en: 'bpm'
    },
    'table.vam': {
      it: 'VAM',
      en: 'VAM'
    },
    'table.delta': {
      it: 'Δ best',
      en: 'Δ best'
    },

    // ─── FETCH STATUS ───────────────────────────────────────────
    'fetch.enterStravaId': {
      it: '⚠ Inserisci l\'ID attività Strava',
      en: '⚠ Enter the Strava activity ID'
    },
    'fetch.fetching': {
      it: '⟳ Fetching da Strava…',
      en: '⟳ Fetching from Strava…'
    },
    'fetch.fetchingShort': {
      it: '⟳ Fetching…',
      en: '⟳ Fetching…'
    },
    'fetch.imported': {
      it: '✓ {count} effort importati da Strava',
      en: '✓ {count} efforts imported from Strava'
    },
    'fetch.matchFound': {
      it: '⟳ Match Strava trovato ({name}), importo effort…',
      en: '⟳ Strava match found ({name}), importing efforts…'
    },
    'fetch.error': {
      it: '⚠ {error}',
      en: '⚠ {error}'
    },
    'fetch.success': {
      it: '✓ {name}: {count} segmenti',
      en: '✓ {name}: {count} segments'
    },

    // ─── CONFIRMATIONS ──────────────────────────────────────────
    'confirm.deleteSegment': {
      it: 'Eliminare segmento "{name}" e tutti i suoi effort storici?',
      en: 'Delete segment "{name}" and all its historical efforts?'
    },
    'confirm.deleteActivity': {
      it: 'Eliminare "{name}" e tutti i suoi effort?',
      en: 'Delete "{name}" and all its efforts?'
    },
    'confirm.deleteEffort': {
      it: 'Eliminare definitivamente questo effort?',
      en: 'Permanently delete this effort?'
    },
    'confirm.refresh': {
      it: 'Ricalcolare aggregati e segmentizzazione per "{name}"? Seleziona il file GPX dell\'attività.',
      en: 'Recalculate aggregates and segmentation for "{name}"? Select the activity GPX file.'
    },

    // ─── ERRORS ─────────────────────────────────────────────────
    'error.generic': {
      it: 'Errore: {message}',
      en: 'Error: {message}'
    },
    'error.refreshFailed': {
      it: 'Refresh fallito: {message}',
      en: 'Refresh failed: {message}'
    },
    'error.stravaEffortFetch': {
      it: 'Errore fetch effort Strava: {message}',
      en: 'Error fetching Strava efforts: {message}'
    },
    'error.deletion': {
      it: 'Errore durante l\'eliminazione: {message}',
      en: 'Error during deletion: {message}'
    },
    'error.renameFailed': {
      it: 'Rinomina fallita: {message}',
      en: 'Rename failed: {message}'
    },

    // ─── PROMPTS ─────────────────────────────────────────────────
    'prompt.rename': {
      it: 'Nuovo nome per l\'attività:',
      en: 'New name for the activity:'
    },

    // ─── UNITS ──────────────────────────────────────────────────
    'unit.km': {
      it: 'km',
      en: 'km'
    },
    'unit.m': {
      it: 'm',
      en: 'm'
    },
    'unit.w': {
      it: 'W',
      en: 'W'
    },
    'unit.bpm': {
      it: 'bpm',
      en: 'bpm'
    },
    'unit.rpm': {
      it: 'rpm',
      en: 'rpm'
    },
    'unit.kcal': {
      it: 'kcal',
      en: 'kcal'
    },
    'unit.kmh': {
      it: 'km/h',
      en: 'km/h'
    },
    'unit.mh': {
      it: 'm/h',
      en: 'm/h'
    },
    'unit.min': {
      it: 'min',
      en: 'min'
    },

    // ─── OVERLAY / TIMEOUT ──────────────────────────────────────
    'overlay.cancel': {
      it: '✕ Annulla',
      en: '✕ Cancel'
    },
    'overlay.cancelled': {
      it: 'Operazione annullata.',
      en: 'Operation cancelled.'
    },
    'overlay.timedOut': {
      it: 'Operazione annullata: timeout di {seconds}s raggiunto.',
      en: 'Operation cancelled: {seconds}s timeout reached.'
    },
    'overlay.timeRemaining': {
      it: 'Timeout in {seconds}s…',
      en: 'Timeout in {seconds}s…'
    },
    'settings.operations': {
      it: 'Operazioni',
      en: 'Operations'
    },
    'settings.overlayTimeout': {
      it: 'Timeout overlay (secondi, 0 = disabilitato)',
      en: 'Overlay timeout (seconds, 0 = disabled)'
    },

    // ─── STRAVA AUTH ────────────────────────────────────────────
    'settings.stravaApi': {
      it: 'Strava API',
      en: 'Strava API'
    },
    'settings.stravaClientId': {
      it: 'Client ID',
      en: 'Client ID'
    },
    'settings.stravaClientSecret': {
      it: 'Client Secret',
      en: 'Client Secret'
    },
    'strava.authConnected': {
      it: '🟢 Connesso',
      en: '🟢 Connected'
    },
    'strava.authExpiring': {
      it: '🟡 In scadenza',
      en: '🟡 Expiring'
    },
    'strava.authExpired': {
      it: '🔴 Scaduto',
      en: '🔴 Expired'
    },
    'strava.authNone': {
      it: '🔴 Non autenticato',
      en: '🔴 Not authenticated'
    },
    'strava.expiresIn': {
      it: 'Scade tra {time}',
      en: 'Expires in {time}'
    },
    'strava.refreshToken': {
      it: '🔄 Refresh token',
      en: '🔄 Refresh token'
    },
    'strava.refreshing': {
      it: '⟳ Refresh…',
      en: '⟳ Refreshing…'
    },
    'strava.refreshOk': {
      it: '✓ Token rinnovato',
      en: '✓ Token refreshed'
    },
    'strava.refreshFailed': {
      it: '⚠ Refresh fallito: {error}',
      en: '⚠ Refresh failed: {error}'
    },
    'strava.credentialsSaved': {
      it: '✓ Credenziali salvate',
      en: '✓ Credentials saved'
    },
    'strava.credentialsFailed': {
      it: '⚠ Salvataggio fallito: {error}',
      en: '⚠ Save failed: {error}'
    },
    'strava.loginHint': {
      it: 'Esegui <code>python run.py auth login</code> per autorizzare',
      en: 'Run <code>python run.py auth login</code> to authorize'
    },

    // ─── AI ANALYSIS ────────────────────────────────────────────
    'settings.aiAnalysis': {
      it: 'Analisi IA',
      en: 'AI Analysis'
    },
    'ai.provider': {
      it: 'Provider',
      en: 'Provider'
    },
    'ai.model': {
      it: 'Modello',
      en: 'Model'
    },
    'ai.selectProvider': {
      it: 'Seleziona provider',
      en: 'Select provider'
    },
    'ai.btn': {
      it: '🤖 AI',
      en: '🤖 AI'
    },
    'ai.btnTitle': {
      it: 'Analisi AI dell\'attività',
      en: 'AI activity analysis'
    },
    'ai.analyzing': {
      it: '🤖 Analisi AI in corso…',
      en: '🤖 AI analysis in progress…'
    },
    'ai.noProvider': {
      it: '⚠ Configura un provider AI nelle Impostazioni',
      en: '⚠ Configure an AI provider in Settings'
    },
    'ai.error': {
      it: '⚠ Errore AI: {error}',
      en: '⚠ AI error: {error}'
    },
    'ai.done': {
      it: '✓ Analisi AI completata e salvata nelle note',
      en: '✓ AI analysis complete and saved to notes'
    },

    // ─── MISC ───────────────────────────────────────────────────
    'misc.on': {
      it: 'su',
      en: 'of'
    },
    'misc.saved': {
      it: '✓ salvato',
      en: '✓ saved'
    },
    'misc.saving': {
      it: '✎ …',
      en: '✎ …'
    },
    'misc.na': {
      it: 'N/A',
      en: 'N/A'
    }
  },

  /**
   * Get current language
   */
  getLang() {
    return this._lang;
  },

  /**
   * Set language
   */
  setLang(lang) {
    if (this.languages[lang]) {
      this._lang = lang;
      localStorage.setItem('stravish_lang', lang);
      return true;
    }
    return false;
  },

  /**
   * Initialize from localStorage or browser preference
   */
  init() {
    const saved = localStorage.getItem('stravish_lang');
    if (saved && this.languages[saved]) {
      this._lang = saved;
    } else {
      // Detect browser language
      const browserLang = navigator.language?.slice(0, 2) || 'it';
      this._lang = this.languages[browserLang] ? browserLang : 'it';
    }
  },

  /**
   * Translate a key with optional parameters
   * @param {string} key - Translation key
   * @param {object} params - Optional parameters for interpolation
   * @returns {string} Translated string
   */
  t(key, params = {}) {
    const entry = this.translations[key];
    if (!entry) {
      console.warn(`Missing translation: ${key}`);
      return key;
    }
    
    let text = entry[this._lang] || entry['it'] || key;
    
    // Replace {param} placeholders
    for (const [k, v] of Object.entries(params)) {
      text = text.replace(new RegExp(`\\{${k}\\}`, 'g'), v);
    }
    
    return text;
  }
};

// Initialize on load
I18N.init();

// Shorthand function
function t(key, params) {
  return I18N.t(key, params);
}
