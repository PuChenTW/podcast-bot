// ---- API wrapper ----
async function api(path, opts = {}) {
    const resp = await fetch('/api' + path, {
        headers: { 'Content-Type': 'application/json' },
        ...opts,
    });
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail || resp.statusText);
    }
    if (resp.status === 204) return null;
    return resp.json();
}

// ---- Router ----
function route() {
    const hash = location.hash || '#/';
    const content = document.getElementById('content');
    content.innerHTML = '';

    if (hash === '#/' || hash === '') {
        renderHome(content);
    } else if (hash.startsWith('#/podcast/')) {
        const parts = hash.slice('#/podcast/'.length).split('?page=');
        const subId = parts[0];
        const page = parts[1] ? parseInt(parts[1], 10) : 0;
        renderEpisodeList(content, subId, page);
    } else if (hash.startsWith('#/episode/')) {
        const parts = hash.slice('#/episode/'.length).split('/');
        const podId = parts[0];
        const guid = decodeURIComponent(parts.slice(1).join('/'));
        renderEpisodeDetail(content, podId, guid);
    } else {
        content.innerHTML = '<p>Page not found.</p>';
    }
}

window.addEventListener('hashchange', route);
window.addEventListener('load', route);

// ---- Home: subscribed podcasts + subscribe form ----
async function renderHome(el) {
    el.innerHTML = '<p class="spinner">Loading subscriptions…</p>';
    try {
        const subs = await api('/subscriptions');
        el.innerHTML = '';

        // Subscribe form
        const form = document.createElement('form');
        form.innerHTML = `
            <input type="url" id="rss-url" placeholder="RSS or Apple Podcasts URL" required>
            <button type="submit">Subscribe</button>
        `;
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const btn = form.querySelector('button');
            const url = document.getElementById('rss-url').value;
            btn.disabled = true;
            btn.textContent = 'Subscribing…';
            try {
                await api('/subscriptions', { method: 'POST', body: JSON.stringify({ rss_url: url }) });
                location.hash = '#/';
            } catch (err) {
                showError(el, err.message);
            } finally {
                btn.disabled = false;
                btn.textContent = 'Subscribe';
            }
        });
        el.appendChild(form);

        if (subs.length === 0) {
            el.insertAdjacentHTML('beforeend', '<p>No subscriptions yet. Add one above.</p>');
            return;
        }

        const grid = document.createElement('div');
        grid.className = 'card-grid';
        for (const sub of subs) {
            const card = document.createElement('div');
            card.className = 'card';
            card.innerHTML = `<h3>${esc(sub.podcast_title)}</h3><p class="subtitle">${esc(sub.rss_url)}</p>`;
            card.addEventListener('click', () => { location.hash = '#/podcast/' + sub.id; });

            // Unsubscribe button
            const delBtn = document.createElement('button');
            delBtn.className = 'danger';
            delBtn.style.marginTop = '0.5rem';
            delBtn.textContent = 'Unsubscribe';
            delBtn.addEventListener('click', async (e) => {
                e.stopPropagation();
                if (!confirm('Unsubscribe from ' + sub.podcast_title + '?')) return;
                await api('/subscriptions/' + sub.id, { method: 'DELETE' });
                location.hash = '#/';
            });
            card.appendChild(delBtn);

            grid.appendChild(card);
        }
        el.appendChild(grid);
    } catch (err) {
        showError(el, err.message);
    }
}

// ---- Episode list ----
async function renderEpisodeList(el, subId, page = 0) {
    el.innerHTML = '<p class="spinner">Loading episodes…</p>';
    try {
        // Fetch subscription metadata and episodes in parallel.
        // podcast_id must be known before rendering rows so click handlers work immediately.
        const [subs, result] = await Promise.all([
            api('/subscriptions'),
            api('/subscriptions/' + subId + '/episodes?page=' + page),
        ]);
        const sub = subs.find(s => s.id === subId);
        if (!sub) { showError(el, 'Subscription not found'); return; }
        const podId = sub.podcast_id;
        const episodes = result.episodes;

        el.innerHTML = `<p><a href="#/">← Back</a></p>`;

        // Custom prompt editor — pre-populate with saved prompt
        const promptSection = document.createElement('details');
        promptSection.innerHTML = '<summary>Custom summarization prompt</summary>';
        const promptArea = document.createElement('textarea');
        promptArea.className = 'prompt-area';
        promptArea.placeholder = 'Leave blank for default prompt';
        promptArea.value = sub.custom_prompt || '';
        const saveBtn = document.createElement('button');
        saveBtn.textContent = 'Save prompt';
        saveBtn.style.marginTop = '0.5rem';
        saveBtn.addEventListener('click', async () => {
            await api('/subscriptions/' + subId + '/prompt', {
                method: 'PUT',
                body: JSON.stringify({ prompt: promptArea.value || null }),
            });
            saveBtn.textContent = 'Saved!';
            setTimeout(() => { saveBtn.textContent = 'Save prompt'; }, 1500);
        });
        promptSection.appendChild(promptArea);
        promptSection.appendChild(saveBtn);
        el.appendChild(promptSection);

        if (episodes.length === 0 && page === 0) {
            el.insertAdjacentHTML('beforeend', '<p>No episodes yet. The bot polls every 6 hours.</p>');
            return;
        }

        for (const ep of episodes) {
            const row = document.createElement('div');
            row.className = 'episode-row';
            row.innerHTML = `
                <span class="episode-title">${esc(ep.title || ep.episode_guid)}</span>
                <span>
                    <span class="episode-date">${ep.published_at ? ep.published_at.slice(0,10) : ''}</span>
                    <span class="badge ${ep.has_summary ? 'badge-yes' : 'badge-no'}">${ep.has_summary ? '✓ Summary' : 'No summary'}</span>
                </span>
            `;
            row.addEventListener('click', () => {
                location.hash = '#/episode/' + podId + '/' + encodeURIComponent(ep.episode_guid);
            });
            el.appendChild(row);
        }

        // Pagination controls
        const nav = document.createElement('div');
        nav.style.cssText = 'display:flex;gap:0.5rem;margin-top:1rem;';
        if (result.has_prev) {
            const prevBtn = document.createElement('button');
            prevBtn.textContent = '← Newer';
            prevBtn.addEventListener('click', () => { location.hash = '#/podcast/' + subId + '?page=' + (page - 1); });
            nav.appendChild(prevBtn);
        }
        if (result.has_next) {
            const nextBtn = document.createElement('button');
            nextBtn.textContent = 'Older →';
            nextBtn.addEventListener('click', () => { location.hash = '#/podcast/' + subId + '?page=' + (page + 1); });
            nav.appendChild(nextBtn);
        }
        if (nav.children.length) el.appendChild(nav);
    } catch (err) {
        showError(el, err.message);
    }
}

