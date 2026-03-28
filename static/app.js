// State
let currentControlId = null;
let currentRunId = null;
let currentSortOrder = 'desc'; // 'asc' or 'desc'
let allRunsGlobal = [];

// --- localStorage Cache Helpers ---
const RUNS_CACHE_KEY = 'sox_runs_cache';

function getRunsFromCache() {
    try { return JSON.parse(localStorage.getItem(RUNS_CACHE_KEY) || '[]'); }
    catch { return []; }
}

function saveRunsToCache(runs) {
    try { localStorage.setItem(RUNS_CACHE_KEY, JSON.stringify(runs)); }
    catch (e) { console.warn('Cache write failed', e); }
}

function mergeRunsWithCache(serverRuns) {
    const cache = getRunsFromCache();
    const merged = {};
    // Cache first (baseline), then server data wins (most up-to-date)
    cache.forEach(r => { merged[r.id] = r; });
    serverRuns.forEach(r => { merged[r.id] = r; });
    return Object.values(merged).sort((a, b) => b.id - a.id);
}

function upsertRunInCache(run) {
    const cache = getRunsFromCache();
    const idx = cache.findIndex(r => r.id === run.id);
    if (idx >= 0) cache[idx] = run; else cache.push(run);
    saveRunsToCache(cache);
}

// Format a UTC datetime string from the DB into Chicago local time
// Handles DST automatically: shows CDT (UTC-5) or CST (UTC-6) as appropriate
function formatChicagoTimestamp(isoString) {
    const raw = isoString ? (isoString.endsWith('Z') ? isoString : isoString + 'Z') : null;
    const d = raw ? new Date(raw) : new Date(NaN);
    if (isNaN(d.getTime())) return 'N/A';
    const datePart = d.toLocaleString('en-US', {
        timeZone: 'America/Chicago',
        month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit',
        hour12: false
    });
    const tzAbbr = new Intl.DateTimeFormat('en-US', {
        timeZone: 'America/Chicago', timeZoneName: 'short'
    }).formatToParts(d).find(p => p.type === 'timeZoneName')?.value || 'CT';
    return `${datePart} ${tzAbbr}`;
}

// Initialization
document.addEventListener('DOMContentLoaded', () => {
    loadControls();
    loadDashboardRuns();
});

// Navigation Helpers
function hideAllViews() {
    document.getElementById('view-dashboard').classList.add('hidden');
    document.getElementById('view-create-control').classList.add('hidden');
    document.getElementById('view-control-detail').classList.add('hidden');
}

function hideWorkspaces() {
    document.getElementById('workspace-new-run').classList.add('hidden');
    document.getElementById('workspace-analysis').classList.add('hidden');
    document.getElementById('workspace-empty').classList.add('hidden');
}

function showDashboard() {
    hideAllViews();
    document.getElementById('view-dashboard').classList.remove('hidden');
    
    const breadcrumb = document.getElementById('top-breadcrumb');
    if (breadcrumb) {
        breadcrumb.classList.add('hidden');
        breadcrumb.classList.remove('flex');
    }
    
    const sidebarTitle = document.getElementById('sidebar-title');
    if (sidebarTitle) sidebarTitle.innerText = "Global History";
    
    const newRunCont = document.getElementById('sidebar-new-run-container');
    if (newRunCont) newRunCont.classList.add('hidden');
    
    loadControls();
    loadDashboardRuns();
}

function showCreateControl() {
    hideAllViews();
    document.getElementById('form-create-control').reset();
    document.getElementById('view-create-control').classList.remove('hidden');
}

