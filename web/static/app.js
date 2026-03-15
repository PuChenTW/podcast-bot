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
    el.innerHTML = '<p class="spinner">Loading…</p>';
    setNavCrumb('');
    try {
        const subs = await api('/subscriptions');
        el.innerHTML = '';

        // Subscribe form
        const panel = document.createElement('div');
        panel.className = 'subscribe-panel';
        panel.innerHTML = '<div class="section-label">新增訂閱</div>';
        const form = document.createElement('form');
        form.innerHTML = `
            <input type="url" id="rss-url" placeholder="RSS 或 Apple Podcasts 網址" required>
            <button type="submit">訂閱</button>
        `;
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const btn = form.querySelector('button');
            const url = document.getElementById('rss-url').value;
            btn.disabled = true;
            btn.textContent = '訂閱中…';
            try {
                await api('/subscriptions', { method: 'POST', body: JSON.stringify({ rss_url: url }) });
                location.hash = '#/';
            } catch (err) {
                showError(el, err.message);
            } finally {
                btn.disabled = false;
                btn.textContent = '訂閱';
            }
        });
        panel.appendChild(form);
        el.appendChild(panel);

        if (subs.length === 0) {
            el.insertAdjacentHTML('beforeend', '<div class="empty-state">尚無訂閱，請在上方新增。</div>');
            return;
        }

        el.insertAdjacentHTML('beforeend', '<div class="section-label">我的訂閱</div>');
        const grid = document.createElement('div');
        grid.className = 'card-grid';
        for (const sub of subs) {
            const card = document.createElement('div');
            card.className = 'card';
            card.innerHTML = `<h3>${esc(sub.podcast_title)}</h3><p class="subtitle">${esc(sub.rss_url)}</p>`;
            card.addEventListener('click', () => { location.hash = '#/podcast/' + sub.id; });

            const delBtn = document.createElement('button');
            delBtn.className = 'danger';
            delBtn.textContent = '退訂';
            delBtn.addEventListener('click', async (e) => {
                e.stopPropagation();
                if (!confirm('確定退訂 ' + sub.podcast_title + '？')) return;
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
    el.innerHTML = '<p class="spinner">載入中…</p>';
    try {
        const [subs, result] = await Promise.all([
            api('/subscriptions'),
            api('/subscriptions/' + subId + '/episodes?page=' + page),
        ]);
        const sub = subs.find(s => s.id === subId);
        if (!sub) { showError(el, '找不到訂閱'); return; }
        const podId = sub.podcast_id;
        if (!result || !result.episodes) { showError(el, '伺服器回應異常'); return; }
        const episodes = result.episodes;

        // Breadcrumb navbar
        setNavCrumb(esc(sub.podcast_title));
        el.innerHTML = '';

        // Custom prompt editor
        const promptDetails = document.createElement('details');
        promptDetails.className = 'prompt-details';
        promptDetails.innerHTML = '<summary>自訂摘要提示詞</summary>';
        const promptArea = document.createElement('textarea');
        promptArea.className = 'prompt-area';
        promptArea.placeholder = '留空則使用預設提示詞';
        promptArea.value = sub.custom_prompt || '';
        const saveBtn = document.createElement('button');
        saveBtn.className = 'secondary';
        saveBtn.textContent = '儲存';
        saveBtn.style.marginTop = '0.5rem';
        saveBtn.addEventListener('click', async () => {
            await api('/subscriptions/' + subId + '/prompt', {
                method: 'PUT',
                body: JSON.stringify({ prompt: promptArea.value || null }),
            });
            saveBtn.textContent = '已儲存！';
            setTimeout(() => { saveBtn.textContent = '儲存'; }, 1500);
        });
        promptDetails.appendChild(promptArea);
        promptDetails.appendChild(saveBtn);
        el.appendChild(promptDetails);

        if (episodes.length === 0 && page === 0) {
            el.insertAdjacentHTML('beforeend', '<div class="empty-state">尚無集數，Bot 每 6 小時自動抓取。</div>');
            return;
        }

        const list = document.createElement('div');
        list.className = 'episode-list';
        for (const ep of episodes) {
            const row = document.createElement('div');
            row.className = 'episode-row';
            row.innerHTML = `
                <span class="episode-title">${esc(ep.title || ep.episode_guid)}</span>
                <span class="episode-meta">
                    <span class="episode-date">${ep.published_at ? ep.published_at.slice(0,10) : ''}</span>
                    <span class="badge ${ep.has_summary ? 'badge-yes' : 'badge-no'}">${ep.has_summary ? '✓ 摘要' : '無摘要'}</span>
                </span>
            `;
            row.addEventListener('click', () => {
                location.hash = '#/episode/' + podId + '/' + encodeURIComponent(ep.episode_guid);
            });
            list.appendChild(row);
        }
        el.appendChild(list);

        // Pagination
        const pag = document.createElement('div');
        pag.className = 'pagination';
        if (result.has_prev) {
            const prevBtn = document.createElement('button');
            prevBtn.className = 'secondary';
            prevBtn.textContent = '← 較新';
            prevBtn.addEventListener('click', () => { location.hash = '#/podcast/' + subId + '?page=' + (page - 1); });
            pag.appendChild(prevBtn);
        } else {
            pag.appendChild(document.createElement('span'));
        }
        pag.insertAdjacentHTML('beforeend', `<span class="page-info">第 ${page + 1} 頁</span>`);
        if (result.has_next) {
            const nextBtn = document.createElement('button');
            nextBtn.className = 'secondary';
            nextBtn.textContent = '較舊 →';
            nextBtn.addEventListener('click', () => { location.hash = '#/podcast/' + subId + '?page=' + (page + 1); });
            pag.appendChild(nextBtn);
        } else {
            pag.appendChild(document.createElement('span'));
        }
        el.appendChild(pag);
    } catch (err) {
        showError(el, err.message);
    }
}

// ---- Episode detail ----
async function renderEpisodeDetail(el, podId, guid) {
    el.innerHTML = '<p class="spinner">載入中…</p>';
    try {
        const detail = await api('/podcasts/' + podId + '/episodes/' + encodeURIComponent(guid) + '/detail');

        setNavCrumb(esc(detail.title || guid));
        el.innerHTML = '';

        el.insertAdjacentHTML('beforeend', `<h2 class="episode-detail-title">${esc(detail.title || guid)}</h2>`);

        // Tabs
        const tabNames = ['摘要', '逐字稿', '精簡版'];
        const tabBar = document.createElement('div');
        tabBar.className = 'tabs';
        const tabPanels = [];

        // Summary panel (created early so regenBtn can reference it)
        const summaryPanel = document.createElement('div');
        summaryPanel.className = 'tab-content active';
        summaryPanel.innerHTML = detail.summary
            ? marked.parse(detail.summary)
            : '<p class="empty-state">尚無摘要。</p>';

        // Regenerate button — injected into tab bar at right
        const regenBtn = document.createElement('button');
        regenBtn.textContent = '重新生成摘要';
        regenBtn.style.marginLeft = 'auto';
        regenBtn.addEventListener('click', () => startRegenerate(podId, guid, summaryPanel, regenBtn));

        tabNames.forEach((name, i) => {
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
        tabBar.appendChild(regenBtn);
        el.appendChild(tabBar);

        // Tab panel wrapper
        const wrapper = document.createElement('div');
        wrapper.className = 'tab-panel-wrapper';

        tabPanels.push(summaryPanel);
        wrapper.appendChild(summaryPanel);

        const transcriptPanel = document.createElement('div');
        transcriptPanel.className = 'tab-content';
        transcriptPanel.innerHTML = detail.transcript
            ? `<pre class="transcript-pre">${esc(detail.transcript)}</pre>`
            : '<p class="empty-state">無逐字稿。</p>';
        tabPanels.push(transcriptPanel);
        wrapper.appendChild(transcriptPanel);

        const condensedPanel = document.createElement('div');
        condensedPanel.className = 'tab-content';
        condensedPanel.innerHTML = detail.condensed_transcript
            ? `<pre class="transcript-pre">${esc(detail.condensed_transcript)}</pre>`
            : '<p class="empty-state">無精簡版逐字稿。</p>';
        tabPanels.push(condensedPanel);
        wrapper.appendChild(condensedPanel);

        el.appendChild(wrapper);
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
                summaryPanel.innerHTML = marked.parse(result);
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

// ---- Navbar breadcrumb ----
function setNavCrumb(label) {
    const navbar = document.getElementById('navbar');
    if (!navbar) return;
    navbar.querySelectorAll('.nav-sep, .nav-crumb').forEach(el => el.remove());
    if (label) {
        navbar.insertAdjacentHTML('beforeend',
            `<span class="nav-sep">/</span><span class="nav-crumb">${label}</span>`);
    }
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
