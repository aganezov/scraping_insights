function resetCountersForRun(){
  const yt = document.getElementById('ytCount');
  if (yt) yt.textContent = '0/0';
  // (leave Reddit to Patch 2)
}

(function () {
  if (!(window.pywebview && window.pywebview.api)) {
    console.debug("[IM] Bridge inactive (not in pywebview)"); return;
  }
  const api = window.pywebview.api;
  const origBuildCli = window.buildCli;
  const origUpdateCmd = window.updateCmd;

  // helpers
  function $(q, el=document){ return el.querySelector(q) }
  function collectKnobsSafe() {
    try { return (window.collectKnobs ? window.collectKnobs() : {}) || {}; } catch { return {}; }
  }
  function cloneRebind(id, handler) {
    const el = document.getElementById(id); if (!el) return;
    const clone = el.cloneNode(true); el.parentNode.replaceChild(clone, el);
    clone.addEventListener('click', handler);
  }
  function ensureSized(el){
    if(!el) return;
    // simple auto-size for readability in modal
    el.style.minHeight = (el.getAttribute("data-min") || "160") + "px";
    el.style.maxHeight = Math.floor(window.innerHeight * 0.6) + "px";
    el.style.overflow = "auto";
    el.style.resize = "vertical";
  }

  // --- RUN / CANCEL (replace simulator binding)
  cloneRebind('runBtn', async () => {
    try {
      const knobs = collectKnobsSafe();
      if (window._im_next_run_id) knobs.__run_id = window._im_next_run_id;
      await api.start_collect(knobs);
    }
    catch (e) { window.log && window.log('! start_collect failed: ' + String(e)); }
  });
  cloneRebind('cancelBtn', async () => {
    try { await api.cancel_collect(); window.log && window.log('Cancelled.'); }
    catch (e) { window.log && window.log('! cancel_collect failed: ' + String(e)); }
  });
  // Clear log button (add next to Export)
  (function(){
    const exportBtn = document.getElementById('exportLog');
    if (exportBtn && !document.getElementById('clearLogBtn')) {
      const btn = document.createElement('button');
      btn.id = 'clearLogBtn';
      btn.className = 'btn small';
      btn.textContent = 'Clear log';
      btn.style.marginLeft = '8px';
      btn.addEventListener('click', ()=> {
        const logEl = document.getElementById('log');
        if (logEl) logEl.textContent = "";
      });
      exportBtn.parentNode.insertBefore(btn, exportBtn);
    }
  })();
  cloneRebind('exportLog', async () => {
    try{
      const txt = document.getElementById('log')?.textContent || "";
      const res = await api.export_log(txt);
      if (res && res.ok) {
        const t = document.getElementById('toast');
        if (t){ t.textContent = 'Log saved'; t.classList.add('show'); setTimeout(()=>t.classList.remove('show'), 1400); }
      } else if (res && res.error){
        alert('Save failed: ' + res.error);
      }
    }catch(e){ alert('Save failed: ' + e); }
  });

  // --- SETTINGS: open modal, load raw .env, allow edit & save ---
  const modal = document.getElementById('modalSettings');
  const moreMenu = document.getElementById('moreMenu');

  // Create a Save button dynamically (v15 mock has only Close)
  let saveBtn = null, pathRow = null;

  async function loadEnvIntoModal() {
    try{
      const data = await api.get_env(); // {env_path, text}
      
      // Support both old (#envMock) and new (#envTextarea) element IDs
      const ta = document.getElementById('envTextarea') || document.getElementById('envMock');
      const pathEl = document.getElementById('envFilePath');
      const statusEl = document.getElementById('settingsStatus');
      
      if (!modal) return;
      
      // Update textarea
      if (ta) {
        ta.value = data.text || "";
        ensureSized(ta);
      }
      
      // Update file path display (new modal structure)
      if (pathEl) {
        pathEl.textContent = data.env_path || "(unknown)";
        pathEl.title = data.env_path || "";
      }
      
      // Clear status
      if (statusEl) {
        statusEl.textContent = "";
      }

      // For old modal structure: Show path + Save button dynamically
      if (!pathEl) {
        const headerRow = modal.querySelector(".row");
        if (headerRow && !pathRow) {
          pathRow = document.createElement('div');
          pathRow.className = 'small';
          pathRow.style.marginLeft = 'auto';
          pathRow.style.marginRight = '10px';
          pathRow.textContent = data.env_path ? `File: ${data.env_path}` : "";
          headerRow.insertBefore(pathRow, headerRow.lastElementChild);
        } else if (pathRow) {
          pathRow.textContent = data.env_path ? `File: ${data.env_path}` : "";
        }

        if (!saveBtn && headerRow) {
          saveBtn = document.createElement('button');
          saveBtn.className = 'btn';
          saveBtn.id = 'saveSettingsBtn';
          saveBtn.textContent = 'Save';
          saveBtn.style.marginRight = '8px';
          saveBtn.addEventListener('click', async ()=>{
            const res = await api.save_env(ta.value);
            if(!res || !res.ok){
              alert('Save failed' + (res && res.error ? (': ' + res.error) : ''));
            } else {
              const t = document.getElementById('toast');
              if (t) { t.textContent='Saved'; t.classList.add('show'); setTimeout(()=>t.classList.remove('show'), 1200); }
              else { alert('Saved.'); }
            }
          });
          headerRow.insertBefore(saveBtn, headerRow.lastElementChild);
        }
      }

      // Cmd/Ctrl+S to save
      modal.addEventListener('keydown', async (e)=>{
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase()==='s') {
          e.preventDefault();
          const textarea = document.getElementById('envTextarea') || document.getElementById('envMock');
          if (textarea) {
            const res = await api.save_env(textarea.value);
            if(!(res && res.ok)) alert('Save failed' + (res && res.error ? (': ' + res.error) : ''));
          }
        }
      }, { once: false });

    }catch(err){
      console.error('[IM] get_env failed', err);
      const statusEl = document.getElementById('settingsStatus');
      if (statusEl) {
        statusEl.textContent = 'Error loading: ' + err.message;
      } else {
        alert('Failed to load .env: ' + err);
      }
    }
  }

  cloneRebind('openSettings', (e)=>{
    e.preventDefault();
    moreMenu && (moreMenu.style.display='none');
    if (modal) {
      modal.style.display='block';
      loadEnvIntoModal();
    }
  });
  cloneRebind('openSourceUpdate', async (e) => {
    e.preventDefault();
    moreMenu && (moreMenu.style.display = 'none');
    const okay = window.confirm('Pull the latest code for this checkout and refresh GUI dependencies? This only works on a clean git checkout.');
    if (!okay) return;
    try {
      const res = await api.update_source_checkout();
      if (!res || !res.ok) {
        alert('Update failed: ' + ((res && res.error) || 'unknown error'));
        return;
      }
      const restartNow = window.confirm((res.message || 'Update completed.') + '\n\nRestart Insight Mine now?');
      if (restartNow) {
        const restart = await api.restart_app();
        if (!restart || !restart.ok) {
          alert('Restart failed: ' + ((restart && restart.error) || 'unknown error'));
        }
      }
    } catch (err) {
      alert('Update failed: ' + err);
    }
  });
  cloneRebind('closeSettingsBtn', ()=>{ modal && (modal.style.display='none'); });

  // Wire up new Settings modal buttons
  // Use cloneRebind to avoid double-binding (base UI already attaches listeners).
  if (document.getElementById('loadEnvBtn')) {
    cloneRebind('loadEnvBtn', async () => {
      try {
        const res = await api.choose_env_file();
        if (res && res.cancelled) return;
        if (res && res.ok) {
          const ta = document.getElementById('envTextarea');
          const pathEl = document.getElementById('envFilePath');
          const statusEl = document.getElementById('settingsStatus');
          if (ta) ta.value = res.text || "";
          if (pathEl) { pathEl.textContent = res.env_path || "(unknown)"; pathEl.title = res.env_path || ""; }
          if (statusEl) { statusEl.textContent = "✓ Loaded"; setTimeout(() => statusEl.textContent = "", 3000); }
          const t = document.getElementById('toast');
          if (t) { t.textContent='Environment file loaded'; t.classList.add('show'); setTimeout(()=>t.classList.remove('show'), 1400); }
        } else if (res && res.error) {
          const statusEl = document.getElementById('settingsStatus');
          if (statusEl) statusEl.textContent = "Error: " + res.error;
        }
      } catch (err) {
        console.error('[IM] choose_env_file failed', err);
      }
    });
  }
  
  if (document.getElementById('saveEnvBtn')) {
    cloneRebind('saveEnvBtn', async () => {
      try {
        const ta = document.getElementById('envTextarea');
        const statusEl = document.getElementById('settingsStatus');
        if (!ta) return;
        const res = await api.save_env(ta.value);
        if (res && res.ok) {
          if (statusEl) { statusEl.textContent = "✓ Saved"; setTimeout(() => statusEl.textContent = "", 3000); }
          const t = document.getElementById('toast');
          if (t) { t.textContent='Settings saved'; t.classList.add('show'); setTimeout(()=>t.classList.remove('show'), 1400); }
        } else {
          if (statusEl) statusEl.textContent = "Error: " + (res && res.error || "unknown");
        }
      } catch (err) {
        console.error('[IM] save_env failed', err);
      }
    });
  }
  
  if (document.getElementById('saveEnvAsBtn')) {
    cloneRebind('saveEnvAsBtn', async () => {
      try {
        const ta = document.getElementById('envTextarea');
        const pathEl = document.getElementById('envFilePath');
        const statusEl = document.getElementById('settingsStatus');
        if (!ta) return;
        const res = await api.save_env_as(ta.value);
        if (res && res.cancelled) return;
        if (res && res.ok) {
          if (pathEl) { pathEl.textContent = res.env_path || "(unknown)"; pathEl.title = res.env_path || ""; }
          if (statusEl) { statusEl.textContent = "✓ Saved to new file"; setTimeout(() => statusEl.textContent = "", 3000); }
          const t = document.getElementById('toast');
          if (t) { t.textContent='Settings saved to new file'; t.classList.add('show'); setTimeout(()=>t.classList.remove('show'), 1400); }
        } else if (res && res.error) {
          if (statusEl) statusEl.textContent = "Error: " + res.error;
        }
      } catch (err) {
        console.error('[IM] save_env_as failed', err);
      }
    });
  }

  // --- RESULTS: ask Python for run list when Results tab is opened
  // Use capture phase to run BEFORE ui.html's handler
  const tabs = document.getElementById('tabs');
  tabs && tabs.addEventListener('click', async (e) => {
    const t = e.target.closest('.tab'); if (!t || t.dataset.tab !== 'results') return;
    
    // Prevent the original handler from running until we have data
    e.stopImmediatePropagation();
    
    try {
      // Fetch runs from backend
      const runsData = await api.list_runs(); // [{id, started_at, topic, items}]
      
      // Process and store runs
      try {
        window.IMBridge.receive('runs_list', { runs: runsData });
      } catch (receiveErr) {
        if ((runsData || []).length === 0) {
          window.runs = [];
          const runList = document.getElementById('runList');
          if (runList) runList.innerHTML = '<div class="small">No runs</div>';
        } else {
          throw receiveErr;
        }
      }
      
      // Now manually trigger what the original handler would do
      // Switch to results tab
      document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
      t.classList.add('active');
      document.querySelectorAll('[data-page]').forEach(p => {
        p.style.display = p.getAttribute('data-page') === 'results' ? 'block' : 'none';
      });
      
      // Auto-load the latest run if available and not already loaded
      if (window.runs && window.runs.length > 0) {
        const latestRun = window.runs[0];
        if (!window.currentRun || window.currentRun._needsFullLoad) {
          try {
            const res = await api.get_run(latestRun.id);
            if (res && res.ok && res.run) {
              res.run._needsFullLoad = false;
              window.currentRun = res.run;
              // Update in runs array
              window.runs[0] = res.run;
              const lbl = document.getElementById('runBtnLabel');
              if (lbl && window.runDesc) lbl.textContent = window.runDesc(window.currentRun);
            } else {
              window.currentRun = latestRun;
            }
          } catch (loadErr) {
            console.error('[IM] Failed to auto-load latest run:', loadErr);
            window.currentRun = latestRun;
          }
        }
      }
      
      if (window.openRunMenu) window.openRunMenu(false);
      if (window.currentRun) {
        try {
          if (window.renderActiveView) window.renderActiveView();
        } catch (renderErr) {
          console.error('[IM] renderActiveView failed on results open', renderErr);
        }
        try {
          if (window.renderTelemetry) window.renderTelemetry();
        } catch (telemetryErr) {
          console.error('[IM] renderTelemetry failed on results open', telemetryErr);
        }
      }
      
    } catch (err) {
      window.log && window.log('! list_runs failed: ' + String(err));
      // Still switch to results tab on error
      document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
      t.classList.add('active');
      document.querySelectorAll('[data-page]').forEach(p => {
        p.style.display = p.getAttribute('data-page') === 'results' ? 'block' : 'none';
      });
    }
  }, true);  // true = capture phase, runs before bubble phase handlers

  // --- Python -> UI events
  window.IMBridge = window.IMBridge || {};
  window.IMBridge.receive = function (type, payload) {
    if (type === 'log'      && window.log)     return window.log(payload.line || '');
    if (type === 'progress' && window.setProg) {
      if (payload.overall != null) window.setProg('#progOverall', payload.overall);
      if (payload.youtube != null && document.querySelector('#progYT')) window.setProg('#progYT', payload.youtube);
      if (payload.reddit  != null && document.querySelector('#progRD')) window.setProg('#progRD',  payload.reddit);
      if (payload.yt_count != null) document.getElementById('ytCount').textContent = String(payload.yt_count);
      if (payload.rd_count != null) document.getElementById('rdCount').textContent = String(payload.rd_count);
      return;
    }
    if (type === 'run_complete') {
      window.currentRun = payload.run;
      window.runs = window.runs || []; window.runs.unshift(payload.run);
      try {
        window.renderActiveView && window.renderActiveView();
      } catch (err) {
        console.error('[IM] renderActiveView failed after run_complete', err);
      }
      try {
        window.renderTelemetry && window.renderTelemetry();
      } catch (err) {
        console.error('[IM] renderTelemetry failed after run_complete', err);
      }
      const lbl = document.getElementById('runBtnLabel');
      if (lbl && window.currentRun && window.runDesc) lbl.textContent = window.runDesc(window.currentRun);
      if (window.log) window.log('DONE');
      return;
    }
    if (type === 'run_error')   return window.log && window.log('! ' + (payload.message || 'Run failed'));
    if (type === 'transcript_ready') {
      const id = payload.video_id;
      const textEl = document.getElementById('tr-text-'+id);
      const blk    = document.getElementById('tr-'+id);
      const fmt = window.formatTranscript || (t => t);
      if (textEl) textEl.textContent = fmt(payload.text || '');
      if (blk) blk.style.display = 'block';
      const dot = document.getElementById('trdot-'+id);
      if (dot) { dot.classList.add('on'); dot.title = 'Transcript available'; }
      return;
    }
    if (type === 'runs_list') {
      const adapt = (r)=> {
        if (r && r.manifest) return r;
        // r.items from list_runs is a count (number), not an array
        // Create a placeholder array of that length for runDesc to work
        const itemCount = typeof r.items === 'number' ? r.items : (Array.isArray(r.items) ? r.items.length : 0);
        const commentCount = typeof r.comments === 'number' ? r.comments : 0;
        const itemsPlaceholder = new Array(itemCount);
        return {
          id: r.id,
          manifest: {
            started_at: r.started_at || "",
            knobs: {"topic": r.topic || ""},
            items: itemsPlaceholder,
          },
          stats: {dropped:{}},
          _itemCount: itemCount,  // Store count for reference
          _commentCount: commentCount,  // Store comment count
          _needsFullLoad: true,   // Flag that this is a summary, not full data
        };
      };
      const adaptedRuns = (payload.runs || []).map(adapt);
      window.runs = adaptedRuns;
      
      // Directly render the run list instead of relying on ui.html's populateRunMenu
      // because ui.html uses a let-declared `runs` variable that we can't access
      const runList = document.getElementById('runList');
      const searchInput = document.getElementById('runSearch');
      const q = (searchInput?.value || '').toLowerCase();
      
      if (runList) {
        runList.innerHTML = '';
        const filtered = adaptedRuns.filter(r => {
          try {
            const desc = window.runDesc ? window.runDesc(r) : r.id;
            return desc.toLowerCase().includes(q);
          } catch (e) {
            return true; // Include anyway
          }
        });
        
        if (filtered.length === 0) {
          runList.innerHTML = '<div class="small">No runs</div>';
        } else {
          filtered.forEach(r => {
            const div = document.createElement('div');
            div.className = 'run-item';
            div.textContent = window.runDesc ? window.runDesc(r) : r.id;
            div.addEventListener('click', async () => {
              // Close menu immediately for responsiveness
              if (window.openRunMenu) window.openRunMenu(false);
              
              // Check if we need to load full data
              if (r._needsFullLoad) {
                // Load full data from backend
                try {
                  const res = await api.get_run(r.id);
                  if (res && res.ok && res.run) {
                    res.run._needsFullLoad = false;
                    window.currentRun = res.run;
                    // Update in runs array
                    const idx = window.runs.findIndex(x => x.id === r.id);
                    if (idx >= 0) window.runs[idx] = res.run;
                  } else {
                    // Fallback to summary data
                    window.currentRun = r;
                  }
                } catch (err) {
                  console.error('[IM] Failed to load run:', err);
                  window.currentRun = r;
                }
              } else {
                window.currentRun = r;
              }
              
              const lbl = document.getElementById('runBtnLabel');
              if (lbl && window.runDesc) lbl.textContent = window.runDesc(window.currentRun);
              if (window.renderActiveView) window.renderActiveView();
              if (window.renderTelemetry) window.renderTelemetry();
            });
            runList.appendChild(div);
          });
        }
      }
      
      // Update the label
      const lbl = document.getElementById('runBtnLabel');
      if (lbl && adaptedRuns[0]) {
        if (window.runDesc) {
          lbl.textContent = window.runDesc(adaptedRuns[0]);
        }
      }
      return;
    }
  };
  
  // Override populateRunMenu to use window.runs instead of ui.html's local `runs` variable
  // This is called by openRunMenu() and on search input
  window.populateRunMenu = function() {
    const runList = document.getElementById('runList');
    const searchInput = document.getElementById('runSearch');
    if (!runList) return;
    
    runList.innerHTML = '';
    const q = (searchInput?.value || '').toLowerCase();
    const runsArr = window.runs || [];
    
    const filtered = runsArr.filter(r => {
      try {
        const desc = window.runDesc ? window.runDesc(r) : r.id;
        return desc.toLowerCase().includes(q);
      } catch (e) {
        return true;
      }
    });
    
    if (filtered.length === 0) {
      runList.innerHTML = '<div class="small">No runs</div>';
      return;
    }
    
    filtered.forEach(r => {
      const div = document.createElement('div');
      div.className = 'run-item';
      div.textContent = window.runDesc ? window.runDesc(r) : r.id;
      div.addEventListener('click', async () => {
        // Close menu immediately
        if (window.openRunMenu) window.openRunMenu(false);
        
        // Load full data if needed
        if (r._needsFullLoad && window.pywebview && window.pywebview.api) {
          try {
            const res = await window.pywebview.api.get_run(r.id);
            if (res && res.ok && res.run) {
              res.run._needsFullLoad = false;
              window.currentRun = res.run;
              const idx = window.runs.findIndex(x => x.id === r.id);
              if (idx >= 0) window.runs[idx] = res.run;
            } else {
              window.currentRun = r;
            }
          } catch (err) {
            console.error('[IM] Failed to load run:', err);
            window.currentRun = r;
          }
        } else {
          window.currentRun = r;
        }
        
        const lbl = document.getElementById('runBtnLabel');
        if (lbl && window.runDesc) lbl.textContent = window.runDesc(window.currentRun);
        if (window.renderActiveView) window.renderActiveView();
        if (window.renderTelemetry) window.renderTelemetry();
      });
      runList.appendChild(div);
    });
    
    // Update label with current run
    if (window.currentRun) {
      const lbl = document.getElementById('runBtnLabel');
      if (lbl && window.runDesc) lbl.textContent = window.runDesc(window.currentRun);
    }
  };
  
  // Override runDesc to show items/comments format
  window.runDesc = function(r) {
    if (!r) return '(no run)';
    const started = r.manifest?.started_at ? new Date(r.manifest.started_at).toLocaleString() : '(unknown)';
    const topic = r.manifest?.knobs?.topic || '(no topic)';
    
    // Get item count
    const items = r._itemCount ?? r.manifest?.items?.length ?? 0;
    
    // Get comment count - either from _commentCount or calculate from items
    let comments = r._commentCount;
    if (comments === undefined && r.manifest?.items) {
      comments = r.manifest.items.reduce((acc, it) => acc + (it.comments?.length || 0), 0);
    }
    comments = comments || 0;
    
    return `${started} — ${topic} — ${items}/${comments}`;
  };
  
  // Override functions that use the local `currentRun` variable to use window.currentRun
  // This is necessary because ui.html declares `let currentRun` which isn't window.currentRun
  
  // Initialize window versions of let-declared variables from ui.html
  // NOTE: We use _im_ prefix to avoid collision with DOM elements (e.g., #pageSize creates window.pageSize)
  if (window._im_page === undefined) window._im_page = 1;
  if (window._im_pageSize === undefined) window._im_pageSize = 25;
  if (window._im_currentView === undefined) window._im_currentView = 'parents';
  
  // Helper to get currentRun from window
  const getCurrentRun = () => window.currentRun;
  
  // Helpers for pagination (ui.html's let-declared vars aren't accessible)
  const getPage = () => window._im_page || 1;
  const setPage = (p) => { window._im_page = p; };
  const getPageSize = () => window._im_pageSize || 25;
  const getCurrentView = () => window._im_currentView || 'parents';
  
  // Override getFilteredSortedItems
  window.getFilteredSortedItems = function(noPaging = false) {
    const run = getCurrentRun();
    if (!run) return [];
    
    const items = run.manifest?.items || [];
    const filteredItems = window.filtered ? window.filtered(items) : items;
    
    if (noPaging) return filteredItems;
    
    const pageSz = getPageSize();
    let pg = getPage();
    const totalPages = Math.max(1, Math.ceil(filteredItems.length / pageSz));
    pg = Math.max(1, Math.min(pg, totalPages));
    setPage(pg);
    
    const pageInfo = document.getElementById('pageInfo');
    if (pageInfo) pageInfo.textContent = `Page ${pg} / ${totalPages}`;
    
    const start = (pg - 1) * pageSz;
    const end = start + pageSz;
    return filteredItems.slice(start, end);
  };
  
  // Override allCommentsOfRun
  window.allCommentsOfRun = function() {
    const run = getCurrentRun();
    if (!run) return [];
    
    const rows = [];
    (run.manifest?.items || []).forEach(p => {
      (p.comments || []).forEach(c => {
        rows.push({
          platform: p.platform,
          text: c.text,
          author: c.author,
          authorUrl: c.authorUrl || '',
          parentTitle: p.title || '',
          parentUrl: p.url,
          ctx: (p.platform === 'youtube' ? (p.context?.channel || '') : (p.context?.subreddit || '')),
          ctxUrl: (p.platform === 'youtube' ? (p.context?.channelUrl || '') : (p.context?.subredditUrl || '')),
          likes: c.likes || 0,
          date: c.created_at,
          url: c.url || p.url
        });
      });
    });
    return rows;
  };
  
  // Override totalPagesForActiveView
  window.totalPagesForActiveView = function() {
    const run = getCurrentRun();
    if (!run) return 1;
    const pageSz = getPageSize();
    if (getCurrentView() === 'parents') {
      const n = window.getFilteredSortedItems(true).length;
      return Math.max(1, Math.ceil(n / pageSz));
    }
    const n = window.getFilteredSortedComments ? window.getFilteredSortedComments(true).length : 0;
    return Math.max(1, Math.ceil(n / pageSz));
  };
  
  // Override getFilteredSortedComments to use window.currentRun and our pagination
  window.getFilteredSortedComments = function(noPaging = false) {
    // Use allCommentsOfRunFilteredSorted if available, otherwise build from allCommentsOfRun
    let rows = [];
    if (window.allCommentsOfRunFilteredSorted) {
      rows = window.allCommentsOfRunFilteredSorted();
    } else {
      rows = window.allCommentsOfRun();
    }
    
    if (noPaging) return rows;
    
    const pageSz = getPageSize();
    let pg = getPage();
    const totalPages = Math.max(1, Math.ceil(rows.length / pageSz));
    pg = Math.max(1, Math.min(pg, totalPages));
    setPage(pg);
    
    const pageInfo = document.getElementById('pageInfo');
    if (pageInfo) pageInfo.textContent = `Page ${pg} / ${totalPages}`;
    
    const start = (pg - 1) * pageSz;
    const end = start + pageSz;
    return rows.slice(start, end);
  };
  
  // Override renderTelemetry to use window.currentRun
  window.renderTelemetry = function() {
    const run = getCurrentRun();
    const keptEl = document.getElementById('keptT');
    const dropEl = document.getElementById('dropT');
    if (!keptEl || !dropEl) return;

    if (!run) {
      keptEl.innerHTML = '';
      dropEl.innerHTML = '';
      return;
    }

    const items = run.manifest?.items || [];
    const dropped = run.stats?.dropped || {};
    const fmt = window.fmt || (v => (v == null ? '' : String(v)));

    keptEl.innerHTML = [
      `<tr><td>YouTube</td><td>${fmt(items.filter(i => i.platform === 'youtube').length)}</td></tr>`,
      `<tr><td>Reddit</td><td>${fmt(items.filter(i => i.platform === 'reddit').length)}</td></tr>`,
    ].join('');

    dropEl.innerHTML = [
      `<tr><td>low_views</td><td>${fmt(dropped.low_views || 0)}</td></tr>`,
      `<tr><td>low_score</td><td>${fmt(dropped.low_score || 0)}</td></tr>`,
      `<tr><td>lang_mismatch</td><td>${fmt(dropped.lang_mismatch || 0)}</td></tr>`,
    ].join('');

    if (window.updateInlineMetrics) window.updateInlineMetrics();
  };
  
  // Override renderResults to use window.currentRun
  window.renderResults = function() {
    const run = getCurrentRun();
    try {
      if (window.populateFilterSuggestions) window.populateFilterSuggestions();
    } catch (err) {
      console.error('[IM] populateFilterSuggestions failed', err);
    }
    if (window.updateInlineMetrics) window.updateInlineMetrics();
    if (window.updateSortIndicatorsParents) window.updateSortIndicatorsParents();
    
    const items = window.getFilteredSortedItems();
    if (window.renderParentsRows) window.renderParentsRows(items);
    
    const total = run ? (run.manifest?.items?.length || 0) : 0;
    const filteredCount = window.getFilteredSortedItems(true).length;
    const pageSz = getPageSize();
    const pg = getPage();
    
    const rowCountEl = document.getElementById('rowCount');
    if (rowCountEl) {
      rowCountEl.textContent = `Filtered ${filteredCount} / Total ${total} — Showing ${(items.length ? ((pg - 1) * pageSz + 1) : 0)}–${((pg - 1) * pageSz + items.length)}`;
    }
    
    if (window.updateExportMeta) window.updateExportMeta();
  };
  
  // Override updateExportMeta to use window.currentRun
  window.updateExportMeta = function() {
    const run = getCurrentRun();
    const exportMetaEl = document.getElementById('exportMeta');
    if (!exportMetaEl) return;
    
    if (!run) {
      exportMetaEl.textContent = '';
      return;
    }
    
    if (getCurrentView() === 'parents') {
      const n = window.getFilteredSortedItems(true).length;
      const total = run.manifest?.items?.length || 0;
      exportMetaEl.textContent = `Subset: ${n} of ${total} items`;
    } else {
      const n = window.getFilteredSortedComments ? window.getFilteredSortedComments(true).length : 0;
      const total = window.allCommentsOfRun().length;
      exportMetaEl.textContent = `Subset: ${n} of ${total} comments`;
    }
  };
  
  // Override renderActiveView to use our overridden functions
  window.renderActiveView = function() {
    if (getCurrentView() === 'comments') {
      window.renderCommentsTable();
    } else {
      window.renderResults();
    }
  };
  
  // Override renderCommentsTable to use window.currentRun and our pagination
  let bridgeCommentRenderToken = 0;
  window.renderCommentsTable = function() {
    if (window.populateFilterSuggestions) window.populateFilterSuggestions();
    if (window.updateSortIndicatorsComments) window.updateSortIndicatorsComments();
    const tb = document.getElementById('commentsBody');
    if (!tb) return;
    tb.innerHTML = '';
    const renderToken = ++bridgeCommentRenderToken;
    
    const rows = window.getFilteredSortedComments();
    let i = 0, n = rows.length, batch = 80;
    
    const YT_ICON = '<span class="yt-icon" aria-label="YouTube"><svg viewBox="0 0 24 18" xmlns="http://www.w3.org/2000/svg"><rect x="0" y="0" width="24" height="18" rx="3" fill="#FF0000"></rect><polygon points="10,5 18,9 10,13" fill="#FFFFFF"></polygon></svg></span>';
    const RD_ICON = '👽';
    const fmt = window.fmt || (v => v == null ? '' : v);
    const escapeHtml = window.escapeHtml || (s => s);
    
    function step() {
      if (renderToken !== bridgeCommentRenderToken) return;
      const frag = document.createDocumentFragment();
      for (let j = 0; j < batch && i < n; j++, i++) {
        const r = rows[i];
        const icon = r.platform === 'youtube' ? YT_ICON : RD_ICON;
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${icon} ${r.platform}</td>
          <td class="comment-cell">
            <div class="copy-wrap" style="min-height:32px">
              <div class="resizable mono copy-target copy-top-left">${escapeHtml(r.text)}</div>
              <button class="copy-btn top-left" type="button" onclick="copyFromSibling(this)" title="Copy comment">⧉</button>
            </div>
          </td>
          <td>${r.authorUrl ? `<a href="${r.authorUrl}" target="_blank" rel="noopener">${escapeHtml(r.author || '')}</a>` : escapeHtml(r.author || '')}</td>
          <td title="${escapeHtml(r.parentTitle)}"><a href="${r.parentUrl}" target="_blank" rel="noopener">${escapeHtml((r.parentTitle || '').slice(0, 80))}${(r.parentTitle || '').length > 80 ? '…' : ''}</a></td>
          <td>${r.ctx ? (r.ctxUrl ? `<a href="${r.ctxUrl}" target="_blank" rel="noopener">${escapeHtml(r.ctx)}</a>` : escapeHtml(r.ctx)) : ''}</td>
          <td>${fmt(r.likes)}</td>
          <td>${(r.date || '').slice(0, 10)}</td>
          <td><a href="${r.url}" target="_blank" rel="noopener">Comment</a></td>`;
        frag.appendChild(tr);
      }
      tb.appendChild(frag);
      if (i < n && renderToken === bridgeCommentRenderToken) {
        requestAnimationFrame(step);
      } else {
        const total = window.allCommentsOfRun().length;
        const filteredTotal = window.getFilteredSortedComments(true).length;
        const pageSz = getPageSize();
        const pg = getPage();
        const countEl = document.getElementById('commentsCount');
        if (countEl) {
          countEl.textContent = `Filtered ${filteredTotal} / Total ${total} comments — Showing ${rows.length ? ((pg - 1) * pageSz + 1) : 0}–${(pg - 1) * pageSz + rows.length}`;
        }
        if (window.updateExportMeta) window.updateExportMeta();
        document.querySelectorAll('#commentsBody .resizable').forEach(el => {
          if (window.ensureSized) window.ensureSized(el);
        });
      }
    }
    requestAnimationFrame(step);
  };
  
  // Override updateInlineMetrics to use window.currentRun
  window.updateInlineMetrics = function() {
    const wrap = document.getElementById('inlineMetrics');
    if (!wrap) return;
    wrap.innerHTML = '';
    
    const run = getCurrentRun();
    if (!run) return;
    
    const items = window.filtered ? window.filtered(run.manifest?.items || []) : (run.manifest?.items || []);
    const yt = items.filter(i => i.platform === 'youtube');
    const rd = items.filter(i => i.platform === 'reddit');
    const comments = items.reduce((a, i) => a + (i.comments?.length || 0), 0);
    const drops = run.stats?.dropped || {};
    const droppedCount = (drops.low_views || 0) + (drops.low_score || 0) + (drops.lang_mismatch || 0);
    
    const fmt = window.fmt || (v => v);
    const mk = (label, val) => `<span class="metric"><b>${fmt(val)}</b> ${label}</span>`;
    wrap.innerHTML = [mk('items', items.length), mk('YouTube', yt.length), mk('Reddit', rd.length), mk('comments', comments), mk('dropped', droppedCount)].join(' ');
  };
  
  // Override fetchTranscript to use the bridge API (with visual debug)
  window.fetchTranscript = async function(id, btn) {
    const orig = btn ? btn.textContent : 'Fetch';
    const setBtn = (txt, bg) => { if(btn){ btn.textContent=txt; if(bg) btn.style.background=bg; } };
    
    setBtn('[1] Starting...', '');
    
    const run = getCurrentRun();
    if (!run) { 
      setBtn('ERR: No run', '#f99');
      setTimeout(() => { if(btn){ btn.textContent=orig; btn.disabled=false; btn.style.background=''; } }, 3000);
      return; 
    }
    setBtn('[2] Got run...', '');
    
    const it = (run.manifest?.items || []).find(x => x.id === id);
    if (!it) { 
      setBtn('ERR: No item', '#f99');
      setTimeout(() => { if(btn){ btn.textContent=orig; btn.disabled=false; btn.style.background=''; } }, 3000);
      return; 
    }
    setBtn('[3] Got item...', '');
    
    if (it.transcript) {
      setBtn(orig, '');
      btn.disabled = false;
      const ok = confirm("Transcript already exists. Re-fetch from source?");
      if (!ok) return;
    }
    
    const block = document.getElementById('tr-' + id);
    const textEl = document.getElementById('tr-text-' + id);
    const errEl = document.getElementById('tr-err-' + id);
    
    if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
    if (btn) btn.disabled = true;
    
    setBtn('[4] API: ' + id.slice(0,8) + '...', '#ff9');
    
    try {
      const runId = run.id || '';
      console.log('[IM] Calling fetch_transcript with id:', id, 'runId:', runId);
      const result = await api.fetch_transcript(id, runId, 'en');
      console.log('[IM] Result:', result);
      setBtn('[5] Got response...', '');
      
      if (result && result.ok) {
        it.transcript = result.text;
        if (block) block.style.display = 'block';
        const fmt = window.formatTranscript || (t => t);
        if (textEl) { textEl.textContent = fmt(result.text); if (window.ensureSized) window.ensureSized(textEl); }
        // Update transcript dot indicator
        const dot = document.getElementById('trdot-' + id);
        if (dot) { dot.classList.add('on'); dot.title = 'Transcript available'; }
        // Show source info (free = no cost, paid = uses API credits)
        const isFree = result.source === 'free';
        setBtn(isFree ? '✓ Free' : '✓ Paid', isFree ? '#9f9' : '#fd9');
        // Show toast with source info
        if (window.showToast) {
          window.showToast(isFree ? 'Transcript fetched (free)' : 'Transcript fetched (used API credits)');
        }
        setTimeout(() => { if(btn){ btn.textContent='Refetch transcript'; btn.style.background=''; btn.disabled=false; } }, 3000);
      } else {
        const errMsg = (result && result.error) || 'Unknown error';
        if (errEl) { errEl.style.display = 'block'; errEl.textContent = errMsg; }
        setBtn('ERR: ' + errMsg.slice(0, 20), '#f99');
        setTimeout(() => { if(btn){ btn.textContent=orig; btn.disabled=false; btn.style.background=''; } }, 5000);
      }
    } catch (e) {
      const errMsg = String(e);
      if (errEl) { errEl.style.display = 'block'; errEl.textContent = 'Error: ' + errMsg; }
      setBtn('CATCH: ' + errMsg.slice(0, 15), '#f99');
      setTimeout(() => { if(btn){ btn.textContent=orig; btn.disabled=false; btn.style.background=''; } }, 5000);
    }
  };
  
  // Add hooks to sync ui.html's internal variables to window when they change
  // These intercept UI interactions to keep window.* in sync
  
  // View toggle (Parents/Comments)
  const viewSeg = document.getElementById('viewSeg');
  if (viewSeg) {
    viewSeg.addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (btn && btn.dataset.val) {
        window._im_currentView = btn.dataset.val;
        window.currentView = btn.dataset.val;
        window._im_page = 1;  // Reset page on view change
      }
    }, true);  // Capture phase to run before ui.html's handler
  }
  
  // Page size change
  const pageSizeEl = document.getElementById('pageSize');
  if (pageSizeEl) {
    pageSizeEl.addEventListener('change', () => {
      window._im_pageSize = parseInt(pageSizeEl.value, 10) || 25;
      window._im_page = 1;
    }, true);
  }
  
  // Pagination buttons
  const prevPageBtn = document.getElementById('prevPage');
  const nextPageBtn = document.getElementById('nextPage');
  if (prevPageBtn) {
    prevPageBtn.addEventListener('click', () => {
      window._im_page = Math.max(1, getPage() - 1);
    }, true);
  }
  if (nextPageBtn) {
    nextPageBtn.addEventListener('click', () => {
      const total = window.totalPagesForActiveView();
      window._im_page = Math.min(total, getPage() + 1);
    }, true);
  }
})();

;(function(){
  if (!(window.pywebview && window.pywebview.api)) return;
  const api = window.pywebview.api;

  // Shorten path for display (tail only)
  function shortPath(p){
    if(!p) return "(not set)";
    const max = 18;
    if(p.length <= max) return p;
    return "..." + p.slice(-max);
  }

  // Create the control in the SAME ROW as the three checkboxes (right-aligned)
  function mountOutCtrl(){
    if(document.getElementById("outDirChip")) return true;  // only once
    const rd = document.getElementById("enableReddit");
    const row = rd ? rd.closest(".row") : null;
    if(!row) return false;

    const chip = document.createElement("div");
    chip.id = "outDirChip";
    chip.className = "row nowrap";
    chip.style.gap = "6px";
    chip.style.marginLeft = "auto";
    chip.style.alignItems = "center";
    chip.innerHTML = `
      <span class="small" style="opacity:.85">out</span>
      <span id="outDirLabel" class="small mono"
            style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer;text-decoration:underline;"
            title="(loading)...">(loading...)</span>
    `;
    row.appendChild(chip);

    const labelEl = chip.querySelector("#outDirLabel");
    const handleChoose = async ()=>{
      try{
        const res = await api.choose_out_dir();
        if(res && res.ok){
          updateOut(res.out_dir);
          window.log && window.log("Output folder set to: " + res.out_dir);
          if (window.updateCmd) window.updateCmd();
        } else if(res && res.error){
          alert("Failed to choose folder: " + res.error);
        }
      }catch(err){ alert("Failed to choose folder: " + err); }
    };
    labelEl && labelEl.addEventListener("click", handleChoose);
    chip.addEventListener("click", (e)=>{ if(e.target === chip) handleChoose(); });

    return true;
  }

  function updateOut(path){
    const lab = document.getElementById("outDirLabel");
    if(lab){ lab.textContent = shortPath(path||""); lab.title = path||""; }
    // Optionally inform preview wrapper about current out dir
    window.IM_OUT_DIR = path || "";
  }

  async function refreshOutFromBackend(){
    try{
      const res = await api.get_output_dir();
      updateOut(res && res.out_dir);
      if (window.updateCmd) window.updateCmd();
    }catch(_){}
  }

  // Listen for Python push (e.g., after choose_out_dir / set_output_dir)
  window.IMBridge = window.IMBridge || {};
  const prevReceive = window.IMBridge.receive;
  window.IMBridge.receive = function(type, payload){
    if (type === "out_dir_changed"){
      updateOut(payload && payload.out_dir);
      if (window.updateCmd) window.updateCmd();
      return;
    }
    if (prevReceive) return prevReceive(type, payload);
  };

  // When Settings modal is saved in your existing code, just ensure to call refreshOutFromBackend afterward.
  // If your Save button has id=saveSettingsBtn (as in previous step), hook it:
  function hookSettingsSave(){
    const btn = document.getElementById("saveSettingsBtn");
    if (!btn || btn.dataset._od_hook) return;
    btn.dataset._od_hook = "1";
    btn.addEventListener("click", ()=> setTimeout(refreshOutFromBackend, 60));
  }

  function initOutCtrl(){
    const mounted = mountOutCtrl();
    if (mounted){
      refreshOutFromBackend();
      hookSettingsSave();
    } else {
      setTimeout(initOutCtrl, 120);
    }
  }

  if (document.readyState === "complete" || document.readyState === "interactive") {
    initOutCtrl();
  } else {
    window.addEventListener("load", initOutCtrl);
  }
  const openSettings = document.getElementById("openSettings");
  openSettings && openSettings.addEventListener("click", ()=> setTimeout(hookSettingsSave, 0));
})();

(function(){
  if (!(window.pywebview && window.pywebview.api)) return;
  const api = window.pywebview.api;

  // --- Helpers ---------------------------------------------------------------
  function on(el, ev, fn){ if(el) el.addEventListener(ev, fn); }
  function collect(){ return (window.collectKnobs ? window.collectKnobs() : {}); }

  // Keep Output folder and preview in sync.
  async function refreshOutDirAndPreview(){
    try{
      const r = await api.get_output_dir();                   // -> { out_dir }
      const path = (r && r.out_dir) ? r.out_dir : "";
      window.IM_OUT_DIR = path;                               // expose for buildCli wrapper
      wrapBuildCli();
      window.updateCmd && window.updateCmd();
    }catch(_){}
  }

  // When Output folder changes from Python side, update preview
  window.IMBridge = window.IMBridge || {};
  const prevReceive = window.IMBridge.receive;
  window.IMBridge.receive = function(type, payload){
    if (type === "out_dir_changed") {
      window.IM_OUT_DIR = (payload && payload.out_dir) || "";
      window.updateCmd && window.updateCmd();
      return;
    }
    if (prevReceive) return prevReceive(type, payload);
  };

  // Bind a robust "live update" on all Collect inputs (if not already)
  const ids = ["topic","since","subs","ytMaxVideos","rdMaxPosts","redditSelector",
               "redditQuery","ytComments","ytMinViews","rdComments","rdMinScore",
               "lang","dedupe","redditSearchSort","redditSearchTime","redditTopTime"];
  ids.forEach(id => { const el=document.getElementById(id); if(el){ el.addEventListener("input", ()=> window.updateCmd && window.updateCmd()); }});
  // Source toggles also update preview
  ["enableYoutube","enableReddit","enableTranscripts"].forEach(id=>{
    const el=document.getElementById(id); if(el){ el.addEventListener("change", ()=> window.updateCmd && window.updateCmd()); }
  });

  // If Settings modal is saved/closed, preview should refresh (IM_OUT_DIR may change)
  on(document.getElementById("closeSettingsBtn"), "click", ()=> setTimeout(refreshOutDirAndPreview, 80));
  document.addEventListener("click", (e)=>{ if(e.target && e.target.id==="saveSettingsBtn") setTimeout(refreshOutDirAndPreview, 80); });

  // Wrap buildCli ONCE so preview always includes --out and respects connector toggles
  function wrapBuildCli(){
    if (!window.buildCli || window.buildCli.__im_wrapped) return;
    const baseBuildCli = window.buildCli;
    const wrappedBuildCli = function(knobs){
      let s = baseBuildCli(knobs);
      const p = (window.IM_OUT_DIR || "").trim();
      if (p && !/\s--out\b/.test(s)) s += " --out " + JSON.stringify(p);
      return s.trim();
    };
    wrappedBuildCli.__im_wrapped = true;
    window.buildCli = wrappedBuildCli;
  }

  // Rebind Run so we execute EXACTLY the preview string
  function rebindRun(){
    const runBtn = document.getElementById("runBtn");
    if(!runBtn || runBtn.dataset._im_bind) return;
    const clone = runBtn.cloneNode(true);
    runBtn.parentNode.replaceChild(clone, runBtn);
    clone.dataset._im_bind = "1";
    clone.addEventListener("click", async ()=>{
      const canRun = (document.getElementById("enableYoutube")?.checked || document.getElementById("enableReddit")?.checked);
      if(!canRun){ alert("Enable at least one source to run."); return; }
      // 1) Get the exact preview text (already includes --out due to wrapper)
      const cmdEl = document.getElementById("cmd");
      const previewText = cmdEl ? (typeof cmdEl.value === "string" ? cmdEl.value : (cmdEl.textContent || "")) : "";
      const cmd = (previewText || (window.buildCli ? window.buildCli(collect()) : "")).trim();
      if(!cmd){ alert("Command preview is empty."); return; }
      const yt = !!document.getElementById("enableYoutube")?.checked;
      const rd = !!document.getElementById("enableReddit")?.checked;
      const transcriptMode = document.getElementById("transcriptMode")?.value || "off";
      const transcriptLang = document.getElementById("lang")?.value || "en";
      const W=(id,v)=>{ const el=document.getElementById(id); if(el) el.style.width=Math.max(0,Math.min(100,v||0))+'%'; };
      const T=(id,t)=>{ const el=document.getElementById(id); if(el) el.textContent=String(t||0); };
      W('progOverall',0); if(yt) W('progYT',0); if(rd) W('progRD',0); resetCountersForRun(); T('rdCount','0');
      try {
        await api.start_collect_cmd(cmd, { youtube: yt, reddit: rd }, transcriptMode, transcriptLang);
      } catch (e) {
        console.error("start_collect_cmd failed", e);
        alert("Failed to start: " + e);
      }
    });
  }

  // Initial sync
  const init = async ()=>{
    rebindRun();
    await refreshOutDirAndPreview();
    stripMockBadges();
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, {once:true}); else init();

  // --- Visibility tweaks for disabled sources (hide item chips / progress) ---
  function syncSourceVisibility(){
    const ytOn = !!document.getElementById("enableYoutube")?.checked;
    const rdOn = !!document.getElementById("enableReddit")?.checked;
    const chips = document.querySelectorAll(".item-chips .item-chip");
    if (chips[0]) chips[0].style.display = ytOn ? "inline-flex" : "none";
    if (chips[1]) chips[1].style.display = rdOn ? "inline-flex" : "none";
    const ytProg = document.getElementById("ytProgWrap");
    const rdProg = document.getElementById("rdProgWrap");
    if (ytProg) ytProg.style.display = ytOn ? "block" : "none";
    if (rdProg) rdProg.style.display = rdOn ? "block" : "none";
  }
  ["enableYoutube","enableReddit"].forEach(id=>{
    const el = document.getElementById(id);
    if (el && !el.dataset._im_vis){
      el.dataset._im_vis = "1";
      el.addEventListener("change", syncSourceVisibility);
    }
  });
  syncSourceVisibility();

  // --- Strip mock-only labels in real app ---
  function stripMockBadges(){
    document.querySelectorAll(".badge").forEach(b=>{
      const t = (b.textContent || "").toLowerCase();
      if (t.includes("self") || t.includes("network")) b.style.display = "none";
    });
    document.querySelectorAll(".small").forEach(el=>{
      const t = (el.textContent || "").toLowerCase();
      if (t.includes("this mock simulates")) el.style.display = "none";
    });
  }
})();

;(function(){
  if (!(window.pywebview && window.pywebview.api)) return;
  const api = window.pywebview.api;

  function setWidth(id, pct){
    const el = document.getElementById(id);
    if (el) el.style.width = Math.max(0, Math.min(100, +pct||0)) + '%';
  }
  function setLiveStatus(state){
    const spin = document.getElementById('liveSpinner');
    const check = document.getElementById('liveCheck');
    if (!spin || !check) return;
    if (state === 'running'){
      spin.classList.remove('hidden');
      check.classList.remove('show');
    } else if (state === 'done'){
      spin.classList.add('hidden');
      check.classList.add('show');
    } else {
      spin.classList.add('hidden');
      check.classList.remove('show');
    }
  }
  setLiveStatus('idle');
  let ytPar=0, ytCom=0, rdPar=0, rdCom=0;
  function setChip(id, par, com){
    const el = document.getElementById(id);
    if (!el) return;
    const p = par==null ? 0 : par;
    const c = com==null ? 0 : com;
    el.textContent = `${p}/${c}`;
  }
  function updateCountsFromPayload(p){
    if (Number.isInteger(p.yt_par)) ytPar = p.yt_par;
    if (Number.isInteger(p.yt_com)) ytCom = p.yt_com;
    const ytEl = document.getElementById('ytCount');
    if (ytEl) ytEl.textContent = `${ytPar}/${ytCom}`;

    const aliasesPar = [p.reddit_par, p.reddit_parents, p.rd_par, p?.items?.reddit?.parents, p?.reddit?.parents];
    const aliasesCom = [p.reddit_com, p.reddit_comments, p.rd_com, p?.items?.reddit?.comments, p?.reddit?.comments];
    const par = aliasesPar.find(v => Number.isInteger(v));
    const com = aliasesCom.find(v => Number.isInteger(v));
    if (Number.isInteger(par)) rdPar = par;
    if (Number.isInteger(com)) rdCom = com;
    const rdEl = document.getElementById('rdCount');
    if (rdEl) rdEl.textContent = `${rdPar}/${rdCom}`;
  }
  function show(sel, on){ const el=document.querySelector(sel); if(el) el.style.display = on ? 'block' : 'none'; }

  window.IMBridge = window.IMBridge || {};
  const prevReceive = window.IMBridge.receive;
  window.IMBridge.receive = function(type, payload){
    if (type === 'yt_counts') {
      const p = (payload && Number.isFinite(payload.parents)) ? payload.parents : 0;
      const c = (payload && Number.isFinite(payload.comments)) ? payload.comments : 0;
      const el = document.getElementById('ytCount');
      if (el) el.textContent = `${p}/${c}`;
      return;
    }
    if (type === 'rd_counts') {
      const p = (payload && Number.isFinite(payload.parents)) ? payload.parents : 0;
      const c = (payload && Number.isFinite(payload.comments)) ? payload.comments : 0;
      const el = document.getElementById('rdCount');
      if (el) el.textContent = `${p}/${c}`;
      rdPar = p;
      rdCom = c;
      return;
    }
    if (type === 'counts'){
      updateCountsFromPayload(payload || {});
      return;
    }
    if (type === 'progress_reset'){
      const sel = payload && payload.selected || {youtube:true, reddit:true};
      setWidth('progOverall', 0);
      setWidth('progYT', 0); setChip('ytCount', 0, 0); show('#ytProgWrap', !!sel.youtube);
      setWidth('progRD', 0); setChip('rdCount', 0, 0); show('#rdProgWrap', !!sel.reddit);
      setLiveStatus('running');
      return;
    }
    if (type === 'progress'){
      const p = payload || {};
      if (p.overall != null) setWidth('progOverall', p.overall);
      if (p.youtube != null) setWidth('progYT', p.youtube);
      if (p.reddit  != null) setWidth('progRD', p.reddit);
      updateCountsFromPayload(p);
      const done = (p.overall != null && p.overall >= 100) &&
                   (p.youtube == null || p.youtube >= 100) &&
                   (p.reddit == null  || p.reddit >= 100);
      setLiveStatus(done ? 'done' : 'running');
      return;
    }
    if (prevReceive) return prevReceive(type, payload);
  };
})();

// ========== RESULTS TAB WIRING ==========
;(function(){
  if (!(window.pywebview && window.pywebview.api)) return;
  const api = window.pywebview.api;

  // Track if we've loaded full run data (summaries vs full)
  let loadedRunIds = new Set();
  let isLoadingRun = false;

  /**
   * Load full run data from Python backend and update UI state
   */
  async function loadFullRun(runId) {
    if (isLoadingRun) return;
    isLoadingRun = true;
    try {
      const res = await api.get_run(runId);
      if (res && res.ok && res.run) {
        loadedRunIds.add(runId);
        // Mark as fully loaded
        res.run._needsFullLoad = false;
        window.currentRun = res.run;
        
        // Update runs array with the full run data
        if (window.runs) {
          const idx = window.runs.findIndex(r => r.id === runId);
          if (idx >= 0) {
            window.runs[idx] = res.run;
          }
        }
        
        // Render the results
        if (window.renderActiveView) window.renderActiveView();
        if (window.renderTelemetry) window.renderTelemetry();
        
        // Update the label
        const lbl = document.getElementById('runBtnLabel');
        if (lbl && window.runDesc) lbl.textContent = window.runDesc(res.run);
        
        // Close dropdown
        if (window.openRunMenu) window.openRunMenu(false);
      } else {
        console.error('[IM] get_run failed:', res && res.error);
      }
    } catch (err) {
      console.error('[IM] loadFullRun error:', err);
    } finally {
      isLoadingRun = false;
    }
  }

  /**
   * Override the run menu population to load full data on selection
   */
  function wireRunSelection() {
    // Hook into populateRunMenu to add our click handlers
    const origPopulate = window.populateRunMenu;
    if (!origPopulate) return;
    
    window.populateRunMenu = function() {
      // Call original to build the menu
      origPopulate.apply(this, arguments);
      
      // Re-wire click handlers on run items to load full data
      const runList = document.getElementById('runList');
      if (!runList) return;
      
      runList.querySelectorAll('.run-item').forEach(item => {
        // Find the run this item represents
        const text = item.textContent || '';
        const run = (window.runs || []).find(r => {
          const desc = window.runDesc ? window.runDesc(r) : r.id;
          return desc === text || text.includes(r.id);
        });
        if (!run) return;
        
        // Clone and rebind to intercept click
        const clone = item.cloneNode(true);
        item.parentNode.replaceChild(clone, item);
        clone.addEventListener('click', async (e) => {
          e.preventDefault();
          e.stopPropagation();
          
          // Check if we already have full data (not just a summary)
          const hasFullData = !run._needsFullLoad && loadedRunIds.has(run.id);
          
          if (hasFullData) {
            // Use cached full data
            window.currentRun = run;
            if (window.renderActiveView) window.renderActiveView();
            if (window.renderTelemetry) window.renderTelemetry();
            const lbl = document.getElementById('runBtnLabel');
            if (lbl && window.runDesc) lbl.textContent = window.runDesc(run);
            if (window.openRunMenu) window.openRunMenu(false);
          } else {
            // Load full data from backend
            await loadFullRun(run.id);
          }
        });
      });
    };
  }

  /**
   * Auto-load the latest run when Results tab opens
   */
  function wireResultsTabAutoLoad() {
    const tabs = document.getElementById('tabs');
    if (!tabs) return;
    
    // Use capture phase to run before the existing handler
    tabs.addEventListener('click', async (e) => {
      const t = e.target.closest('.tab');
      if (!t || t.dataset.tab !== 'results') return;
      
      // Give the existing handler time to fetch list_runs
      setTimeout(async () => {
        // If we have runs but no fully-loaded currentRun, load the first one
        if (window.runs && window.runs.length > 0) {
          const firstRun = window.runs[0];
          // Check if this is just a summary (needs full load)
          const needsLoad = firstRun._needsFullLoad || !loadedRunIds.has(firstRun.id);
          
          // Also check if currentRun needs loading
          const currentNeedsLoad = !window.currentRun || 
            window.currentRun._needsFullLoad || 
            !loadedRunIds.has(window.currentRun.id);
          
          if (needsLoad && currentNeedsLoad) {
            await loadFullRun(firstRun.id);
          }
        }
      }, 100);
    }, true);
  }

  /**
   * Handle run_loaded event from backend
   */
  window.IMBridge = window.IMBridge || {};
  const prevReceive = window.IMBridge.receive;
  window.IMBridge.receive = function(type, payload) {
    if (type === 'run_loaded' && payload && payload.run) {
      loadedRunIds.add(payload.run.id);
      window.currentRun = payload.run;
      if (window.renderActiveView) window.renderActiveView();
      if (window.renderTelemetry) window.renderTelemetry();
      const lbl = document.getElementById('runBtnLabel');
      if (lbl && window.runDesc) lbl.textContent = window.runDesc(payload.run);
      return;
    }
    if (prevReceive) return prevReceive(type, payload);
  };

  // Initialize when DOM is ready
  function init() {
    wireRunSelection();
    wireResultsTabAutoLoad();
  }
  
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    // Small delay to ensure ui.html's scripts are loaded
    setTimeout(init, 50);
  }
})();

// ========== PASTE-READY MODAL WIRING ==========
;(function(){
  if (!(window.pywebview && window.pywebview.api)) return;
  const api = window.pywebview.api;

  /**
   * Load paste-ready content from file when "All" is selected
   */
  async function loadPasteReadyFromFile() {
    if (!window.currentRun || !window.currentRun.id) return null;
    try {
      const res = await api.get_paste_ready(window.currentRun.id);
      if (res && res.ok && res.text) {
        return res.text;
      }
    } catch (err) {
      console.error('[IM] get_paste_ready error:', err);
    }
    return null;
  }

  // Override renderPaste to use window.currentRun and load from file when appropriate
  function wirePasteModal() {
    // Completely override renderPaste to use window.currentRun
    window.renderPaste = async function(mode) {
      const run = window.currentRun;
      const preEl = document.getElementById('pastePre');
      const metaEl = document.getElementById('pasteMeta');
      
      if (!run) {
        if (preEl) preEl.textContent = '(run first)';
        if (metaEl) metaEl.textContent = '';
        return;
      }
      
      let text = '', meta = '';
      const currentView = window._im_currentView || 'parents';
      
      if (mode === 'subset') {
        if (currentView === 'parents') {
          const parents = window.getFilteredSortedItems ? window.getFilteredSortedItems(true) : (run.manifest?.items || []);
          const total = run.manifest?.items?.length || 0;
          const exportMode = document.getElementById('exportMode')?.value || 'parents+comments';
          text = exportMode === 'parents+comments' 
            ? (window.buildPasteParentsPlusComments ? window.buildPasteParentsPlusComments(parents) : JSON.stringify(parents, null, 2))
            : (window.buildPasteParentsOnly ? window.buildPasteParentsOnly(parents) : JSON.stringify(parents, null, 2));
          meta = `Subset (${parents.length} of ${total} items) — ${exportMode.replace('+', ' + ')}`;
        } else {
          const rows = window.getFilteredSortedComments ? window.getFilteredSortedComments(true) : [];
          const total = window.allCommentsOfRun ? window.allCommentsOfRun().length : 0;
          text = window.buildPasteFromComments ? window.buildPasteFromComments(rows) : JSON.stringify(rows, null, 2);
          meta = `Subset (${rows.length} of ${total} comments)`;
        }
      } else {
        // "All" mode - use same JS-generated format as subset for consistency
        const parents = run.manifest?.items || [];
        const exportMode = document.getElementById('exportMode')?.value || 'parents+comments';
        text = exportMode === 'parents+comments'
          ? (window.buildPasteParentsPlusComments ? window.buildPasteParentsPlusComments(parents) : JSON.stringify(parents, null, 2))
          : (window.buildPasteParentsOnly ? window.buildPasteParentsOnly(parents) : JSON.stringify(parents, null, 2));
        meta = `All (${parents.length} items) — ${exportMode.replace('+', ' + ')}`;
      }
      
      if (preEl) preEl.textContent = text || '(empty)';
      if (metaEl) metaEl.textContent = meta;
    };
  }

  // Initialize
  function init() {
    wirePasteModal();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    setTimeout(init, 50);
  }
})();

// ========== EXPORT BUTTONS WIRING ==========
;(function(){
  if (!(window.pywebview && window.pywebview.api)) return;
  const api = window.pywebview.api;

  function showToast(msg) {
    const t = document.getElementById('toast');
    if (t) {
      t.textContent = msg;
      t.classList.add('show');
      setTimeout(() => t.classList.remove('show'), 1600);
    }
  }

  /**
   * Wire export JSON button to use native file dialog
   */
  function wireExportJSON() {
    const btn = document.getElementById('exportJSON');
    if (!btn || btn.dataset._im_export) return;
    
    const clone = btn.cloneNode(true);
    btn.parentNode.replaceChild(clone, btn);
    clone.dataset._im_export = '1';
    
    clone.addEventListener('click', async () => {
      if (!window.currentRun) {
        alert('No run selected');
        return;
      }
      
      const view = window._im_currentView || window.currentView || 'parents';
      const mode = document.getElementById('exportMode')?.value || 'parents+comments';
      
      try {
        if (view === 'parents') {
          const parents = window.getFilteredSortedItems ?
                         window.getFilteredSortedItems(true) :
                         (window.currentRun.manifest?.items || []);
          
          if (mode === 'parents-only') {
            // Strip comments
            const stripped = parents.map(p => {
              const { comments, ...rest } = p;
              return rest;
            });
            const res = await api.export_json(stripped, 'parents.json');
            if (res && res.ok) showToast(`Exported ${stripped.length} parents`);
            else if (res && !res.cancelled) alert('Export failed: ' + (res.error || 'unknown'));
          } else {
            // Parents with comments
            const res = await api.export_json(parents, 'parents_with_comments.json');
            if (res && res.ok) showToast(`Exported ${parents.length} items with comments`);
            else if (res && !res.cancelled) alert('Export failed: ' + (res.error || 'unknown'));
          }
        } else {
          // Comments view
          const rows = window.getFilteredSortedComments ? 
                      window.getFilteredSortedComments(true) : [];
          const res = await api.export_json(rows, 'comments.json');
          if (res && res.ok) showToast(`Exported ${rows.length} comments`);
          else if (res && !res.cancelled) alert('Export failed: ' + (res.error || 'unknown'));
        }
      } catch (err) {
        console.error('[IM] export_json error:', err);
        alert('Export failed: ' + err);
      }
    });
  }

  /**
   * Wire export CSV button to use native file dialog
   */
  function wireExportCSV() {
    const btn = document.getElementById('exportCSV');
    if (!btn || btn.dataset._im_export) return;
    
    const clone = btn.cloneNode(true);
    btn.parentNode.replaceChild(clone, btn);
    clone.dataset._im_export = '1';
    
    clone.addEventListener('click', async () => {
      if (!window.currentRun) {
        alert('No run selected');
        return;
      }
      
      const view = window._im_currentView || window.currentView || 'parents';
      
      try {
        if (view === 'parents') {
          const parents = window.getFilteredSortedItems ?
                         window.getFilteredSortedItems(true) :
                         (window.currentRun.manifest?.items || []);
          
          // Transform to flat CSV rows
          const rows = parents.map(p => ({
            platform: p.platform,
            title: p.title || '',
            author: p.author || '',
            context: p.platform === 'youtube' ? (p.context?.channel || '') : (p.context?.subreddit || ''),
            score_or_likes: p.platform === 'youtube' ? (p.metrics?.likes || 0) : (p.metrics?.score || 0),
            replies: p.metrics?.replies || 0,
            views: p.metrics?.views || '',
            created_at: p.created_at || '',
            url: p.url || '',
            transcript: p.transcript || ''
          }));
          
          const columns = ['platform', 'title', 'author', 'context', 'score_or_likes', 
                          'replies', 'views', 'created_at', 'url', 'transcript'];
          
          const res = await api.export_csv(rows, columns, 'parents.csv');
          if (res && res.ok) showToast(`Exported ${rows.length} parents to CSV`);
          else if (res && !res.cancelled) alert('Export failed: ' + (res.error || 'unknown'));
        } else {
          // Comments view
          const comments = window.getFilteredSortedComments ? 
                          window.getFilteredSortedComments(true) : [];
          
          const rows = comments.map(c => ({
            platform: c.platform,
            comment: c.text || '',
            author: c.author || '',
            parent_title: c.parentTitle || '',
            context: c.ctx || '',
            likes_or_score: c.likes || 0,
            date: c.date || '',
            url: c.url || ''
          }));
          
          const columns = ['platform', 'comment', 'author', 'parent_title', 
                          'context', 'likes_or_score', 'date', 'url'];
          
          const res = await api.export_csv(rows, columns, 'comments.csv');
          if (res && res.ok) showToast(`Exported ${rows.length} comments to CSV`);
          else if (res && !res.cancelled) alert('Export failed: ' + (res.error || 'unknown'));
        }
      } catch (err) {
        console.error('[IM] export_csv error:', err);
        alert('Export failed: ' + err);
      }
    });
  }

  /**
   * Wire paste-ready download button to use native file dialog
   */
  function wirePasteDownload() {
    // The download button in paste modal uses onclick="downloadText(...)"
    // We'll override the downloadText function
    const origDownload = window.downloadText;
    
    window.downloadText = async function(name, text) {
      if (window.pywebview && window.pywebview.api) {
        try {
          const res = await api.export_text(text, name);
          if (res && res.ok) showToast(`Saved ${name}`);
          else if (res && !res.cancelled) alert('Save failed: ' + (res.error || 'unknown'));
          return;
        } catch (err) {
          console.error('[IM] export_text error:', err);
        }
      }
      // Fallback to original
      if (origDownload) return origDownload.apply(this, arguments);
    };
  }

  // Initialize
  function init() {
    wireExportJSON();
    wireExportCSV();
    wirePasteDownload();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    setTimeout(init, 100);
  }
})();

// ========== UI RESILIENCE WIRING ==========
;(function(){
  if (!(window.pywebview && window.pywebview.api)) return;

  const debounce = window.debounce || ((fn, ms) => {
    let t = null;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...args), ms);
    };
  });

  function cloneRebind(id, handler, eventName = 'click') {
    const el = document.getElementById(id);
    if (!el) return null;
    const clone = el.cloneNode(true);
    el.parentNode.replaceChild(clone, el);
    clone.addEventListener(eventName, handler);
    return clone;
  }

  function bindOnce(el, key, eventName, handler, options) {
    if (!el || el.dataset[key]) return;
    el.dataset[key] = '1';
    el.addEventListener(eventName, handler, options);
  }

  function switchTab(tabName) {
    document.querySelectorAll('.tab').forEach(tab => {
      tab.classList.toggle('active', tab.dataset.tab === tabName);
    });
    document.querySelectorAll('[data-page]').forEach(page => {
      page.style.display = page.getAttribute('data-page') === tabName ? 'block' : 'none';
    });
  }

  function setStatusChip(id, label, enabled) {
    const el = document.getElementById(id);
    if (!el) return;
    el.className = 'status-chip ' + (enabled ? 'status-ok' : 'status-off');
    el.textContent = `${label}: ${enabled ? 'enabled' : 'disabled'}`;
  }

  function syncCollectState() {
    const ytOn = !!document.getElementById('enableYoutube')?.checked;
    const rdOn = !!document.getElementById('enableReddit')?.checked;
    const transcriptMode = document.getElementById('transcriptMode')?.value || 'off';
    const transcriptOn = transcriptMode !== 'off';

    setStatusChip('ytStatus', 'YouTube', ytOn);
    setStatusChip('rdStatus', 'Reddit', rdOn);

    const trStatus = document.getElementById('trStatus');
    if (trStatus) {
      trStatus.className = 'status-chip ' + (transcriptOn ? 'status-ok' : '');
      trStatus.textContent = `Transcripts: ${transcriptMode}`;
    }

    const ytProgWrap = document.getElementById('ytProgWrap');
    const rdProgWrap = document.getElementById('rdProgWrap');
    if (ytProgWrap) ytProgWrap.style.display = ytOn ? 'block' : 'none';
    if (rdProgWrap) rdProgWrap.style.display = rdOn ? 'block' : 'none';

    const chips = document.querySelectorAll('.item-chips .item-chip');
    if (chips[0]) chips[0].style.display = ytOn ? 'inline-flex' : 'none';
    if (chips[1]) chips[1].style.display = rdOn ? 'inline-flex' : 'none';

    const runBtn = document.getElementById('runBtn');
    const runHint = document.getElementById('runHint');
    const canRun = ytOn || rdOn;
    if (runBtn) runBtn.disabled = !canRun;
    if (runHint) runHint.style.display = canRun ? 'none' : 'inline';
  }

  function pulse(el) {
    if (!el || !el.classList) return;
    el.classList.add('active-pulse');
    setTimeout(() => el.classList.remove('active-pulse'), 260);
  }

  function applyQuickSince(days, btn) {
    const since = document.getElementById('since');
    if (!since || Number.isNaN(days)) return;
    const d = new Date();
    d.setDate(d.getDate() - days);
    since.value = d.toISOString().slice(0, 10);
    pulse(since);
    pulse(btn);
    if (window.updateCmd) window.updateCmd();
  }

  function wireCollectInteractions() {
    document.querySelectorAll('.quick-since').forEach(btn => {
      bindOnce(btn, '_im_quick_since', 'click', () => {
        applyQuickSince(parseInt(btn.dataset.days || '0', 10), btn);
      });
    });

    document.querySelectorAll('.topic-idea').forEach(btn => {
      bindOnce(btn, '_im_topic_idea', 'click', () => {
        const topic = document.getElementById('topic');
        if (!topic) return;
        topic.value = btn.dataset.topic || '';
        topic.focus();
        pulse(topic);
        pulse(btn);
        if (window.updateCmd) window.updateCmd();
      });
    });

    ['enableYoutube', 'enableReddit', 'transcriptMode'].forEach(id => {
      const eventName = id === 'transcriptMode' ? 'change' : 'change';
      const el = document.getElementById(id);
      bindOnce(el, `_im_collect_${id}`, eventName, () => {
        syncCollectState();
        if (window.updateCmd) window.updateCmd();
      });
    });

    cloneRebind('openSubredditPicker', () => {
      if (window.openSubredditModal) window.openSubredditModal();
    });
    cloneRebind('closeSubredditsBtn', () => {
      if (window.closeSubredditModal) window.closeSubredditModal();
    });
    cloneRebind('addSubredditBtn', () => {
      if (window.addSubreddit) window.addSubreddit();
    });

    const subredditInput = document.getElementById('subredditInput');
    bindOnce(subredditInput, '_im_subreddit_enter', 'keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        if (window.addSubreddit) window.addSubreddit();
      }
    });

    cloneRebind('explain', () => {
      const knobs = window.collectKnobs ? window.collectKnobs() : {};
      const buildCli = window.buildCli || (() => '');
      const pre = document.getElementById('explainPre');
      const modal = document.getElementById('modalExplain');
      if (pre) pre.textContent = JSON.stringify({ knobs, cli: buildCli(knobs) }, null, 2);
      if (window.ensureSized && pre) window.ensureSized(pre);
      if (modal) modal.style.display = 'block';
    });

    syncCollectState();
  }

  function ensureCollectTabWorks() {
    const tabs = document.getElementById('tabs');
    bindOnce(tabs, '_im_collect_tab', 'click', (e) => {
      const tab = e.target.closest('.tab');
      if (!tab || tab.dataset.tab !== 'collect') return;
      e.stopImmediatePropagation();
      switchTab('collect');
      const menu = document.getElementById('runMenu');
      if (menu) menu.style.display = 'none';
    }, true);
  }

  function readParentFilters() {
    return {
      title: document.getElementById('f_title')?.value || '',
      author: document.getElementById('f_author')?.value || '',
      ctx: document.getElementById('f_ctx')?.value || '',
      score: document.getElementById('f_score')?.value || '',
      replies: document.getElementById('f_replies')?.value || '',
      views: document.getElementById('f_views')?.value || '',
      date: document.getElementById('f_date')?.value || '',
    };
  }

  function readCommentFilters() {
    return {
      text: document.getElementById('cf_text')?.value || '',
      author: document.getElementById('cf_author')?.value || '',
      parent: document.getElementById('cf_parent')?.value || '',
      ctx: document.getElementById('cf_ctx')?.value || '',
      likes: document.getElementById('cf_likes')?.value || '',
      date: document.getElementById('cf_date')?.value || '',
    };
  }

  function parseNumFilterSafe(input, value) {
    if (window.parseNumFilter) return window.parseNumFilter(input, value);
    const s = (input || '').trim();
    if (!s) return true;
    if (s.startsWith('>=')) return value >= (+s.slice(2));
    if (s.startsWith('<=')) return value <= (+s.slice(2));
    if (s.startsWith('>')) return value > (+s.slice(1));
    if (s.startsWith('<')) return value < (+s.slice(1));
    return String(value).includes(s);
  }

  function parentSortState() {
    if (!window._im_sortKey) window._im_sortKey = 'created_at';
    if (!window._im_sortDir) window._im_sortDir = 'desc';
    return { key: window._im_sortKey, dir: window._im_sortDir };
  }

  function commentSortState() {
    if (!window._im_cSortKey) window._im_cSortKey = 'c_date';
    if (!window._im_cSortDir) window._im_cSortDir = 'desc';
    return { key: window._im_cSortKey, dir: window._im_cSortDir };
  }

  function currentParentPlatform() {
    return window._im_parentPlatform ||
      document.querySelector('#platformSegParents button.active')?.dataset.val ||
      'all';
  }

  function currentCommentPlatform() {
    return window._im_commentPlatform ||
      document.querySelector('#platformSegComments button.active')?.dataset.val ||
      'all';
  }

  function parentKey(it, key) {
    switch (key) {
      case 'platform': return it.platform;
      case 'title': return it.title || '';
      case 'author': return it.author || '';
      case 'context': return it.platform === 'youtube' ? (it.context?.channel || '') : (it.context?.subreddit || '');
      case 'metrics_score': return it.platform === 'youtube' ? (it.metrics?.likes || 0) : (it.metrics?.score || 0);
      case 'metrics_replies': return it.metrics?.replies || 0;
      case 'metrics_views': return it.metrics?.views || 0;
      case 'created_at': return new Date(it.created_at || 0).getTime();
      default: return '';
    }
  }

  function filterParents(items) {
    const filters = readParentFilters();
    const platform = currentParentPlatform();
    let rows = (items || []).slice();

    if (platform !== 'all') rows = rows.filter(item => item.platform === platform);
    if (filters.title) rows = rows.filter(item => (item.title || '').toLowerCase().includes(filters.title.toLowerCase()));
    if (filters.author) rows = rows.filter(item => (item.author || '').toLowerCase().includes(filters.author.toLowerCase()));
    if (filters.ctx) rows = rows.filter(item => {
      const ctx = item.platform === 'youtube' ? (item.context?.channel || '') : (item.context?.subreddit || '');
      return ctx.toLowerCase().includes(filters.ctx.toLowerCase());
    });
    if (filters.score) rows = rows.filter(item => parseNumFilterSafe(filters.score, item.platform === 'youtube' ? (item.metrics?.likes || 0) : (item.metrics?.score || 0)));
    if (filters.replies) rows = rows.filter(item => parseNumFilterSafe(filters.replies, item.metrics?.replies || 0));
    if (filters.views) rows = rows.filter(item => parseNumFilterSafe(filters.views, item.metrics?.views || 0));
    if (filters.date) rows = rows.filter(item => (item.created_at || '').slice(0, 7).includes(filters.date));

    const sort = parentSortState();
    if (sort.dir !== 'none' && sort.key) {
      rows.sort((a, b) => {
        const va = parentKey(a, sort.key);
        const vb = parentKey(b, sort.key);
        if (va == null && vb == null) return 0;
        if (va == null) return 1;
        if (vb == null) return -1;
        if (typeof va === 'number' && typeof vb === 'number') return sort.dir === 'asc' ? va - vb : vb - va;
        return sort.dir === 'asc' ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
      });
    }

    return rows;
  }

  function filterComments(rows) {
    const filters = readCommentFilters();
    const platform = currentCommentPlatform();
    let items = (rows || []).slice();

    if (platform !== 'all') items = items.filter(row => row.platform === platform);
    if (filters.text) items = items.filter(row => (row.text || '').toLowerCase().includes(filters.text.toLowerCase()));
    if (filters.author) items = items.filter(row => (row.author || '').toLowerCase().includes(filters.author.toLowerCase()));
    if (filters.parent) items = items.filter(row => (row.parentTitle || '').toLowerCase().includes(filters.parent.toLowerCase()));
    if (filters.ctx) items = items.filter(row => (row.ctx || '').toLowerCase().includes(filters.ctx.toLowerCase()));
    if (filters.likes) items = items.filter(row => parseNumFilterSafe(filters.likes, row.likes || 0));
    if (filters.date) items = items.filter(row => (row.date || '').slice(0, 7).includes(filters.date));

    const sort = commentSortState();
    if (sort.dir !== 'none' && sort.key) {
      items.sort((a, b) => {
        const get = (row) => {
          switch (sort.key) {
            case 'c_platform': return row.platform;
            case 'c_text': return row.text || '';
            case 'c_author': return row.author || '';
            case 'c_parent': return row.parentTitle || '';
            case 'c_ctx': return row.ctx || '';
            case 'c_likes': return row.likes || 0;
            case 'c_date': return new Date(row.date || 0).getTime();
            default: return '';
          }
        };
        const va = get(a);
        const vb = get(b);
        if (typeof va === 'number' && typeof vb === 'number') return sort.dir === 'asc' ? va - vb : vb - va;
        return sort.dir === 'asc' ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
      });
    }

    return items;
  }

  window.updateSortIndicatorsParents = function() {
    const sort = parentSortState();
    document.querySelectorAll('#resultsTable th.sortable').forEach(th => {
      const ind = th.querySelector('.sort-ind');
      if (!ind) return;
      ind.textContent = '';
      if (th.dataset.key === sort.key) {
        ind.textContent = sort.dir === 'asc' ? '▲' : (sort.dir === 'desc' ? '▼' : '•');
      }
    });
  };

  window.updateSortIndicatorsComments = function() {
    const sort = commentSortState();
    document.querySelectorAll('#commentsTable th.sortable').forEach(th => {
      const ind = th.querySelector('.sort-ind');
      if (!ind) return;
      ind.textContent = '';
      if (th.dataset.key === sort.key) {
        ind.textContent = sort.dir === 'asc' ? '▲' : (sort.dir === 'desc' ? '▼' : '•');
      }
    });
  };

  window.getFilteredSortedItems = function(noPaging = false) {
    const run = window.currentRun;
    if (!run) return [];
    const items = filterParents(run.manifest?.items || []);
    if (noPaging) return items;

    const pageSize = window._im_pageSize || 25;
    let page = window._im_page || 1;
    const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
    page = Math.max(1, Math.min(page, totalPages));
    window._im_page = page;

    const pageInfo = document.getElementById('pageInfo');
    if (pageInfo) pageInfo.textContent = `Page ${page} / ${totalPages}`;

    const start = (page - 1) * pageSize;
    return items.slice(start, start + pageSize);
  };

  window.getParentsSubset = function() {
    return window.getFilteredSortedItems(true);
  };

  window.getFilteredSortedComments = function(noPaging = false) {
    const comments = filterComments(window.allCommentsOfRun ? window.allCommentsOfRun() : []);
    if (noPaging) return comments;

    const pageSize = window._im_pageSize || 25;
    let page = window._im_page || 1;
    const totalPages = Math.max(1, Math.ceil(comments.length / pageSize));
    page = Math.max(1, Math.min(page, totalPages));
    window._im_page = page;

    const pageInfo = document.getElementById('pageInfo');
    if (pageInfo) pageInfo.textContent = `Page ${page} / ${totalPages}`;

    const start = (page - 1) * pageSize;
    return comments.slice(start, start + pageSize);
  };

  window.updateInlineMetrics = function() {
    const wrap = document.getElementById('inlineMetrics');
    if (!wrap) return;
    wrap.innerHTML = '';

    const run = window.currentRun;
    if (!run) return;

    const items = window.getFilteredSortedItems ? window.getFilteredSortedItems(true) : (run.manifest?.items || []);
    const yt = items.filter(item => item.platform === 'youtube');
    const rd = items.filter(item => item.platform === 'reddit');
    const comments = items.reduce((count, item) => count + (item.comments?.length || 0), 0);
    const drops = run.stats?.dropped || {};
    const fmt = window.fmt || (value => value);
    const mk = (label, value) => `<span class="metric"><b>${fmt(value)}</b> ${label}</span>`;
    wrap.innerHTML = [
      mk('items', items.length),
      mk('YouTube', yt.length),
      mk('Reddit', rd.length),
      mk('comments', comments),
      mk('dropped', (drops.low_views || 0) + (drops.low_score || 0) + (drops.lang_mismatch || 0)),
    ].join(' ');
  };

  function rebindResultsControls() {
    const parentSortHeaders = document.querySelectorAll('#resultsTable th.sortable');
    parentSortHeaders.forEach(th => {
      bindOnce(th, '_im_parent_sort', 'click', (e) => {
        e.stopImmediatePropagation();
        const key = th.dataset.key;
        if (!key) return;
        if (window._im_sortKey === key) {
          window._im_sortDir = window._im_sortDir === 'asc' ? 'desc' : (window._im_sortDir === 'desc' ? 'none' : 'asc');
        } else {
          window._im_sortKey = key;
          window._im_sortDir = 'asc';
        }
        window._im_page = 1;
        if (window.renderResults) window.renderResults();
      }, true);
    });

    const commentSortHeaders = document.querySelectorAll('#commentsTable th.sortable');
    commentSortHeaders.forEach(th => {
      bindOnce(th, '_im_comment_sort', 'click', (e) => {
        e.stopImmediatePropagation();
        const key = th.dataset.key;
        if (!key) return;
        if (window._im_cSortKey === key) {
          window._im_cSortDir = window._im_cSortDir === 'asc' ? 'desc' : (window._im_cSortDir === 'desc' ? 'none' : 'asc');
        } else {
          window._im_cSortKey = key;
          window._im_cSortDir = 'asc';
        }
        window._im_page = 1;
        if (window.renderCommentsTable) window.renderCommentsTable();
      }, true);
    });

    ['f_title','f_author','f_ctx','f_score','f_replies','f_views','f_date'].forEach(id => {
      const el = document.getElementById(id);
      bindOnce(el, `_im_filter_${id}`, 'input', debounce(() => {
        window._im_page = 1;
        if (window.renderResults) window.renderResults();
      }, 120));
    });

    ['cf_text','cf_author','cf_parent','cf_ctx','cf_likes','cf_date'].forEach(id => {
      const el = document.getElementById(id);
      bindOnce(el, `_im_filter_${id}`, 'input', debounce(() => {
        window._im_page = 1;
        if (window.renderCommentsTable) window.renderCommentsTable();
      }, 120));
    });

    const parentSeg = document.getElementById('platformSegParents');
    bindOnce(parentSeg, '_im_parent_seg', 'click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      parentSeg.querySelectorAll('button').forEach(node => node.classList.remove('active'));
      btn.classList.add('active');
      window._im_parentPlatform = btn.dataset.val || 'all';
      window._im_page = 1;
      if (window.renderResults) window.renderResults();
    }, true);

    const commentSeg = document.getElementById('platformSegComments');
    bindOnce(commentSeg, '_im_comment_seg', 'click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      commentSeg.querySelectorAll('button').forEach(node => node.classList.remove('active'));
      btn.classList.add('active');
      window._im_commentPlatform = btn.dataset.val || 'all';
      window._im_page = 1;
      if (window.renderCommentsTable) window.renderCommentsTable();
    }, true);

    window.openRunMenu = function(show = true) {
      const menu = document.getElementById('runMenu');
      if (!menu) return;
      menu.style.display = show ? 'block' : 'none';
      if (show) {
        const search = document.getElementById('runSearch');
        if (search) search.focus();
        if (window.populateRunMenu) window.populateRunMenu();
      }
    };

    cloneRebind('runBtnOpen', () => {
      const menu = document.getElementById('runMenu');
      const isOpen = menu && menu.style.display === 'block';
      if (window.openRunMenu) window.openRunMenu(!isOpen);
    });

    const runSearch = document.getElementById('runSearch');
    bindOnce(runSearch, '_im_run_search', 'input', () => {
      if (window.populateRunMenu) window.populateRunMenu();
    });
  }

  function init() {
    if (window._im_currentView === undefined) window._im_currentView = 'parents';
    if (window.currentView === undefined) window.currentView = window._im_currentView;
    if (window._im_parentPlatform === undefined) window._im_parentPlatform = 'all';
    if (window._im_commentPlatform === undefined) window._im_commentPlatform = 'all';

    ensureCollectTabWorks();
    wireCollectInteractions();
    rebindResultsControls();
    if (window.updateSortIndicatorsParents) window.updateSortIndicatorsParents();
    if (window.updateSortIndicatorsComments) window.updateSortIndicatorsComments();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    setTimeout(init, 0);
  }
})();