// API Interactions & Render Logic - Controls
async function loadControls() {
    const list = document.getElementById('controls-list');
    list.innerHTML = `<li class="p-4 text-center text-gray-500">Loading controls...</li>`;
    
    try {
        const res = await fetch('/api/controls/');
        const data = await res.json();
        
        if (data.length === 0) {
            list.innerHTML = `<li class="p-8 text-center text-gray-500">No controls yet. Click <strong>New Procedure</strong> to create your first control.</li>`;
            return;
        }
        
        list.innerHTML = '';
        data.forEach(control => {
            const shortDesc = control.description.length > 100 ? control.description.substring(0, 100) + '...' : control.description;
            const item = document.createElement('li');
            item.className = "hover:bg-slate-100 dark:hover:bg-slate-800 cursor-pointer transition border-b border-slate-100 dark:border-slate-800 last:border-0";
            item.innerHTML = `
                <div class="px-4 py-4 flex items-center justify-between" onclick="openControl(${control.id})">
                    <div>
                        <p class="text-xs font-bold text-ui-lightText dark:text-ui-darkText uppercase tracking-wider">Control ID: ${control.id}</p>
                        <p class="mt-1 text-sm text-slate-600 dark:text-slate-400 font-medium">${shortDesc}</p>
                    </div>
                    <div class="ml-4 flex-shrink-0">
                        <i class="fas fa-chevron-right text-slate-400"></i>
                    </div>
                </div>
            `;
            list.appendChild(item);
        });
    } catch (e) {
        console.error(e);
        list.innerHTML = `<li class="p-4 text-center text-red-500">Failed to load controls. Is backend running?</li>`;
    }
}

async function loadDashboardRuns() {
    try {
        const response = await fetch('/api/test_runs/');
        const serverRuns = await response.json();
        // Merge server runs with locally cached runs so history survives cold starts
        const merged = mergeRunsWithCache(serverRuns);
        saveRunsToCache(merged);
        allRunsGlobal = merged;
        renderDashboardRuns();
    } catch (e) {
        console.error('Dashboard runs failed', e);
        // Fall back to cache on network/server error
        allRunsGlobal = getRunsFromCache();
        renderDashboardRuns();
    }
}

function toggleSort() {
    currentSortOrder = currentSortOrder === 'desc' ? 'asc' : 'desc';
    
    // Update icons
    const sidebarIcon = document.getElementById('sidebar-sort-icon');
    const dashIcon = document.getElementById('dash-sort-icon');
    
    if (currentSortOrder === 'asc') {
        if (sidebarIcon) sidebarIcon.className = "fas fa-sort-amount-up";
        if (dashIcon) dashIcon.className = "fas fa-sort-amount-up-alt";
    } else {
        if (sidebarIcon) sidebarIcon.className = "fas fa-sort-amount-down";
        if (dashIcon) dashIcon.className = "fas fa-sort-amount-down-alt";
    }
    
    renderDashboardRuns();
}

function renderDashboardRuns() {
    const list = document.getElementById('dashboard-runs-list');
    const sidebarList = document.getElementById('sidebar-runs-list');
    
    if (list) list.innerHTML = `<li class="p-4 text-center text-slate-500">Loading...</li>`;
    if (sidebarList) sidebarList.innerHTML = `<div class="animate-pulse space-y-4"><div class="h-12 bg-slate-100 dark:bg-slate-800 rounded-lg"></div></div>`;

    // Sort local copy
    const runs = [...allRunsGlobal].sort((a, b) => {
        const dateA = new Date(a.created_at || 0);
        const dateB = new Date(b.created_at || 0);
        return currentSortOrder === 'desc' ? dateB - dateA : dateA - dateB;
    });

    if (list) list.innerHTML = '';
    if (sidebarList) sidebarList.innerHTML = '';

    if (runs.length === 0) {
        const empty = '<li class="p-8 text-center text-slate-400 font-medium italic">No test runs yet.</li>';
        if (list) list.innerHTML = empty;
        if (sidebarList) sidebarList.innerHTML = empty;
        return;
    }

    runs.forEach(run => {
        let statusStyle = "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400";
        let icon = "fa-clock";

        if (run.status === 'Analyzed') {
            statusStyle = "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400";
            icon = "fa-check-double";
        } else if (run.status === 'Error') {
            statusStyle = "bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-400";
            icon = "fa-exclamation-triangle";
        } else if (run.status === 'Analyzing...') {
            statusStyle = "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 animate-pulse";
            icon = "fa-sync fa-spin";
        }

        // Real formatted date
        const timestamp = formatChicagoTimestamp(run.created_at);

        const renderItem = (isSidebar) => `
            <div class="px-4 py-3 group cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors" onclick="openControlAndRun(${run.control_id}, ${run.id})">
                <div class="flex justify-between items-center mb-1">
                    <span class="font-bold text-xs text-ui-lightText dark:text-ui-darkText">Run #${run.id}</span>
                    <span class="px-2 py-0.5 rounded-md text-[10px] font-bold ${statusStyle} uppercase tracking-wider border border-current opacity-90">${run.status}</span>
                </div>
                <div class="flex items-center gap-2 text-[10px] text-slate-500 dark:text-slate-400 font-bold">
                    <i class="fas ${icon}"></i>
                    <span>Rating: ${run.rating ? run.rating.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) : 'Pending'}</span>
                    <span class="ml-auto opacity-60">${timestamp}</span>
                </div>
            </div>
        `;

        if (list) {
            const item = document.createElement('li');
            item.innerHTML = renderItem(false);
            list.appendChild(item);
        }

        if (sidebarList) {
            const sidebarItem = document.createElement('div');
            sidebarItem.className = "bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm hover:shadow-md hover:border-ui-accent transition-all";
            sidebarItem.innerHTML = renderItem(true);
            sidebarList.appendChild(sidebarItem);
        }
    });
}