// ---- Episode detail ----
async function renderEpisodeDetail(el, podId, guid) {
    el.innerHTML = '<p class="spinner">Loading episode…</p>';
    try {
        const detail = await api('/podcasts/' + podId + '/episodes/' + encodeURIComponent(guid) + '/detail');
        el.innerHTML = `<p><a href="#/">← Back</a></p><h2>${esc(detail.title || guid)}</h2>`;

        // Tabs
        const tabs = ['Summary', 'Transcript', 'Condensed'];
        const tabBar = document.createElement('div');
        tabBar.className = 'tabs';
        const tabPanels = [];

        tabs.forEach((name, i) => {
            const btn = document.createElement('button');
            btn.className = 'tab-btn' + (i === 0 ? ' active' : '');
            btn.textContent = name;
            btn.addEventListener('click', () => {
                tabBar.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                tabPanels.forEach(p => p.classList.remove('active'));
                btn.classList.add('active');
                tabPanels[i].classList.add('active');
            });
            tabBar.appendChild(btn);
        });
        el.appendChild(tabBar);

        // Summary tab
        const summaryPanel = document.createElement('div');
        summaryPanel.className = 'tab-content active';
        if (detail.summary) {
            summaryPanel.innerHTML = marked.parse(detail.summary);
        } else {
            summaryPanel.innerHTML = '<p>No summary yet.</p>';
        }
        // Regenerate button
        const regenBtn = document.createElement('button');
        regenBtn.textContent = 'Regenerate summary';
        regenBtn.style.marginTop = '1rem';
        regenBtn.addEventListener('click', () => startRegenerate(podId, guid, summaryPanel, regenBtn));
        summaryPanel.appendChild(regenBtn);
        tabPanels.push(summaryPanel);
        el.appendChild(summaryPanel);

        // Transcript tab
        const transcriptPanel = document.createElement('div');
        transcriptPanel.className = 'tab-content';
        transcriptPanel.innerHTML = detail.transcript
            ? '<pre style="white-space:pre-wrap;word-break:break-word">' + esc(detail.transcript) + '</pre>'
            : '<p>No transcript available.</p>';
        tabPanels.push(transcriptPanel);
        el.appendChild(transcriptPanel);

        // Condensed tab
        const condensedPanel = document.createElement('div');
        condensedPanel.className = 'tab-content';
        condensedPanel.innerHTML = detail.condensed_transcript
            ? '<pre style="white-space:pre-wrap;word-break:break-word">' + esc(detail.condensed_transcript) + '</pre>'
            : '<p>No condensed transcript available.</p>';
        tabPanels.push(condensedPanel);
        el.appendChild(condensedPanel);
    } catch (err) {
        showError(el, err.message);
    }
}

async function startRegenerate(podId, guid, summaryPanel, regenBtn) {
    regenBtn.disabled = true;
    regenBtn.textContent = 'Regenerating…';
    try {
        const { job_id } = await api('/podcasts/' + podId + '/episodes/' + encodeURIComponent(guid) + '/regenerate', { method: 'POST' });
        pollJob(job_id,
            (result) => {
                // Remove old summary content (keep the button)
                while (summaryPanel.firstChild && summaryPanel.firstChild !== regenBtn) {
                    summaryPanel.removeChild(summaryPanel.firstChild);
                }
                summaryPanel.insertAdjacentHTML('afterbegin', marked.parse(result));
                regenBtn.disabled = false;
                regenBtn.textContent = 'Regenerate summary';
            },
            (errMsg) => {
                summaryPanel.insertAdjacentHTML('afterbegin', `<p class="error-msg">Error: ${esc(errMsg)}</p>`);
                regenBtn.disabled = false;
                regenBtn.textContent = 'Regenerate summary';
            }
        );
    } catch (err) {
        summaryPanel.insertAdjacentHTML('afterbegin', `<p class="error-msg">Error: ${esc(err.message)}</p>`);
        regenBtn.disabled = false;
        regenBtn.textContent = 'Regenerate summary';
    }
}

function pollJob(jobId, onDone, onError) {
    setTimeout(async () => {
        try {
            const job = await api('/jobs/' + jobId);
            if (job.status === 'done') {
                onDone(job.result);
            } else if (job.status === 'error') {
                onError(job.error || 'Unknown error');
            } else {
                pollJob(jobId, onDone, onError); // keep polling
            }
        } catch (err) {
            onError(err.message);
        }
    }, 2000);
}

// ---- Utilities ----
function esc(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function showError(el, msg) {
    el.innerHTML = `<p class="error-msg">Error: ${esc(msg)}</p>`;
}