async function openControlAndRun(controlId, runId) {
    await openControl(controlId);
    openRun(runId);
}

async function handleCreateControl(e) {
    e.preventDefault();
    const btn = document.getElementById('btn-create-control');
    btn.innerHTML = "Saving...";
    btn.disabled = true;

    const desc = document.getElementById('control-desc').value;
    const proc = document.getElementById('control-proc').value;
    
    const formData = new FormData();
    formData.append('description', desc);
    formData.append('test_procedure', proc);

    try {
        const res = await fetch('/api/controls/', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        openControl(data.id);
    } catch (e) {
        alert("Error creating control");
        console.error(e);
    } finally {
        btn.innerHTML = "Save Control";
        btn.disabled = false;
    }
}

async function openControl(id) {
    currentControlId = id;
    hideAllViews();
    
    document.getElementById('view-control-detail').classList.remove('hidden');
    document.getElementById('detail-desc').innerText = "Loading...";
    hideWorkspaces();
    document.getElementById('workspace-empty').classList.remove('hidden');
    
    // UI specific to the workspace mode
    const breadcrumb = document.getElementById('top-breadcrumb');
    if (breadcrumb) {
        breadcrumb.classList.add('flex');
        breadcrumb.classList.remove('hidden');
    }
    const sidebarTitle = document.getElementById('sidebar-title');
    if (sidebarTitle) sidebarTitle.innerText = `Control #${id} Runs`;
    
    const newRunCont = document.getElementById('sidebar-new-run-container');
    if (newRunCont) newRunCont.classList.remove('hidden');
    
    // Fetch details
    try {
        const res = await fetch(`/api/controls/${id}`);
        const control = await res.json();
        document.getElementById('detail-desc').innerText = control.description;
        document.getElementById('detail-proc').innerText = control.test_procedure;
        
        loadTestRuns(id);
    } catch (e) {
        console.error("Failed fetching control", e);
    }
}

// API Interactions & Render Logic - Test Runs
async function loadTestRuns(controlId) {
    // Re-use the master sidebar list instead of a local card list
    const list = document.getElementById('sidebar-runs-list');
    list.innerHTML = `<div class="p-4 text-center text-slate-500">Loading runs for control...</div>`;
    
    try {
        const res = await fetch(`/api/test_runs/?control_id=${controlId}`);
        const data = await res.json();
        
        if (data.length === 0) {
            list.innerHTML = `<div class="p-8 text-center text-slate-400 font-medium italic">No test runs executed for this control yet.</div>`;
            return;
        }
        
        list.innerHTML = '';
        data.forEach(run => {
            let statusStyle = "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400";
            let icon = "fa-clock";

            if (run.status === 'Analyzed') {
                statusStyle = "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400";
                icon = "fa-check-double";
            } else if (run.status === 'Error') {
                statusStyle = "bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-400";
                icon = "fa-exclamation-triangle";
            } else if (run.status === 'Analyzing...') {
                statusStyle = "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 animate-pulse";
                icon = "fa-sync fa-spin";
            }

            const timestamp = formatChicagoTimestamp(run.created_at);
            
            const item = document.createElement('div');
            item.className = "bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm hover:shadow-md hover:border-ui-accent transition-all";
            item.innerHTML = `
                <div class="px-4 py-3 group cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors" onclick="openRun(${run.id})">
                    <div class="flex justify-between items-center mb-1">
                        <span class="font-bold text-xs text-ui-lightText dark:text-ui-darkText">Run #${run.id}</span>
                        <span class="px-2 py-0.5 rounded-md text-[10px] font-bold ${statusStyle} uppercase tracking-wider border border-current opacity-90">${run.status}</span>
                    </div>
                    <div class="flex items-center gap-2 text-[10px] text-slate-500 dark:text-slate-400 font-bold">
                        <i class="fas ${icon}"></i>
                        <span>Rating: ${run.rating ? run.rating.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) : 'Pending'}</span>
                        <span class="ml-auto opacity-60">${timestamp}</span>
                    </div>
                </div>
            `;
            list.appendChild(item);
        });
    } catch (e) {
        console.error("Failed fetching runs", e);
    }
}

function showCreateRun() {
    hideWorkspaces();
    document.getElementById('form-create-run').reset();
    document.getElementById('run-control-id').value = currentControlId;
    document.getElementById('workspace-new-run').classList.remove('hidden');
}

async function handleCreateRun(e) {
    e.preventDefault();
    const btn = document.getElementById('btn-create-run');
    btn.innerHTML = "Uploading...";
    btn.disabled = true;

    const fileInput = document.getElementById('run-files');
    const files = fileInput.files;
    
    if (files.length > 3) {
        alert("Maximum 3 files allowed based on requirements.");
        btn.innerHTML = "Upload & Create Run";
        btn.disabled = false;
        return;
    }

    const formData = new FormData();
    formData.append('control_id', currentControlId);
    
    for (let i = 0; i < files.length; i++) {
        formData.append('files', files[i]);
    }

    try {
        const res = await fetch('/api/test_runs/', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        upsertRunInCache(data);          // persist new run immediately
        await loadDashboardRuns();       // refresh global history
        loadTestRuns(currentControlId);
        openRun(data.id);
    } catch (ex) {
        alert("Error creating run");
        console.error(ex);
    } finally {
        btn.innerHTML = "Upload & Create Run";
        btn.disabled = false;
    }
}

let pollingInterval = null;

async function openRun(id) {
    currentRunId = id;
    hideWorkspaces();
    document.getElementById('workspace-analysis').classList.remove('hidden');
    
    if (pollingInterval) clearInterval(pollingInterval);
    
    await fetchAndRenderRunStatus(id);
}

async function fetchAndRenderRunStatus(id) {
    try {
        const res = await fetch(`/api/test_runs/${id}`);
        const run = await res.json();
        
        document.getElementById('ar-run-id').innerText = run.id;
        document.getElementById('ar-status').innerText = run.status;
        
        const analyzeBtn = document.getElementById('btn-analyze');
        
        if (run.status === 'Pending') {
            analyzeBtn.style.display = 'block';
            analyzeBtn.disabled = false;
            analyzeBtn.innerHTML = `<i class="fas fa-robot mr-2"></i> Analyze Evidence`;
            analyzeBtn.className = "bg-green-600 hover:bg-green-700 text-white font-medium py-2 px-4 rounded-md shadow transition flex items-center";
            
            document.getElementById('ar-rating').innerText = "Pending Analysis";
            document.getElementById('ar-rating').className = "text-xl font-bold p-2 rounded inline-block bg-gray-200 text-gray-600";
            document.getElementById('ar-issues').innerHTML = "Click analyze to start.";
            document.getElementById('ar-issues').className = "text-sm whitespace-pre-wrap text-gray-500 font-medium";
            document.getElementById('ar-checklist-body').innerHTML = `<tr><td colspan="3" class="px-4 py-4 text-center text-gray-500">Run analysis to view checklist...</td></tr>`;
            document.getElementById('ar-summary').innerHTML = "Files uploaded, awaiting parsing.";
            document.getElementById('ar-workpaper').value = "";
            
        } else if (run.status === 'Analyzing...') {
            analyzeBtn.style.display = 'block';
            analyzeBtn.disabled = true;
            analyzeBtn.innerHTML = `<i class="fas fa-circle-notch fa-spin mr-2"></i> Analyzing...`;
            analyzeBtn.className = "bg-gray-400 text-white font-medium py-2 px-4 rounded-md shadow flex items-center cursor-not-allowed";
            
            document.getElementById('ar-rating').innerText = "Analyzing...";
            document.getElementById('ar-rating').className = "text-xl font-bold p-2 rounded inline-block bg-blue-100 text-blue-800 animate-pulse";
            document.getElementById('ar-issues').innerHTML = "Reading documents and applying control criteria...";
            document.getElementById('ar-checklist-body').innerHTML = `<tr><td colspan="3" class="px-4 py-4 text-center text-blue-500"><i class="fas fa-circle-notch fa-spin mr-2"></i> Analyzing...</td></tr>`;
            
            // Poll every 2 seconds
            pollingInterval = setTimeout(() => fetchAndRenderRunStatus(id), 2000);
            
        } else if (run.status === 'Analyzed') {
            analyzeBtn.style.display = 'none';
            upsertRunInCache(run);       // cache the fully analyzed run
            loadDashboardRuns();         // refresh global history with latest data
            // Re-fetch list to update rating string in sidebar
            loadTestRuns(currentControlId);
            renderAnalysisResults(run);
        } else if (run.status === 'Error') {
             analyzeBtn.style.display = 'block';
             analyzeBtn.disabled = false;
             analyzeBtn.innerHTML = `<i class="fas fa-redo mr-2"></i> Retry Analysis`;
             
             document.getElementById('ar-rating').innerText = "Error";
             document.getElementById('ar-rating').className = "text-xl font-bold p-2 rounded inline-block bg-red-100 text-red-800";
             document.getElementById('ar-issues').innerText = run.issues;
        }
    } catch (e) {
        console.error("Failed fetching test run", e);
    }
}

function renderAnalysisResults(run) {
    // Rating Colors
    const ratingEl = document.getElementById('ar-rating');
    const displayRating = run.rating ? run.rating.replace(/_/g, ' ').toUpperCase() : "UNKNOWN";
    ratingEl.innerText = displayRating;
    if (run.rating === "likely_sufficient") {
        ratingEl.className = "text-xl font-bold p-2 rounded inline-block bg-green-100 text-green-800";
    } else if (run.rating === "likely_insufficient") {
        ratingEl.className = "text-xl font-bold p-2 rounded inline-block bg-red-100 text-red-800";
    } else {
        ratingEl.className = "text-xl font-bold p-2 rounded inline-block bg-yellow-100 text-yellow-800";
    }
    
    // Issues summary
    try {
        const issuesList = JSON.parse(run.issues || "[]");
        if (issuesList.length > 0) {
            document.getElementById('ar-issues').innerText = "• " + issuesList.join("\n• ");
            document.getElementById('ar-issues').className = "text-sm whitespace-pre-wrap text-red-600 font-medium pb-2";
        } else {
            document.getElementById('ar-issues').innerText = "No major issues identified.";
            document.getElementById('ar-issues').className = "text-sm text-green-600 font-medium";
        }
    } catch(e) {
        document.getElementById('ar-issues').innerText = run.issues;
    }

    // Checklist Table
    const tbody = document.getElementById('ar-checklist-body');
    tbody.innerHTML = '';
    if (run.checklist_json) {
        try {
            const checklist = JSON.parse(run.checklist_json);
            const critLabels = {
                "period_matches": "Period Matches",
                "population_complete": "Population Complete",
                "approvals_present": "Approvals Present",
                "timing_sla_met": "Timing SLA Met"
            };
            
            for (const [key, val] of Object.entries(checklist)) { 
                let badgeClass = "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400";
                let icon = '❓';
                let stateText = val ? val.toUpperCase() : "UNKNOWN";
                
                if (val === 'pass') {
                    badgeClass = "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400";
                    icon = '✅';
                } else if (val === 'fail') {
                    badgeClass = "bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-400";
                    icon = '❌';
                } else if (val === 'unclear') {
                    badgeClass = "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400";
                    icon = '❓';
                }
                
                const tr = document.createElement('tr');
                tr.className = "hover:bg-slate-50/50 dark:hover:bg-slate-900/50 transition-colors";
                tr.innerHTML = `
                    <td class="px-6 py-4 font-bold text-slate-700 dark:text-slate-200">${critLabels[key] || key}</td>
                <td class="px-6 py-4 text-center">
                    <span class="inline-flex items-center gap-1.5 px-3 py-1 text-[10px] font-bold rounded-full ${badgeClass} uppercase tracking-wider border border-current">
                        <span>${icon}</span>
                        <span>${stateText}</span>
                    </span>
                </td>
                <td class="px-6 py-4 text-slate-600 dark:text-slate-400">
                    <span class="text-xs font-medium">Evaluation Complete: ${stateText} confirmed by engine.</span>
                </td>
                `;
                tbody.appendChild(tr);
            }
        } catch(e) {
            console.error("Failed to parse checklist JSON", e);
            tbody.innerHTML = `<tr><td colspan="3" class="px-4 py-4 text-center text-red-500">Error parsing checklist JSON</td></tr>`;
        }
    } else {
         tbody.innerHTML = `<tr><td colspan="3" class="px-4 py-4 text-center text-gray-500">No checklist data found</td></tr>`;
    }
    
    // File Summaries
    try {
         const filesArr = JSON.parse(run.summary || "[]");
         let htmlParts = [];
         if (filesArr.length === 0) {
             htmlParts.push("No files analyzed.");
         }
         filesArr.forEach(f => {
            let cols = f.columns ? f.columns.slice(0,4).join(", ") : "";
            if (f.columns && f.columns.length > 4) cols += "...";
            htmlParts.push(`<strong>${f.name}</strong><br>Summary: ${f.summary}<br>${f.rows ? `Rows: ${f.rows}` : ''} ${cols ? `<br>Columns: ${cols}` : ''}<br>Coverage: ${f.date_coverage || 'N/A'}`);
         });
         document.getElementById('ar-summary').innerHTML = htmlParts.join('<br><hr class="my-2">');
    } catch(e) {
         document.getElementById('ar-summary').innerHTML = run.summary || "No data.";
    }
    
    // Workpaper
    document.getElementById('ar-workpaper').value = run.workpaper || "No workpaper generated.";
}

async function handleAnalyze() {
    if (!currentRunId) return;
    const btn = document.getElementById('btn-analyze');
    const oldContent = btn.innerHTML;
    
    // Set loading state immediately
    btn.disabled = true;
    btn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> <span>Processing...</span>`;
    
    try {
        await fetch(`/api/test_runs/${currentRunId}/analyze`, { method: 'POST' });
        // Polling will take care of the rest, but we keep the button in "Analyzing..." state
        fetchAndRenderRunStatus(currentRunId);
    } catch (e) {
         alert("Failed to start analysis");
         btn.disabled = false;
         btn.innerHTML = oldContent;
         console.error(e);
    }
}

function downloadSampleJML() {
    window.location.href = '/api/dev/sample_jml_csv';
}

async function saveWorkpaper() {
    if (!currentRunId) return;
    const btn = document.getElementById('btn-save-wp');
    const oldHtml = btn.innerHTML;
    btn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Saving...`;
    btn.disabled = true;
    
    const text = document.getElementById('ar-workpaper').value;
    try {
        const res = await fetch(`/api/test_runs/${currentRunId}/workpaper`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ workpaper: text })
        });
        if (res.ok) {
            btn.innerHTML = `<i class="fas fa-check"></i> Saved`;
            setTimeout(() => { btn.innerHTML = oldHtml; btn.disabled = false; }, 2000);
        } else {
            throw new Error("Failed to save");
        }
    } catch(e) {
        alert("Error saving workpaper");
        btn.innerHTML = oldHtml;
        btn.disabled = false;
    }
}

function exportWorkpaperTXT() {
    const text = document.getElementById('ar-workpaper').value;
    if (!text) return;
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `workpaper_run_${currentRunId}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

async function exportWorkpaperPDF() {
    const text = document.getElementById('ar-workpaper').value;
    if (!text) return;
    
    try {
        const res = await fetch(`/api/test_runs/${currentRunId}/export_pdf`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ workpaper: text })
        });
        
        if (!res.ok) throw new Error("Failed to generate PDF");
        
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `workpaper_run_${currentRunId}.pdf`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    } catch(e) {
        alert("Error exporting PDF");
        console.error(e);
    }
}
